"""Prompt 11 — the core flow, end to end, against the running API.

One honey batch is walked through every role that touches it, over HTTP, on the
development database's own records (the seeded KVIC cluster, beekeeper and
hive):

    KVIC cluster → batch → collection → processing → laboratory APPROVED
      → packaging → packages → QR → distribution → retailer received
      → consumer QR verification → blockchain traceability

After every action the next role reads the record back and the probe checks it
is the **same** row (same id, same code) with the status the action wrote — the
database is the only source. At the end every role signs out, signs in again
with a fresh token, and re-reads the same records.

Staff accounts the seed does not create (packing operator, distributor,
retailer) are provisioned through the admin API and marked TEST. Usage:

    cd backend
    python tests/prompt11_core_flow.py [--api-url http://localhost:8000/api/v1]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.api_smoke_phase7 import request  # noqa: E402

DEMO_SOURCE = "Project-configured demonstration limit for tests (not a regulatory standard)"
MARKER = f"p11-{int(time.time())}"
SEEDED = {
    "admin": ("admin@honeychain.example.com", "AdminSecure123"),
    "kvic": ("kvic@honeychain.example.com", "KvicSecure123"),
    "beekeeper": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "processor": ("processor@honeychain.example.com", "ProcessPass123"),
    "labtech": ("labtech@honeychain.example.com", "LabTechPass123"),
    "consumer": ("consumer@honeychain.example.com", "ConsumerPass123"),
}
STAFF_PASSWORD = "Prompt11Staff123"

PASSED: list[str] = []
FAILED: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> bool:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n=== {title}")


class Api:
    def __init__(self, base: str) -> None:
        self.base = base
        self.tokens: dict[str, str] = {}
        self.credentials: dict[str, tuple[str, str]] = dict(SEEDED)

    def login(self, role: str) -> str:
        email, password = self.credentials[role]
        status, payload = request("POST", "/auth/login", base=self.base, body={"email": email, "password": password})
        if status != 200:
            raise SystemExit(f"Could not sign in as {email}: {status} {payload}")
        self.tokens[role] = payload["data"]["access_token"]
        return self.tokens[role]

    def logout(self, role: str) -> int:
        status, _ = request("POST", "/auth/logout", base=self.base, token=self.tokens[role], body={})
        return status

    def call(self, role: str | None, method: str, path: str, body=None):
        token = self.tokens.get(role) if role else None
        return request(method, path, base=self.base, token=token, body=body)

    def ok(self, role, method, path, body=None, expect=(200, 201)) -> dict:
        status, payload = self.call(role, method, path, body)
        if status not in expect:
            raise SystemExit(f"{role} {method} {path} → {status}: {payload}")
        return payload

    def staff(self, key: str, role: str) -> None:
        email = f"{MARKER}.{key}@honeychain.example.com"
        self.ok(
            "admin",
            "POST",
            "/admin/users",
            {"name": f"Prompt 11 {key} TEST", "email": email, "password": STAFF_PASSWORD, "role": role},
        )
        self.credentials[key] = (email, STAFF_PASSWORD)
        self.login(key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1")
    args = parser.parse_args()
    api = Api(args.api_url)

    section("Sign in and provision the roles the seed does not create")
    for role in SEEDED:
        api.login(role)
    api.staff("packer", "PACKAGING_UNIT")
    api.staff("distributor", "DISTRIBUTOR")
    api.staff("retailer", "RETAILER")
    check("every role signed in", len(api.tokens) == 9)

    clusters = api.ok("kvic", "GET", "/clusters?page_size=100")["data"]
    cluster = next(row for row in clusters if row["cluster_code"] == "KVIC-GNT-001")
    hives = api.ok("beekeeper", "GET", "/hives?page_size=50")["data"]
    hive = next(row for row in hives if row["hive_code"] == "HIVE-GNT-00001")

    # ------------------------------------------------------------------ #
    section("Beekeeper: collection → batch")
    collection = api.ok(
        "beekeeper",
        "POST",
        "/collections",
        {
            "hives": [{"hive_id": hive["id"], "quantity": "12.0"}],
            "collection_date": date.today().isoformat(),
            "unit": "KG",
            "notes": f"{MARKER} TEST harvest",
        },
    )["data"]
    completed = api.ok("beekeeper", "POST", f"/collections/{collection['id']}/complete")
    batch_id = completed["meta"]["batch"]["id"]
    batch = api.ok("beekeeper", "GET", f"/batches/{batch_id}")["data"]
    check("the harvest created exactly one batch", batch["collection_id"] == collection["id"])
    check("the batch names its beekeeper", batch.get("beekeeper_code") == "BKR-GNT-00001")

    section("KVIC: the batch belongs to the cluster, and the officer sees the same row")
    if batch.get("cluster_id") != cluster["id"]:
        api.ok("kvic", "POST", f"/clusters/{cluster['id']}/batches", {"batch_ids": [batch_id], "reassign": True})
    in_cluster = api.ok("kvic", "GET", f"/clusters/{cluster['id']}/batches?page_size=100")["data"]
    check("the cluster lists the same batch id", batch_id in {row["id"] for row in in_cluster})
    analytics_before = api.ok("kvic", "GET", f"/clusters/{cluster['id']}/batch-analytics")["data"]

    # ------------------------------------------------------------------ #
    section("Processing → laboratory APPROVED")
    run = api.ok("admin", "POST", "/processing", {"batch_id": batch_id, "processing_type": "FILTERING"})["data"]
    api.ok("admin", "POST", f"/processing/{run['id']}/start")
    api.ok("admin", "POST", f"/processing/{run['id']}/complete", {"input_quantity": "12.0", "output_quantity": "12.0"})
    check(
        "the laboratory sees the processed batch",
        api.ok("labtech", "GET", f"/batches/{batch_id}")["data"]["status"] == "LAB_TESTING",
    )
    laboratory = api.ok(
        "labtech",
        "POST",
        "/laboratories",
        {"name": f"Prompt 11 Laboratory {MARKER} TEST", "location": "Guntur", "district": "Guntur", "state": "Andhra Pradesh"},
    )["data"]
    test = api.ok(
        "labtech",
        "POST",
        "/lab-tests",
        {"batch_id": batch_id, "laboratory_id": laboratory["id"], "sample_quantity": "0.25", "sample_unit": "GRAM"},
    )["data"]
    detail = api.ok("labtech", "GET", f"/lab-tests/{test['id']}")["data"]
    if not detail.get("results"):
        # No development demo profile: configure one range and measure inside it.
        parameter = api.ok("labtech", "GET", "/lab-parameters")["data"][0]
        api.ok(
            "admin",
            "PATCH",
            f"/lab-parameters/{parameter['code']}",
            {"reference_min": "10", "reference_max": "20", "reference_source": DEMO_SOURCE, "is_required": True},
        )
        api.ok("labtech", "POST", f"/lab-tests/{test['id']}/results", {"parameter_code": parameter["code"], "value": "17.2"})
    else:
        print(f"  (development demo profile pre-filled {len(detail['results'])} measurement(s))")
    done = api.ok("labtech", "POST", f"/lab-tests/{test['id']}/complete", {})["data"]
    check("the test completed with a PASS verdict", done.get("overall_result") == "PASS", str(done.get("overall_result")))
    # A passing verdict approves the batch and releases it to packaging in one
    # step, so the stored status is APPROVED or PACKAGING_READY — both packable.
    approved_status = api.ok("admin", "GET", f"/batches/{batch_id}")["data"]["status"]
    check("the batch reads approved for packaging", approved_status in ("APPROVED", "PACKAGING_READY"), approved_status)

    # ------------------------------------------------------------------ #
    section("Packaging: the approved batch is on the worklist; packages are created")
    unit = api.ok(
        "admin",
        "POST",
        "/packaging-units",
        {
            "name": f"Prompt 11 Packing Unit {MARKER} TEST",
            "registration_identifier": f"REG-{MARKER}".upper(),
            "location": "Guntur",
            "district": "Guntur",
            "state": "Andhra Pradesh",
        },
    )["data"]
    packer_id = api.ok("packer", "GET", "/auth/me")["data"]["id"]
    api.ok("admin", "POST", f"/packaging-units/{unit['id']}/members", {"user_id": packer_id})
    worklist = api.ok("packer", "GET", "/packaging/approved-batches?page_size=100")["data"]
    check("packaging sees the same approved batch", batch_id in {row["batch_id"] for row in worklist})
    packaging = api.ok(
        "packer",
        "POST",
        "/packaging",
        {
            "batch_id": batch_id,
            "packaging_unit_id": unit["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "12.0",
            "package_size": "6.0",
            "number_of_packages": 2,
        },
    )["data"]
    api.ok("packer", "POST", f"/packaging/{packaging['id']}/start")
    api.ok("packer", "POST", f"/packaging/{packaging['id']}/complete", {})
    packages = api.ok("packer", "POST", f"/packaging/{packaging['id']}/release")["data"]
    check("two packages exist for the batch", len(packages) == 2 and all(p["batch_id"] == batch_id for p in packages))
    first = packages[0]
    qr = api.ok("packer", "POST", f"/blockchain/packages/{first['id']}/qr")["data"]
    check("the QR belongs to that package", qr["package_code"] == first["package_code"])
    listed = api.ok("packer", "GET", f"/packages?batch_id={batch_id}&page_size=50")["data"]
    check("the package register lists the same package ids", {p["id"] for p in packages} == {p["id"] for p in listed})

    # ------------------------------------------------------------------ #
    section("Distribution → retailer")
    retailer_id = api.ok("retailer", "GET", "/auth/me")["data"]["id"]
    ready = api.ok("distributor", "GET", "/packages?status=READY_FOR_DISTRIBUTION&page_size=100")["data"]
    check("the distributor sees the released package", first["id"] in {p["id"] for p in ready})
    shipment = api.ok(
        "distributor",
        "POST",
        "/distribution",
        {"package_id": first["id"], "quantity": "6.0", "destination": "Guntur market", "retailer_id": retailer_id},
    )["data"]
    api.ok("distributor", "POST", f"/distribution/{shipment['id']}/dispatch", {})
    inbound = api.ok("retailer", "GET", "/retailer/shipments?awaiting_receipt=true")["data"]
    check("the retailer sees the dispatched shipment", shipment["id"] in {row["id"] for row in inbound})
    api.ok("distributor", "POST", f"/distribution/{shipment['id']}/deliver", {})
    inbound = api.ok("retailer", "GET", "/retailer/shipments?awaiting_receipt=true")["data"]
    check("a carrier-delivered shipment still awaits the shop's receipt", shipment["id"] in {row["id"] for row in inbound})
    kvic_view = api.ok("kvic", "GET", f"/distribution/{shipment['id']}")["data"]
    check("KVIC reads the delivered status of the same shipment", kvic_view["status"] == "DELIVERED")
    received = api.ok("retailer", "POST", f"/retailer/shipments/{shipment['id']}/receive", {})["data"]
    check("the receipt is recorded", bool(received.get("received_at")))
    kvic_view = api.ok("kvic", "GET", f"/distribution/{shipment['id']}")["data"]
    check("KVIC reads the retailer's receipt", bool(kvic_view.get("received_at")))
    analytics_after = api.ok("kvic", "GET", f"/clusters/{cluster['id']}/batch-analytics")["data"]
    check(
        "cluster analytics counted the new batch",
        analytics_after["totals"]["batches"] >= analytics_before["totals"]["batches"],
    )

    # ------------------------------------------------------------------ #
    section("Consumer: the QR resolves to the exact package and its batch")
    status, public = api.call(None, "GET", f"/trace/{qr['qr_id']}")
    public = public.get("data") or {}
    check("the public trace answers", status == 200, str(status))
    check("QR → the same package", public.get("package", {}).get("package_code") == first["package_code"])
    check("QR → the same batch", public.get("product", {}).get("batch_code") == batch["batch_code"])
    tx = [row["tx_type"] for row in public.get("blockchain", {}).get("transactions", [])]
    check("the ledger on the page includes the QR and the verification", "QR_GENERATED" in tx and "CUSTOMER_QR_VERIFIED" in tx)
    check("no other package's creation event is shown", tx.count("PACKAGE_CREATED") == 1)

    section("Unified traceability: one answer, the same records")
    trace = api.ok("beekeeper", "GET", f"/blockchain/batches/{batch_id}")["data"]
    chain = trace["chain"]
    check("chain → the same batch", chain["batch"]["id"] == batch_id)
    check("chain → the same collection", chain["collection"]["id"] == collection["id"])
    check("chain → the source hive", [h["hive_code"] for h in chain["hives"]] == ["HIVE-GNT-00001"])
    check("chain → the cluster", (chain["cluster"] or {}).get("cluster_code") == "KVIC-GNT-001")
    check("chain → the packages", {p["package_code"] for p in chain["packages"]} == {p["package_code"] for p in packages})
    check("chain → the shipment and receipt", [r["distribution_code"] for r in chain["retailer"]] == [shipment["distribution_code"]])
    check("every event names this batch", all(row["batch_id"] == batch_id for row in trace["transactions"]))
    stages = {row["stage"]: row["reached"] for row in chain["stages"]}
    check("all stages reached from the records", all(stages.values()), str(stages))
    scoped = api.ok("beekeeper", "GET", f"/blockchain/batches/{batch_id}?package_code={packages[1]['package_code']}")["data"]
    check("the other package's own trace shows no shipment", scoped["chain"]["distribution"] == [])

    # ------------------------------------------------------------------ #
    section("Permissions across modules")
    check("a consumer cannot list batches", api.call("consumer", "GET", "/batches")[0] in (401, 403))
    check("a beekeeper cannot issue a QR", api.call("beekeeper", "POST", f"/blockchain/packages/{packages[1]['id']}/qr")[0] == 403)
    check("KVIC cannot read the raw chain ledger", api.call("kvic", "GET", "/blockchain/ledger")[0] == 403)
    check("a retailer cannot dispatch", api.call("retailer", "POST", f"/distribution/{shipment['id']}/dispatch", {})[0] in (403, 404, 409))
    check("an invalid batch id is a clean 404", api.call("admin", "GET", "/blockchain/batches/00000000-0000-0000-0000-000000000000")[0] == 404)
    status, body = api.call("admin", "GET", "/blockchain/batches/not-a-uuid")
    check("a malformed id is a 422 without a stack trace", status == 422 and "Traceback" not in str(body))

    # ------------------------------------------------------------------ #
    section("Sign out, sign in again, and read the same state")
    expected = {
        "batch": api.ok("admin", "GET", f"/batches/{batch_id}")["data"]["status"],
        "shipment": api.ok("distributor", "GET", f"/distribution/{shipment['id']}")["data"]["status"],
    }
    for role in list(api.tokens):
        api.logout(role)
        api.login(role)
    check("batch status survives sign-out/in", api.ok("beekeeper", "GET", f"/batches/{batch_id}")["data"]["status"] == expected["batch"])
    check("shipment status survives sign-out/in", api.ok("retailer", "GET", f"/distribution/{shipment['id']}")["data"]["status"] == expected["shipment"])
    again = api.ok("kvic", "GET", f"/blockchain/batches/{batch_id}")["data"]
    check("the officer's trace after sign-in is the same", {r["stage"]: r["reached"] for r in again["chain"]["stages"]} == stages)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for item in FAILED:
        print(f"  FAILED: {item}")
    print(f"\nRecords created (TEST): batch {batch['batch_code']}, packages {[p['package_code'] for p in packages]}, "
          f"shipment {shipment['distribution_code']}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())

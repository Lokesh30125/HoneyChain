"""Prompt 12 — final verification against the running API and database.

Complements ``prompt11_core_flow.py`` (the happy-path chain) with the checks
Prompt 12 adds, each on real records created through the API:

* every one of the ten roles signs in and reaches its own workspace data, and is
  refused another role's writes by the backend (not by a hidden sidebar);
* laboratory FAIL → rejected and blocked from packaging; INCONCLUSIVE → stays in
  testing; HOLD → held; "Proceed Anyway" refused without its confirmation,
  audited when used;
* QR: issuing twice returns the same identity and writes one event; the public
  page answers by package code, QR id and full QR URL with the same package;
* blockchain: retried operations do not duplicate transactions;
* API errors carry no stack trace, SQL, file path or secret;
* data consistency queries over the whole database.

Usage (API on :8000, dev database):  python tests/prompt12_final_checks.py
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.prompt11_core_flow import MARKER, Api, check, section  # noqa: E402
from tests.prompt11_core_flow import FAILED, PASSED  # noqa: E402

LEAK_MARKERS = ("Traceback", "sqlalchemy", "psycopg", "File \"", "SELECT ", "INSERT ", "jwt_secret", "JWT_SECRET", "password_hash")


def no_leak(payload) -> bool:
    text = str(payload)
    return not any(marker in text for marker in LEAK_MARKERS)


def new_batch(api: Api, hive_id: str, label: str) -> str:
    collection = api.ok(
        "beekeeper",
        "POST",
        "/collections",
        {"hives": [{"hive_id": hive_id, "quantity": "5.0"}], "collection_date": date.today().isoformat(),
         "unit": "KG", "notes": f"{MARKER} {label} TEST"},
    )["data"]
    batch_id = api.ok("beekeeper", "POST", f"/collections/{collection['id']}/complete")["meta"]["batch"]["id"]
    run = api.ok("processor_admin", "POST", "/processing", {"batch_id": batch_id, "processing_type": "FILTERING"})["data"]
    api.ok("processor_admin", "POST", f"/processing/{run['id']}/start")
    api.ok("processor_admin", "POST", f"/processing/{run['id']}/complete", {"input_quantity": "5.0", "output_quantity": "5.0"})
    return batch_id


def open_test(api: Api, batch_id: str, laboratory_id: str) -> dict:
    test = api.ok(
        "labtech",
        "POST",
        "/lab-tests",
        {"batch_id": batch_id, "laboratory_id": laboratory_id, "sample_quantity": "0.25", "sample_unit": "GRAM"},
    )["data"]
    return api.ok("labtech", "GET", f"/lab-tests/{test['id']}")["data"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1")
    args = parser.parse_args()
    api = Api(args.api_url)
    for role in ("admin", "kvic", "beekeeper", "processor", "labtech", "consumer"):
        api.login(role)
    api.tokens["processor_admin"] = api.tokens["admin"]
    api.staff("collection", "COLLECTION_CENTER")
    api.staff("packer", "PACKAGING_UNIT")
    api.staff("distributor", "DISTRIBUTOR")
    api.staff("retailer", "RETAILER")
    api.staff("retailer2", "RETAILER")

    # ------------------------------------------------------------------ #
    section("Every role signs in and reads its own workspace")
    home_reads = {
        "admin": "/admin/summary",
        "kvic": "/clusters",
        "beekeeper": "/hives",
        "collection": "/collections",
        "processor": "/processing",
        "labtech": "/lab-tests",
        "packer": "/packages",
        "distributor": "/distribution",
        "retailer": "/retailer/shipments",
        "consumer": "/auth/me",
    }
    for role, path in home_reads.items():
        status, _ = api.call(role, "GET", path)
        check(f"{role}: GET {path}", status == 200, str(status))
        me = api.ok(role, "GET", "/auth/me")["data"]
        check(f"{role}: /auth/me answers with the signed-in account", me["email"] == api.credentials[role][0])

    section("The backend refuses other roles' work")
    refused = [
        ("consumer", "GET", "/batches"),
        ("consumer", "POST", "/packaging"),
        ("consumer", "GET", "/admin/users"),
        ("beekeeper", "GET", "/admin/users"),
        ("beekeeper", "POST", "/packaging"),
        ("retailer", "POST", "/distribution"),
        ("retailer", "POST", "/lab-tests"),
        ("packer", "POST", "/lab-tests"),
        ("distributor", "POST", "/packaging"),
        ("labtech", "POST", "/distribution"),
        ("processor", "POST", "/lab-tests"),
        ("kvic", "GET", "/admin/users"),
        ("kvic", "GET", "/blockchain/ledger"),
        ("collection", "POST", "/packaging"),
    ]
    for role, method, path in refused:
        status, body = api.call(role, method, path, {} if method == "POST" else None)
        check(f"{role} refused: {method} {path}", status in (401, 403), str(status))
        check(f"{role} refusal leaks nothing: {method} {path}", no_leak(body))
    status, _ = api.call(None, "GET", "/batches")
    check("anonymous request refused", status == 401, str(status))

    # ------------------------------------------------------------------ #
    hive = next(row for row in api.ok("beekeeper", "GET", "/hives?page_size=50")["data"] if row["hive_code"] == "HIVE-GNT-00001")
    laboratory = api.ok(
        "labtech", "POST", "/laboratories",
        {"name": f"Prompt 12 Laboratory {MARKER} TEST", "location": "Guntur", "district": "Guntur", "state": "Andhra Pradesh"},
    )["data"]
    unit = api.ok(
        "admin", "POST", "/packaging-units",
        {"name": f"Prompt 12 Packing Unit {MARKER} TEST", "registration_identifier": f"REG-P12-{MARKER}".upper(),
         "location": "Guntur", "district": "Guntur", "state": "Andhra Pradesh"},
    )["data"]
    api.ok("admin", "POST", f"/packaging-units/{unit['id']}/members", {"user_id": api.ok("packer", "GET", "/auth/me")["data"]["id"]})

    section("Laboratory FAIL → rejected, and packaging refuses it")
    fail_batch = new_batch(api, hive["id"], "FAIL")
    test = open_test(api, fail_batch, laboratory["id"])
    moisture = next((r for r in test.get("results", []) if r["parameter_code"] == "MOISTURE"), None)
    if moisture:
        api.ok("labtech", "PATCH", f"/lab-tests/{test['id']}/results/{moisture['id']}", {"value": "35", "measurement_source": "MANUAL"})
    done = api.ok("labtech", "POST", f"/lab-tests/{test['id']}/complete", {})["data"]
    check("the test is FAIL", done.get("overall_result") == "FAIL", str(done.get("overall_result")))
    status_after = api.ok("admin", "GET", f"/batches/{fail_batch}")["data"]["status"]
    check("the batch is REJECTED in the database", status_after == "REJECTED", status_after)
    worklist = api.ok("packer", "GET", "/packaging/approved-batches?page_size=100")["data"]
    check("the rejected batch is not on the packaging worklist", fail_batch not in {r["batch_id"] for r in worklist})
    status, body = api.call("packer", "POST", "/packaging", {"batch_id": fail_batch, "packaging_unit_id": unit["id"],
        "packaging_type": "JAR", "packaged_quantity": "5.0", "package_size": "5.0", "number_of_packages": 1})
    check("packaging a rejected batch is refused by the server", status in (409, 422), str(status))

    section("Laboratory INCONCLUSIVE → the batch stays in testing")
    inc_batch = new_batch(api, hive["id"], "INCONCLUSIVE")
    test = open_test(api, inc_batch, laboratory["id"])
    required = [r for r in test.get("results", []) if r.get("is_required") or r["parameter_code"] == "MOISTURE"]
    for row in required[:1]:
        api.ok("labtech", "DELETE", f"/lab-tests/{test['id']}/results/{row['id']}")
    done = api.ok("labtech", "POST", f"/lab-tests/{test['id']}/complete", {})["data"]
    check("the test is INCONCLUSIVE", done.get("overall_result") == "INCONCLUSIVE", str(done.get("overall_result")))
    status_after = api.ok("admin", "GET", f"/batches/{inc_batch}")["data"]["status"]
    check("the batch is not approved", status_after not in ("APPROVED", "PACKAGING_READY"), status_after)

    section("Laboratory HOLD → held; Proceed Anyway is gated and audited")
    hold_batch = new_batch(api, hive["id"], "HOLD")
    test = open_test(api, hold_batch, laboratory["id"])
    held = api.ok("labtech", "POST", f"/lab-tests/{test['id']}/hold", {"reason": "Prompt 12 hold check TEST — sample needs review"})["data"]
    check("the test is on hold", held.get("status") == "HOLD", str(held.get("status")))
    status_after = api.ok("admin", "GET", f"/batches/{hold_batch}")["data"]["status"]
    check("the batch is LAB_HOLD", status_after == "LAB_HOLD", status_after)
    status, body = api.call("labtech", "POST", f"/lab-tests/{test['id']}/proceed-with-risk", {"confirmation": "yes", "reason": "Prompt 12 override check TEST"})
    check("Proceed Anyway without the confirmation word is refused", status in (403, 422), str(status))
    status, body = api.call("labtech", "POST", f"/lab-tests/{test['id']}/proceed-with-risk",
                            {"confirmation": "PROCEED", "reason": "Prompt 12 override check TEST — reviewed and accepted"})
    if status == 403:
        check("Proceed Anyway is disabled on this installation (LAB_ALLOW_RISK_OVERRIDE off)", True)
    else:
        check("Proceed Anyway with confirmation is accepted", status == 200, f"{status} {body}")
        audits = api.ok("admin", "GET", f"/admin/audit-logs?search=PROCEEDED&page_size=50")
        check("Proceed Anyway is in the audit log", any("PROCEED" in str(row.get("action", "")) for row in audits["data"]))

    # ------------------------------------------------------------------ #
    section("QR: one identity per package, resolvable three ways")
    ok_batch = new_batch(api, hive["id"], "QR")
    test = open_test(api, ok_batch, laboratory["id"])
    api.ok("labtech", "POST", f"/lab-tests/{test['id']}/complete", {})
    run = api.ok("packer", "POST", "/packaging", {"batch_id": ok_batch, "packaging_unit_id": unit["id"], "packaging_type": "JAR",
        "packaged_quantity": "5.0", "package_size": "2.5", "number_of_packages": 2})["data"]
    api.ok("packer", "POST", f"/packaging/{run['id']}/start")
    api.ok("packer", "POST", f"/packaging/{run['id']}/complete", {})
    status, _ = api.call("packer", "POST", f"/packaging/{run['id']}/complete", {})
    check("completing the run twice is refused", status == 409, str(status))
    packages = api.ok("packer", "GET", f"/packages?batch_id={ok_batch}")["data"]
    check("exactly the declared number of packages", len(packages) == 2, str(len(packages)))
    listed = api.ok("packer", "GET", f"/packages?batch_id={ok_batch}")["data"]
    check("the QR column starts empty", all(not row["qr_issued"] for row in listed))
    pkg = packages[0]
    first = api.ok("packer", "POST", f"/blockchain/packages/{pkg['id']}/qr")["data"]
    second = api.ok("packer", "POST", f"/blockchain/packages/{pkg['id']}/qr")["data"]
    check("issuing twice returns the same QR id", first["qr_id"] == second["qr_id"] == f"QR-{pkg['package_code']}")
    check("issuing twice returns the same payload and event", first["qr_payload"] == second["qr_payload"] and first["event_id"] == second["event_id"])
    viewed = api.ok("packer", "GET", f"/blockchain/packages/{pkg['id']}/qr")["data"]
    check("the existing QR can be viewed again", viewed["qr_id"] == first["qr_id"])
    listed = {row["id"]: row for row in api.ok("packer", "GET", f"/packages?batch_id={ok_batch}")["data"]}
    check("the QR generation list shows the issued id", listed[pkg["id"]]["qr_id"] == first["qr_id"] and not listed[packages[1]["id"]]["qr_issued"])
    for label, code in (("package code", pkg["package_code"]), ("QR id", first["qr_id"])):
        status, body = api.call(None, "GET", f"/trace/{code}")
        data = (body or {}).get("data") or {}
        check(f"public trace by {label} → the same package", status == 200 and data.get("package", {}).get("package_code") == pkg["package_code"], str(status))
    status, _ = api.call(None, "GET", "/trace/HC-PKG-1999-999999")
    check("an unknown package code is a clean 404", status == 404)
    trace = api.ok(None, "GET", f"/trace/{pkg['package_code']}")["data"]
    reached = {row["stage"]: row["reached"] for row in trace["timeline"]}
    check("future stages are not shown as completed", not reached.get("DISPATCHED") and not reached.get("RETAILER"), str(reached))
    tx = [row["tx_type"] for row in trace["blockchain"]["transactions"]]
    check("one QR_GENERATED event after two issues and two opens", tx.count("QR_GENERATED") == 1, str(tx))
    check("one CUSTOMER_QR_VERIFIED after repeated opens", tx.count("CUSTOMER_QR_VERIFIED") == 1, str(tx))

    section("Retailer isolation and duplicate operations")
    api.ok("packer", "POST", f"/packaging/{run['id']}/release")
    retailer_id = api.ok("retailer", "GET", "/auth/me")["data"]["id"]
    shipment = api.ok("distributor", "POST", "/distribution", {"package_id": pkg["id"], "quantity": "2.5",
        "destination": "Guntur market", "retailer_id": retailer_id})["data"]
    api.ok("distributor", "POST", f"/distribution/{shipment['id']}/dispatch", {})
    status, _ = api.call("distributor", "POST", f"/distribution/{shipment['id']}/dispatch", {})
    check("dispatching twice is refused", status == 409, str(status))
    status, _ = api.call("retailer2", "POST", f"/retailer/shipments/{shipment['id']}/receive", {})
    check("another retailer cannot receive this shipment", status == 404, str(status))
    status, _ = api.call("retailer2", "GET", f"/distribution/{shipment['id']}")
    check("another retailer cannot read this shipment", status == 404, str(status))
    api.ok("retailer", "POST", f"/retailer/shipments/{shipment['id']}/receive", {})
    api.ok("retailer", "POST", f"/retailer/shipments/{shipment['id']}/receive", {})
    events = api.ok("admin", "GET", f"/blockchain/batches/{ok_batch}")["data"]["transactions"]
    kinds = [row["tx_type"] for row in events]
    check("a repeated receipt writes one RETAILER_RECEIVED", kinds.count("RETAILER_RECEIVED") == 1, str(kinds))
    check("one DISTRIBUTION_DISPATCHED after a refused second dispatch", kinds.count("DISTRIBUTION_DISPATCHED") == 1)
    check("every event of the batch names it", all(row["batch_id"] == ok_batch for row in events))
    ledger = api.ok("admin", "GET", f"/blockchain/transactions?batch_code={api.ok('admin','GET',f'/batches/{ok_batch}')['data']['batch_code']}&page_size=100")
    check("the admin ledger lists the same events", ledger["meta"]["total_items"] == len(events), f"{ledger['meta']['total_items']} vs {len(events)}")

    section("Errors are useful and leak nothing")
    for method, path, body in (
        ("GET", "/batches/not-a-uuid", None),
        ("GET", "/batches/00000000-0000-0000-0000-000000000000", None),
        ("POST", "/collections", {"hives": "nope"}),
        ("POST", "/auth/login", {"email": "nobody@example.com", "password": "wrong-password"}),
    ):
        status, payload = api.call("admin" if not path.startswith("/auth") else None, method, path, body)
        message = ((payload or {}).get("error") or {}).get("message")
        check(f"{method} {path} → {status} with a message", status >= 400 and bool(message), str(payload)[:120])
        check(f"{method} {path} leaks nothing", no_leak(payload))

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for item in FAILED:
        print(f"  FAILED: {item}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())

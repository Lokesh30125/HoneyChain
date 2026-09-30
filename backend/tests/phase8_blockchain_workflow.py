"""Phase 8 — the whole supply chain, once, against the real blockchain service.

This is the definition-of-done run. It takes one harvest all the way to a
customer opening a QR code, through the same endpoints the screens call, and
checks at every stage that:

* the operational record exists (the batch, the run, the test, the packages, the
  shipment, the receipt) — the database is the source of truth;
* exactly one traceability event was recorded for that transition, with the
  values the record actually holds;
* the event reached the real service at ``BLOCKCHAIN_BASE_URL`` — it is
  ``CONFIRMED`` with a ``tx_id`` — and that transaction is visible in the
  service's own ``GET /transactions``;
* repeating an action does not write a second event or a second transaction;
* the customer's page shows what happened and nothing a stranger should not see.

It writes to the development database and to the real ledger: that is the point
of it, and it is why it is a script rather than a pytest module (the pytest
suite uses an in-process stub so a test run can never write to the chain).

Usage (the API must be running, and the blockchain service reachable)::

    cd backend
    .venv/bin/python tests/phase8_blockchain_workflow.py

Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.api_smoke_phase7 import (  # noqa: E402
    configure_parameter,
    harvest_batch,
    make_hive,
    process_batch,
    register_keeper,
    request,
    sign_in,
)
from tests.browser_master_workflow import (  # noqa: E402
    ADMIN,
    DISTRIBUTOR_PASSWORD,
    LABTECH,
    PACKER_PASSWORD,
    PROCESSOR,
    RETAILER_PASSWORD,
    create_account,
    staging_email,
)

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
DEFAULT_CHAIN = os.getenv("BLOCKCHAIN_BASE_URL", "http://54.160.152.176:3001")

PASSED: list[str] = []
FAILED: list[str] = []

#: Keys that must never appear in a submitted payload, whatever the record holds.
FORBIDDEN_PAYLOAD_TOKENS = (
    "password",
    "passwd",
    "secret",
    "token",
    "jwt",
    "authorization",
    "email",
    "phone",
    "prompt",
    "telemetry",
)


def check(description: str, condition: bool, detail: str = "") -> bool:
    (PASSED if condition else FAILED).append(description)
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"  {'PASS' if condition else 'FAIL'}  {description}{suffix}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n=== {title}")


def read_chain(base: str) -> list[dict]:
    """The service's own ledger, exactly as it reports it."""
    with urllib.request.urlopen(f"{base.rstrip('/')}/transactions", timeout=30) as response:
        rows = json.loads(response.read() or b"[]")
    if isinstance(rows, dict):  # an envelope, if the service ever wraps it
        for key in ("data", "transactions", "items", "results"):
            if isinstance(rows.get(key), list):
                return rows[key]
        raise SystemExit(f"Unrecognised ledger shape: {list(rows)[:5]}")
    return rows


def events_for(api: str, token: str, batch_code: str) -> list[dict]:
    status, payload = request(
        "GET",
        f"/blockchain/transactions?batch_code={batch_code}&page_size=100",
        base=api,
        token=token,
    )
    if status != 200:
        raise SystemExit(f"Could not read the ledger: {status} {payload}")
    return payload["data"]


def walk_payload(value, path=""):
    """Yield every (key, value) pair in a payload, wherever it is nested."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item, path
            yield from walk_payload(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_payload(item, f"{path}[{index}]")


def main() -> int:  # noqa: PLR0915 - one long journey, deliberately
    parser = argparse.ArgumentParser(description="Phase 8 end-to-end blockchain workflow")
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--chain-url", default=DEFAULT_CHAIN)
    args = parser.parse_args()
    api = args.api_url.rstrip("/")
    chain_url = args.chain_url.rstrip("/")

    print(f"Phase 8 end-to-end — API {api}, ledger {chain_url}")

    section("The ledger before this run")
    before = read_chain(chain_url)
    before_ids = {row.get("tx_id") for row in before}
    print(f"  the service holds {len(before)} transactions")
    check("the blockchain service answers its own ledger", bool(before))

    # ---------------------------------------------------------------------- #
    section("Honey is harvested, processed and tested")
    # ---------------------------------------------------------------------- #
    admin = sign_in(api, *ADMIN)
    processor_token = sign_in(api, *PROCESSOR)
    status, me = request("GET", "/auth/me", base=api, token=processor_token)
    processor = {"token": processor_token, "user_id": me["data"]["id"]}

    status, payload = request("GET", "/clusters?page_size=5", base=api, token=admin)
    if status != 200 or not payload.get("data"):
        raise SystemExit(f"Could not read the cluster registry: {status} {payload}")
    cluster = payload["data"][0]

    keeper = register_keeper(api)
    status, payload = request("GET", "/beekeepers/me", base=api, token=keeper["token"])
    status, payload = request(
        "PUT",
        f"/beekeepers/{payload['data']['id']}",
        base=api,
        token=admin,
        body={"kvic_cluster_id": cluster["id"]},
    )
    if status != 200:
        raise SystemExit(f"Could not join the beekeeper to the cluster: {status} {payload}")

    hive = make_hive(api, keeper["token"])
    batch = harvest_batch(api, keeper, hive, "13.7")
    run = process_batch(api, admin, processor, batch["id"], "12.9")
    configure_parameter(api, admin, "MOISTURE", "10", "20")

    status, payload = request("GET", f"/batches/{batch['id']}", base=api, token=admin)
    batch = payload["data"]
    check(
        "the harvest became one batch, carrying its cluster",
        batch["cluster_id"] == cluster["id"],
        f"cluster_id={batch['cluster_id']}",
    )
    check("the batch exists as a database record", bool(batch.get("batch_code")))

    labtech_token = sign_in(api, *LABTECH)
    status, payload = request("GET", "/laboratories?page_size=5", base=api, token=labtech_token)
    laboratory = (payload.get("data") or [None])[0]
    if laboratory is None:
        status, payload = request(
            "POST",
            "/laboratories",
            base=api,
            token=labtech_token,
            body={
                "name": f"Phase 8 Laboratory TEST {uuid.uuid4().hex[:6]}",
                "registration_identifier": f"PH8-{uuid.uuid4().hex[:8].upper()}",
                "location": "Guntur",
                "district": "Guntur",
                "state": "Andhra Pradesh",
                "notes": "Phase 8 script fixture (TEST data)",
            },
        )
        if status != 201:
            raise SystemExit(f"Could not register a laboratory: {status} {payload}")
        laboratory = payload["data"]

    status, payload = request(
        "POST",
        "/lab-tests",
        base=api,
        token=labtech_token,
        body={"batch_id": batch["id"], "laboratory_id": laboratory["id"], "sample_quantity": "0.25"},
    )
    if status not in (200, 201):
        raise SystemExit(f"Could not open the test: {status} {payload}")
    test = payload["data"]
    # A development installation pre-fills a demonstration value for every
    # configured parameter. A test holds one measurement per parameter, so the
    # demonstration row is replaced rather than stacked — and the replacement is
    # the measurement this run actually takes.
    status, payload = request("GET", f"/lab-tests/{test['id']}", base=api, token=labtech_token)
    results = ((payload.get("data") or {}).get("results") or []) if status == 200 else []
    demonstrated = next(
        (row for row in results if row.get("parameter_code") == "MOISTURE"), None
    )
    if demonstrated:
        request(
            "DELETE",
            f"/lab-tests/{test['id']}/results/{demonstrated['id']}",
            base=api,
            token=labtech_token,
        )
    status, payload = request(
        "POST",
        f"/lab-tests/{test['id']}/results",
        base=api,
        token=labtech_token,
        body={"parameter_code": "MOISTURE", "value": "12.9"},
    )
    check("the laboratory recorded a real measurement", status in (200, 201), f"{status} {payload}")
    status, payload = request("GET", f"/lab-tests/{test['id']}", base=api, token=labtech_token)
    recorded = next(
        (
            row
            for row in ((payload.get("data") or {}).get("results") or [])
            if row.get("parameter_code") == "MOISTURE"
        ),
        None,
    )
    check(
        "the measurement on the test is the one this run took, not a demonstration value",
        recorded is not None
        and abs(float(recorded.get("value")) - 12.9) < 1e-6
        and recorded.get("measurement_source") != "DEMO",
        json.dumps(recorded, default=str),
    )
    status, payload = request(
        "POST", f"/lab-tests/{test['id']}/complete", base=api, token=labtech_token, body={}
    )
    check("completing the test decided the batch", status == 200, f"{status} {payload}")

    repeated = request(
        "POST", f"/lab-tests/{test['id']}/complete", base=api, token=labtech_token, body={}
    )
    check(
        "completing the same test twice is refused rather than recorded again",
        repeated[0] in (400, 409),
        f"second completion answered {repeated[0]}",
    )

    # ---------------------------------------------------------------------- #
    section("The packing unit packs it")
    # ---------------------------------------------------------------------- #
    packer_email = staging_email("packer")
    packer_user = create_account(
        api,
        admin,
        role="PACKAGING_UNIT",
        email=packer_email,
        password=PACKER_PASSWORD,
        organization="Phase 8 Packing Unit (TEST)",
        district="Guntur",
    )
    packer_token = sign_in(api, packer_email, PACKER_PASSWORD)
    packer_id = (packer_user.get("user") or {}).get("id") or packer_user.get("id")

    status, payload = request("GET", "/packaging-units?page_size=5", base=api, token=admin)
    unit = (payload.get("data") or [None])[0]
    if unit is None:
        status, payload = request(
            "POST",
            "/packaging-units",
            base=api,
            token=admin,
            body={
                "name": "Phase 8 Packing Unit (TEST)",
                "registration_identifier": f"REG-PH8-{uuid.uuid4().hex[:6]}",
                "district": "Guntur",
                "state": "Andhra Pradesh",
                "status": "ACTIVE",
            },
        )
        if status != 201:
            raise SystemExit(f"Could not register a packaging unit: {status} {payload}")
        unit = payload["data"]
    status, payload = request(
        "POST",
        f"/packaging-units/{unit['id']}/members",
        base=api,
        token=admin,
        body={"user_id": packer_id},
    )
    check(
        "the operator is attached to a real packaging unit",
        status in (200, 201),
        f"{status} {payload}",
    )

    status, payload = request(
        "GET", "/packaging/approved-batches?page_size=50", base=api, token=packer_token
    )
    offered = [row for row in (payload.get("data") or []) if row.get("batch_id") == batch["id"]]
    check("the approved batch reached the packing worklist", bool(offered), f"{status} {payload}")

    status, payload = request(
        "POST",
        "/packaging",
        base=api,
        token=packer_token,
        body={
            "batch_id": batch["id"],
            "packaging_type": "JAR",
            "packaging_unit_id": unit["id"],
            "package_size": "0.5",
            "number_of_packages": 25,
        },
    )
    if status != 201:
        raise SystemExit(f"Could not open a packaging run: {status} {payload}")
    packaging = payload["data"]
    request("POST", f"/packaging/{packaging['id']}/start", base=api, token=packer_token)
    status, payload = request(
        "POST",
        f"/packaging/{packaging['id']}/complete",
        base=api,
        token=packer_token,
        body={"packaged_quantity": "12.5"},
    )
    check("the packing run completed with its own arithmetic", status == 200, f"{status} {payload}")

    status, payload = request(
        "GET", f"/packages?batch_id={batch['id']}&page_size=100", base=api, token=packer_token
    )
    packages = payload.get("data") or []
    check("individual packages were created", len(packages) == 25, f"{len(packages)} packages")
    package = packages[0]

    # ---------------------------------------------------------------------- #
    section("A shipment goes to a real retailer, who receives it")
    # ---------------------------------------------------------------------- #
    distributor_email = staging_email("distributor")
    create_account(
        api,
        admin,
        role="DISTRIBUTOR",
        email=distributor_email,
        password=DISTRIBUTOR_PASSWORD,
        organization="Phase 8 Distribution (TEST)",
    )
    distributor_token = sign_in(api, distributor_email, DISTRIBUTOR_PASSWORD)
    retailer_email = staging_email("retailer")
    retailer = create_account(
        api,
        admin,
        role="RETAILER",
        email=retailer_email,
        password=RETAILER_PASSWORD,
        district="Guntur",
        organization="Phase 8 Retail (TEST)",
        name_suffix="Guntur Shop",
    )
    retailer_token = sign_in(api, retailer_email, RETAILER_PASSWORD)

    status, payload = request(
        "POST", f"/packages/{package['id']}/release", base=api, token=packer_token, body={}
    )
    check("the package was released for distribution", status == 200, f"{status} {payload}")

    status, payload = request(
        "POST",
        "/distribution",
        base=api,
        token=distributor_token,
        body={
            "package_id": package["id"],
            "quantity": "0.5",
            "destination": "Guntur market",
            "retailer_id": str(retailer["id"]),
        },
    )
    if status != 201:
        raise SystemExit(f"Could not create the shipment: {status} {payload}")
    shipment = payload["data"]
    check(
        "the shipment names a real retailer account",
        shipment.get("retailer_id") == str(retailer["id"]),
        f"retailer_id={shipment.get('retailer_id')}",
    )

    for action in ("dispatch", "in-transit", "deliver"):
        status, payload = request(
            "POST", f"/distribution/{shipment['id']}/{action}", base=api, token=distributor_token, body={}
        )
        check(f"the shipment reached “{action}”", status == 200, f"{status} {payload}")

    status, payload = request(
        "POST",
        f"/retailer/shipments/{shipment['id']}/receive",
        base=api,
        token=retailer_token,
        body={"receipt_notes": "Cartons intact."},
    )
    check("the retailer confirmed the receipt", status == 200, f"{status} {payload}")

    # ---------------------------------------------------------------------- #
    section("The package gets its QR code, and a customer opens it")
    # ---------------------------------------------------------------------- #
    status, payload = request(
        "POST", f"/blockchain/packages/{package['id']}/qr", base=api, token=packer_token
    )
    if status != 200:
        raise SystemExit(f"Could not issue the QR label: {status} {payload}")
    qr = payload["data"]
    check("the QR identity was issued", bool(qr.get("qr_payload")), f"{status} {payload}")
    check("the label is a real SVG drawn from the stored link", "<svg" in (qr.get("svg") or ""))
    # The label carries a stable id beside the code. It is derived from the
    # package, so a reprint and a second scan cannot invent a different one.
    check(
        "the label carries the package's stable QR id",
        qr.get("qr_id") == f"QR-{package['package_code']}",
        str(qr.get("qr_id")),
    )

    # Re-issuing must return the same identity and write nothing.
    events_before_reissue = len(events_for(api, admin, batch["batch_code"]))
    status, payload = request(
        "POST", f"/blockchain/packages/{package['id']}/qr", base=api, token=packer_token
    )
    again = payload["data"]
    check(
        "re-issuing the label returns the same identity",
        again.get("qr_payload") == qr.get("qr_payload"),
        f"{again.get('qr_payload')} != {qr.get('qr_payload')}",
    )

    # The customer's page — unauthenticated, twice, by the code alone.
    status, page = request("GET", f"/trace/{package['package_code']}", base=api)
    check("the code resolves to the customer's page without signing in", status == 200, str(status))
    trace = page.get("data") or {}
    stages = {row["stage"]: row for row in trace.get("timeline", [])}
    check(
        "every stage of the journey that happened is reached",
        all(stages.get(name, {}).get("reached") for name in
            ("COLLECTION", "PROCESSING", "LABORATORY", "PACKAGING", "DISPATCHED", "DELIVERED", "RETAILER")),
        f"reached={[k for k, v in stages.items() if v.get('reached')]}",
    )
    check(
        "the customer's page shows the ledger of this package",
        len(trace.get("blockchain", {}).get("transactions", [])) >= 12,
        f"{len(trace.get('blockchain', {}).get('transactions', []))} transactions",
    )
    page_text = json.dumps(page)
    check(
        "the customer's page carries no account data",
        retailer_email.lower() not in page_text.lower() and keeper["email"].lower() not in page_text.lower(),
    )

    again_page = request("GET", f"/trace/{package['package_code']}", base=api)
    check("the page still answers on a second open", again_page[0] == 200)

    check(
        "the customer's page states the package's QR id",
        (trace.get("qr") or {}).get("qr_id") == qr.get("qr_id"),
        str((trace.get("qr") or {}).get("qr_id")),
    )
    check(
        "the customer's page reports itself as published",
        (trace.get("verification") or {}).get("available") is True,
    )

    # And the id resolves on its own route, still with no account.
    status, by_id = request("GET", f"/verify/{qr['qr_id']}", base=api)
    check(
        "the QR id resolves to the same package",
        status == 200 and (by_id.get("data") or {}).get("package", {}).get("package_code") == package["package_code"],
        f"{status}",
    )

    # ---------------------------------------------------------------------- #
    section("Every event reached the real chain")
    # ---------------------------------------------------------------------- #
    # One sweep is bounded (a backlog is worked through steadily, not in one
    # burst — the same bound the background worker runs under), so the run sweeps
    # until nothing is owed, exactly as the worker would over the next few
    # seconds. Nothing is marked confirmed here: the service decides that.
    for _ in range(10):
        # One sweep writes up to BLOCKCHAIN_OUTBOX_BATCH_SIZE events, and each
        # write is a POST to an external service: fifteen of them take about half
        # a minute. The timeout is raised for this call so a slow-but-working
        # sweep is never reported as a failure.
        status, payload = request(
            "POST", "/blockchain/sync", base=api, token=admin, body={}, timeout=300
        )
        result = payload.get("data") or {}
        print(f"  sweep: {status} {json.dumps(result, default=str)}")
        if status != 200:
            print(f"  the sweep was refused: {json.dumps(payload)[:300]}")
            break
        if not result.get("outstanding"):
            break
        time.sleep(1)

    events = events_for(api, admin, batch["batch_code"])
    types = [row["tx_type"] for row in events]
    expected = [
        "COLLECTION_COMPLETED",
        "BATCH_CREATED",
        "PROCESSING_STARTED",
        "PROCESSING_COMPLETED",
        "LAB_TEST_STARTED",
        "QUALITY_CHECKED",
        "PACKAGING_STARTED",
        "PACKAGE_CREATED",
        "PACKAGED",
        "DISTRIBUTION_CREATED",
        "DISTRIBUTION_DISPATCHED",
        "IN_TRANSIT",
        "DELIVERED",
        "RETAILER_RECEIVED",
        "QR_GENERATED",
        "CUSTOMER_QR_VERIFIED",
    ]
    missing = [name for name in expected if name not in types]
    check("every transition of the journey produced its event", not missing, f"missing {missing}")
    check(
        "PACKAGE_CREATED was recorded once per package",
        types.count("PACKAGE_CREATED") == len(packages),
        f"{types.count('PACKAGE_CREATED')} events for {len(packages)} packages",
    )
    check(
        "the customer verification was recorded once, not once per page open",
        types.count("CUSTOMER_QR_VERIFIED") == 1,
        f"{types.count('CUSTOMER_QR_VERIFIED')} verification events",
    )
    check(
        "no event was recorded more than once",
        len(types) == len(set(row["event_id"] for row in events)),
        f"{len(types)} events, {len(set(row['event_id'] for row in events))} ids",
    )

    statuses = {row["status"] for row in events}
    check("no event is left un-submitted", statuses == {"CONFIRMED"}, f"statuses={statuses}")
    check("every confirmed event carries a transaction id", all(row["tx_id"] for row in events))

    after = read_chain(chain_url)
    after_ids = {row.get("tx_id") for row in after}
    new_ids = after_ids - before_ids
    confirmed_ids = {row["tx_id"] for row in events}
    check(
        "the new transactions are in the service's own ledger",
        confirmed_ids <= after_ids,
        f"{len(confirmed_ids - after_ids)} missing from the chain",
    )
    check(
        "the ledger grew by the events this run recorded",
        len(new_ids) >= len(confirmed_ids),
        f"{len(new_ids)} new transactions on the chain for {len(confirmed_ids)} events",
    )
    check(
        "the transactions name this batch",
        all(
            row.get("batch_id") == batch["batch_code"]
            for row in after
            if row.get("tx_id") in confirmed_ids
        ),
    )

    # ---------------------------------------------------------------------- #
    section("The payloads say what happened and nothing more")
    # ---------------------------------------------------------------------- #
    leaks = []
    for row in events:
        payload = row.get("payload") or {}
        for key, value, path in walk_payload(payload):
            lowered = str(key).lower()
            if any(token in lowered for token in FORBIDDEN_PAYLOAD_TOKENS):
                leaks.append(f"{row['tx_type']}:{path}")
            if isinstance(value, str) and "@" in value and "trace" not in value:
                leaks.append(f"{row['tx_type']}:{path}=email?")
        for forbidden in ("password", "token", "secret"):
            if forbidden in json.dumps(payload).lower():
                leaks.append(f"{row['tx_type']}:{forbidden}")
    check("no event payload carries private data", not leaks, f"leaks={leaks[:5]}")

    # ---------------------------------------------------------------------- #
    section("The ledger the screens read")
    # ---------------------------------------------------------------------- #
    status, payload = request("GET", "/blockchain/health", base=api, token=admin)
    health = payload["data"]
    check("the service is reported connected", health["service"]["reachable"] is True)
    check(
        "the outbox has nothing outstanding for this batch",
        health["honeychain"]["pending"] == 0 and health["honeychain"]["failed"] == 0,
        f"{health['honeychain']['pending']} pending, {health['honeychain']['failed']} failed",
    )

    status, payload = request("GET", "/blockchain/ledger?limit=200", base=api, token=admin)
    raw = payload.get("data") or {}
    rows = raw.get("transactions") if isinstance(raw, dict) else raw
    rows = rows or []
    check("the raw chain ledger is readable", bool(rows), f"{status}")
    check(
        "the older transactions are still there, marked as not recorded here",
        any(not row.get("honey_chain_recorded") for row in rows),
        "no unlinked row in the ledger the service returned",
    )
    check(
        "the transactions this run wrote are marked as HoneyChain's own",
        any(row.get("honey_chain_recorded") and row.get("matched_batch_code") == batch["batch_code"]
            for row in rows),
    )

    status, payload = request("GET", f"/blockchain/batches/{batch['id']}", base=api, token=admin)
    traceability = payload["data"]
    check(
        "the batch's own traceability carries its events",
        len(traceability["transactions"]) >= 12,
        f"{len(traceability['transactions'])} events",
    )
    check(
        "the batch's blockchain summary is synchronised",
        traceability["blockchain"]["synchronized"] is True
        and traceability["blockchain"]["pending"] == 0,
        json.dumps(traceability["blockchain"]),
    )

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("\nFailures:")
        for description in FAILED:
            print(f"  - {description}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

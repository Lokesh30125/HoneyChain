"""Phase-6 smoke test against a *running* API.

``tests/test_processing.py`` and ``tests/test_laboratory.py`` check the rules
inside one process. This script walks the same ground over HTTP, against the
development server, in the order the people involved actually work:

    a beekeeper's harvest becomes a batch → a processor opens a run against it,
    starts it, records what went in and what came out, completes it → the batch
    is ready for the laboratory → a laboratory technician records a sample and
    measures it → with nothing configured to compare against, the test is
    INCONCLUSIVE and the batch does **not** move → an administrator configures a
    reference range, saying where it came from → the next test passes and the
    batch is APPROVED → a retest is opened against the decided batch, which
    returns it to testing, and this one fails → the batch is REJECTED → an
    administrator overrides that outcome by hand, on the record.

Along the way it checks the things that are easy to claim and hard to do: that a
batch never receives a quantity nobody measured, that a completed run cannot be
edited, that a completed test's measurements cannot be rewritten, that a
beekeeper can see their own honey's progress but touch none of it, and that a KVIC
officer reads the same single records through their cluster's scope and nothing
from outside it.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_phase6.py [--base-url http://localhost:8000/api/v1]

Exit code 0 means every check passed. The fixtures it creates are throwaway
accounts, hives and facilities registered by the run; the seeded development data
is only read. Cleanup SQL is printed at the end, in an order the foreign keys
accept.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone

DEFAULT_BASE = "http://localhost:8000/api/v1"

CREDENTIALS = {
    "admin": ("admin@honeychain.example.com", "AdminSecure123"),
    "kvic": ("kvic@honeychain.example.com", "KvicSecure123"),
    "beekeeper": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "processor": ("processor@honeychain.example.com", "ProcessPass123"),
    "labtech": ("labtech@honeychain.example.com", "LabTechPass123"),
    "consumer": ("consumer@honeychain.example.com", "ConsumerPass123"),
}

#: Everything this run creates carries this marker, so cleanup is unambiguous.
MARKER = "smoke.p6"

PASSED: list[str] = []
FAILED: list[str] = []
CREATED: dict[str, list[str]] = {"users": [], "hives": [], "clusters": []}


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(f"{label} — {detail}")
        print(f"  FAIL  {label} — {detail}")


def request(
    method: str,
    path: str,
    *,
    base: str,
    token: str | None = None,
    body: dict | list | None = None,
):
    """Return ``(status, payload)``. Never raises for HTTP error statuses."""
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read() or b"{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw.decode(errors="replace")}
    except Exception as error:  # network failure
        return 0, {"error": {"code": "NETWORK", "message": str(error)}}


def login(base: str, who: str) -> str:
    email, password = CREDENTIALS[who]
    status, payload = request(
        "POST", "/auth/login", base=base, body={"email": email, "password": password}
    )
    if status != 200:
        raise SystemExit(f"Could not sign in as {who}: {status} {payload}")
    return payload["data"]["access_token"]


def register(base: str, label: str, role: str = "BEEKEEPER") -> dict:
    email = f"{MARKER}.{label}.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeP6Pass123"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": f"Smoke Phase 6 {label}",
            "email": email,
            "password": password,
            "phone": f"+9197{uuid.uuid4().int % 100000000:08d}",
            "role": role,
            "accepted_terms": True,
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register {label}: {status} {payload}")
    data = payload["data"]
    CREATED["users"].append(email)
    return {
        "email": email,
        "password": password,
        "token": data["access_token"],
        "user_id": data["user"]["id"],
        "beekeeper_id": (data.get("beekeeper") or {}).get("id"),
        "beekeeper_code": (data.get("beekeeper") or {}).get("beekeeper_code"),
    }


def make_hive(base: str, token: str, village: str) -> dict:
    status, payload = request(
        "POST",
        "/hives",
        base=base,
        token=token,
        body={
            "bee_species": "Apis cerana indica",
            "village": village,
            "district": f"Sm{uuid.uuid4().hex[:4]}",
            "state": "Andhra Pradesh",
            "notes": "Phase 6 smoke fixture",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a hive: {status} {payload}")
    CREATED["hives"].append(payload["data"]["hive_code"])
    return payload["data"]


def harvest_and_batch(base: str, keeper: dict, hives: list[tuple[str, str]], **extra) -> dict:
    """Record a harvest, complete it, and return the batch it produced."""
    body = {
        "hives": [{"hive_id": hive_id, "quantity": quantity} for hive_id, quantity in hives],
        "collection_date": date.today().isoformat(),
        "unit": "KG",
        **extra,
    }
    status, payload = request("POST", "/collections", base=base, token=keeper["token"], body=body)
    if status != 201:
        raise SystemExit(f"Could not record a harvest: {status} {payload}")
    collection = payload["data"]
    status, payload = request(
        "POST",
        f"/collections/{collection['id']}/complete",
        base=base,
        token=keeper["token"],
    )
    if status != 200:
        raise SystemExit(f"Could not complete the harvest: {status} {payload}")
    # ``/complete`` names the batch it created; the batch itself is then read from
    # its own endpoint, which is where its status and quantities live.
    meta = payload.get("meta") or {}
    if not meta.get("batch"):
        raise SystemExit(f"No batch in the completion response: {str(payload)[:400]}")
    status, payload = request(
        "GET", f"/batches/{meta['batch']['id']}", base=base, token=keeper["token"]
    )
    if status != 200:
        raise SystemExit(f"Could not read the batch: {status} {payload}")
    return {"collection": collection, "batch": payload["data"], "batch_created": meta.get("batch_created")}


def seeded_cluster(base: str, admin_token: str) -> dict | None:
    status, payload = request("GET", "/clusters?page=1&page_size=50", base=base, token=admin_token)
    if status != 200:
        return None
    for cluster in payload.get("data", []):
        if cluster.get("cluster_code") == "KVIC-GNT-001":
            return cluster
    return None


def cleanup_sql() -> str:
    users = "', '".join(CREATED["users"])
    hives = "', '".join(CREATED["hives"])
    parts = [
        "-- Rows created by tests/api_smoke_phase6.py (delete in this order):",
        "DELETE FROM lab_test_results WHERE recorded_by_id IN "
        f"(SELECT id FROM users WHERE email IN ('{users}'));",
        "DELETE FROM lab_tests WHERE technician_id IN "
        f"(SELECT id FROM users WHERE email IN ('{users}'));",
        "DELETE FROM honey_processing_records WHERE operator_id IN "
        f"(SELECT id FROM users WHERE email IN ('{users}'));",
        "DELETE FROM audit_logs WHERE actor_email IN ('{users}');".format(users=users),
        "DELETE FROM honey_batches WHERE collection_id IN (SELECT id FROM honey_collections WHERE "
        f"beekeeper_id IN (SELECT id FROM beekeepers WHERE user_id IN "
        f"(SELECT id FROM users WHERE email IN ('{users}'))));",
        "DELETE FROM honey_collections WHERE beekeeper_id IN (SELECT id FROM beekeepers WHERE user_id IN "
        f"(SELECT id FROM users WHERE email IN ('{users}')));",
        f"DELETE FROM hives WHERE hive_code IN ('{hives}');",
        "DELETE FROM processing_units WHERE notes LIKE 'Phase 6 smoke%';",
        "DELETE FROM laboratories WHERE notes LIKE 'Phase 6 smoke%';",
    ]
    return "\n".join(parts)


def main() -> int:  # noqa: C901 - a smoke script reads best as one linear story
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 70)
    print("  HoneyChain — Phase 6 smoke (processing → laboratory → quality outcome)")
    print(f"  {base}")
    print("=" * 70)

    tokens = {who: login(base, who) for who in CREDENTIALS}

    # ================================================================= #
    print("\n1. Sign-in and honest empty states")
    # ================================================================= #
    keeper = register(base, "keeper")
    other = register(base, "other")

    status, payload = request(
        "GET", "/processing/awaiting", base=base, token=keeper["token"]
    )
    check(
        "a new beekeeper has no batches awaiting processing",
        status == 200 and payload["data"] == [],
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request("GET", "/processing", base=base, token=keeper["token"])
    check("and no processing runs", status == 200 and payload["data"] == [], f"{status}")
    status, payload = request("GET", "/lab-tests", base=base, token=keeper["token"])
    check("and no laboratory tests", status == 200 and payload["data"] == [], f"{status}")
    status, payload = request("GET", "/processing/summary", base=base, token=keeper["token"])
    check(
        "the processing summary counts zero rather than guessing",
        status == 200
        and payload["data"]["total"] == 0
        and payload["data"]["awaiting_processing"] == 0
        and payload["data"]["by_unit"] == {},
        str(payload.get("data"))[:200],
    )
    status, payload = request("GET", "/lab-tests/summary", base=base, token=keeper["token"])
    check(
        "the laboratory summary counts zero",
        status == 200 and payload["data"]["total"] == 0 and payload["data"]["passed"] == 0,
        str(payload.get("data"))[:200],
    )

    # ================================================================= #
    print("\n2. Harvest → batch (unchanged from Phase 5)")
    # ================================================================= #
    hive_a = make_hive(base, keeper["token"], "Tenali")
    hive_b = make_hive(base, keeper["token"], "Tenali")
    foreign_hive = make_hive(base, other["token"], "Elsewhere")
    made = harvest_and_batch(
        base, keeper, [(hive_a["id"], "9.2"), (hive_b["id"], "4.5")]
    )
    batch = made["batch"]
    collection = made["collection"]
    batch_id = batch["id"]
    check(
        "the harvest produced a batch at COLLECTED",
        batch["status"] == "COLLECTED" and batch["current_stage"] == "COLLECTION",
        str(batch.get("status")),
    )
    check(
        "the batch carries the harvest quantity, 13.7 kg",
        float(batch["quantity"]) == 13.7 and batch["unit"] == "KG",
        str(batch.get("quantity")),
    )

    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    detail = payload["data"]
    check(
        "the batch reports no processing yet, and invents no figures for it",
        status == 200 and detail["processing_count"] == 0 and detail["processing"] is None,
        f"{status} {str(detail.get('processing'))[:120]}",
    )
    check(
        "nor any laboratory test",
        detail["test_count"] == 0 and detail["laboratory"] is None,
        str(detail.get("laboratory"))[:120],
    )
    timeline = {row["stage"]: row for row in detail["timeline"]}
    check(
        "the timeline marks the collection complete",
        timeline["COLLECTION"]["state"] == "completed",
        str(timeline.get("COLLECTION"))[:160],
    )
    check(
        "processing and laboratory are offered but not started",
        timeline["PROCESSING"]["state"] == "not_started"
        and timeline["PROCESSING"]["module_available"] is True
        and timeline["LABORATORY"]["state"] == "not_started"
        and timeline["LABORATORY"]["module_available"] is True,
        str({stage: timeline[stage]["state"] for stage in ("PROCESSING", "LABORATORY")}),
    )
    check(
        "packaging, distribution and completion are still not implemented",
        all(
            timeline[stage]["state"] == "not_started"
            and timeline[stage]["module_available"] is False
            for stage in ("PACKAGING", "DISTRIBUTION", "COMPLETED")
        ),
        str({stage: timeline[stage]["module_available"] for stage in ("PACKAGING", "DISTRIBUTION")}),
    )
    check(
        "the batch advertises only the move that is actually permitted next",
        detail["allowed_next_statuses"] == ["PROCESSING"],
        str(detail.get("allowed_next_statuses")),
    )

    # ================================================================= #
    print("\n3. Access: who may do what")
    # ================================================================= #
    status, payload = request(
        "GET", "/processing/awaiting", base=base, token=tokens["processor"]
    )
    check("a processor sees the work queue", status == 200, f"{status}")
    status, payload = request("POST", "/processing", base=base, token=keeper["token"], body={"batch_id": batch_id})
    check(
        "a beekeeper cannot open a processing run on their own honey",
        status == 403,
        f"got {status}: {str(payload)[:160]}",
    )
    status, payload = request(
        "POST", "/laboratories", base=base, token=keeper["token"], body={"name": "Nowhere"}
    )
    check("a beekeeper cannot register a laboratory", status == 403, f"got {status}")
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=tokens["processor"],
        body={"batch_id": batch_id, "laboratory_id": str(uuid.uuid4()), "sample_quantity": "0.25"},
    )
    check(
        "a processor cannot open a laboratory test",
        status == 403,
        f"got {status}: {str(payload)[:160]}",
    )
    status, payload = request("GET", "/admin/users", base=base, token=tokens["labtech"])
    check("a laboratory technician gains no administrator access", status == 403, f"got {status}")
    status, payload = request("GET", "/admin/users", base=base, token=tokens["processor"])
    check("nor does a processor", status == 403, f"got {status}")
    status, payload = request(
        "POST",
        "/collections",
        base=base,
        token=tokens["labtech"],
        body={"hives": [{"hive_id": hive_a["id"], "quantity": "1"}], "collection_date": date.today().isoformat()},
    )
    check(
        "a laboratory technician cannot record a harvest",
        status == 403,
        f"got {status}: {str(payload)[:160]}",
    )

    # ================================================================= #
    print("\n4. Processing: unit, run, start, quantities, completion")
    # ================================================================= #
    status, payload = request(
        "POST",
        "/processing-units",
        base=base,
        token=tokens["processor"],
        body={
            "name": f"Smoke Phase 6 Processing Unit {uuid.uuid4().hex[:6]}",
            "location": "Tenali Industrial Estate",
            "district": "Guntur",
            "state": "Andhra Pradesh",
            "capacity_kg_per_day": "200",
            "notes": "Phase 6 smoke fixture",
        },
    )
    check("a processor may register a processing unit", status == 201, f"{status} {str(payload)[:200]}")
    unit = payload["data"]
    check(
        "the unit code is issued by the server",
        unit["unit_code"].startswith("HC-PU-"),
        str(unit.get("unit_code")),
    )
    status, payload = request(
        "POST",
        "/processing-units",
        base=base,
        token=tokens["labtech"],
        body={"name": "Not mine to create"},
    )
    check("a laboratory technician may not register a processing unit", status == 403, f"got {status}")

    status, payload = request(
        "GET", f"/processing/awaiting?page_size=50", base=base, token=tokens["processor"]
    )
    awaiting = payload["data"]
    check(
        "the batch appears in the processing worklist",
        status == 200 and batch["batch_code"] in [row["batch_code"] for row in awaiting],
        f"{status} {[row.get('batch_code') for row in awaiting][:6]}",
    )

    status, payload = request(
        "POST",
        "/processing",
        base=base,
        token=tokens["processor"],
        body={"batch_id": str(uuid.uuid4()), "processing_type": "FILTERING"},
    )
    check("a run against a nonexistent batch is a 404", status == 404, f"got {status}")

    status, payload = request(
        "POST",
        "/processing",
        base=base,
        token=tokens["processor"],
        body={"batch_id": batch_id, "processing_type": "FILTERING", "processing_unit_id": unit["id"]},
    )
    check("opening a run against the COLLECTED batch succeeds", status == 201, f"{status} {str(payload)[:200]}")
    run = payload["data"]
    check("the run's code is issued by the server", run["processing_code"].startswith("HC-PROC-"), str(run.get("processing_code")))
    check("the run opens as PENDING", run["status"] == "PENDING", str(run.get("status")))
    check(
        "and it records no quantity it has not been told",
        run["input_quantity"] is None and run["output_quantity"] is None and run["loss_quantity"] is None,
        str({k: run.get(k) for k in ("input_quantity", "output_quantity", "loss_quantity")}),
    )
    check("the operator is the signed-in processor, not a client-supplied id", run["operator_id"] == tokens["processor_id"] if "processor_id" in tokens else run["operator_id"] is not None, str(run.get("operator_id")))
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    check(
        "opening a run does not move the batch",
        payload["data"]["status"] == "COLLECTED" and payload["data"]["processing"]["status"] == "PENDING",
        f"{payload['data']['status']} / {payload['data']['processing']['status']}",
    )

    status, payload = request(
        "POST",
        "/processing",
        base=base,
        token=tokens["processor"],
        body={"batch_id": batch_id, "processing_type": "FILTERING"},
    )
    check(
        "a second open run on the same batch is refused",
        status == 409,
        f"got {status}: {str(payload)[:200]}",
    )

    status, payload = request(
        "POST",
        f"/processing/{run['id']}/complete",
        base=base,
        token=tokens["processor"],
        body={"output_quantity": "12.9"},
    )
    check(
        "a run cannot be completed before it is started",
        status == 409,
        f"got {status}: {str(payload)[:160]}",
    )

    status, payload = request(
        "POST", f"/processing/{run['id']}/start", base=base, token=tokens["processor"]
    )
    check("starting the run succeeds", status == 200 and payload["data"]["status"] == "IN_PROGRESS", f"{status} {str(payload)[:160]}")
    check(
        "starting the run moves the batch to PROCESSING",
        payload["data"]["batch_status"] == "PROCESSING",
        str(payload["data"].get("batch_status")),
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    check(
        "the batch itself now reads PROCESSING, with the run's own start time",
        payload["data"]["status"] == "PROCESSING"
        and payload["data"]["processing"]["status"] == "IN_PROGRESS"
        and payload["data"]["processing"]["start_time"] is not None,
        str(payload["data"]["processing"].get("start_time")),
    )
    check(
        "and the collector's harvest quantity is untouched by processing",
        float(payload["data"]["quantity"]) == 13.7,
        str(payload["data"].get("quantity")),
    )

    status, payload = request(
        "PATCH",
        f"/processing/{run['id']}",
        base=base,
        token=tokens["processor"],
        body={"input_quantity": "13.7", "output_quantity": "14.1"},
    )
    check(
        "an output larger than the input is refused",
        status == 422,
        f"got {status}: {str(payload)[:200]}",
    )

    status, payload = request(
        "PATCH",
        f"/processing/{run['id']}",
        base=base,
        token=tokens["processor"],
        body={"input_quantity": "13.7", "output_quantity": "12.9", "notes": "Filtered into food-grade drums"},
    )
    check("recording the measured quantities succeeds", status == 200, f"{status} {str(payload)[:160]}")
    check(
        "the difference is stored, not left to the reader to compute",
        float(payload["data"]["loss_quantity"]) == 0.8,
        str(payload["data"].get("loss_quantity")),
    )
    check(
        "and the unit is the collection's own unit, not a unit chosen here",
        payload["data"]["unit"] == "KG" and payload["data"]["unit_label"] == collection["unit_label"],
        f"{payload['data'].get('unit')} {payload['data'].get('unit_label')} vs {collection.get('unit_label')}",
    )

    status, payload = request(
        "POST", f"/processing/{run['id']}/complete", base=base, token=tokens["labtech"]
    )
    check("a laboratory technician cannot complete a processing run", status == 403, f"got {status}")

    status, payload = request(
        "POST",
        f"/processing/{run['id']}/complete",
        base=base,
        token=tokens["processor"],
        body={},
    )
    check("completing the run succeeds", status == 200 and payload["data"]["status"] == "COMPLETED", f"{status} {str(payload)[:200]}")
    check(
        "completing the run moves the batch to LAB_TESTING",
        payload["data"]["batch_status"] == "LAB_TESTING",
        str(payload["data"].get("batch_status")),
    )
    check(
        "and the run keeps both measured figures with their difference",
        float(payload["data"]["input_quantity"]) == 13.7
        and float(payload["data"]["output_quantity"]) == 12.9
        and float(payload["data"]["loss_quantity"]) == 0.8,
        str({k: payload["data"].get(k) for k in ("input_quantity", "output_quantity", "loss_quantity")}),
    )
    check(
        "the completion time is recorded",
        payload["data"]["completion_time"] is not None,
        str(payload["data"].get("completion_time")),
    )

    status, payload = request(
        "POST", f"/processing/{run['id']}/complete", base=base, token=tokens["processor"], body={}
    )
    check(
        "completing the same run twice is refused",
        status == 409,
        f"got {status}: {str(payload)[:200]}",
    )
    status, payload = request(
        "PATCH",
        f"/processing/{run['id']}",
        base=base,
        token=tokens["processor"],
        body={"input_quantity": "13.0"},
    )
    check(
        "a completed run's quantities cannot be edited",
        status == 409,
        f"got {status}: {str(payload)[:160]}",
    )
    check(
        "and the refusal names the protected fields",
        isinstance(payload.get("error", {}).get("details", {}).get("protected_fields"), list)
        and "input_quantity" in payload["error"]["details"]["protected_fields"],
        str(payload.get("error", {}).get("details"))[:200],
    )
    status, payload = request(
        "POST",
        "/processing",
        base=base,
        token=tokens["processor"],
        body={"batch_id": batch_id, "processing_type": "FILTERING"},
    )
    check(
        "nor can a fresh run be opened on a batch that is past COLLECTED",
        status == 409,
        f"got {status}: {str(payload)[:200]}",
    )

    # ================================================================= #
    print("\n5. The batch timeline after processing")
    # ================================================================= #
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    detail = payload["data"]
    timeline = {row["stage"]: row for row in detail["timeline"]}
    check(
        "processing now reads COMPLETED, with the actual figures",
        timeline["PROCESSING"]["state"] == "completed"
        and "13.7" in (timeline["PROCESSING"]["detail"] or "")
        and "12.9" in (timeline["PROCESSING"]["detail"] or ""),
        str(timeline["PROCESSING"].get("detail"))[:200],
    )
    check(
        "the laboratory stage is current, not complete",
        timeline["LABORATORY"]["state"] == "current",
        str(timeline["LABORATORY"].get("state")),
    )
    check(
        "packaging is still honestly NOT STARTED",
        timeline["PACKAGING"]["state"] == "not_started"
        and timeline["PACKAGING"]["module_available"] is False,
        str(timeline["PACKAGING"]),
    )
    check(
        "the batch detail carries the processing summary",
        detail["processing_count"] == 1 and detail["processing"]["processing_code"] == run["processing_code"],
        str(detail.get("processing_count")),
    )
    check(
        "the beekeeper reads the run but is offered no edits to it",
        detail["processing"]["status"] == "COMPLETED",
        str(detail["processing"].get("status")),
    )

    # ================================================================= #
    print("\n6. Laboratory: facility, sample, measured values")
    # ================================================================= #
    # The run starts from a known state: this measurement is left unconfigured, so
    # the first test below has nothing to be judged against. That is not a defect
    # being worked around — it is the behaviour requirement 14 asks for, and the
    # smoke asserts it before configuring anything.
    status, payload = request(
        "PATCH",
        "/lab-parameters/MOISTURE",
        base=base,
        token=tokens["admin"],
        body={"reference_min": None, "reference_max": None, "reference_source": None, "is_required": False},
    )
    check(
        "a parameter can be returned to 'recorded, not evaluated'",
        status == 200 and payload["data"]["is_configured"] is False and payload["data"]["reference_max"] is None,
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        "/laboratories",
        base=base,
        token=tokens["labtech"],
        body={
            "name": f"Smoke Phase 6 Laboratory {uuid.uuid4().hex[:6]}",
            "location": "Guntur",
            "district": "Guntur",
            "state": "Andhra Pradesh",
            "accredited": None,
            "notes": "Phase 6 smoke fixture — accreditation not stated",
        },
    )
    check("a laboratory technician may register a laboratory", status == 201, f"{status} {str(payload)[:200]}")
    laboratory = payload["data"]
    check("the facility code is issued by the server", laboratory["laboratory_code"].startswith("HC-LABUNIT-"), str(laboratory.get("laboratory_code")))
    check(
        "the platform does not claim accreditation the facility did not state",
        laboratory["accredited"] is None,
        str(laboratory.get("accredited")),
    )

    status, payload = request(
        "GET", "/lab-tests/awaiting?page_size=50", base=base, token=tokens["labtech"]
    )
    worklist = payload["data"]
    check(
        "the batch appears in the laboratory worklist",
        status == 200 and batch["batch_code"] in [row["batch_code"] for row in worklist],
        f"{status} {[row.get('batch_code') for row in worklist][:6]}",
    )
    check(
        "and the worklist names the completed processing run behind it",
        next(row for row in worklist if row["batch_code"] == batch["batch_code"])["processing_code"]
        == run["processing_code"],
        str([row.get("processing_code") for row in worklist][:4]),
    )

    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=tokens["labtech"],
        body={"batch_id": batch_id, "laboratory_id": laboratory["id"], "sample_quantity": "0.25"},
    )
    check("opening a test against the batch succeeds", status == 201, f"{status} {str(payload)[:200]}")
    test = payload["data"]
    check("the test and sample codes are distinct and server-issued", test["test_code"].startswith("HC-LAB-") and test["sample_code"].startswith("HC-SMP-") and test["test_code"] != test["sample_code"], f"{test.get('test_code')} / {test.get('sample_code')}")
    check("the test opens as PENDING with no result claimed", test["status"] == "PENDING" and test["overall_result"] == "PENDING", f"{test.get('status')} / {test.get('overall_result')}")
    check(
        "the processing run is read from the batch, not supplied by the caller",
        test["processing_id"] == run["id"] and test["processing"]["processing_code"] == run["processing_code"],
        f"{test.get('processing_id')} vs {run['id']}",
    )
    check(
        "the sample is recorded with the quantity that was taken",
        float(test["sample_quantity"]) == 0.25 and test["sample_unit"] == "GRAM",
        f"{test.get('sample_quantity')} {test.get('sample_unit')}",
    )
    check(
        "a test cannot be opened against a batch another beekeeper cannot see",
        request(
            "POST",
            "/lab-tests",
            base=base,
            token=other["token"],
            body={"batch_id": batch_id, "laboratory_id": laboratory["id"], "sample_quantity": "0.1"},
        )[0]
        == 403,
        "other beekeeper",
    )
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=tokens["labtech"],
        body={"batch_id": batch_id, "laboratory_id": laboratory["id"], "sample_quantity": "0.1"},
    )
    check(
        "a second open test on the same batch is refused",
        status == 409,
        f"got {status}: {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=tokens["labtech"],
        body={"batch_id": str(uuid.uuid4()), "laboratory_id": laboratory["id"], "sample_quantity": "0.1"},
    )
    check("a test against a nonexistent batch is a 404", status == 404, f"got {status}")

    status, payload = request(
        "POST", f"/lab-tests/{test['id']}/complete", base=base, token=tokens["labtech"], body={}
    )
    check(
        "a test with no measurements cannot be completed",
        status == 422,
        f"got {status}: {str(payload)[:200]}",
    )

    status, payload = request(
        "POST",
        f"/lab-tests/{test['id']}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "NOT_A_PARAMETER", "value": "1"},
    )
    check("an unknown parameter is refused", status == 404, f"got {status}")

    status, payload = request(
        "POST",
        f"/lab-tests/{test['id']}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "MOISTURE", "value": "17.2", "unit": "pH"},
    )
    check(
        "a value in the wrong unit is refused",
        status == 422,
        f"got {status}: {str(payload)[:200]}",
    )

    status, payload = request(
        "POST",
        f"/lab-tests/{test['id']}/results",
        base=base,
        token=tokens["labtech"],
        body={
            "parameter_code": "MOISTURE",
            "value": "17.2",
            "method": "Refractometer",
            "remarks": "Smoke measurement — a value, not a certificate",
        },
    )
    check("recording a measured value succeeds", status == 201, f"{status} {str(payload)[:200]}")
    result = next(row for row in payload["data"]["results"] if row["parameter_code"] == "MOISTURE")
    check(
        "the value is stored exactly as measured",
        float(result["value"]) == 17.2,
        str(result.get("value")),
    )
    check(
        "with no configured range it is NOT_EVALUATED, not silently passed",
        result["status"] == "NOT_EVALUATED" and result["evaluated"] is False,
        f"{result.get('status')} evaluated={result.get('evaluated')}",
    )
    check(
        "and the test moves to IN_PROGRESS because work has begun",
        payload["data"]["status"] == "IN_PROGRESS",
        str(payload["data"].get("status")),
    )

    status, payload = request(
        "POST",
        f"/lab-tests/{test['id']}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "MOISTURE", "value": "17.5"},
    )
    check(
        "a second value for the same parameter is refused, pointing at the correction route",
        status == 409,
        f"got {status}: {str(payload)[:200]}",
    )

    status, payload = request(
        "POST", f"/lab-tests/{test['id']}/complete", base=base, token=tokens["labtech"], body={}
    )
    check("the test completes with the measurement on record", status == 200, f"{status} {str(payload)[:200]}")
    check(
        "the outcome is INCONCLUSIVE, because nothing is configured to compare against",
        payload["data"]["overall_result"] == "INCONCLUSIVE",
        str(payload["data"].get("overall_result")),
    )
    check(
        "and the reasons say so in words",
        any("reference range" in note for note in payload["data"]["evaluation_notes"]),
        str(payload["data"].get("evaluation_notes"))[:240],
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    check(
        "an inconclusive test leaves the batch at LAB_TESTING",
        payload["data"]["status"] == "LAB_TESTING",
        str(payload["data"].get("status")),
    )
    status, payload = request(
        "PATCH",
        f"/lab-tests/{test['id']}",
        base=base,
        token=tokens["labtech"],
        body={"sample_quantity": "0.30"},
    )
    check(
        "a completed test's sample details cannot be edited",
        status == 409,
        f"got {status}: {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test['id']}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "PH", "value": "4.1"},
    )
    check(
        "and no new measurement can be added to it",
        status == 409,
        f"got {status}: {str(payload)[:160]}",
    )

    # ================================================================= #
    print("\n7. Configuring what 'acceptable' means (administrator only)")
    # ================================================================= #
    status, payload = request(
        "PATCH",
        "/lab-parameters/MOISTURE",
        base=base,
        token=tokens["labtech"],
        body={"reference_min": "0", "reference_max": "20", "reference_source": "Smoke fixture"},
    )
    check(
        "a laboratory technician cannot configure a reference range",
        status == 403,
        f"got {status}: {str(payload)[:160]}",
    )
    status, payload = request(
        "PATCH",
        "/lab-parameters/MOISTURE",
        base=base,
        token=tokens["admin"],
        body={"reference_min": "0", "reference_max": "20"},
    )
    check(
        "a range with no stated source is refused",
        status == 422,
        f"got {status}: {str(payload)[:200]}",
    )
    status, payload = request(
        "PATCH",
        "/lab-parameters/MOISTURE",
        base=base,
        token=tokens["admin"],
        body={
            "reference_min": "0",
            "reference_max": "20",
            "reference_source": "Project-configured demonstration limit (not a regulatory standard)",
            "is_required": True,
        },
    )
    check("an administrator may configure the parameter", status == 200, f"{status} {str(payload)[:200]}")
    check(
        "the configuration reports itself as configured, with its source",
        payload["data"]["is_configured"] is True
        and "not a regulatory standard" in (payload["data"]["reference_source"] or ""),
        str(payload["data"].get("reference_source"))[:160],
    )
    status, payload = request("GET", "/lab-parameters", base=base, token=keeper["token"])
    check("a beekeeper may not read the parameter catalogue", status == 403, f"got {status}")
    status, payload = request("GET", "/lab-parameters", base=base, token=tokens["kvic"])
    check("a KVIC officer may read it", status == 200, f"got {status}")

    # ================================================================= #
    print("\n8. A second test on the same batch: PASS → APPROVED")
    # ================================================================= #
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=tokens["labtech"],
        body={
            "batch_id": batch_id,
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_notes": "Second sample from the same run",
        },
    )
    check("a further test on a batch still under testing is allowed", status == 201, f"{status} {str(payload)[:200]}")
    test2 = payload["data"]
    check(
        "it is a new record with its own codes, and the first test is untouched",
        test2["test_code"] != test["test_code"] and test2["round_number"] == 2,
        f"{test2.get('test_code')} round {test2.get('round_number')}",
    )
    status, payload = request("GET", f"/lab-tests/{test['id']}", base=base, token=tokens["labtech"])
    check(
        "the earlier test still reads as it did, INCONCLUSIVE and complete",
        payload["data"]["overall_result"] == "INCONCLUSIVE" and payload["data"]["status"] == "COMPLETED",
        f"{payload['data'].get('overall_result')} / {payload['data'].get('status')}",
    )

    status, payload = request(
        "POST",
        f"/lab-tests/{test2['id']}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "MOISTURE", "value": "17.4", "method": "Refractometer"},
    )
    check("the measurement is recorded", status == 201, f"{status} {str(payload)[:200]}")
    result2 = payload["data"]["results"][0]
    check(
        "now it is judged against the configured range and passes",
        result2["status"] == "PASS" and result2["evaluated"] is True,
        f"{result2.get('status')}",
    )
    check(
        "the range it was judged against is snapshotted onto the result",
        str(result2["reference_min"]) == "0.0000"
        and str(result2["reference_max"]) == "20.0000"
        and "not a regulatory standard" in (result2["reference_source"] or ""),
        f"{result2.get('reference_min')}–{result2.get('reference_max')} {result2.get('reference_source')}",
    )
    status, payload = request(
        "POST", f"/lab-tests/{test2['id']}/complete", base=base, token=tokens["labtech"], body={}
    )
    check("completing the test succeeds", status == 200, f"{status} {str(payload)[:220]}")
    check(
        "every required parameter passing gives PASS",
        payload["data"]["overall_result"] == "PASS",
        str(payload["data"].get("overall_result")),
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    detail = payload["data"]
    timeline = {row["stage"]: row for row in detail["timeline"]}
    check(
        "the batch is now APPROVED",
        detail["status"] == "APPROVED",
        str(detail.get("status")),
    )
    check(
        "the timeline shows the laboratory stage completed with the APPROVED outcome",
        timeline["LABORATORY"]["state"] == "completed"
        and timeline["LABORATORY"]["outcome"] == "APPROVED",
        str(timeline["LABORATORY"]),
    )
    check(
        "the batch detail carries the laboratory summary with recorded values only",
        detail["laboratory"]["overall_result"] == "PASS"
        and [row["parameter_code"] for row in detail["laboratory"]["results"]] == ["MOISTURE"]
        and float(detail["laboratory"]["results"][0]["value"]) == 17.4,
        str(detail.get("laboratory"))[:240],
    )
    check(
        "and the harvest quantity is still exactly what the beekeeper recorded",
        float(detail["quantity"]) == 13.7,
        str(detail.get("quantity")),
    )
    status, payload = request("GET", f"/collections/{collection['id']}", base=base, token=keeper["token"])
    check(
        "re-reading the collection confirms processing changed nothing about the harvest",
        float(payload["data"]["total_quantity"]) == 13.7,
        str(payload["data"].get("total_quantity")),
    )

    # ================================================================= #
    print("\n9. Retest: a decided batch can be examined again")
    # ================================================================= #
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=tokens["labtech"],
        body={"batch_id": batch_id, "laboratory_id": laboratory["id"], "sample_quantity": "0.2"},
    )
    check(
        "a retest on a decided batch requires a reason",
        status == 422,
        f"got {status}: {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=tokens["labtech"],
        body={
            "batch_id": batch_id,
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
            "retest_reason": "Dispute: the buyer asked for a second measurement from a fresh sample.",
        },
    )
    check("with a reason it is accepted", status == 201, f"{status} {str(payload)[:220]}")
    test3 = payload["data"]
    check(
        "the retest points back at the test it follows",
        test3["retest_of_id"] == test2["id"] and test3["round_number"] == 3,
        f"{test3.get('retest_of_id')} vs {test2['id']}",
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    check(
        "opening a retest returns the batch to LAB_TESTING",
        payload["data"]["status"] == "LAB_TESTING",
        str(payload["data"].get("status")),
    )
    check(
        "and the previous decision remains on record",
        payload["data"]["test_count"] == 3,
        str(payload["data"].get("test_count")),
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test3['id']}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "MOISTURE", "value": "21.6", "remarks": "Second sample read high"},
    )
    check("the retest measurement is recorded", status == 201, f"{status} {str(payload)[:200]}")
    check(
        "and it fails the configured range",
        payload["data"]["results"][0]["status"] == "FAIL",
        str(payload["data"]["results"][0].get("status")),
    )
    status, payload = request(
        "POST", f"/lab-tests/{test3['id']}/complete", base=base, token=tokens["labtech"], body={}
    )
    check(
        "a required failure gives FAIL",
        status == 200 and payload["data"]["overall_result"] == "FAIL",
        f"{status} {str(payload.get('data', {}).get('overall_result'))}",
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    detail = payload["data"]
    timeline = {row["stage"]: row for row in detail["timeline"]}
    check(
        "the batch is REJECTED",
        detail["status"] == "REJECTED",
        str(detail.get("status")),
    )
    check(
        "the timeline shows the laboratory stage with a REJECTED outcome rather than a plain success",
        timeline["LABORATORY"]["state"] == "completed"
        and timeline["LABORATORY"]["outcome"] == "REJECTED",
        str(timeline["LABORATORY"]),
    )
    check(
        "packaging remains unreachable for a rejected batch, as for any batch",
        timeline["PACKAGING"]["module_available"] is False
        and timeline["PACKAGING"]["state"] == "not_started",
        str(timeline["PACKAGING"]),
    )
    status, payload = request("GET", f"/lab-tests/{test3['id']}", base=base, token=tokens["labtech"])
    result3 = payload["data"]["results"][0]
    status, payload = request(
        "PATCH",
        f"/lab-tests/{test3['id']}/results/{result3['id']}",
        base=base,
        token=tokens["labtech"],
        body={"value": "17.0", "correction_reason": "attempted rewrite"},
    )
    check(
        "a completed test's measurement cannot be rewritten, not even by the technician who recorded it",
        status == 409,
        f"got {status}: {str(payload)[:160]}",
    )
    status, payload = request(
        "DELETE",
        f"/lab-tests/{test3['id']}/results/{result3['id']}",
        base=base,
        token=tokens["labtech"],
    )
    check("nor deleted", status == 409, f"got {status}")
    check(
        "the value still reads 21.6",
        float(
            request("GET", f"/lab-tests/{test3['id']}", base=base, token=tokens["labtech"])[1][
                "data"
            ]["results"][0]["value"]
        )
        == 21.6,
        "value changed",
    )

    # ================================================================= #
    print("\n10. Overriding a decision, on the record")
    # ================================================================= #
    status, payload = request(
        "POST",
        f"/lab-tests/{test3['id']}/override",
        base=base,
        token=tokens["labtech"],
        body={"overall_result": "PASS", "reason": "Should not be permitted for this role"},
    )
    check(
        "a laboratory technician cannot override an outcome",
        status == 403,
        f"got {status}: {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test3['id']}/override",
        base=base,
        token=tokens["admin"],
        body={"overall_result": "PASS", "reason": "short"},
    )
    check("a ten-character reason is required", status == 422, f"got {status}")
    status, payload = request(
        "POST",
        f"/lab-tests/{test3['id']}/override",
        base=base,
        token=tokens["admin"],
        body={"overall_result": "FAIL", "reason": "Agrees with the computed result; no override needed"},
    )
    check(
        "overriding to the computed result is refused as pointless",
        status == 422,
        f"got {status}: {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test3['id']}/override",
        base=base,
        token=tokens["admin"],
        body={
            "overall_result": "INCONCLUSIVE",
            "reason": "The sample was handled in transit; the result is not reliable enough to reject on.",
        },
    )
    check("an administrator may override with a reason", status == 200, f"{status} {str(payload)[:240]}")
    check(
        "the test is marked as overridden for every reader",
        payload["data"]["is_override"] is True
        and payload["data"]["override_reason"] is not None
        and "override" in payload["data"]["result_summary"].lower()
        or "set by hand" in (payload["data"]["result_summary"] or ""),
        str(payload["data"].get("result_summary"))[:200],
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    check(
        "an override to INCONCLUSIVE decides nothing: the batch stays under testing",
        payload["data"]["status"] == "LAB_TESTING",
        str(payload["data"].get("status")),
    )
    status, payload = request(
        "GET", "/admin/audit-logs?action=LAB_TEST_OVERRIDDEN&page_size=20",
        base=base,
        token=tokens["admin"],
    )
    check(
        "the override is in the audit log with its reason",
        status == 200
        and any(
            row.get("metadata", row.get("event_metadata", {})).get("reason", "").startswith("The sample was handled")
            for row in payload.get("data", [])
        ),
        f"{status} {str(payload)[:200]}",
    )

    # ================================================================= #
    print("\n11. Traceability and the quality summary a beekeeper sees")
    # ================================================================= #
    status, payload = request("GET", f"/lab-tests/{test2['id']}", base=base, token=keeper["token"])
    detail = payload["data"]
    kinds = [node["kind"] for node in detail["traceability"]]
    check(
        "the sample's chain runs test → sample → batch → processing → collection → hives → beekeeper → cluster → laboratory",
        status == 200
        and kinds[0] == "LAB_TEST"
        and {"SAMPLE", "BATCH", "PROCESSING", "COLLECTION", "HIVE", "BEEKEEPER", "LABORATORY"}.issubset(set(kinds)),
        str(kinds),
    )
    check(
        "every node carries a real identifier",
        all(node["identifier"] for node in detail["traceability"]),
        str([node.get("identifier") for node in detail["traceability"]])[:200],
    )
    check(
        "the beekeeper sees only their own honey's test",
        request("GET", f"/lab-tests/{test2['id']}", base=base, token=other["token"])[0] == 404,
        "other beekeeper",
    )
    status, payload = request("GET", f"/processing/{run['id']}", base=base, token=keeper["token"])
    check(
        "the beekeeper reads the processing run but is offered no actions on it",
        status == 200
        and payload["data"]["can_edit"] is False
        and payload["data"]["can_start"] is False
        and payload["data"]["can_complete"] is False
        and payload["data"]["can_cancel"] is False,
        str({k: payload["data"].get(k) for k in ("can_edit", "can_start", "can_complete")}),
    )
    status, payload = request("GET", f"/processing/{run['id']}", base=base, token=tokens["processor"])
    check(
        "a completed run offers the processor no actions either",
        payload["data"]["can_edit"] is False and payload["data"]["can_complete"] is False,
        str({k: payload["data"].get(k) for k in ("can_edit", "can_complete")}),
    )

    # ================================================================= #
    print("\n12. KVIC visibility: the same records, bounded by cluster")
    # ================================================================= #
    cluster = seeded_cluster(base, tokens["admin"])
    cluster_ok = False
    if cluster is not None:
        status, payload = request(
            "POST",
            f"/clusters/{cluster['id']}/beekeepers/{keeper['beekeeper_id']}",
            base=base,
            token=tokens["kvic"],
        )
        cluster_ok = status in (200, 201)
        check("the officer places the beekeeper in their cluster", cluster_ok, f"{status} {str(payload)[:160]}")

    if cluster_ok:
        joined = harvest_and_batch(base, keeper, [(hive_a["id"], "6.4")])
        cluster_batch = joined["batch"]
        status, payload = request(
            "POST",
            "/processing",
            base=base,
            token=tokens["processor"],
            body={"batch_id": cluster_batch["id"], "processing_type": "DECRYSTALLIZATION"},
        )
        check("a run is opened on the in-cluster batch", status == 201, f"{status} {str(payload)[:160]}")
        cluster_run = payload["data"]
        request("POST", f"/processing/{cluster_run['id']}/start", base=base, token=tokens["processor"])
        request(
            "PATCH",
            f"/processing/{cluster_run['id']}",
            base=base,
            token=tokens["processor"],
            body={"input_quantity": "6.4", "output_quantity": "6.1"},
        )
        request("POST", f"/processing/{cluster_run['id']}/complete", base=base, token=tokens["processor"])

        status, payload = request(
            "GET", f"/processing?cluster_id={cluster['id']}&page_size=50", base=base, token=tokens["kvic"]
        )
        codes = [row["processing_code"] for row in payload.get("data", [])]
        check(
            "the KVIC officer reads the cluster's processing runs",
            status == 200 and cluster_run["processing_code"] in codes,
            f"{status} {codes[:6]}",
        )
        check(
            "and not the runs of batches outside their clusters",
            run["processing_code"] not in codes,
            str(codes[:6]),
        )
        # A beekeeper who is in no cluster of this officer's: their honey is
        # processed too, and none of it may reach the officer's screens.
        other_batch = harvest_and_batch(
            base, other, [(foreign_hive["id"], "5.5")]
        )["batch"]
        status, payload = request(
            "POST",
            "/processing",
            base=base,
            token=tokens["processor"],
            body={"batch_id": other_batch["id"], "processing_type": "FILTERING"},
        )
        check("a run is opened on an out-of-cluster batch", status == 201, f"{status} {str(payload)[:160]}")
        outside_run = payload["data"]
        request("POST", f"/processing/{outside_run['id']}/start", base=base, token=tokens["processor"])
        request(
            "PATCH",
            f"/processing/{outside_run['id']}",
            base=base,
            token=tokens["processor"],
            body={"input_quantity": "5.5", "output_quantity": "5.3"},
        )
        request("POST", f"/processing/{outside_run['id']}/complete", base=base, token=tokens["processor"])

        status, payload = request("GET", "/processing?page_size=100", base=base, token=tokens["kvic"])
        seen = [row["processing_code"] for row in payload.get("data", [])]
        check(
            "the unfiltered listing is scoped to the officer's clusters",
            status == 200
            and cluster_run["processing_code"] in seen
            and outside_run["processing_code"] not in seen,
            str(seen[:8]),
        )
        status, payload = request(
            "GET", f"/processing/{outside_run['id']}", base=base, token=tokens["kvic"]
        )
        check(
            "opening an out-of-cluster run by id answers 404, not 403",
            status == 404,
            f"got {status}",
        )
        status, payload = request(
            "GET", f"/lab-tests/awaiting?page_size=100", base=base, token=tokens["kvic"]
        )
        check(
            "the laboratory worklist is scoped the same way",
            status == 200
            and outside_run["processing_code"]
            not in [row.get("processing_code") for row in payload.get("data", [])],
            str([row.get("batch_code") for row in payload.get("data", [])][:6]),
        )
        status, payload = request(
            "GET", f"/batches/{other_batch['id']}", base=base, token=tokens["kvic"]
        )
        check(
            "and the out-of-cluster batch itself is invisible to the officer",
            status == 404,
            f"got {status}",
        )
        status, payload = request(
            "POST",
            "/processing",
            base=base,
            token=tokens["kvic"],
            body={"batch_id": cluster_batch["id"], "processing_type": "FILTERING"},
        )
        check("a KVIC officer cannot process honey", status == 403, f"got {status}")
        status, payload = request(
            "POST",
            f"/lab-tests",
            base=base,
            token=tokens["kvic"],
            body={"batch_id": cluster_batch["id"], "laboratory_id": laboratory["id"], "sample_quantity": "0.1"},
        )
        check("and cannot open a laboratory test", status == 403, f"got {status}")
        status, payload = request(
            "POST",
            f"/lab-tests/{test2['id']}/override",
            base=base,
            token=tokens["kvic"],
            body={"overall_result": "PASS", "reason": "KVIC should not be able to override a result"},
        )
        check("nor override a laboratory outcome", status == 403, f"got {status}")
        status, payload = request(
            "POST",
            "/laboratories",
            base=base,
            token=tokens["kvic"],
            body={"name": "Should not be allowed"},
        )
        check("nor register a laboratory", status == 403, f"got {status}")
        status, payload = request("GET", f"/lab-tests/{test2['id']}", base=base, token=tokens["kvic"])
        check(
            "the officer cannot read a test outside their clusters",
            status == 404,
            f"got {status}",
        )

    # ================================================================= #
    print("\n13. Audit trail for everything Phase 6 did")
    # ================================================================= #
    for action, label in (
        ("PROCESSING_UNIT_CREATED", "registering a processing unit"),
        ("PROCESSING_CREATED", "opening a processing run"),
        ("PROCESSING_STARTED", "starting a run"),
        ("PROCESSING_UPDATED", "recording quantities"),
        ("PROCESSING_COMPLETED", "completing a run"),
        ("LABORATORY_CREATED", "registering a laboratory"),
        ("LAB_TEST_CREATED", "opening a test"),
        ("LAB_SAMPLE_RECORDED", "recording a sample"),
        ("LAB_RESULT_RECORDED", "recording a measurement"),
        ("LAB_TEST_COMPLETED", "completing a test"),
        ("LAB_TEST_OVERRIDDEN", "overriding an outcome"),
        ("BATCH_APPROVED", "approving a batch"),
        ("BATCH_REJECTED", "rejecting a batch"),
        ("LAB_PARAMETER_CONFIGURED", "configuring a parameter"),
    ):
        status, payload = request(
            "GET", f"/admin/audit-logs?action={action}&page_size=50", base=base, token=tokens["admin"]
        )
        rows = payload.get("data", []) if status == 200 else []
        ours = [
            row
            for row in rows
            if (row.get("actor_email") or "").startswith(MARKER)
            or (row.get("actor_email") or "") in {email for email, _ in CREDENTIALS.values()}
        ]
        check(
            f"the audit log records {label}",
            status == 200 and len(ours) > 0,
            f"{status} rows={len(rows)} ours={len(ours)}",
        )

    status, payload = request(
        "GET", "/admin/audit-logs?action=PROCESSING_COMPLETED&page_size=50", base=base, token=tokens["admin"]
    )
    entry = next(
        (row for row in payload.get("data", []) if row.get("metadata", row.get("event_metadata", {})).get("batch_code") == batch["batch_code"]),
        None,
    )
    check(
        "a processing completion entry carries the actor, the entity and the quantities",
        entry is not None
        and entry.get("actor_email")
        and entry.get("entity_type") == "processing"
        and entry.get("metadata", {}).get("input_quantity") == "13.700"
        and entry.get("metadata", {}).get("output_quantity") == "12.900",
        str(entry)[:260],
    )
    check(
        "and the previous and new batch statuses",
        entry is not None
        and entry.get("metadata", {}).get("previous_batch_status") == "PROCESSING"
        and entry.get("metadata", {}).get("batch_status") == "LAB_TESTING",
        str(entry.get("metadata") if entry else None)[:240],
    )
    status, payload = request(
        "GET", "/admin/audit-logs?action=LAB_RESULT_RECORDED&page_size=50", base=base, token=tokens["admin"]
    )
    entry = next(
        (row for row in payload.get("data", []) if row.get("metadata", row.get("event_metadata", {})).get("test_code") == test2["test_code"]),
        None,
    )
    check(
        "a recorded result is audited with its value and the range it was judged against",
        entry is not None
        and float(entry["metadata"].get("value")) == 17.4
        and str(entry["metadata"].get("reference_max")) == "20.0000"
        and entry["metadata"].get("reference_source", "").startswith("Project-configured"),
        str(entry)[:260] if entry else "no entry",
    )

    # ================================================================= #
    print("\n14. Nothing in this phase reaches beyond it")
    # ================================================================= #
    status, payload = request("GET", "/batches/summary", base=base, token=tokens["admin"])
    check("the Phase-5 batch summary still answers", status == 200, f"{status}")
    for verb, path in (
        ("POST", f"/batches/{batch_id}/package"),
        ("POST", f"/batches/{batch_id}/distribute"),
        ("GET", f"/batches/{batch_id}/qr"),
        ("GET", "/trust-score"),
        ("GET", "/blockchain/records"),
    ):
        status, payload = request(verb, path, base=base, token=tokens["admin"])
        check(
            f"{path} does not exist in this build",
            status == 404,
            f"got {status}",
        )
    status, payload = request(
        "PATCH",
        f"/batches/{batch_id}",
        base=base,
        token=tokens["admin"],
        body={"status": "PACKAGED"},
    )
    check(
        "and a batch status cannot be set directly by anyone",
        status in (404, 405),
        f"got {status}",
    )

    # ================================================================= #
    print("\n15. Leaving the catalogue as it was found")
    # ================================================================= #
    status, payload = request(
        "PATCH",
        "/lab-parameters/MOISTURE",
        base=base,
        token=tokens["admin"],
        body={"reference_min": None, "reference_max": None, "reference_source": None, "is_required": False},
    )
    check(
        "the demonstration range is cleared again",
        status == 200 and payload["data"]["is_configured"] is False,
        f"{status} {str(payload)[:200]}",
    )
    check(
        "so a later reader is not shown a limit this project invented",
        payload["data"]["reference_max"] is None and payload["data"]["reference_source"] is None,
        str(payload["data"].get("reference_source")),
    )
    status, payload = request(
        "GET", "/lab-parameters", base=base, token=tokens["admin"]
    )
    check(
        "and no parameter is left configured by this run",
        status == 200 and all(row["is_configured"] is False for row in payload["data"]),
        str([row["code"] for row in payload.get("data", []) if row.get("is_configured")]),
    )

    # ================================================================= #
    print("\n16. Earlier phases still work")
    # ================================================================= #
    status, payload = request("GET", "/health", base=base)
    check("the health endpoint answers", status == 200, f"{status}")
    status, payload = request("GET", "/hives/summary", base=base, token=tokens["admin"])
    check("the hive summary answers", status == 200, f"{status}")
    status, payload = request("GET", "/iot/devices/summary", base=base, token=tokens["admin"])
    check("the device summary answers", status == 200, f"{status}")
    status, payload = request("GET", "/clusters?page_size=5", base=base, token=tokens["admin"])
    check("the cluster registry answers", status == 200, f"{status}")
    status, payload = request("GET", "/batches?page_size=5", base=base, token=tokens["admin"])
    check("the batch listing answers", status == 200, f"{status}")
    status, payload = request("GET", "/collections?page_size=5", base=base, token=tokens["admin"])
    check("the collection listing answers", status == 200, f"{status}")
    status, payload = request(
        "GET", "/meta/roles", base=base
    )
    check("the role metadata answers", status in (200, 404), f"{status}")

    # ================================================================= #
    print("\n" + "=" * 70)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  Failures:")
        for item in FAILED:
            print(f"    - {item}")
    print("=" * 70)
    print("\nCleanup SQL (run by hand if you want the development database tidy):\n")
    print(cleanup_sql())
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

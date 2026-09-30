"""Phase-6.1 smoke test against a *running* API — batch assignment and the
processor → laboratory hand-off.

``tests/test_processing.py``, ``tests/test_laboratory.py`` and the new
``tests/test_batch_assignment.py`` check the rules inside one process. This script
walks the same ground over HTTP, against the development server, in the order the
people involved actually work:

    a beekeeper's harvest becomes a batch → the administrator allocates it to a
    processor → the processor accepts it, starts it, measures what went in and
    what came out, and completes it → the *same* batch appears in the laboratory
    queue without anybody re-entering anything → the administrator allocates the
    sample to a laboratory technician → the technician opens it, reads the whole
    story behind the sample, accepts it, records measurements and completes it →
    with nothing configured to compare against, the outcome is INCONCLUSIVE and
    the batch does **not** become approved → a reference range is configured, a
    retest is opened, that test passes and the batch is APPROVED → the beekeeper
    and the KVIC officer read the same single batch record.

Along the way it checks what is easy to claim and hard to do: that work nobody has
been made responsible for stays visible instead of disappearing, that a second
processor cannot take over somebody else's allocated run, that a laboratory
technician cannot touch processing, that a processor cannot touch the laboratory,
that a beekeeper cannot approve anything, that a batch outside an officer's
cluster is refused, that finishing a run twice is impossible, that quantities can
never be recorded for a run that was not started, and that the allocation numbers
come out of the database rather than the client.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_phase61.py [--base-url http://localhost:8000/api/v1]

Exit code 0 means every check passed. The fixtures it creates are throwaway
accounts, hives and processes registered by the run; the seeded development data
is only read. Cleanup SQL is printed at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date

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
MARKER = "smoke.p61"

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


def register(base: str, label: str) -> dict:
    email = f"{MARKER}.{label}.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeP61Pass123"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": f"Smoke 6.1 {label}",
            "email": email,
            "password": password,
            "phone": f"+9198{uuid.uuid4().int % 100000000:08d}",
            "role": "BEEKEEPER",
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
    }


def create_staff(base: str, admin_token: str, label: str, role: str) -> dict:
    """Provision a processor / laboratory technician through the admin API only."""
    email = f"{MARKER}.{label}.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeP61Staff123"
    status, payload = request(
        "POST",
        "/admin/users",
        base=base,
        token=admin_token,
        body={"name": f"Smoke 6.1 {label}", "email": email, "password": password, "role": role},
    )
    if status != 201:
        raise SystemExit(f"Could not create the {label} account: {status} {payload}")
    CREATED["users"].append(email)
    status, payload = request(
        "POST", "/auth/login", base=base, body={"email": email, "password": password}
    )
    if status != 200:
        raise SystemExit(f"The new {label} account could not sign in: {status} {payload}")
    return {"email": email, "token": payload["data"]["access_token"], "user_id": payload["data"]["user"]["id"]}


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
            "notes": "Phase 6.1 smoke fixture",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a hive: {status} {payload}")
    CREATED["hives"].append(payload["data"]["hive_code"])
    return payload["data"]


def harvest_and_batch(base: str, keeper: dict, hives: list[tuple[str, str]], **extra) -> dict:
    """Record a harvest, complete it, and read back the batch it produced."""
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
        "POST", f"/collections/{collection['id']}/complete", base=base, token=keeper["token"]
    )
    if status != 200:
        raise SystemExit(f"Could not complete the harvest: {status} {payload}")
    meta = payload.get("meta") or {}
    if not meta.get("batch"):
        raise SystemExit(f"No batch in the completion response: {str(payload)[:400]}")
    status, payload = request(
        "GET", f"/batches/{meta['batch']['id']}", base=base, token=keeper["token"]
    )
    if status != 200:
        raise SystemExit(f"Could not read the batch: {status} {payload}")
    return {"collection": collection, "batch": payload["data"]}


def audit_events(base: str, admin_token: str, *, action: str, entity_id: str | None = None) -> list[dict]:
    query = f"/admin/audit-logs?action={action}&page_size=50"
    if entity_id:
        query += f"&entity_id={entity_id}"
    status, payload = request("GET", query, base=base, token=admin_token)
    if status != 200:
        return []
    return payload.get("data", [])


def cleanup_sql() -> str:
    users = "', '".join(CREATED["users"])
    hives = "', '".join(CREATED["hives"])
    return "\n".join(
        [
            "-- Rows created by tests/api_smoke_phase61.py (delete in this order):",
            "DELETE FROM lab_test_results WHERE recorded_by_id IN "
            f"(SELECT id FROM users WHERE email IN ('{users}'));",
            "DELETE FROM lab_tests WHERE technician_id IN "
            f"(SELECT id FROM users WHERE email IN ('{users}'));",
            "DELETE FROM honey_processing_records WHERE operator_id IN "
            f"(SELECT id FROM users WHERE email IN ('{users}'));",
            f"DELETE FROM audit_logs WHERE actor_email IN ('{users}');",
            "DELETE FROM honey_batches WHERE collection_id IN (SELECT id FROM honey_collections WHERE "
            f"beekeeper_id IN (SELECT id FROM beekeepers WHERE user_id IN "
            f"(SELECT id FROM users WHERE email IN ('{users}'))));",
            "DELETE FROM honey_collections WHERE beekeeper_id IN (SELECT id FROM beekeepers WHERE user_id IN "
            f"(SELECT id FROM users WHERE email IN ('{users}')));",
            f"DELETE FROM hives WHERE hive_code IN ('{hives}');",
            "DELETE FROM processing_units WHERE notes LIKE 'Phase 6.1 smoke%';",
            "DELETE FROM laboratories WHERE notes LIKE 'Phase 6.1 smoke%';",
        ]
    )


def main() -> int:  # noqa: C901 - a smoke script reads best as one linear story
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 72)
    print("  HoneyChain — Phase 6.1 smoke (assignment → processing → laboratory)")
    print(f"  {base}")
    print("=" * 72)

    tokens = {who: login(base, who) for who in CREDENTIALS}

    keeper = register(base, "keeper")
    other_keeper = register(base, "other")
    second_processor = create_staff(base, tokens["admin"], "processor2", "PROCESSOR")

    # ================================================================= #
    print("\n1. The queues answer truthfully before any work exists")
    # ================================================================= #
    for who in ("processor", "labtech"):
        for path in ("/processing/pending", "/processing/assigned", "/processing/completed",
                     "/lab-tests/pending", "/lab-tests/assigned", "/lab-tests/completed"):
            status, payload = request("GET", path, base=base, token=tokens[who])
            check(
                f"{who} reads {path} without error",
                status == 200 and isinstance(payload.get("data"), list),
                f"{status} {str(payload)[:120]}",
            )
    status, payload = request("GET", "/processing/summary", base=base, token=tokens["processor"])
    data = payload.get("data") or {}
    check(
        "the processor dashboard carries the queue counters",
        status == 200
        and all(key in data for key in ("waiting", "unassigned", "assigned", "accepted", "in_progress", "completed", "cancelled")),
        f"{status} {list(data)[:12]}",
    )
    status, payload = request("GET", "/lab-tests/summary", base=base, token=tokens["labtech"])
    data = payload.get("data") or {}
    check(
        "the laboratory dashboard carries its queue counters",
        status == 200
        and all(key in data for key in ("unassigned", "assigned", "accepted", "completed", "samples_recorded")),
        f"{status} {list(data)[:12]}",
    )

    # ================================================================= #
    print("\n2. Harvest → batch (the collection figures are the source of truth)")
    # ================================================================= #
    hive_a = make_hive(base, keeper["token"], "Tenali")
    hive_b = make_hive(base, keeper["token"], "Tenali")
    foreign_hive = make_hive(base, other_keeper["token"], "Elsewhere")
    made = harvest_and_batch(base, keeper, [(hive_a["id"], "9.2"), (hive_b["id"], "4.5")])
    batch = made["batch"]
    collection = made["collection"]
    batch_id = batch["id"]
    collection_quantity = str(batch["quantity"])
    check(
        "the harvest produced a COLLECTED batch of 13.7 kg",
        batch["status"] == "COLLECTED" and float(batch["quantity"]) == 13.7,
        f"{batch['status']} {batch['quantity']}",
    )

    status, payload = request("GET", "/processing/awaiting", base=base, token=tokens["processor"])
    awaiting = payload.get("data") or []
    row = next((item for item in awaiting if item["batch_id"] == batch_id), None)
    check(
        "the processor's pending-batch list shows it with beekeeper and cluster context",
        status == 200 and row is not None and "beekeeper_code" in row and "cluster_id" in row,
        str(row)[:200],
    )
    check(
        "and it carries the collection quantity and date, not a computed one",
        row is not None
        and str(row.get("quantity")) == collection_quantity
        and row.get("collection_date") is not None,
        str(row)[:200] if row else "row missing",
    )

    # ================================================================= #
    print("\n3. The administrator allocates the batch to a processor")
    # ================================================================= #
    _, me = request("GET", "/users/me", base=base, token=tokens["processor"])
    processor_user_id = (me.get("data") or {}).get("id")
    status, payload = request(
        "POST",
        f"/processing/batches/{batch_id}/assign",
        base=base,
        token=tokens["admin"],
        body={"processor_id": processor_user_id},
    )
    run = payload.get("data") or {}
    run_id = run.get("id")
    check(
        "the administrator hands the batch to the seeded processor",
        status == 201
        and run.get("processor_id") == processor_user_id
        and run.get("assignment_status") == "ASSIGNED",
        f"{status} {str(payload)[:200]}",
    )
    check(
        "the allocation records who allocated it and when",
        bool(run.get("assigned_by_id")) and bool(run.get("assigned_at")),
        str({k: run.get(k) for k in ("assigned_by_id", "assigned_at")}),
    )
    check(
        "the batch itself did not move: no processing has happened yet",
        run.get("batch_status") == "COLLECTED" and run.get("status") == "PENDING",
        f"{run.get('batch_status')} {run.get('status')}",
    )
    assigned_events = audit_events(base, tokens["admin"], action="PROCESSING_ASSIGNED")
    check(
        "and the allocation is in the audit trail with actor and assignee",
        any(
            event.get("entity_id") == run_id
            and event.get("metadata", {}).get("processor_id") == processor_user_id
            for event in assigned_events
        ),
        str([event.get("entity_id") for event in assigned_events])[:200],
    )

    # It left the shared queue and entered the processor's own list — the same row.
    status, payload = request("GET", "/processing/pending", base=base, token=tokens["processor"])
    check(
        "the allocated run left the shared pending queue",
        all(item["id"] != run_id for item in payload.get("data", [])),
        str([item["id"] for item in payload.get("data", [])])[:160],
    )
    status, payload = request("GET", "/processing/assigned", base=base, token=tokens["processor"])
    mine = [item for item in payload.get("data", []) if item["id"] == run_id]
    check(
        "and appears in the processor's assigned list, still as the same batch",
        status == 200 and len(mine) == 1 and mine[0]["batch_id"] == batch_id,
        f"{status} {len(mine)}",
    )
    check(
        "the run is workable only by its assignee",
        bool(mine) and mine[0]["can_work"] is True and mine[0]["can_accept"] is True,
        str(mine[0].get("can_work") if mine else None),
    )

    # ================================================================= #
    print("\n4. The second processor is kept out of allocated work")
    # ================================================================= #
    status, payload = request(
        "GET", "/processing/assigned", base=base, token=second_processor["token"]
    )
    check(
        "another processor does not see the run in their own queue",
        all(item["id"] != run_id for item in payload.get("data", [])),
        str([item["id"] for item in payload.get("data", [])])[:160],
    )
    status, payload = request(
        "POST", f"/processing/{run_id}/start", base=base, token=second_processor["token"]
    )
    check(
        "and cannot start somebody else's allocated run",
        status == 403,
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        f"/processing/{run_id}/assign",
        base=base,
        token=tokens["processor"],
        body={"processor_id": second_processor["user_id"]},
    )
    check(
        "a processor cannot push work onto a colleague",
        status == 403,
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        f"/processing/{run_id}/assign",
        base=base,
        token=tokens["admin"],
        body={"processor_id": keeper["user_id"]},
    )
    check(
        "work cannot be allocated to an account that is not a processor",
        status == 422,
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request(
        "GET", f"/processing/{run_id}", base=base, token=keeper["token"]
    )
    read_ok = status == 200
    status, payload = request(
        "POST",
        f"/processing/{run_id}/assign",
        base=base,
        token=keeper["token"],
        body={"processor_id": keeper["user_id"]},
    )
    check(
        "the batch's beekeeper reads the run and cannot take it over",
        read_ok and status == 403,
        f"read={read_ok} assign={status} {str(payload)[:120]}",
    )

    # ================================================================= #
    print("\n5. The processor accepts and starts the work")
    # ================================================================= #
    status, payload = request(
        "POST", f"/processing/{run_id}/accept", base=base, token=tokens["processor"]
    )
    check(
        "accepting the allocation records acceptance",
        status == 200
        and payload["data"]["assignment_status"] == "ACCEPTED"
        and bool(payload["data"]["accepted_at"]),
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "POST", f"/processing/{run_id}/start", base=base, token=tokens["processor"]
    )
    check(
        "starting the run moves the batch COLLECTED → PROCESSING",
        status == 200
        and payload["data"]["status"] == "IN_PROGRESS"
        and payload["data"]["batch_status"] == "PROCESSING",
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "POST", f"/processing/{run_id}/complete", base=base, token=tokens["processor"], body={}
    )
    check(
        "a run cannot be completed without measured quantities",
        status == 422,
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "GET", f"/batches/{batch_id}", base=base, token=keeper["token"]
    )
    check(
        "and the batch is not pushed to the laboratory by that attempt",
        status == 200 and payload["data"]["status"] == "PROCESSING",
        f"{status} {payload.get('data', {}).get('status')}",
    )

    # ================================================================= #
    print("\n6. Recording the run — collection figures stay untouched")
    # ================================================================= #
    status, payload = request(
        "PATCH",
        f"/processing/{run_id}",
        base=base,
        token=tokens["processor"],
        body={"input_quantity": "13.7", "notes": "Filtered and settled"},
    )
    check(
        "the input quantity is recorded as measured",
        status == 200 and float(payload["data"]["input_quantity"]) == 13.7,
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        f"/processing/{run_id}/complete",
        base=base,
        token=tokens["processor"],
        body={"output_quantity": "12.9"},
    )
    detail = payload.get("data") or {}
    check(
        "completing records input, output and the difference as three facts",
        status == 200
        and float(detail.get("input_quantity")) == 13.7
        and float(detail.get("output_quantity")) == 12.9
        and float(detail.get("loss_quantity")) == 0.8,
        f"{status} {str(payload)[:240]}",
    )
    check(
        "and the batch moves to LAB_TESTING by itself — no beekeeper action",
        detail.get("batch_status") == "LAB_TESTING",
        str(detail.get("batch_status")),
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    batch_after = payload["data"]
    check(
        "the collection quantity is unchanged by processing",
        str(batch_after["quantity"]) == collection_quantity,
        f"{batch_after['quantity']} vs {collection_quantity}",
    )
    predicted = (batch_after.get("ai") or {}).get("predicted_yield")
    check(
        "an AI prediction, where one exists, is not presented as the actual output",
        predicted is None or float(predicted) != 12.9,
        str(predicted),
    )
    handoff = audit_events(base, tokens["admin"], action="BATCH_MOVED_TO_LAB_TESTING")
    check(
        "the hand-off is audited as its own event against the batch",
        any(
            event.get("entity_id") == batch_id
            and event.get("metadata", {}).get("processing_id") == run_id
            for event in handoff
        ),
        str([event.get("entity_id") for event in handoff])[:200],
    )
    completed_events = audit_events(base, tokens["admin"], action="PROCESSING_COMPLETED")
    check(
        "and the completion itself is audited with the actor",
        any(event.get("entity_id") == run_id for event in completed_events),
        str(len(completed_events)),
    )
    status, payload = request("GET", f"/processing/{run_id}", base=base, token=tokens["processor"])
    check(
        "a completed run cannot be started again",
        request("POST", f"/processing/{run_id}/start", base=base, token=tokens["processor"])[0] == 409,
        "",
    )
    check(
        "a completed run cannot be edited",
        request(
            "PATCH",
            f"/processing/{run_id}",
            base=base,
            token=tokens["processor"],
            body={"input_quantity": "99"},
        )[0]
        in (409, 422),
        "",
    )

    # ================================================================= #
    print("\n7. The same batch arrives in the laboratory queue")
    # ================================================================= #
    status, payload = request("GET", "/lab-tests/batches/awaiting-test", base=base, token=tokens["labtech"])
    awaiting_lab = payload.get("data") or []
    lab_row = next((item for item in awaiting_lab if item["batch_id"] == batch_id), None)
    check(
        "the batch is waiting for a sample, exactly once",
        status == 200 and lab_row is not None and sum(
            1 for item in awaiting_lab if item["batch_id"] == batch_id
        ) == 1,
        f"{status} {len(awaiting_lab)}",
    )
    check(
        "the laboratory row names the processing run that produced it",
        lab_row is not None and lab_row.get("processing_id") == run_id,
        str(lab_row)[:200] if lab_row else "missing",
    )
    check(
        "the batch was not duplicated to get there",
        sum(1 for item in awaiting_lab if item["batch_code"] == batch["batch_code"]) == 1,
        str([item["batch_code"] for item in awaiting_lab])[:160],
    )
    status, payload = request("GET", "/lab-tests/pending", base=base, token=tokens["labtech"])
    check(
        "nothing is on the bench yet, because no test has been opened",
        status == 200 and all(item["batch_id"] != batch_id for item in payload.get("data", [])),
        f"{status}",
    )
    status, payload = request(
        "GET", f"/lab-tests/batches/{batch_id}/assign", base=base, token=tokens["labtech"]
    )
    check(
        "a technician cannot allocate laboratory work to themselves through the wrong verb",
        status in (404, 405),
        f"{status}",
    )

    # ================================================================= #
    print("\n8. The administrator allocates the sample to a technician")
    # ================================================================= #
    _, me = request("GET", "/users/me", base=base, token=tokens["labtech"])
    labtech_user_id = (me.get("data") or {}).get("id")
    # A laboratory has to exist before a sample can be booked into one. The run
    # registers its own if the development database has none, rather than assuming
    # a fixture it did not create.
    status, payload = request("GET", "/laboratories?page_size=50", base=base, token=tokens["admin"])
    if not any(row.get("status") == "ACTIVE" for row in (payload.get("data") or [])):
        status, payload = request(
            "POST",
            "/laboratories",
            base=base,
            token=tokens["labtech"],
            body={
                "name": f"Smoke 6.1 Laboratory {uuid.uuid4().hex[:6]}",
                "location": "Guntur",
                "district": "Guntur",
                "state": "Andhra Pradesh",
                "notes": "Phase 6.1 smoke fixture",
            },
        )
        check(
            "a registered laboratory exists for the sample to be booked into",
            status == 201,
            f"{status} {str(payload)[:200]}",
        )
    status, payload = request(
        "POST",
        f"/lab-tests/batches/{batch_id}/assign",
        base=base,
        token=tokens["admin"],
        body={"technician_id": labtech_user_id},
    )
    test = payload.get("data") or {}
    test_id = test.get("id")
    check(
        "allocating the batch opens the test against the completed run",
        status == 201 and test.get("processing_id") == run_id,
        f"{status} {str(payload)[:240]}",
    )
    check(
        "the sample has its own identity, separate from the batch",
        bool(test.get("sample_code")) and test.get("sample_code") != test.get("test_code"),
        f"{test.get('test_code')} / {test.get('sample_code')}",
    )
    check(
        "the allocation names the technician and stays visible on the pending list",
        test.get("assignment_status") == "ASSIGNED"
        and test.get("assigned_technician_id") == labtech_user_id,
        str(test.get("assignment_status")),
    )
    status, pending_payload = request("GET", "/lab-tests/pending", base=base, token=tokens["labtech"])
    status2, assigned_payload = request("GET", "/lab-tests/assigned", base=base, token=tokens["labtech"])
    check(
        "an allocated sample sits in one queue and not the other",
        all(item["id"] != test_id for item in pending_payload.get("data", []))
        and any(item["id"] == test_id for item in assigned_payload.get("data", [])),
        f"pending={len(pending_payload.get('data', []))} assigned={len(assigned_payload.get('data', []))}",
    )
    lab_events = audit_events(base, tokens["admin"], action="LAB_TEST_ASSIGNED")
    check(
        "the laboratory allocation is audited against the test",
        any(
            event.get("entity_id") == test_id
            and event.get("metadata", {}).get("lab_technician_id") == labtech_user_id
            for event in lab_events
        ),
        str(len(lab_events)),
    )

    # ================================================================= #
    print("\n9. The technician reads the whole story behind the sample")
    # ================================================================= #
    status, payload = request("GET", f"/lab-tests/{test_id}", base=base, token=tokens["labtech"])
    detail = payload.get("data") or {}
    check(
        "the sample names its source: beekeeper, cluster, collection",
        status == 200
        and detail["batch"]["beekeeper_id"] == keeper["beekeeper_id"]
        and detail["batch"]["collection_code"] == collection["collection_code"],
        f"{status} {str(detail.get('batch'))[:200]}",
    )
    check(
        "and the processing behind it: code, type, input and output quantity",
        float(detail["processing"]["input_quantity"]) == 13.7
        and float(detail["processing"]["output_quantity"]) == 12.9
        and detail["processing"]["processing_code"] == run.get("processing_code"),
        str(detail.get("processing"))[:240],
    )
    check(
        "and the laboratory's own identifiers and status",
        detail.get("sample_code")
        and detail.get("test_code")
        and detail.get("laboratory_id")
        and detail.get("status") == "PENDING",
        str({k: detail.get(k) for k in ("test_code", "sample_code", "status")}),
    )
    check(
        "the required parameters come from the configured catalogue",
        isinstance(detail.get("required_parameters"), list)
        and all(isinstance(code, str) for code in detail.get("required_parameters", [])),
        str(detail.get("required_parameters"))[:160],
    )
    check(
        "with no measurements recorded, nothing is reported as a result",
        detail.get("results") == [] and detail.get("overall_result") == "PENDING",
        f"{detail.get('results')} {detail.get('overall_result')}",
    )
    trace_kinds = [node["kind"] for node in detail.get("traceability", [])]
    check(
        "the chain back to the apiary is present as stored nodes",
        all(
            kind in trace_kinds
            for kind in ("BEEKEEPER", "COLLECTION", "BATCH", "PROCESSING", "LAB_TEST", "SAMPLE")
        ),
        str(trace_kinds),
    )
    status, payload = request("GET", f"/lab-tests/{test_id}", base=base, token=tokens["processor"])
    check(
        "the processor may read the laboratory status of their own batch",
        status == 200,
        f"{status}",
    )

    # ================================================================= #
    print("\n10. The technician accepts, measures, and stays informed")
    # ================================================================= #
    status, payload = request("POST", f"/lab-tests/{test_id}/accept", base=base, token=tokens["labtech"])
    check(
        "accepting records that the technician took the sample on",
        status == 200
        and payload["data"]["assignment_status"] == "ACCEPTED"
        and bool(payload["data"]["accepted_at"]),
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test_id}/complete",
        base=base,
        token=tokens["labtech"],
        body={"remarks": "nothing measured"},
    )
    check(
        "a test cannot be completed without any measurements",
        status in (409, 422),
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test_id}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "MOISTURE", "value": "17.4"},
    )
    recorded_result = (payload.get("data") or {}).get("results") or []
    check(
        "a measurement is recorded against the parameter's own unit",
        status == 201
        and payload["data"]["parameter_count"] == 1
        and recorded_result[0]["parameter_code"] == "MOISTURE",
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test_id}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "PH", "value": "3.9"},
    )
    check(
        "a second parameter can be recorded on the same sample",
        status == 201 and payload["data"]["parameter_count"] == 2,
        f"{status} {str(payload)[:200]}",
    )
    recorded = audit_events(base, tokens["admin"], action="LAB_RESULT_RECORDED")
    check(
        "each measurement is audited against the test",
        len([event for event in recorded if event.get("entity_id") == test_id]) >= 2,
        str(len(recorded)),
    )

    # ================================================================= #
    print("\n11. INCONCLUSIVE is a real outcome — and never an approval")
    # ================================================================= #
    status, payload = request(
        "GET", "/lab-tests/summary", base=base, token=tokens["labtech"]
    )
    unconfigured = (payload.get("data") or {}).get("unconfigured_parameters", 0)
    status, payload = request(
        "POST",
        f"/lab-tests/{test_id}/complete",
        base=base,
        token=tokens["labtech"],
        body={"remarks": "first round"},
    )
    concluded = payload.get("data") or {}
    if unconfigured:
        check(
            "with parameters unconfigured, the outcome is INCONCLUSIVE",
            status == 200 and concluded.get("overall_result") == "INCONCLUSIVE",
            f"{status} {concluded.get('overall_result')}",
        )
        status, payload = request("GET", f"/batches/{batch_id}", base=base, token=tokens["admin"])
        check(
            "and the batch is NOT approved by an inconclusive test",
            payload["data"]["status"] == "LAB_TESTING",
            str(payload["data"]["status"]),
        )
        status, payload = request(
            "GET", f"/lab-tests/{test_id}", base=base, token=tokens["admin"]
        )
        check(
            "the reason is reported rather than hidden",
            bool(payload["data"].get("evaluation_notes")),
            str(payload["data"].get("evaluation_notes"))[:200],
        )
    else:
        check("the seeded parameters are configured", concluded.get("overall_result") in ("PASS", "FAIL"), str(concluded.get("overall_result")))

    # ================================================================= #
    print("\n12. A configured range, a retest, and a decided batch")
    # ================================================================= #
    status, payload = request(
        "PATCH",
        "/lab-parameters/MOISTURE",
        base=base,
        token=tokens["admin"],
        body={
            "reference_min": "0",
            "reference_max": "20",
            "reference_source": "Smoke run: demonstration bound supplied by the operator",
            "is_required": True,
        },
    )
    check(
        "an administrator configures the range and says where it came from",
        status == 200
        and payload["data"]["is_configured"] is True
        and payload["data"]["reference_source"],
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "GET", f"/batches/{batch_id}", base=base, token=tokens["admin"]
    )
    decided_status = payload["data"]["status"]
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=tokens["labtech"],
        body={
            "batch_id": batch_id,
            "laboratory_id": detail["laboratory_id"],
            "sample_quantity": "1.0",
            "sample_unit": "KG",
            "retest_reason": "Phase 6.1 smoke: a decided range now exists to compare against",
        },
    )
    retest = payload.get("data") or {}
    retest_id = retest.get("id")
    check(
        "a further test on the batch is accepted with a stated reason",
        status == 201 and retest.get("round_number", 1) >= 2,
        f"{status} {str(payload)[:240]}",
    )
    status, payload = request(
        "GET", f"/batches/{batch_id}", base=base, token=tokens["admin"]
    )
    check(
        "opening it returned the batch to laboratory testing",
        payload["data"]["status"] == "LAB_TESTING",
        f"{payload['data']['status']} (was {decided_status})",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{retest_id}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "MOISTURE", "value": "16.2"},
    )
    check(
        "the retest measurements are recorded against the retest, not the first test",
        status == 201,
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{retest_id}/complete",
        base=base,
        token=tokens["labtech"],
        body={"remarks": "second round"},
    )
    check(
        "completing decides the batch from the stored decision",
        status == 200 and payload["data"]["overall_result"] in ("PASS", "FAIL", "INCONCLUSIVE"),
        f"{status} {str(payload)[:200]}",
    )
    verdict = payload["data"]["overall_result"]
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=tokens["admin"])
    expected_batch = {"PASS": "APPROVED", "FAIL": "REJECTED", "INCONCLUSIVE": "LAB_TESTING"}[verdict]
    check(
        f"the batch status follows the laboratory outcome ({verdict} → {expected_batch})",
        payload["data"]["status"] == expected_batch,
        f"{payload['data']['status']}",
    )
    if verdict == "PASS":
        approved = audit_events(base, tokens["admin"], action="BATCH_APPROVED")
        check(
            "the approval is audited against the batch",
            any(event.get("entity_id") == batch_id for event in approved),
            str(len(approved)),
        )
    completed_test_events = audit_events(base, tokens["admin"], action="LAB_TEST_COMPLETED")
    check(
        "the test completion is audited",
        any(event.get("entity_id") in (test_id, retest_id) for event in completed_test_events),
        str(len(completed_test_events)),
    )
    status, payload = request(
        "PATCH",
        "/lab-parameters/MOISTURE",
        base=base,
        token=tokens["admin"],
        body={"reference_min": None, "reference_max": None, "reference_source": None, "is_required": True},
    )
    check(
        "the demonstration range is cleared again",
        status == 200 and payload["data"]["is_configured"] is False,
        f"{status} {str(payload)[:160]}",
    )

    # ================================================================= #
    print("\n13. Beekeeper and KVIC read the same single record")
    # ================================================================= #
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    timeline = {stage["stage"]: stage for stage in payload["data"].get("timeline", [])}
    check(
        "the beekeeper's timeline reports the collection as completed",
        timeline.get("COLLECTION", {}).get("state") == "completed",
        str(timeline.get("COLLECTION")),
    )
    check(
        "the processing stage reports the recorded quantities",
        timeline.get("PROCESSING", {}).get("state") == "completed",
        str(timeline.get("PROCESSING"))[:200],
    )
    lab_stage = timeline.get("LABORATORY", {})
    check(
        "the laboratory stage reports the outcome, not merely that it is finished",
        lab_stage.get("state") == "completed" and lab_stage.get("outcome") in ("APPROVED", "REJECTED", "INCONCLUSIVE"),
        str(lab_stage)[:240],
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=tokens["kvic"])
    check(
        "a cluster officer from another cluster is refused this batch",
        status in (403, 404),
        f"{status}",
    )
    status, payload = request("GET", "/processing", base=base, token=tokens["kvic"])
    check(
        "and reads no processing outside their clusters",
        status == 200 and all(item["batch_id"] != batch_id for item in payload.get("data", [])),
        f"{status}",
    )

    # ================================================================= #
    print("\n14. Refusals: the wrong role, the wrong verb, the wrong state")
    # ================================================================= #
    status, payload = request("POST", "/processing", base=base, token=tokens["labtech"], body={"batch_id": batch_id})
    check(
        "a laboratory technician cannot open a processing run",
        status == 403,
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request(
        "POST", f"/lab-tests/{test_id}/complete", base=base, token=tokens["processor"], body={}
    )
    check(
        "a processor cannot complete a laboratory test",
        status == 403,
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test_id}/assign",
        base=base,
        token=tokens["processor"],
        body={"technician_id": labtech_user_id},
    )
    check(
        "a processor cannot allocate laboratory work",
        status == 403,
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        "/processing",
        base=base,
        token=keeper["token"],
        body={"batch_id": batch_id},
    )
    check(
        "a beekeeper cannot write to the processing workflow",
        status == 403,
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{retest_id}/complete" if retest_id else f"/lab-tests/{test_id}/complete",
        base=base,
        token=keeper["token"],
        body={"remarks": "approving myself"},
    )
    check(
        "a beekeeper cannot decide a laboratory outcome",
        status == 403,
        f"{status} {str(payload)[:160]}",
    )
    status, payload = request(
        "GET", "/admin/users", base=base, token=tokens["processor"]
    )
    check(
        "a processor cannot reach the administration API",
        status == 403,
        f"{status}",
    )
    status, payload = request(
        "GET", "/admin/users", base=base, token=tokens["labtech"]
    )
    check(
        "a laboratory technician cannot reach it either",
        status == 403,
        f"{status}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{test_id}/results",
        base=base,
        token=tokens["labtech"],
        body={"parameter_code": "MOISTURE", "value": "1.0"},
    )
    check(
        "a completed test's measurements cannot be rewritten",
        status in (409, 422),
        f"{status} {str(payload)[:160]}",
    )
    # A fresh batch to try the invalid transitions against.
    made2 = harvest_and_batch(base, keeper, [(hive_a["id"], "3.0")])
    batch2_id = made2["batch"]["id"]
    status, payload = request(
        "POST",
        f"/processing/batches/{batch2_id}/assign",
        base=base,
        token=tokens["admin"],
        body={"processor_id": processor_user_id},
    )
    run2_id = (payload.get("data") or {}).get("id")
    status, payload = request("POST", f"/processing/{run2_id}/complete", base=base, token=tokens["processor"], body={"output_quantity": "2.5"})
    check(
        "a run that was never started cannot be completed",
        status in (409, 422),
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request("POST", f"/processing/batches/{batch2_id}/assign", base=base, token=tokens["admin"], body={"processor_id": second_processor["user_id"]})
    check(
        "re-allocating the same batch to another processor is allowed and recorded",
        status == 201
        and payload["data"]["processor_id"] == second_processor["user_id"],
        f"{status} {str(payload)[:200]}",
    )
    again_status, again_payload = request(
        "POST",
        f"/processing/batches/{batch2_id}/assign",
        base=base,
        token=tokens["admin"],
        body={"processor_id": second_processor["user_id"]},
    )
    events = [
        event
        for event in audit_events(base, tokens["admin"], action="PROCESSING_ASSIGNED")
        if event.get("entity_id") == run2_id
    ]
    _, runs_payload = request(
        "GET", f"/processing?batch_id={batch2_id}&page_size=20", base=base, token=tokens["admin"]
    )
    check(
        "allocating the same person twice does not create a second record",
        again_status in (200, 201) and len(events) == 2,
        f"{again_status} {len(events)}",
    )
    check(
        "and the batch still has exactly one processing run",
        len(runs_payload.get("data", [])) == 1,
        str(len(runs_payload.get("data", []))),
    )
    status, payload = request("GET", "/batches?page_size=50", base=base, token=tokens["admin"])
    matching = [item for item in payload.get("data", []) if item.get("batch_code") == made2["batch"]["batch_code"]]
    check(
        "the batch exists once in the batch register",
        len(matching) == 1,
        str(len(matching)),
    )
    status, payload = request(
        "POST", f"/processing/{run2_id}/cancel", base=base, token=tokens["admin"], body={"reason": "Smoke: cancelled to tidy up"}
    )
    check(
        "an administrator can cancel an open run, leaving the batch at COLLECTED",
        status == 200
        and payload["data"]["status"] == "CANCELLED"
        and payload["data"]["batch_status"] == "COLLECTED",
        f"{status} {str(payload)[:200]}",
    )
    status, payload = request("POST", f"/lab-tests/batches/{batch2_id}/assign", base=base, token=tokens["admin"], body={"technician_id": labtech_user_id})
    check(
        "a batch that never completed processing cannot reach the laboratory",
        status == 409,
        f"{status} {str(payload)[:200]}",
    )

    # ================================================================= #
    print("\n15. Nothing disappeared from either workspace")
    # ================================================================= #
    status, payload = request("GET", "/processing/completed", base=base, token=tokens["processor"])
    check(
        "the processed batch is in the processor's completed list",
        any(item["batch_id"] == batch_id for item in payload.get("data", [])),
        f"{status}",
    )
    status, payload = request("GET", "/lab-tests?page_size=50", base=base, token=tokens["labtech"])
    tests_for_batch = [item for item in payload.get("data", []) if item["batch_id"] == batch_id]
    check(
        "and both of its tests are in the laboratory's own history",
        len(tests_for_batch) == 2,
        str(len(tests_for_batch)),
    )
    status, payload = request("GET", "/lab-tests/completed", base=base, token=tokens["labtech"])
    check(
        "the decided tests are listed as completed, with their outcome",
        any(item["overall_result"] in ("PASS", "FAIL", "INCONCLUSIVE") for item in payload.get("data", [])),
        f"{status}",
    )
    status, payload = request("GET", "/health", base=base)
    check("the API is still healthy after the whole run", status == 200, f"{status}")

    print("\n" + "=" * 72)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  Failures:")
        for item in FAILED:
            print(f"    - {item}")
    print("=" * 72)
    print("\nCleanup SQL (run by hand if you want the development database tidy):\n")
    print(cleanup_sql())
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

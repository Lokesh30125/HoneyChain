"""Phase-5 smoke test against a *running* API.

``tests/test_collections.py`` and ``tests/test_honey_batches.py`` prove the rules
inside one process, against a database the suite controls. This script walks the
same ground over HTTP, against the development server, the way the two people
involved actually use it:

    a beekeeper records a harvest from two of their own hives → the cluster is
    filled in from their membership, not from the request → the harvest is
    completed, which creates exactly one batch → the batch is read back with its
    sources, its collection and an honest AI context → a second harvest is
    cancelled, and cancelling it is the end of it (no batch, ever) → a KVIC
    officer sees the same rows through the cluster screen, read-only, and sees
    nothing at all from a beekeeper outside their clusters.

Every fixture it creates is a throwaway account registered by this run; the
seeded development data is only read. The run prints the SQL that removes what it
created, in an order the foreign keys accept.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_phase5.py [--base-url http://localhost:8000/api/v1]

Exit code 0 means every check passed.
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
    "consumer": ("consumer@honeychain.example.com", "ConsumerPass123"),
}

EMAIL_LIKE = "smoke.p5.%"

PASSED: list[str] = []
FAILED: list[str] = []


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
    status, payload = request("POST", "/auth/login", base=base, body={"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"Could not sign in as {who}: {status} {payload}")
    return payload["data"]["access_token"]


def register_beekeeper(base: str, label: str) -> dict:
    email = f"smoke.p5.{label}.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeP5Pass123"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": f"Smoke Phase 5 {label}",
            "email": email,
            "password": password,
            "phone": f"+9196{uuid.uuid4().int % 100000000:08d}",
            "role": "BEEKEEPER",
            "accepted_terms": True,
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register the throwaway beekeeper: {status} {payload}")
    data = payload["data"]
    return {
        "email": email,
        "password": password,
        "token": data["access_token"],
        "user_id": data["user"]["id"],
        "beekeeper_id": data["beekeeper"]["id"],
        "beekeeper_code": data["beekeeper"]["beekeeper_code"],
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
            "notes": "Phase 5 smoke fixture",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a hive: {status} {payload}")
    return payload["data"]


def record(base: str, token: str, hives: list[tuple[str, str]], **extra):
    """Record a harvest. ``hives`` is a list of ``(hive_id, quantity)``."""
    body = {
        "hives": [{"hive_id": hive_id, "quantity": quantity} for hive_id, quantity in hives],
        "collection_date": date.today().isoformat(),
        "unit": "KG",
        **extra,
    }
    return request("POST", "/collections", base=base, token=token, body=body)


def seeded_cluster(base: str, admin_token: str) -> dict | None:
    status, payload = request("GET", "/clusters?page=1&page_size=50", base=base, token=admin_token)
    if status != 200:
        return None
    for cluster in payload.get("data", []):
        if cluster.get("cluster_code") == "KVIC-GNT-001":
            return cluster
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 68)
    print("  HoneyChain — Phase 5 smoke (collection → honey batch)")
    print(f"  {base}")
    print("=" * 68)

    tokens = {who: login(base, who) for who in ("admin", "kvic", "beekeeper", "consumer")}

    # ------------------------------------------------- 1. honest empty state
    print("\n1. An apiary with nothing in it yet")
    keeper = register_beekeeper(base, "keeper")
    other = register_beekeeper(base, "other")

    status, payload = request("GET", "/collections", base=base, token=keeper["token"])
    check("a new beekeeper's collection list is empty", status == 200 and payload["data"] == [], str(payload)[:200])

    status, payload = request("GET", "/collections/summary", base=base, token=keeper["token"])
    check(
        "the summary reports zero rather than an error",
        status == 200 and payload["data"]["total"] == 0 and payload["data"]["harvested_totals"] == {},
        str(payload.get("data"))[:200],
    )

    status, payload = request("GET", "/collections/eligible-hives", base=base, token=keeper["token"])
    check(
        "the empty eligible-hive list explains itself in words",
        status == 200 and payload["data"]["hives"] == []
        and payload["data"]["note"] == "No eligible hives available for collection.",
        str(payload.get("data"))[:200],
    )

    status, payload = request("GET", "/batches", base=base, token=keeper["token"])
    check("a new beekeeper's batch list is empty", status == 200 and payload["data"] == [], str(payload)[:200])

    # ------------------------------------------------------ 2. the harvest
    print("\n2. Recording a harvest from two hives")
    hive_a = make_hive(base, keeper["token"], "Tenali")
    hive_b = make_hive(base, keeper["token"], "Tenali")
    foreign_hive = make_hive(base, other["token"], "Elsewhere")

    status, payload = request(
        "GET", "/collections/eligible-hives", base=base, token=keeper["token"]
    )
    check(
        "only the caller's own hives are offered",
        status == 200
        and {row["hive_code"] for row in payload["data"]["hives"]} == {hive_a["hive_code"], hive_b["hive_code"]},
        str(payload.get("data"))[:200],
    )

    status, payload = record(
        base, keeper["token"], [(hive_a["id"], "10.5"), (hive_b["id"], "7.25")]
    )
    check("a two-hive harvest is accepted", status == 201, f"{status} {payload}")
    collection = payload["data"] if status == 201 else {}
    check(
        "the total is the sum of the per-hive quantities",
        float(collection.get("total_quantity", 0)) == 17.75,
        str(collection.get("total_quantity")),
    )
    check(
        "each source hive is kept with its own code",
        collection.get("source_hive_count") == 2
        and set(collection.get("source_hive_codes", [])) == {hive_a["hive_code"], hive_b["hive_code"]},
        str(collection.get("source_hive_codes")),
    )
    check(
        "the code is issued by the server",
        str(collection.get("collection_code", "")).startswith("HC-COL-")
        and collection.get("collection_code", "").split("-")[-1].isdigit(),
        str(collection.get("collection_code")),
    )
    check(
        "a harvest recorded with no cluster claims no cluster",
        collection.get("cluster_id") is None and collection.get("cluster_code") is None,
        str(collection.get("cluster_id")),
    )
    check("a new harvest is open, not complete", collection.get("status") in {"PLANNED", "IN_PROGRESS"}, str(collection.get("status")))
    check("no batch exists yet", collection.get("has_batch") is False, str(collection.get("has_batch")))

    status, payload = record(base, keeper["token"], [(foreign_hive["id"], "3")])
    check(
        "honey cannot be recorded from another beekeeper's hive",
        status == 404,
        f"got {status}: {str(payload)[:160]}",
    )

    status, payload = record(
        base, keeper["token"], [(hive_a["id"], "3")], beekeeper_id=other["beekeeper_id"]
    )
    check(
        "a client-supplied beekeeper_id is refused outright",
        status == 422,
        f"got {status}: {str(payload)[:160]}",
    )

    status, payload = record(
        base, keeper["token"], [(hive_a["id"], "3")], cluster_id=uuid.uuid4().hex
    )
    check("a client-supplied cluster_id is refused outright", status == 422, f"got {status}")

    # ------------------------------------------------- 3. idempotent form
    print("\n3. A resubmitted form writes one harvest, not two")
    reference = f"smoke-form-{uuid.uuid4().hex[:8]}"
    status, first = request(
        "POST",
        "/collections",
        base=base,
        token=keeper["token"],
        body={
            "hives": [{"hive_id": hive_a["id"], "quantity": "2"}],
            "collection_date": date.today().isoformat(),
            "client_reference": reference,
        },
    )
    check("the first submission is created", status == 201, f"{status} {str(first)[:160]}")
    status, second = request(
        "POST",
        "/collections",
        base=base,
        token=keeper["token"],
        body={
            "hives": [{"hive_id": hive_a["id"], "quantity": "2"}],
            "collection_date": date.today().isoformat(),
            "client_reference": reference,
        },
    )
    check(
        "the repeat is acknowledged as the same record",
        status == 201 and second.get("meta", {}).get("reused") is True
        and second["data"]["id"] == first["data"]["id"],
        f"{status} {str(second.get('meta'))[:160]}",
    )
    status, listed = request("GET", "/collections?page_size=50", base=base, token=keeper["token"])
    codes = [row["collection_code"] for row in listed.get("data", [])]
    check(
        "and no second record was written",
        status == 200 and len(codes) == len(set(codes)) == 2,
        str(codes),
    )

    # ---------------------------------------- 4. the beekeeper sees their own
    print("\n4. Isolation between beekeepers")
    status, payload = request(
        "GET", f"/collections/{collection['id']}", base=base, token=other["token"]
    )
    check("another beekeeper cannot read the harvest by id", status == 404, f"got {status}")
    status, payload = request(
        "PATCH",
        f"/collections/{collection['id']}",
        base=base,
        token=other["token"],
        body={"total_quantity": "999"},
    )
    check("nor correct it", status == 404, f"got {status}")
    status, payload = request(
        "POST", f"/collections/{collection['id']}/complete", base=base, token=other["token"]
    )
    check("nor complete it (so cannot mint a batch for it)", status == 404, f"got {status}")

    # ------------------------------------------------ 5. cluster inheritance
    print("\n5. The cluster comes from the beekeeper's membership")
    cluster = seeded_cluster(base, tokens["admin"])
    if cluster is None:
        check("the seeded cluster KVIC-GNT-001 is present", False, "not found")
    else:
        status, payload = request(
            "POST",
            f"/clusters/{cluster['id']}/beekeepers/{keeper['beekeeper_id']}",
            base=base,
            token=tokens["admin"],
            body={"verification_status": "VERIFIED"},
        )
        check("the officer places the beekeeper in the cluster", status in (200, 201), f"{status} {str(payload)[:160]}")

        status, payload = record(base, keeper["token"], [(hive_a["id"], "4")])
        inherited = payload["data"] if status == 201 else {}
        check(
            "a harvest recorded afterwards inherits that cluster",
            inherited.get("cluster_id") == cluster["id"],
            f"got {inherited.get('cluster_id')}",
        )
        status, payload = request(
            "GET", f"/collections/{collection['id']}", base=base, token=keeper["token"]
        )
        check(
            "and the earlier harvest is left exactly as it was recorded",
            status == 200 and payload["data"]["cluster_id"] == collection["cluster_id"],
            f"got {payload.get('data', {}).get('cluster_id')}",
        )

        # KVIC reads the same single row.
        status, payload = request(
            "GET", f"/collections/{inherited['id']}", base=base, token=tokens["kvic"]
        )
        check(
            "the officer reads the same record the beekeeper wrote",
            status == 200 and payload["data"]["id"] == inherited["id"]
            and payload["data"]["collection_code"] == inherited["collection_code"],
            f"got {status}",
        )
        check(
            "and is offered no actions on it",
            status == 200
            and payload["data"]["can_edit"] is False
            and payload["data"]["can_complete"] is False
            and payload["data"]["can_cancel"] is False,
            str(payload.get("data", {}).get("can_edit")),
        )
        status, payload = request(
            "GET", f"/clusters/{cluster['id']}/collections?page_size=50", base=base, token=tokens["kvic"]
        )
        check(
            "the cluster screen lists that harvest",
            status == 200
            and inherited["collection_code"] in [row["collection_code"] for row in payload.get("data", [])],
            f"got {status}",
        )
        status, payload = request(
            "GET", f"/collections/{collection['id']}", base=base, token=tokens["kvic"]
        )
        check(
            "a harvest recorded outside the officer's clusters is invisible to them",
            status == 404,
            f"got {status}",
        )
        status, payload = request(
            "PATCH",
            f"/collections/{inherited['id']}",
            base=base,
            token=tokens["kvic"],
            body={"total_quantity": "1"},
        )
        check("the officer cannot correct a beekeeper's harvest", status == 403, f"got {status}")

        # Completing the in-cluster harvest gives the cluster screen a batch to
        # show — and gives this run a second, independent code to compare with.
        status, payload = request(
            "POST", f"/collections/{inherited['id']}/complete", base=base, token=keeper["token"]
        )
        check(
            "a harvest recorded after joining the cluster still completes normally",
            status == 200 and payload["meta"]["batch_created"] is True,
            f"{status} {str(payload.get('meta'))[:160]}",
        )
        cluster_batch_code = (payload.get("meta", {}).get("batch") or {}).get("batch_code")
        status, payload = request(
            "GET", f"/batches?cluster_id={cluster['id']}&page_size=50", base=base, token=keeper["token"]
        )
        check(
            "and its batch carries the inherited cluster",
            status == 200 and cluster_batch_code in [row["batch_code"] for row in payload.get("data", [])],
            f"got {status}",
        )

    status, payload = request(
        "POST",
        "/collections",
        base=base,
        token=tokens["kvic"],
        body={
            "hives": [{"hive_id": hive_a["id"], "quantity": "1"}],
            "collection_date": date.today().isoformat(),
        },
    )
    check("an officer cannot record a harvest at all", status == 403, f"got {status}")

    # ------------------------------------------ 6. completion creates a batch
    print("\n6. Completing a harvest creates exactly one batch")
    status, payload = request(
        "POST", f"/collections/{collection['id']}/complete", base=base, token=keeper["token"]
    )
    check("completion succeeds", status == 200, f"{status} {str(payload)[:200]}")
    meta = payload.get("meta", {}) if status == 200 else {}
    batch_ref = meta.get("batch", {})
    check("it reports that the batch was created", meta.get("batch_created") is True, str(meta)[:200])
    check(
        "the batch code is issued by the server",
        str(batch_ref.get("batch_code", "")).startswith("HC-BATCH-"),
        str(batch_ref.get("batch_code")),
    )
    check(
        "and the harvest is now complete",
        payload.get("data", {}).get("status") == "COMPLETED",
        str(payload.get("data", {}).get("status")),
    )
    check(
        "an AI estimate was either stored with the harvest or honestly absent",
        payload.get("data", {}).get("ai_predicted_yield_kg") is not None
        or payload.get("data", {}).get("ai_context", {}).get("difference_kg") is None,
        str(payload.get("data", {}).get("ai_context"))[:200],
    )

    status, retry = request(
        "POST", f"/collections/{collection['id']}/complete", base=base, token=keeper["token"]
    )
    check(
        "completing again returns the same batch instead of a second one",
        status == 200
        and retry["meta"]["batch_created"] is False
        and retry["meta"]["batch"]["batch_code"] == batch_ref.get("batch_code"),
        f"{status} {str(retry.get('meta'))[:200]}",
    )

    batch_id = batch_ref.get("id")
    status, payload = request("GET", "/batches", base=base, token=keeper["token"])
    mine = [row for row in payload.get("data", []) if row.get("collection_id") == collection["id"]]
    check("the beekeeper has exactly one batch for that harvest", len(mine) == 1, str(len(mine)))

    status, payload = request(
        "GET", f"/collections/{collection['id']}/batch", base=base, token=keeper["token"]
    )
    check(
        "the harvest reports its batch",
        status == 200 and payload["meta"]["batch_exists"] is True and payload["data"]["id"] == batch_id,
        f"{status} {str(payload.get('meta'))[:200]}",
    )

    # --------------------------------------------------- 7. the batch record
    print("\n7. What the batch preserves")
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    check("the batch detail is readable by its owner", status == 200, f"got {status}")
    batch = payload.get("data", {})
    check("it starts at COLLECTED", batch.get("status") == "COLLECTED" and batch.get("current_stage") == "COLLECTION", str(batch.get("status")))
    check(
        "it carries the harvest's quantity, unit and date",
        float(batch.get("quantity", 0)) == 17.75
        and batch.get("unit") == "KG"
        and batch.get("collection_date") == collection.get("collection_date"),
        f"{batch.get('quantity')} {batch.get('unit')} {batch.get('collection_date')}",
    )
    check(
        "it points at the harvest it came from",
        batch.get("collection", {}).get("collection_code") == collection.get("collection_code"),
        str(batch.get("collection"))[:200],
    )
    check(
        "it preserves every source hive and its contribution",
        {row["hive_code"] for row in batch.get("sources", [])}
        == {hive_a["hive_code"], hive_b["hive_code"]}
        and abs(sum(float(row["contribution_share"]) for row in batch.get("sources", [])) - 1.0) < 0.001,
        str(batch.get("sources"))[:200],
    )
    check(
        "it keeps the beekeeper it was made for",
        batch.get("beekeeper_code") == keeper["beekeeper_code"],
        str(batch.get("beekeeper_code")),
    )
    check(
        "no field of it is editable in this phase",
        batch.get("editable_fields") == [],
        str(batch.get("editable_fields")),
    )

    timeline = {row["stage"]: row for row in batch.get("timeline", [])}
    check(
        "the timeline marks the collection complete",
        timeline.get("COLLECTION", {}).get("state") == "completed",
        str(timeline.get("COLLECTION"))[:160],
    )
    check(
        "and marks processing and the laboratory not started but reachable",
        all(
            timeline.get(stage, {}).get("state") == "not_started"
            and timeline.get(stage, {}).get("module_available") is True
            for stage in ("PROCESSING", "LABORATORY")
        ),
        str({stage: timeline.get(stage) for stage in ("PROCESSING", "LABORATORY")})[:200],
    )
    check(
        "and marks the stages this build cannot reach as unavailable",
        all(
            timeline.get(stage, {}).get("state") == "not_started"
            and timeline.get(stage, {}).get("module_available") is False
            for stage in ("PACKAGING", "DISTRIBUTION", "COMPLETED")
        ),
        str({stage: timeline.get(stage) for stage in ("PACKAGING", "DISTRIBUTION", "COMPLETED")})[:200],
    )

    ai_context = batch.get("ai_context", {})
    check(
        "the AI context never invents a comparison",
        (ai_context.get("has_analysis") is True and ai_context.get("difference_kg") is not None)
        or (
            ai_context.get("has_analysis") is False
            and ai_context.get("predicted_yield_kg") is None
            and ai_context.get("difference_kg") is None
            and "nothing to compare" in (ai_context.get("note") or "").lower()
        ),
        str(ai_context)[:240],
    )

    status, payload = request("GET", f"/batches/{batch_id}/sources", base=base, token=keeper["token"])
    check(
        "the source-hive endpoint lists each contribution",
        status == 200 and len(payload.get("data", [])) == 2,
        f"got {status}",
    )
    status, payload = request("GET", f"/batches/{batch_id}/hives", base=base, token=keeper["token"])
    check(
        "the hive endpoint reads the registry and says it is today's state",
        status == 200
        and len(payload.get("data", [])) == 2
        and all("current registry state" in (row.get("note") or "").lower() for row in payload["data"]),
        f"got {status}",
    )
    status, payload = request("GET", f"/batches/{batch_id}/collection", base=base, token=keeper["token"])
    check(
        "the batch can be traced back to its collection",
        status == 200 and payload["data"]["collection_code"] == collection["collection_code"],
        f"got {status}",
    )
    status, payload = request("GET", f"/batches/{batch_id}/timeline", base=base, token=keeper["token"])
    check("the timeline is served on its own endpoint too", status == 200 and len(payload.get("data", [])) >= 6, f"got {status}")

    # --------------------------------------- 8. the lifecycle cannot be moved
    print("\n8. There is no way to move a batch along")
    status, _ = request("POST", "/batches", base=base, token=tokens["admin"], body={"batch_code": "HC-BATCH-2026-000001"})
    check("no batch create endpoint exists", status == 405, f"got {status}")
    status, _ = request("PATCH", f"/batches/{batch_id}", base=base, token=tokens["admin"], body={"status": "PACKAGED"})
    check("no batch update endpoint exists (not even for an administrator)", status == 405, f"got {status}")
    status, _ = request("DELETE", f"/batches/{batch_id}", base=base, token=tokens["admin"])
    check("and no delete endpoint exists", status == 405, f"got {status}")
    status, payload = request("GET", "/batches?status=PACKAGED", base=base, token=tokens["admin"])
    check(
        "nothing is filed under a later status",
        status == 200 and payload["meta"]["total_items"] == 0,
        str(payload.get("meta"))[:200],
    )
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    check(
        "and the batch is still exactly where it was",
        payload["data"]["status"] == "COLLECTED",
        str(payload.get("data", {}).get("status")),
    )

    # --------------------------------------- 9. a cancelled harvest is final
    print("\n9. A cancelled harvest never produces a batch")
    status, payload = record(base, keeper["token"], [(hive_b["id"], "6")])
    doomed = payload["data"] if status == 201 else {}
    status, payload = request(
        "POST",
        f"/collections/{doomed['id']}/cancel",
        base=base,
        token=keeper["token"],
        body={"reason": "Rain stopped the harvest"},
    )
    check(
        "the harvest is cancelled with the reason recorded",
        status == 200 and payload["data"]["status"] == "CANCELLED"
        and payload["data"]["cancellation_reason"] == "Rain stopped the harvest",
        f"{status} {str(payload.get('data'))[:160]}",
    )
    status, payload = request(
        "POST", f"/collections/{doomed['id']}/complete", base=base, token=keeper["token"]
    )
    check("completing it afterwards is refused", status == 409, f"got {status}")
    status, payload = request(
        "POST", f"/collections/{doomed['id']}/complete", base=base, token=keeper["token"]
    )
    status, payload = request(
        "PATCH", f"/collections/{doomed['id']}", base=base, token=keeper["token"], body={"total_quantity": "7"}
    )
    check("and it cannot be edited either", status == 409, f"got {status}")
    status, payload = request(
        "GET", f"/collections/{doomed['id']}/batch", base=base, token=keeper["token"]
    )
    check(
        "it reports no batch, as a fact rather than an error",
        status == 200 and payload.get("meta", {}).get("batch_exists") is False and payload.get("data") is None,
        f"{status} {str(payload)[:200]}",
    )

    # -------------------------------- 10. a completed harvest is immutable
    print("\n10. A completed harvest cannot be rewritten")
    status, payload = request(
        "PATCH",
        f"/collections/{collection['id']}",
        base=base,
        token=keeper["token"],
        body={"total_quantity": "1"},
    )
    check("correcting a completed harvest is refused", status == 409, f"got {status}")
    status, payload = request(
        "POST", f"/collections/{collection['id']}/cancel", base=base, token=keeper["token"]
    )
    check("and so is cancelling it", status == 409, f"got {status}")

    # ------------------------------------------------ 11. the audit trail
    print("\n11. The audit trail names every step")
    for action in ("COLLECTION_CREATED", "COLLECTION_COMPLETED", "COLLECTION_CANCELLED", "BATCH_CREATED"):
        status, payload = request(
            "GET", f"/admin/audit-logs?action={action}&page_size=50", base=base, token=tokens["admin"]
        )
        entries = payload.get("data", []) if status == 200 else []
        check(f"the log answers for {action}", status == 200 and len(entries) >= 1, f"got {status}, {len(entries)} entries")

    status, payload = request(
        "GET", "/admin/audit-logs?action=BATCH_CREATED&page_size=50", base=base, token=tokens["admin"]
    )
    metadata = next(
        (row.get("metadata") or {} for row in payload.get("data", []) if (row.get("metadata") or {}).get("batch_code") == batch_ref.get("batch_code")),
        {},
    )
    check(
        "a batch entry records the chain it came from",
        metadata.get("collection_code") == collection.get("collection_code")
        and bool(metadata.get("source_hive_codes")),
        str(metadata)[:240],
    )

    # ------------------------------------------------------- 12. staff scope
    print("\n12. Staff scope")
    status, payload = request(
        "GET", f"/batches/{batch_id}", base=base, token=other["token"]
    )
    check("another beekeeper cannot read the batch", status == 404, f"got {status}")

    status, payload = request("GET", "/collections", base=base, token=tokens["consumer"])
    check("a consumer has no access to harvest records", status == 403, f"got {status}")
    status, payload = request("GET", "/batches", base=base, token=tokens["consumer"])
    check("nor to batches", status == 403, f"got {status}")

    status, admin_view = request("GET", "/batches?page_size=50", base=base, token=tokens["admin"])
    admin_codes = [row["batch_code"] for row in admin_view.get("data", [])] if status == 200 else []
    check("an administrator can read every batch", status == 200 and batch_ref.get("batch_code") in admin_codes, f"got {status}")

    if cluster is not None:
        status, payload = request(
            "GET", f"/clusters/{cluster['id']}/batches?page_size=50", base=base, token=tokens["kvic"]
        )
        listed_codes = [row["batch_code"] for row in payload.get("data", [])] if status == 200 else []
        check(
            "the cluster screen lists the cluster's batches",
            status == 200 and cluster_batch_code in listed_codes,
            f"got {status}: {listed_codes}",
        )
        check(
            "and not the batch of a harvest recorded outside the cluster",
            status == 200 and batch_ref.get("batch_code") not in listed_codes,
            f"{batch_ref.get('batch_code')} in {listed_codes}",
        )

    # ------------------------------------------------------------ wind-down
    print("\nCleanup")
    print("  Fixtures created by this run (remove with SQL, in this order):")
    print(f"    DELETE FROM honey_collections WHERE beekeeper_id IN (SELECT id FROM beekeepers WHERE user_id IN (SELECT id FROM users WHERE email LIKE '{EMAIL_LIKE}'));")
    print(f"    DELETE FROM beekeepers WHERE user_id IN (SELECT id FROM users WHERE email LIKE '{EMAIL_LIKE}');")
    print(f"    DELETE FROM users WHERE email LIKE '{EMAIL_LIKE}';")

    print("\n" + "=" * 68)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 68)
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())

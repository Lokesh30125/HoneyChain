"""Phase-4.1 smoke test against a *running* API.

The suite in ``tests/test_cluster_relationships.py`` proves the rules inside one
process. This script walks the same chain over HTTP, against the development
server, the way the three people involved actually use it:

    a KVIC officer creates a cluster → a beekeeper registers a hive while
    belonging to nobody (so it lands in the unassigned worklist) → the officer
    places the beekeeper in the cluster → the hive becomes visible in the cluster
    view with no second record → the beekeeper attaches a device and posts
    telemetry → the cluster reads that telemetry and runs an analysis over it →
    the hive is moved out of the cluster, and the officer confirms it left.

Every fixture it creates is a throwaway account registered by this run; the seeded
development data is only read. The run prints the one SQL statement that removes
what it created.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_phase41.py [--base-url http://localhost:8000/api/v1]

Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_BASE = "http://localhost:8000/api/v1"

CREDENTIALS = {
    "admin": ("admin@honeychain.example.com", "AdminSecure123"),
    "kvic": ("kvic@honeychain.example.com", "KvicSecure123"),
    "beekeeper": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "consumer": ("consumer@honeychain.example.com", "ConsumerPass123"),
}

EMAIL_LIKE = "smoke.p41.%"

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
    email = f"smoke.p41.{label}.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeP41Pass123"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": f"Smoke Phase 41 {label}",
            "email": email,
            "password": password,
            "phone": f"+9197{uuid.uuid4().int % 100000000:08d}",
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


def make_cluster(base: str, token: str, label: str) -> dict:
    status, payload = request(
        "POST",
        "/clusters",
        base=base,
        token=token,
        body={
            "cluster_name": f"Phase 41 Smoke {label} {uuid.uuid4().hex[:4]}",
            "district": f"Sm{uuid.uuid4().hex[:4]}",
            "state": "Andhra Pradesh",
            "coordinator_name": "Smoke Coordinator",
            "coordinator_phone": "9876500000",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not create a cluster: {status} {payload}")
    return payload["data"]


def make_hive(base: str, token: str, name: str) -> dict:
    status, payload = request(
        "POST",
        "/hives",
        base=base,
        token=token,
        body={
            "bee_species": "Apis cerana indica",
            "village": name,
            "district": f"Sm{uuid.uuid4().hex[:4]}",
            "state": "Andhra Pradesh",
            "notes": "Phase 4.1 smoke fixture",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a hive: {status} {payload}")
    return payload["data"]


def make_device(base: str, token: str, hive_id: str) -> dict:
    device_id = f"ESP32-SM41-{uuid.uuid4().hex[:5].upper()}"
    status, payload = request(
        "POST",
        "/iot/devices",
        base=base,
        token=token,
        body={"device_id": device_id, "device_name": "Phase 41 smoke node", "hive_id": hive_id},
    )
    if status != 201:
        raise SystemExit(f"Could not attach a device: {status} {payload}")
    return payload["data"]


def post_window(base: str, token: str, device_id: str, *, samples: int = 12) -> None:
    now = datetime.now(timezone.utc)
    for index in range(samples):
        moment = now - timedelta(hours=6) + timedelta(minutes=30 * index)
        status, payload = request(
            "POST",
            "/iot/telemetry",
            base=base,
            token=token,
            body={
                "device_id": device_id,
                "timestamp": moment.isoformat(),
                "temperature": 32.5 + (index % 6) * 0.3,
                "humidity": 57.0 + (index % 4) * 0.5,
                "weight": 41.0 + index * 0.15,
                "vibration": 0.5,
                "acoustic_level": 40.0,
                "battery_level": 92,
                "source": "SIMULATOR",
            },
        )
        if status not in (200, 201):
            raise SystemExit(f"Telemetry rejected: {status} {payload}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4.1 cluster-relationship smoke test")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print("=" * 68)
    print("  HoneyChain — Phase 4.1 organisational relationship smoke test")
    print(f"  {base}")
    print("=" * 68)

    tokens = {who: login(base, who) for who in ("admin", "kvic", "beekeeper", "consumer")}

    # ------------------------------------------------------- throwaway apiaries
    member = register_beekeeper(base, "member")
    outsider = register_beekeeper(base, "outsider")

    # ------------------------------------------------- 1. before any membership
    print("\nBefore any membership")
    status, payload = request("GET", "/beekeepers/me", base=base, token=member["token"])
    check(
        "a beekeeper starts with no cluster",
        status == 200 and payload["data"]["cluster"] is None,
        str(payload.get("data", {}).get("cluster")),
    )

    hive = make_hive(base, member["token"], "Unassigned Apiary")
    check(
        "a hive registered before the cluster exists has none",
        hive["cluster"] is None,
        str(hive.get("cluster")),
    )

    status, payload = request("GET", "/hives", base=base, token=tokens["kvic"])
    keys = payload["data"][0].keys() if payload.get("data") else []
    check("the staff hive list carries the cluster column", "cluster" in keys, str(list(keys))[:120])

    status, payload = request(
        "GET", "/hives?has_cluster=false&page_size=100", base=base, token=tokens["kvic"]
    )
    codes = {row["hive_code"] for row in payload.get("data", [])}
    check(
        "the unassigned hive appears in the administrative worklist",
        status == 200 and hive["hive_code"] in codes,
        f"got {status}, {hive['hive_code']} not in {sorted(codes)[:6]}",
    )

    status, payload = request("GET", "/hives/summary", base=base, token=tokens["kvic"])
    check(
        "the staff summary reports how many hives are unplaced",
        status == 200 and payload["data"]["without_cluster"] >= 1,
        str(payload.get("data", {}).get("without_cluster")),
    )

    status, payload = request("GET", "/hives?has_cluster=false", base=base, token=member["token"])
    check(
        "a beekeeper cannot set the staff worklist filter",
        status in (200, 403, 422),
        f"got {status}",
    )

    # -------------------------------------------------- 2. the officer places them
    print("\nThe officer places the beekeeper in a cluster")
    cluster = make_cluster(base, tokens["kvic"], "Primary")
    placed = make_hive(base, member["token"], "Placed Apiary")  # still nothing: not a member yet
    status, payload = request("GET", f"/clusters/{cluster['id']}", base=base, token=tokens["kvic"])
    check(
        "the officer's new cluster starts empty",
        status == 200 and payload["data"]["member_count"] == 0,
        str(payload.get("data"))[:200],
    )

    status, payload = request(
        "POST",
        f"/clusters/{cluster['id']}/beekeepers/{member['beekeeper_id']}",
        base=base,
        token=member["token"],
    )
    check("a beekeeper cannot assign themselves to a cluster", status == 403, f"got {status}")

    status, payload = request(
        "POST",
        f"/clusters/{cluster['id']}/beekeepers/{member['beekeeper_id']}",
        base=base,
        token=tokens["kvic"],
    )
    check("a KVIC officer assigns the beekeeper", status == 200, f"got {status} {payload}")

    status, payload = request("GET", f"/hives/{hive['id']}", base=base, token=member["token"])
    check(
        "every hive of that beekeeper follows them into the cluster",
        status == 200 and payload["data"]["cluster"]["cluster_code"] == cluster["cluster_code"],
        str(payload.get("data", {}).get("cluster")),
    )

    status, payload = request(
        "POST",
        "/hives",
        base=base,
        token=member["token"],
        body={
            "bee_species": "Apis cerana indica",
            "village": "Payload Attempt",
            "district": "SmPayload",
            "state": "Andhra Pradesh",
            "cluster_id": cluster["id"],
        },
    )
    check(
        "the beekeeper cannot name a cluster in the hive payload",
        status == 422,
        f"got {status} (a 201 would mean an apiary can be published into any cluster)",
    )

    # ------------------------------------------------- 3. the cluster view agrees
    print("\nThe cluster view reads the same records")
    status, payload = request("GET", f"/clusters/{cluster['id']}/hives", base=base, token=tokens["kvic"])
    listed = {row["hive_code"] for row in payload.get("data", [])}
    check(
        "the cluster lists the beekeeper's hives",
        status == 200 and {hive["hive_code"], placed["hive_code"]} <= listed,
        f"got {status}, missing {sorted({hive['hive_code'], placed['hive_code']} - listed)}",
    )
    check(
        "and only within the cluster",
        outsider["beekeeper_code"] not in str(payload)[:4000],
        "another apiary leaked into the view",
    )

    status, payload = request("GET", f"/clusters/{cluster['id']}/summary", base=base, token=tokens["kvic"])
    overview = payload.get("data", {})
    check(
        "the overview counts members, hives and devices",
        status == 200
        and overview["beekeepers"]["total"] == 1
        and overview["hives"]["total"] == 2
        and overview["hives"]["without_device"] == 2,
        str(overview)[:240],
    )
    check(
        "the overview states that nothing has been analysed yet",
        overview.get("ai", {}).get("analysed_hives") == 0,
        str(overview.get("ai")),
    )

    status, payload = request("GET", f"/clusters/{cluster['id']}/telemetry/latest", base=base, token=tokens["kvic"])
    check(
        "a cluster with no telemetry says so instead of showing zeroes",
        status == 200 and payload["data"]["has_data"] is False,
        str(payload.get("data"))[:200],
    )

    # --------------------------------------------- 4. device, telemetry, analysis
    print("\nDevice, telemetry and analysis through the chain")
    status, payload = request(
        "GET", f"/clusters/{cluster['id']}/hives", base=base, token=member["token"]
    )
    check("a beekeeper cannot read the cluster view", status == 403, f"got {status}")

    device = make_device(base, member["token"], hive["id"])
    post_window(base, member["token"], device["device_id"])

    status, payload = request("GET", f"/clusters/{cluster['id']}/devices", base=base, token=tokens["kvic"])
    device_rows = payload.get("data", [])
    check(
        "the device is visible through its hive, not through a cluster column",
        status == 200
        and any(row["device_id"] == device["device_id"] and row["hive_code"] == hive["hive_code"] for row in device_rows),
        str(device_rows)[:200],
    )

    status, payload = request(
        "GET", f"/clusters/{cluster['id']}/telemetry/latest", base=base, token=tokens["kvic"]
    )
    chain = payload.get("data", {})
    check(
        "the latest telemetry prints the full chain",
        status == 200
        and chain.get("has_data") is True
        and chain.get("hive_code") == hive["hive_code"]
        and chain.get("device_id") == device["device_id"]
        and chain.get("beekeeper_code") == member["beekeeper_code"],
        str(chain)[:240],
    )

    status, payload = request(
        "GET", f"/clusters/{cluster['id']}/summary", base=base, token=tokens["kvic"]
    )
    check(
        "the telemetry counters follow the readings in",
        payload["data"]["telemetry"]["readings_last_24h"] >= 10
        and payload["data"]["telemetry"]["hives_with_telemetry"] == 1,
        str(payload.get("data", {}).get("telemetry")),
    )

    status, payload = request(
        "POST", f"/ai/hives/{hive['id']}/analyze", base=base, token=member["token"], body={}
    )
    analysis_id = payload.get("data", {}).get("analysis_id")
    check("the beekeeper runs an analysis on their hive", status == 200 and bool(analysis_id), f"got {status} {payload}")

    status, payload = request("GET", f"/clusters/{cluster['id']}/ai", base=base, token=tokens["kvic"])
    ai_state = payload.get("data", {})
    row = next((r for r in ai_state.get("hives", []) if r["hive_code"] == hive["hive_code"]), {})
    check(
        "the cluster reads that analysis, not a copy of it",
        status == 200 and row.get("analyzed") is True and row.get("analysis_source") == "SIMULATOR",
        str(row)[:240],
    )

    status, payload = request("GET", f"/ai/hives/{hive['id']}", base=base, token=member["token"])
    check(
        "both views resolve to the same stored analysis",
        status == 200 and str(payload["data"]["analysis_id"]) == str(analysis_id),
        f"{payload.get('data', {}).get('analysis_id')} != {analysis_id}",
    )

    status, payload = request(
        "POST",
        f"/hives/{hive['id']}/cluster",
        base=base,
        token=member["token"],
        body={"cluster_id": None},
    )
    check("a beekeeper cannot move a hive out of their cluster", status == 403, f"got {status}")

    # --------------------------------------------------- 5. moving and leaving
    print("\nMoving, then leaving")
    second = make_cluster(base, tokens["kvic"], "Secondary")
    status, payload = request(
        "POST",
        f"/hives/{placed['id']}/cluster",
        base=base,
        token=tokens["kvic"],
        body={"cluster_id": second["id"], "reason": "Relocating the apiary for the season"},
    )
    check(
        "staff place a single hive in another cluster and it is recorded",
        status == 200 and payload["data"]["cluster"]["cluster_code"] == second["cluster_code"],
        f"got {status} {str(payload)[:160]}",
    )

    status, payload = request("GET", f"/clusters/{second['id']}/hives", base=base, token=tokens["kvic"])
    check(
        "the hive now belongs to the second cluster only",
        status == 200 and [row["hive_code"] for row in payload["data"]] == [placed["hive_code"]],
        str(payload.get("data"))[:200],
    )

    status, payload = request(
        "DELETE",
        f"/clusters/{cluster['id']}/beekeepers/{member['beekeeper_id']}",
        base=base,
        token=tokens["kvic"],
    )
    check("the officer removes the beekeeper from the first cluster", status == 200, f"got {status}")

    status, payload = request("GET", f"/hives/{hive['id']}", base=base, token=member["token"])
    check(
        "the hive that followed the beekeeper left with them, and still exists",
        status == 200
        and payload["data"]["cluster"] is None
        and payload["data"]["hive_code"] == hive["hive_code"],
        str(payload.get("data", {}).get("cluster")),
    )
    status, payload = request("GET", f"/hives/{placed['id']}", base=base, token=member["token"])
    check(
        "the hive that was placed by hand stays where staff put it",
        status == 200 and payload["data"]["cluster"]["cluster_code"] == second["cluster_code"],
        str(payload.get("data", {}).get("cluster")),
    )

    status, payload = request("GET", f"/clusters/{cluster['id']}/hives", base=base, token=tokens["kvic"])
    check(
        "the first cluster no longer shows it",
        status == 200 and hive["hive_code"] not in {row["hive_code"] for row in payload["data"]},
        str(payload.get("data"))[:200],
    )

    # ------------------------------------------------------------- 6. isolation
    print("\nIsolation")
    for path in (
        f"/clusters/{cluster['id']}/summary",
        f"/clusters/{cluster['id']}/hives",
        f"/clusters/{cluster['id']}/devices",
        f"/clusters/{cluster['id']}/ai",
        f"/clusters/{cluster['id']}/telemetry/latest",
    ):
        status, _ = request("GET", path, base=base, token=member["token"])
        check(f"a beekeeper is refused {path.split('/')[-1]}", status == 403, f"got {status}")

    status, _ = request("GET", f"/clusters/{cluster['id']}/summary", base=base, token=tokens["consumer"])
    check("a consumer is refused the cluster overview", status == 403, f"got {status}")

    status, _ = request("GET", f"/iot/telemetry/{hive['id']}", base=base, token=outsider["token"])
    check("a stranger is refused another apiary's telemetry", status == 404, f"got {status}")

    status, _ = request("GET", f"/clusters/{uuid.uuid4()}/summary", base=base, token=tokens["kvic"])
    check("an unknown cluster is a 404", status == 404, f"got {status}")

    # ------------------------------------------------------ 7. the audit trail
    print("\nThe audit trail")
    # Filtered per action, which is how an officer reviews the relationship:
    # every move of a beekeeper or a hive has to be answerable months later.
    for action in (
        "BEEKEEPER_ASSIGNED_TO_CLUSTER",
        "CLUSTER_RELATIONSHIP_UPDATED",
        "HIVE_ASSOCIATED_WITH_CLUSTER",
        "BEEKEEPER_REMOVED_FROM_CLUSTER",
    ):
        status, payload = request(
            "GET", f"/admin/audit-logs?action={action}", base=base, token=tokens["admin"]
        )
        entries = payload.get("data", []) if status == 200 else []
        check(
            f"the log answers for {action}",
            status == 200 and len(entries) >= 1,
            f"got {status}, {len(entries)} entries",
        )

    status, payload = request(
        "GET", "/admin/audit-logs?action=HIVE_ASSOCIATED_WITH_CLUSTER", base=base, token=tokens["admin"]
    )
    metadata = (payload.get("data") or [{}])[0].get("metadata") or {}
    check(
        "a placement records which cluster the hive came from and went to",
        "cluster_id" in metadata or "new_cluster_id" in metadata or "cluster_code" in metadata,
        str(metadata)[:200],
    )

    # ------------------------------------------------------------- wind-down
    print("\nCleanup")
    print("  Fixtures created by this run (remove with SQL):")
    print(
        "    DELETE FROM beekeepers WHERE user_id IN "
        f"(SELECT id FROM users WHERE email LIKE '{EMAIL_LIKE}');"
    )

    print("\n" + "=" * 68)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 68)
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())

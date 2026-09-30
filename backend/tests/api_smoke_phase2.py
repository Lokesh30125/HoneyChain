"""Phase-2 end-to-end smoke test against a *running* API.

Unlike the pytest suite (which builds its own app and test database), this script
talks to the live development server over HTTP and exercises the flow a person
actually performs: sign in as each role, read and edit a profile, review and
verify a beekeeper, manage a cluster and read the audit log.

It registers one throwaway beekeeper per run and performs every destructive check
against **that** record — a smoke test must never change a real person's
verification state.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_phase2.py [--base-url http://localhost:8000/api/v1]

Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

DEFAULT_BASE = "http://localhost:8000/api/v1"

CREDENTIALS = {
    "admin": ("admin@honeychain.example.com", "AdminSecure123"),
    "kvic": ("kvic@honeychain.example.com", "KvicSecure123"),
    "beekeeper": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "consumer": ("consumer@honeychain.example.com", "ConsumerPass123"),
}

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
    body: dict | None = None,
):
    """Return (status, payload). Never raises for HTTP error statuses."""
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
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
        raise SystemExit(f"Could not sign in as {who} ({email}): {status} {payload}")
    return payload["data"]["access_token"]


def register_throwaway_beekeeper(base: str) -> dict:
    """Create the record the destructive checks are allowed to touch."""
    suffix = uuid.uuid4().hex[:8]
    email = f"smoke.phase2.{suffix}@honeychain.example.com"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": "Smoke Phase Two",
            "email": email,
            "password": "SmokePass123",
            "phone": f"9{int(suffix, 16) % 10**9:09d}",
            "role": "BEEKEEPER",
            "district": "Guntur",
            "state": "Andhra Pradesh",
            "accepted_terms": True,
            "beekeeper": {
                "village": "Tenali",
                "mandal": "Tenali",
                "district": "Guntur",
                "state": "Andhra Pradesh",
                "pincode": "522201",
                "experience_years": 3,
                "bee_species": "Apis cerana indica",
                "number_of_hives": 8,
            },
        },
    )
    data = payload.get("data", {})
    check(
        "registration creates the account and a PENDING beekeeper record",
        status == 201 and data.get("beekeeper", {}).get("verification_status") == "PENDING",
        f"got {status} / {data.get('beekeeper')}",
    )
    check(
        "registration returns the role's home route",
        data.get("home_route") == "/beekeeper",
        f"got {data.get('home_route')}",
    )
    check("the apiary details sent at registration are stored",
          data.get("beekeeper", {}).get("district") == "Guntur")

    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": "Privilege Escalation",
            "email": f"smoke.escalate.{suffix}@honeychain.example.com",
            "password": "SmokePass123",
            "role": "ADMIN",
            "accepted_terms": True,
        },
    )
    check("registration refuses the ADMIN role", status == 422, f"got {status}")

    return {"email": email, "code": data.get("beekeeper", {}).get("beekeeper_code")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-2 API smoke test.")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")

    print(f"HoneyChain Phase-2 API smoke test → {base}\n")

    # ---------------------------------------------------------------- health
    print("Health & metadata")
    status, _ = request("GET", "/health", base=base)
    check("GET /health is 200", status == 200, f"got {status}")
    status, payload = request("GET", "/health/db", base=base)
    tables = set(payload.get("data", {}).get("tables", []))
    check(
        "GET /health/db reports the domain tables",
        status == 200
        and {"users", "user_profiles", "beekeepers", "kvic_clusters",
             "beekeeper_verification_history", "audit_logs"} <= tables,
        f"got {status} / {sorted(tables)}",
    )

    # ------------------------------------------------------------------- auth
    print("\nAuthentication")
    tokens = {who: login(base, who) for who in CREDENTIALS}
    check("all four seeded roles can sign in", len(tokens) == 4)
    status, payload = request("GET", "/auth/me", base=base, token=tokens["admin"])
    check("GET /auth/me identifies the admin",
          status == 200 and payload["data"]["role"] == "ADMIN", f"got {status}")

    # ---------------------------------------------------------------- profile
    print("\nProfiles")
    status, payload = request("GET", "/profile", base=base, token=tokens["beekeeper"])
    data = payload.get("data", {})
    check("GET /profile returns account + profile + beekeeper",
          status == 200 and {"account", "profile", "beekeeper"} <= set(data),
          f"got {status} / {list(data)}")
    check("the profile carries the beekeeper code",
          bool(data.get("beekeeper", {}).get("beekeeper_code")))

    status, payload = request(
        "PATCH", "/profile", base=base, token=tokens["beekeeper"],
        body={"village": "Tenali", "mandal": "Tenali", "district": "Guntur",
              "state": "Andhra Pradesh", "pincode": "522201", "gender": "prefer_not_to_say"},
    )
    check("PATCH /profile saves location details",
          status == 200 and payload["data"]["profile"]["pincode"] == "522201", f"got {status}")

    status, _ = request("PATCH", "/profile", base=base, token=tokens["beekeeper"],
                        body={"role": "ADMIN"})
    check("PATCH /profile cannot change your own role", status == 422, f"got {status}")

    # ------------------------------------------------- self-service beekeeper
    print("\nBeekeeper self-service")
    status, payload = request("GET", "/beekeepers/me", base=base, token=tokens["beekeeper"])
    check("GET /beekeepers/me returns the own record", status == 200
          and payload["data"]["verification_status"] in {"PENDING", "UNDER_REVIEW", "VERIFIED"},
          f"got {status}")

    status, payload = request("PUT", "/beekeepers/me", base=base, token=tokens["beekeeper"],
                              body={"experience_years": 7, "bee_species": "Apis cerana indica",
                                    "number_of_hives": 24, "village": "Tenali",
                                    "mandal": "Tenali", "district": "Guntur",
                                    "state": "Andhra Pradesh", "pincode": "522201"})
    check("PUT /beekeepers/me updates apiary details",
          status == 200 and payload["data"]["number_of_hives"] == 24, f"got {status}")

    status, _ = request("PUT", "/beekeepers/me", base=base, token=tokens["beekeeper"],
                        body={"kvic_cluster_id": str(uuid.uuid4())})
    check("a beekeeper cannot claim a cluster", status == 422, f"got {status}")

    # ------------------------------------------------------------ registration
    print("\nRegistration (one throwaway account per run)")
    throwaway = register_throwaway_beekeeper(base)
    target_code = throwaway["code"]

    # -------------------------------------------------------------- directory
    print("\nBeekeeper directory & verification (on the throwaway record)")
    status, payload = request("GET", f"/beekeepers?search={target_code}&page=1&page_size=5",
                              base=base, token=tokens["admin"])
    rows = payload.get("data", [])
    meta = payload.get("meta", {})
    check("ADMIN lists beekeepers with pagination meta",
          status == 200 and isinstance(rows, list) and "total_items" in meta, f"got {status}")
    target = next((row for row in rows if row["beekeeper_code"] == target_code), None)
    check("the search filter finds the new record by code", target is not None)

    status, payload = request("GET", "/beekeepers?verification_status=PENDING&page=1&page_size=20",
                              base=base, token=tokens["admin"])
    check("verification_status filter is honoured",
          status == 200 and all(r["verification_status"] == "PENDING" for r in payload.get("data", [])),
          f"got {status}")

    status, payload = request("GET", "/beekeepers/filters", base=base, token=tokens["admin"])
    check("GET /beekeepers/filters returns stored values",
          status == 200 and isinstance(payload["data"]["districts"], list), f"got {status}")

    status, payload = request("GET", "/beekeepers/summary", base=base, token=tokens["admin"])
    check("GET /beekeepers/summary returns counts",
          status == 200 and payload["data"]["total"] >= 1, f"got {status}")

    if target:
        beekeeper_id = target["id"]
        status, _ = request(
            "PATCH", f"/beekeepers/{beekeeper_id}/verification", base=base, token=tokens["kvic"],
            body={"status": "REJECTED"},
        )
        check("rejection without a remark is refused", status == 422, f"got {status}")

        status, payload = request(
            "PATCH", f"/beekeepers/{beekeeper_id}/verification", base=base, token=tokens["kvic"],
            body={"status": "UNDER_REVIEW", "remarks": "Field visit scheduled for next week."},
        )
        check("KVIC officer moves a record to UNDER_REVIEW",
              status == 200 and payload["data"]["beekeeper"]["verification_status"] == "UNDER_REVIEW",
              f"got {status}")

        status, payload = request("GET", f"/beekeepers/{beekeeper_id}", base=base, token=tokens["kvic"])
        history = payload.get("data", {}).get("verification_history", [])
        check("verification history is appended and readable",
              status == 200 and len(history) >= 2, f"got {status} / {len(history)} entries")

        status, _ = request("GET", "/beekeepers/me", base=base, token=tokens["admin"])
        check("an administrator has no beekeeper record of their own", status == 403, f"got {status}")

    # ---------------------------------------------------------------- clusters
    print("\nClusters")
    status, payload = request("GET", "/clusters?page=1&page_size=10", base=base, token=tokens["kvic"])
    check("KVIC officer lists clusters",
          status == 200 and isinstance(payload.get("data"), list), f"got {status}")

    cluster_code = f"KVIC-TST-{uuid.uuid4().hex[:4].upper()}"
    status, payload = request(
        "POST", "/clusters", base=base, token=tokens["kvic"],
        body={"cluster_code": cluster_code, "cluster_name": "Smoke Test Cluster",
              "district": "Guntur", "state": "Andhra Pradesh",
              "coordinator_name": "Smoke Coordinator"},
    )
    created = payload.get("data", {})
    check("KVIC officer creates a cluster",
          status == 201 and created.get("cluster_code") == cluster_code,
          f"got {status} / {created.get('cluster_code')}")

    if created.get("id"):
        cluster_id = created["id"]
        status, payload = request("PATCH", f"/clusters/{cluster_id}/status", base=base,
                                  token=tokens["kvic"], body={"is_active": False})
        check("a cluster can be deactivated",
              status == 200 and payload["data"]["is_active"] is False, f"got {status}")

        status, payload = request("GET", f"/clusters/{cluster_id}", base=base, token=tokens["kvic"])
        check("cluster detail reports membership",
              status == 200 and "member_count" in payload.get("data", {}), f"got {status}")

        status, _ = request("DELETE", f"/clusters/{cluster_id}", base=base, token=tokens["admin"])
        check("there is no cluster delete endpoint", status == 405, f"got {status}")

    # ------------------------------------------------------------- admin area
    print("\nAdministration")
    status, payload = request("GET", "/admin/summary", base=base, token=tokens["admin"])
    summary = payload.get("data", {})
    check("GET /admin/summary reports users, beekeepers, clusters and modules",
          status == 200 and {"users", "beekeepers", "clusters", "modules"} <= set(summary),
          f"got {status} / {list(summary)}")
    check("the module list is honest about what exists",
          summary.get("modules", {}).get("user_management") == "available"
          and summary.get("modules", {}).get("blockchain") == "available",
          f"modules={summary.get('modules')}")

    status, payload = request("GET", "/admin/users?page=1&page_size=5&role=BEEKEEPER",
                              base=base, token=tokens["admin"])
    check("the admin user list filters by role",
          status == 200 and all(u["role"] == "BEEKEEPER" for u in payload.get("data", [])),
          f"got {status}")

    status, payload = request("GET", "/admin/audit-logs?page=1&page_size=10&action=USER_LOGIN",
                              base=base, token=tokens["admin"])
    entries = payload.get("data", [])
    check("the audit log records sign-ins", status == 200 and len(entries) >= 1, f"got {status}")
    check("audit entries never contain secrets",
          all("password" not in json.dumps(entry).lower() for entry in entries))

    status, payload = request("GET", "/admin/activity?hours=24", base=base, token=tokens["admin"])
    check("GET /admin/activity returns a window summary",
          status == 200 and "total" in payload.get("data", {}), f"got {status}")

    # ---------------------------------------------------------- authorisation
    print("\nAuthorisation")
    forbidden = [
        ("consumer", "GET", "/beekeepers", 403),
        ("consumer", "GET", "/admin/users", 403),
        ("beekeeper", "GET", "/admin/users", 403),
        ("beekeeper", "GET", "/beekeepers", 403),
        ("kvic", "GET", "/admin/users", 403),
        ("beekeeper", "GET", "/beekeepers/me", 200),
    ]
    for who, method, path, expected in forbidden:
        status, _ = request(method, path, base=base, token=tokens[who])
        check(f"{who} {method} {path} → {expected}", status == expected, f"got {status}")

    status, _ = request("GET", "/beekeepers", base=base)
    check("anonymous requests are refused", status == 401, f"got {status}")

    status, _ = request("GET", "/beekeepers/me", base=base, token=tokens["consumer"])
    check("a consumer has no beekeeper record of their own", status == 403, f"got {status}")

    # ---------------------------------------------------------------- summary
    print("\n" + "=" * 68)
    print(f"{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  ✗ {failure}")
    print("=" * 68)
    print(
        "NOTE: this run created throwaway fixtures in the development database:\n"
        f"  account: {throwaway['email']}\n"
        f"  cluster: {cluster_code}\n"
        "Remove them with:\n"
        "  psql \"$DATABASE_URL\" -c \"delete from users where email like 'smoke.%';\" \\\n"
        "                        -c \"delete from kvic_clusters where cluster_name like 'Smoke Test%';\""
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())

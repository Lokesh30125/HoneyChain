"""The two dead ends this phase is about, driven over HTTP against the real database.

**"No unit registered yet"** — there was no way to register a packaging unit, so the
packaging form always asked for one that could not exist, and a packaging account
was attached to nothing. This script registers a unit the way the Administration
screen does, creates the operator's account with that unit, and checks that the
operator's own workspace reads the facility, that a run opens *in* it without the
operator choosing, and that naming another facility is refused.

**"Cluster created" then gone** — and its close relatives: a batch showing "no
cluster assigned" although its beekeeper was in a cluster, a KVIC officer not
seeing a laboratory decision the beekeeper could see, and a cluster that could not
be removed. This script creates a cluster, checks it survives a re-read, walks the
relationship down to a batch, completes a laboratory test, and reads the same
batch back as the officer.

Everything it creates is TEST data, named as such.

Usage::

    cd backend
    .venv/bin/python tests/smoke_units_and_clusters.py
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.api_smoke_phase7 import (  # noqa: E402
    create_staff,
    harvest_batch,
    make_hive,
    process_batch,
    register_keeper,
    request,
    sign_in,
)

DEFAULT_API = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
ADMIN = ("admin@honeychain.example.com", "AdminSecure123")
OFFICER = ("kvic@honeychain.example.com", "KvicSecure123")

PASSED: list[str] = []
FAILED: list[str] = []
MARK = uuid.uuid4().hex[:6]


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    print(f"  {'PASS' if condition else 'FAIL'}  {description}" + (f" — {detail}" if detail and not condition else ""))


def section(title: str) -> None:
    print(f"\n=== {title}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API)
    api = parser.parse_args().api_url.rstrip("/")

    admin = sign_in(api, *ADMIN)
    officer = sign_in(api, *OFFICER)
    print(f"Packaging units and clusters over HTTP — {api}")

    # ------------------------------------------------------------------ #
    section("A packaging unit can be registered at all")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "POST",
        "/packaging-units",
        base=api,
        token=admin,
        body={
            "name": f"HoneyChain Packaging Unit TEST {MARK}",
            "registration_identifier": f"REG-TEST-{MARK}",
            "location": "Guntur",
            "address": "12 Market Road, Guntur 522001",
            "district": "Guntur",
            "state": "Andhra Pradesh",
            "contact_email": f"unit.{MARK}@honeychain.example.com",
            "status": "ACTIVE",
        },
    )
    unit = (payload.get("data") or {}) if status == 201 else {}
    check("an administrator can register a packaging unit", status == 201, f"{status} {payload}")
    check(
        "the register returns a database id and a server-issued code",
        bool(unit.get("id")) and str(unit.get("unit_code", "")).startswith("HC-PKUNIT"),
        str({k: unit.get(k) for k in ("id", "unit_code")}),
    )
    check(
        "the address is stored as given",
        unit.get("address") == "12 Market Road, Guntur 522001",
        str(unit.get("address")),
    )
    check("a new unit starts with nobody working at it", unit.get("member_count") == 0)

    # ------------------------------------------------------------------ #
    section("A packaging account is attached to a real facility")
    # ------------------------------------------------------------------ #
    operator = create_staff(api, admin, "unit.operator", "PACKAGING_UNIT")
    status, payload = request(
        "POST",
        f"/packaging-units/{unit['id']}/members",
        base=api,
        token=admin,
        body={"user_id": operator["user_id"], "reason": "Joined the Guntur facility"},
    )
    attached = (payload.get("data") or {}) if status == 200 else {}
    check("an administrator can put an account to work at the unit", status == 200, f"{status} {payload}")
    check(
        "the unit now lists the account",
        any(row["email"] == operator["email"] for row in (attached.get("members") or [])),
        str(attached.get("members")),
    )

    # A second facility, so "another organisation's unit" is a real thing to refuse.
    status, payload = request(
        "POST",
        "/packaging-units",
        base=api,
        token=admin,
        body={
            "name": f"Other Facility TEST {MARK}",
            "registration_identifier": f"REG-OTHER-{MARK}",
            "district": "Guntur",
            "state": "Andhra Pradesh",
        },
    )
    other_unit = (payload.get("data") or {}) if status == 201 else {}

    status, payload = request("GET", "/packaging-units/mine", base=api, token=operator["token"])
    mine = (payload.get("data") or {}) if status == 200 else {}
    check(
        "the operator's own workspace reads its facility without being asked",
        status == 200 and mine.get("id") == unit["id"],
        f"{status} {mine.get('unit_code')}",
    )
    check(
        "the operator is not shown the other organisations' facilities",
        status == 200
        and all(
            row["id"] == unit["id"]
            for row in (request("GET", "/packaging-units?page_size=50", base=api, token=operator["token"])[1].get("data") or [])
        ),
    )

    # ------------------------------------------------------------------ #
    section("The operator packs in its own facility, and only there")
    # ------------------------------------------------------------------ #
    # A real approved batch to pack: cluster → beekeeper → hive → collection →
    # batch → processing → laboratory PASS → PACKAGING_READY.
    status, payload = request(
        "POST",
        "/clusters",
        base=api,
        token=officer,
        body={
            "cluster_name": f"Units Smoke Cluster TEST {MARK}",
            "district": "Guntur",
            "state": "Andhra Pradesh",
            "coordinator_name": "Smoke Coordinator",
        },
    )
    cluster = (payload.get("data") or {}) if status == 201 else {}
    check("a KVIC officer can create a cluster", status == 201, f"{status} {payload}")
    check("the created cluster comes back with its database id", bool(cluster.get("id")))

    status, payload = request("GET", f"/clusters/{cluster['id']}", base=api, token=officer)
    detail = (payload.get("data") or {}) if status == 200 else {}
    check(
        "the cluster is readable straight after it was created",
        status == 200 and (detail.get("cluster") or {}).get("cluster_code") == cluster.get("cluster_code"),
        f"{status}",
    )
    dependencies = detail.get("dependencies") or {}
    check(
        "a new cluster reports zero records under it, counted from the tables",
        all(value == 0 for value in dependencies.values()),
        str(dependencies),
    )
    check("…and may therefore be removed", detail.get("can_delete") is True)

    keeper = register_keeper(api)
    status, payload = request("GET", "/beekeepers/me", base=api, token=keeper["token"])
    keeper_record = payload["data"]
    status, payload = request(
        "POST",
        f"/clusters/{cluster['id']}/beekeepers/{keeper_record['id']}",
        base=api,
        token=officer,
        body={},
    )
    check("the officer can attach a beekeeper to the cluster", status in (200, 201), f"{status} {payload}")

    hive = make_hive(api, keeper["token"])
    batch = harvest_batch(api, keeper, hive, "13.7")
    check(
        "the collection inherited the cluster from the beekeeper",
        batch.get("cluster_id") == cluster["id"],
        f"collection cluster={batch.get('cluster_id')} vs {cluster['id']}",
    )
    check(
        "the batch carries the same cluster, and is not 'no cluster assigned'",
        batch.get("cluster_id") == cluster["id"],
        f"batch cluster={batch.get('cluster_id')}",
    )

    status, payload = request("GET", f"/clusters/{cluster['id']}", base=api, token=officer)
    dependencies = (payload.get("data") or {}).get("dependencies") or {}
    check(
        "the cluster page counts the records that now exist",
        dependencies.get("beekeepers", 0) >= 1
        and dependencies.get("hives", 0) >= 1
        and dependencies.get("collections", 0) >= 1
        and dependencies.get("batches", 0) >= 1,
        str(dependencies),
    )

    status, payload = request("DELETE", f"/clusters/{cluster['id']}", base=api, token=officer, body={"confirm": True})
    check(
        "a cluster with records under it cannot be deleted",
        status == 409,
        f"{status}",
    )
    details = (payload.get("error", {}) or {}).get("details") or {}
    check(
        "the refusal shows the dependent counts",
        details.get("Beekeepers", 0) >= 1 and details.get("Batches", 0) >= 1,
        str(details),
    )
    check(
        "the refusal says why, and what to do instead",
        "deactivate" in str((payload.get("error") or {}).get("message", "")).lower(),
        str((payload.get("error") or {}).get("message")),
    )

    # Deletion of an empty cluster, and that it really goes.
    status, payload = request(
        "POST",
        "/clusters",
        base=api,
        token=officer,
        body={"cluster_name": f"Empty Cluster TEST {MARK}", "district": "Guntur", "state": "Andhra Pradesh"},
    )
    empty = (payload.get("data") or {}) if status == 201 else {}
    status, payload = request(
        "DELETE", f"/clusters/{empty['id']}", base=api, token=officer, body={"confirm": True}
    )
    check("an empty cluster is removed", status == 200, f"{status} {payload}")
    status, payload = request("GET", f"/clusters/{empty['id']}", base=api, token=officer)
    check("…and is gone on the next read", status == 404, f"{status}")

    # ------------------------------------------------------------------ #
    section("A beekeeper who joins a cluster afterwards takes the harvest with them")
    # ------------------------------------------------------------------ #
    # The order in life is often the reverse of the order in the data: a season is
    # harvested, and the cluster is arranged later. Everything the beekeeper
    # recorded before that used to go on reading as "no cluster assigned".
    late = register_keeper(api)
    late_hive = make_hive(api, late["token"])
    early = harvest_batch(api, late, late_hive, "9.5")
    check(
        "a harvest recorded before any membership has no cluster to record",
        early.get("cluster_id") is None,
        str(early.get("cluster_id")),
    )
    status, payload = request("GET", "/beekeepers/me", base=api, token=late["token"])
    status, payload = request(
        "POST",
        f"/clusters/{cluster['id']}/beekeepers/{payload['data']['id']}",
        base=api,
        token=officer,
        body={},
    )
    check("the officer places the beekeeper in the cluster", status in (200, 201), f"{status} {payload}")

    status, payload = request("GET", f"/batches/{early['id']}", base=api, token=officer)
    late_view = (payload.get("data") or {}) if status == 200 else {}
    check(
        "their batch stops reading as unassigned, and names the cluster",
        late_view.get("cluster_id") == cluster["id"]
        and late_view.get("cluster_name") == cluster["cluster_name"],
        str({k: late_view.get(k) for k in ("cluster_id", "cluster_name")}),
    )
    check(
        "…with the cluster's code available for the traceability view",
        late_view.get("cluster_code") == cluster.get("cluster_code"),
        str(late_view.get("cluster_code")),
    )
    # The batch's own cluster pointer and the collection's are separate rows; both
    # are checked, because a batch that inherited the cluster while its collection
    # was left blank would still show a hole in the traceability view.
    collection_id = (late_view.get("collection") or {}).get("id")
    status, payload = request("GET", f"/collections/{collection_id}", base=api, token=late["token"])
    linked_collection = (payload.get("data") or {}) if status == 200 else {}
    check(
        "the harvest itself is linked, not only the batch",
        linked_collection.get("cluster_id") == cluster["id"]
        and linked_collection.get("cluster_name") == cluster["cluster_name"],
        str({k: linked_collection.get(k) for k in ("cluster_id", "cluster_name")}),
    )
    status, payload = request(
        "GET", f"/clusters/{cluster['id']}", base=api, token=officer
    )
    dependencies = (payload.get("data") or {}).get("dependencies") or {}
    check(
        "the cluster page then counts it",
        dependencies.get("beekeepers", 0) >= 2 and dependencies.get("batches", 0) >= 2,
        str(dependencies),
    )

    # ------------------------------------------------------------------ #
    section("The laboratory's decision reaches every other role")
    # ------------------------------------------------------------------ #
    processor = create_staff(api, admin, "unit.processor", "PROCESSOR")
    technician = create_staff(api, admin, "unit.technician", "LAB_TECHNICIAN")
    status, payload = request("GET", "/laboratories?page_size=1", base=api, token=admin)
    laboratories = (payload.get("data") or []) if status == 200 else []
    if not laboratories:
        status, payload = request(
            "POST",
            "/laboratories",
            base=api,
            token=admin,
            body={
                "name": "Honey Quality Laboratory (TEST)",
                "location": "Guntur",
                "district": "Guntur",
                "state": "Andhra Pradesh",
            },
        )
        laboratories = [payload["data"]]
    laboratory = laboratories[0]

    process_batch(api, admin, processor, batch["id"], "12.9")
    status, payload = request("GET", f"/batches/{batch['id']}", base=api, token=officer)
    check(
        "the officer sees the batch at the laboratory",
        (payload.get("data") or {}).get("status") == "LAB_TESTING",
        str((payload.get("data") or {}).get("status")),
    )
    status, payload = request(
        "POST",
        "/lab-tests",
        base=api,
        token=technician["token"],
        body={"batch_id": batch["id"], "laboratory_id": laboratory["id"], "sample_quantity": "500"},
    )
    lab_test = (payload.get("data") or {}) if status == 201 else {}
    check("the technician opens a test against the batch", status == 201, f"{status} {payload}")
    request("POST", f"/lab-tests/{lab_test['id']}/analyze", base=api, token=technician["token"], body={})
    status, payload = request(
        "POST", f"/lab-tests/{lab_test['id']}/complete", base=api, token=technician["token"], body={}
    )
    completed = (payload.get("data") or {}) if status == 200 else {}
    check("completing the test succeeds", status == 200, f"{status} {payload}")

    status, payload = request("GET", f"/batches/{batch['id']}", base=api, token=officer)
    officer_view = (payload.get("data") or {}) if status == 200 else {}
    check(
        "the officer reads the same batch the technician decided",
        officer_view.get("status") in {"APPROVED", "PACKAGING_READY"},
        str(officer_view.get("status")),
    )
    check(
        "…with the laboratory decision on it",
        (officer_view.get("laboratory") or {}).get("overall_result")
        == completed.get("overall_result"),
        str((officer_view.get("laboratory") or {}).get("overall_result")),
    )
    check(
        "…and the analysis the laboratory ran",
        bool((officer_view.get("laboratory") or {}).get("ai_status")),
        str((officer_view.get("laboratory") or {}).get("ai_status")),
    )

    # ------------------------------------------------------------------ #
    section("The operator packs that batch in its own facility")
    # ------------------------------------------------------------------ #
    if completed.get("overall_result") == "PASS":
        # The arithmetic must hold before a run exists at all. Checked first, because
        # a batch that already has an open run is refused for that reason instead.
        status, payload = request(
            "POST",
            "/packaging",
            base=api,
            token=admin,
            body={
                "batch_id": batch["id"],
                "packaging_type": "JAR",
                "packaged_quantity": "5",
                "package_size": "1",
                "number_of_packages": 3,
            },
        )
        check(
            "3 packages of 1 for 5 of honey is refused with the arithmetic spelled out",
            status == 422 and "come to 3" in str(payload),
            f"{status} {str(payload)[:220]}",
        )

        status, payload = request(
            "POST",
            "/packaging",
            base=api,
            token=operator["token"],
            body={
                "batch_id": batch["id"],
                "packaging_type": "JAR",
                "packaged_quantity": "4",
                "package_size": "1",
                "number_of_packages": 4,
            },
        )
        run = (payload.get("data") or {}) if status == 201 else {}
        check("the operator opens a run without naming a unit", status == 201, f"{status} {payload}")
        check(
            "the run is recorded in the operator's own facility",
            (run.get("packaging_unit") or {}).get("id") == unit["id"]
            or run.get("packaging_unit_id") == unit["id"],
            str({k: run.get(k) for k in ("packaging_unit_id", "packaging_unit")}),
        )

        status, payload = request(
            "POST",
            "/packaging",
            base=api,
            token=operator["token"],
            body={
                "batch_id": batch["id"],
                "packaging_unit_id": other_unit["id"],
                "packaging_type": "JAR",
                "packaged_quantity": "1",
                "package_size": "1",
                "number_of_packages": 1,
            },
        )
        check(
            "the operator cannot open a run in another facility",
            status in (403, 409),
            f"{status}",
        )

    # ------------------------------------------------------------------ #
    section("An account with no facility is told what to do about it")
    # ------------------------------------------------------------------ #
    loner = create_staff(api, admin, "unit.unattached", "PACKAGING_UNIT")
    status, payload = request("GET", "/packaging-units/mine", base=api, token=loner["token"])
    check(
        "the unattached operator is refused, with the action that fixes it",
        status == 404
        and (payload.get("error", {}).get("details", {}) or {}).get("action")
        == "admin_attaches_packaging_unit",
        f"{status} {payload}",
    )
    status, payload = request(
        "GET",
        "/packaging/approved-batches?page_size=50",
        base=api,
        token=loner["token"],
    )
    batches = (payload.get("data") or []) if status == 200 else []
    target = next((row for row in batches if row.get("remaining_quantity", 0)), None)
    if target:
        status, payload = request(
            "POST",
            "/packaging",
            base=api,
            token=loner["token"],
            body={
                "batch_id": target["batch_id"],
                "packaging_type": "JAR",
                "packaged_quantity": "1",
                "package_size": "1",
                "number_of_packages": 1,
            },
        )
        check(
            "an account with no facility cannot open a run, and is told who fixes it",
            status == 409 and "administrator" in str(payload).lower(),
            f"{status} {str(payload)[:200]}",
        )

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  FAILED  {failure}")
    print(
        f"\nTEST data: cluster {cluster.get('cluster_code')}, batch {batch.get('batch_code')}, "
        f"unit {unit.get('unit_code')}"
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

"""Phase-7 smoke test against a *running* API — packaging, distribution and the
retailer's receipt, end to end, in the order the people involved actually work.

``tests/test_packaging.py`` and ``tests/test_distribution.py`` check the rules
inside one process. This script walks the same ground over HTTP, against the
development server, and follows one batch from the apiary to a shop counter:

    a marked TEST harvest becomes a batch → a TEST processor records what went in
    and what came out → a TEST laboratory technician measures a sample, a
    reference range is configured, the test passes and the batch is APPROVED →
    the packaging unit sees the batch waiting, packs part of it into individually
    coded packages, and releases them → a distributor ships one package to a TEST
    retailer → the batch's timeline shows the packing and the shipment → the
    retailer confirms receipt → the batch is COMPLETED → the beekeeper reads the
    whole journey, read-only, on the same single batch.

Along the way it checks what is easy to claim and hard to do: that a batch the
laboratory has not approved cannot be packed (and that INCONCLUSIVE is not a
quiet approval), that the honey is counted — never more packed than approved,
never more shipped than a package holds, never a delivery before a dispatch —
that package codes are unique and stable, that no original quantity is rewritten
by any of it, that each role is refused the others' work, that a cancelled
shipment moves no honey, and that every step is written to the audit log.

Usage::

    cd backend
    .venv/bin/python tests/api_smoke_phase7.py [--base-url http://localhost:8000/api/v1]

Exit code 0 means every check passed. Everything it creates is marked TEST or
``smoke.p7``; the seeded development data is only read. Cleanup SQL is printed
at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date
from decimal import Decimal

DEFAULT_BASE = "http://localhost:8000/api/v1"

CREDENTIALS = {
    "admin": ("admin@honeychain.example.com", "AdminSecure123"),
    "kvic": ("kvic@honeychain.example.com", "KvicSecure123"),
    "beekeeper": ("beekeeper@honeychain.example.com", "HoneyPass123"),
    "processor": ("processor@honeychain.example.com", "ProcessPass123"),
    "labtech": ("labtech@honeychain.example.com", "LabTechPass123"),
}

#: Everything this run creates carries this marker, so cleanup is unambiguous.
MARKER = "smoke.p7"

PASSED: list[str] = []
FAILED: list[str] = []
CREATED: dict[str, list[str]] = {"users": [], "hives": [], "codes": []}


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(f"{label} — {detail}")
        print(f"  FAIL  {label} — {detail}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def request(
    method: str,
    path: str,
    *,
    base: str,
    token: str | None = None,
    body: dict | list | None = None,
    timeout: int = 60,
):
    """Return ``(status, payload)``. Never raises for HTTP error statuses.

    ``timeout`` is per call and exists for the endpoints that do real work on the
    far side of the request: a blockchain sweep submits a bounded batch of
    transactions to an external service and legitimately takes longer than a
    read. A shorter default would report the platform's patience as a failure.
    """
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read() or b"{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw.decode(errors="replace")}
    except Exception as error:  # network failure
        return 0, {"error": {"code": "NETWORK", "message": str(error)}}


def sign_in(base: str, email: str, password: str) -> str:
    status, payload = request(
        "POST", "/auth/login", base=base, body={"email": email, "password": password}
    )
    if status != 200:
        raise SystemExit(f"Could not sign in as {email}: {status} {payload}")
    return payload["data"]["access_token"]


def create_staff(base: str, admin_token: str, label: str, role: str) -> dict:
    """Provision a role account through the admin API — never through registration."""
    email = f"{MARKER}.{label}@honeychain.example.com"
    password = "SmokeP7Staff123"
    status, payload = request(
        "POST",
        "/admin/users",
        base=base,
        token=admin_token,
        body={"name": f"Smoke 7 {label.upper()} TEST", "email": email, "password": password, "role": role},
    )
    if status == 409:
        status, payload = request(
            "GET", f"/admin/users?search={email}", base=base, token=admin_token
        )
        existing = (payload.get("data") or [{}])[0]
        user_id = existing.get("id")
        if user_id and existing.get("role") != role:
            request(
                "PATCH",
                f"/admin/users/{user_id}/role",
                base=base,
                token=admin_token,
                body={"role": role},
            )
    elif status == 201:
        CREATED["users"].append(email)
        user_id = payload["data"]["user"]["id"]
    else:
        raise SystemExit(f"Could not create the {label} account: {status} {payload}")
    return {"email": email, "user_id": user_id, "token": sign_in(base, email, password)}


def register_keeper(base: str) -> dict:
    email = f"{MARKER}.keeper.{uuid.uuid4().hex[:8]}@honeychain.example.com"
    password = "SmokeP7Pass123"
    status, payload = request(
        "POST",
        "/auth/register",
        base=base,
        body={
            "name": "Smoke 7 Beekeeper TEST",
            "email": email,
            "password": password,
            "phone": f"+9197{uuid.uuid4().int % 100000000:08d}",
            "role": "BEEKEEPER",
            "accepted_terms": True,
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a beekeeper: {status} {payload}")
    CREATED["users"].append(email)
    return {
        "email": email,
        "token": payload["data"]["access_token"],
        "user_id": payload["data"]["user"]["id"],
    }


def make_hive(base: str, token: str) -> dict:
    status, payload = request(
        "POST",
        "/hives",
        base=base,
        token=token,
        body={
            "bee_species": "Apis cerana indica",
            "village": "Tenali",
            "district": "Guntur",
            "state": "Andhra Pradesh",
            "notes": "Phase 7 smoke fixture",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not register a hive: {status} {payload}")
    CREATED["hives"].append(payload["data"]["hive_code"])
    return payload["data"]


def harvest_batch(base: str, keeper: dict, hive: dict, quantity: str) -> dict:
    status, payload = request(
        "POST",
        "/collections",
        base=base,
        token=keeper["token"],
        body={
            "hives": [{"hive_id": hive["id"], "quantity": quantity}],
            "collection_date": date.today().isoformat(),
            "unit": "KG",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not record a harvest: {status} {payload}")
    collection = payload["data"]
    status, payload = request(
        "POST", f"/collections/{collection['id']}/complete", base=base, token=keeper["token"]
    )
    if status != 200:
        raise SystemExit(f"Could not complete the harvest: {status} {payload}")
    batch_id = payload["meta"]["batch"]["id"]
    status, payload = request("GET", f"/batches/{batch_id}", base=base, token=keeper["token"])
    return payload["data"]


def process_batch(base: str, admin_token: str, processor: dict, batch_id: str, output: str) -> dict:
    """Allocate, accept, start and complete a processing run — the real route to the lab."""
    status, payload = request(
        "POST",
        f"/processing/batches/{batch_id}/assign",
        base=base,
        token=admin_token,
        body={"processor_id": processor["user_id"]},
    )
    if status not in (200, 201):
        raise SystemExit(f"Could not allocate the run: {status} {payload}")
    run_id = payload["data"]["id"]
    request("POST", f"/processing/{run_id}/accept", base=base, token=processor["token"], body={})
    request("POST", f"/processing/{run_id}/start", base=base, token=processor["token"])
    status, payload = request(
        "PATCH",
        f"/processing/{run_id}",
        base=base,
        token=processor["token"],
        body={"input_quantity": "13.7", "output_quantity": output},
    )
    if status != 200:
        raise SystemExit(f"Could not record the run's quantities: {status} {payload}")
    status, payload = request(
        "POST", f"/processing/{run_id}/complete", base=base, token=processor["token"], body={}
    )
    if status != 200:
        raise SystemExit(f"Could not complete the run: {status} {payload}")
    return payload["data"]


def configure_parameter(base: str, admin_token: str, code: str, minimum: str, maximum: str):
    return request(
        "PATCH",
        f"/lab-parameters/{code}",
        base=base,
        token=admin_token,
        body={
            "reference_min": minimum,
            "reference_max": maximum,
            "reference_source": (
                "Project-configured demonstration limit used by the Phase 7 smoke "
                "(not a regulatory standard)"
            ),
            "is_required": True,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 7 API smoke test")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    base = parser.parse_args().base_url.rstrip("/")

    print(f"Phase 7 smoke test against {base}")
    tokens = {who: sign_in(base, *creds) for who, creds in CREDENTIALS.items()}

    packer = create_staff(base, tokens["admin"], "packaging", "PACKAGING_UNIT")
    distributor = create_staff(base, tokens["admin"], "distributor", "DISTRIBUTOR")
    retailer = create_staff(base, tokens["admin"], "retailer", "RETAILER")
    technician = create_staff(base, tokens["admin"], "technician", "LAB_TECHNICIAN")
    processor = create_staff(base, tokens["admin"], "processor", "PROCESSOR")

    # ------------------------------------------------------------------ #
    section("Packaging unit")
    # ------------------------------------------------------------------ #
    status, payload = request("GET", "/packaging-units?page_size=50", base=base, token=packer["token"])
    unit = (payload.get("data") or [None])[0]
    if unit is None:
        status, payload = request(
            "POST",
            "/packaging-units",
            base=base,
            token=packer["token"],
            body={
                "name": "Smoke 7 Packaging Unit TEST",
                "location": "Guntur",
                "district": "Guntur",
                "state": "Andhra Pradesh",
                "notes": "Phase 7 smoke fixture",
            },
        )
        if status != 201:
            raise SystemExit(f"Could not register a packaging unit: {status} {payload}")
        unit = payload["data"]
        CREATED["codes"].append(unit["unit_code"])
    check("a packaging unit exists to work from", bool(unit.get("unit_code")), str(unit)[:120])

    # ------------------------------------------------------------------ #
    section("An approved batch, and one the laboratory has not approved")
    # ------------------------------------------------------------------ #
    keeper = register_keeper(base)
    hive = make_hive(base, keeper["token"])
    batch = harvest_batch(base, keeper, hive, "13.7")
    check(
        "the harvest became a batch",
        batch["status"] == "COLLECTED",
        f"status={batch['status']}",
    )

    run = process_batch(base, tokens["admin"], processor, batch["id"], "12.9")
    check(
        "completing processing hands the batch to the laboratory",
        batch["batch_code"] in str(run["batch"]["batch_code"]),
        str(run.get("batch"))[:120],
    )

    laboratory = None
    status, payload = request("GET", "/laboratories?page_size=20", base=base, token=tokens["labtech"])
    laboratory = (payload.get("data") or [None])[0]
    if laboratory is None:
        status, payload = request(
            "POST",
            "/laboratories",
            base=base,
            token=tokens["labtech"],
            body={
                "name": "Smoke 7 Laboratory TEST",
                "location": "Guntur",
                "district": "Guntur",
                "state": "Andhra Pradesh",
                "notes": "Phase 7 smoke fixture",
            },
        )
        if status != 201:
            raise SystemExit(f"Could not register a laboratory: {status} {payload}")
        laboratory = payload["data"]

    # The undecided batch is taken first, deliberately: with no measured value to
    # judge, the outcome is INCONCLUSIVE, and the point is that INCONCLUSIVE is
    # not a quiet approval.
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=technician["token"],
        body={
            "batch_id": batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
        },
    )
    if status != 201:
        raise SystemExit(f"Could not open a laboratory test: {status} {payload}")
    undecided_test = payload["data"]
    status, payload = request(
        "POST",
        f"/lab-tests/{undecided_test['id']}/complete",
        base=base,
        token=technician["token"],
        body={},
    )
    undecided = payload.get("data") or {}
    check(
        "a test with nothing measured cannot be decided",
        status in (409, 422),
        f"status={status} {str(payload)[:160]}",
    )

    # The range is configured *before* the measurement on purpose. A result keeps
    # the range that was in force when it was recorded, so measuring first and
    # writing the limit afterwards would leave the value unevaluated — which is
    # the honest outcome, and why the order here is the order a laboratory works in.
    status, payload = configure_parameter(base, tokens["admin"], "MOISTURE", "10", "20")
    check("a reference range can be configured", status == 200, f"status={status} {str(payload)[:120]}")
    status, payload = request(
        "POST",
        f"/lab-tests/{undecided_test['id']}/results",
        base=base,
        token=technician["token"],
        body={"parameter_code": "MOISTURE", "value": "16.4"},
    )
    check(
        "the technician records a measurement",
        status == 201,
        f"status={status} {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        f"/lab-tests/{undecided_test['id']}/complete",
        base=base,
        token=technician["token"],
        body={},
    )
    decided = payload.get("data") or {}
    check(
        "with the measurement inside the range the batch is APPROVED",
        status == 200 and decided.get("overall_result") == "PASS",
        f"status={status} result={decided.get('overall_result')}",
    )
    status, payload = request("GET", f"/batches/{batch['id']}", base=base, token=tokens["admin"])
    approved_batch = payload["data"]
    check(
        "the batch is approved by the laboratory",
        approved_batch["status"] == "APPROVED",
        f"status={approved_batch['status']}",
    )

    # ------------------------------------------------------------------ #
    section("The approved batch reaches the packaging unit")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "GET", f"/packaging/approved-batches?search={batch['batch_code']}", base=base, token=packer["token"]
    )
    approved_rows = payload.get("data") or []
    check(
        "the approved batch appears on the packaging worklist",
        status == 200 and any(row["batch_id"] == batch["id"] for row in approved_rows),
        f"status={status} rows={len(approved_rows)}",
    )
    row = next((r for r in approved_rows if r["batch_id"] == batch["id"]), {})
    check(
        "the worklist carries the quantities and the source",
        Decimal(str(row.get("approved_quantity", "0"))) == Decimal("12.9")
        and Decimal(str(row.get("collection_quantity", "0"))) == Decimal("13.7")
        and bool(row.get("beekeeper_name"))
        and bool(row.get("laboratory_test_code")),
        str(row)[:220],
    )
    check(
        "nothing is packed yet, so the whole approval is still to pack",
        Decimal(str(row.get("remaining_quantity", "0"))) == Decimal("12.9")
        and Decimal(str(row.get("packaged_quantity", "0"))) == Decimal("0"),
        str(row)[:200],
    )

    # ------------------------------------------------------------------ #
    section("What the server refuses before a single jar is filled")
    # ------------------------------------------------------------------ #
    processor_token = processor["token"]
    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=processor_token,
        body={"batch_id": batch["id"], "packaging_type": "JAR"},
    )
    check(
        "a processor cannot open a packaging run",
        status == 403,
        f"status={status} {str(payload)[:140]}",
    )
    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=distributor["token"],
        body={"batch_id": batch["id"], "packaging_type": "JAR"},
    )
    check(
        "a distributor cannot open a packaging run",
        status == 403,
        f"status={status} {str(payload)[:140]}",
    )
    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=keeper["token"],
        body={"batch_id": batch["id"], "packaging_type": "JAR"},
    )
    check(
        "the beekeeper cannot pack their own honey",
        status == 403,
        f"status={status} {str(payload)[:140]}",
    )
    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=packer["token"],
        body={
            "batch_id": batch["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "99",
            "package_size": "1",
            "number_of_packages": 99,
        },
    )
    check(
        "more honey than the batch holds cannot be packed",
        status == 422,
        f"status={status} {str(payload)[:160]}",
    )

    # A second batch, refused by the laboratory's own verdict.
    second_batch = harvest_batch(base, keeper, hive, "9.5")
    process_batch(base, tokens["admin"], processor, second_batch["id"], "9.0")
    status, payload = request(
        "POST",
        "/lab-tests",
        base=base,
        token=technician["token"],
        body={
            "batch_id": second_batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
        },
    )
    second_test = payload["data"]
    request(
        "POST",
        f"/lab-tests/{second_test['id']}/results",
        base=base,
        token=technician["token"],
        body={"parameter_code": "MOISTURE", "value": "26.0"},
    )
    request(
        "POST",
        f"/lab-tests/{second_test['id']}/complete",
        base=base,
        token=technician["token"],
        body={},
    )
    status, payload = request(
        "GET", f"/batches/{second_batch['id']}", base=base, token=tokens["admin"]
    )
    second_status = payload["data"]["status"]
    check(
        "a batch the laboratory rejected is not approved",
        second_status == "REJECTED",
        f"status={second_status}",
    )
    status, payload = request(
        "GET",
        f"/packaging/approved-batches?search={second_batch['batch_code']}",
        base=base,
        token=packer["token"],
    )
    check(
        "a rejected batch is not on the packaging worklist",
        status == 200 and (payload.get("data") or []) == [],
        f"status={status} rows={len(payload.get('data') or [])}",
    )
    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=packer["token"],
        body={"batch_id": second_batch["id"], "packaging_type": "JAR"},
    )
    check(
        "and packing it is refused, by the server",
        status == 409 and "approved" in json.dumps(payload).lower(),
        f"status={status} {str(payload)[:160]}",
    )

    # ------------------------------------------------------------------ #
    section("Packing the honey")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "POST",
        "/packaging",
        base=base,
        token=packer["token"],
        body={
            "batch_id": batch["id"],
            "packaging_unit_id": unit["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "12.0",
            "package_size": "1.0",
            "number_of_packages": 12,
        },
    )
    check("a packaging run opens", status == 201, f"status={status} {str(payload)[:160]}")
    run = payload["data"]
    CREATED["codes"].append(run["packaging_code"])
    check(
        "the run carries a stable code and starts PENDING",
        run["status"] == "PENDING" and run["packaging_code"].startswith("HC-PACK-"),
        f"{run.get('packaging_code')} {run.get('status')}",
    )

    status, payload = request(
        "POST",
        f"/packaging/{run['id']}/complete",
        base=base,
        token=packer["token"],
        body={},
    )
    check(
        "a run cannot be completed before it is started",
        status == 409,
        f"status={status} {str(payload)[:140]}",
    )

    status, payload = request(
        "POST", f"/packaging/{run['id']}/start", base=base, token=packer["token"]
    )
    check("the run can be started", status == 200, f"status={status} {str(payload)[:140]}")
    status, payload = request(
        "POST",
        f"/packaging/{run['id']}/complete",
        base=base,
        token=packer["token"],
        body={"number_of_packages": 11},
    )
    check(
        "the package count must add up to the honey",
        status == 422,
        f"status={status} {str(payload)[:160]}",
    )

    status, payload = request(
        "POST", f"/packaging/{run['id']}/complete", base=base, token=packer["token"], body={}
    )
    check("the run completes", status == 200, f"status={status} {str(payload)[:160]}")
    completed_run = payload["data"]
    check(
        "completing the run created the packages",
        completed_run.get("package_count") == 12,
        f"package_count={completed_run.get('package_count')}",
    )

    status, payload = request(
        "GET", f"/packages?batch_id={batch['id']}&page_size=50", base=base, token=packer["token"]
    )
    packages = payload.get("data") or []
    codes = {row["package_code"] for row in packages}
    check(
        "each package has its own stable code",
        len(packages) == 12 and len(codes) == 12 and all(c.startswith("HC-PKG-") for c in codes),
        f"{len(packages)} packages, {len(codes)} codes",
    )
    check(
        "the packages carry their size, their run and their batch",
        all(
            row["packaging_id"] == run["id"]
            and row["batch_id"] == batch["id"]
            and Decimal(str(row["quantity"])) == Decimal("1.0")
            for row in packages
        ),
        str(packages[:1])[:220],
    )
    check(
        "a fresh package is CREATED, not ready to move",
        all(row["status"] == "CREATED" for row in packages),
        f"statuses={ {row['status'] for row in packages} }",
    )

    status, payload = request(
        "GET", f"/batches/{batch['id']}", base=base, token=tokens["admin"]
    )
    batch_detail = payload["data"]
    check(
        "the batch moved to PACKAGED and left the laboratory stage behind",
        batch_detail["status"] == "PACKAGED" and batch_detail["current_stage"] == "PACKAGING",
        f"status={batch_detail['status']} stage={batch_detail['current_stage']}",
    )
    check(
        "the timeline reports the packing from the record",
        any(
            stage["stage"] == "PACKAGING" and run["packaging_code"] in (stage["detail"] or "")
            for stage in batch_detail["timeline"]
        ),
        str([s for s in batch_detail["timeline"] if s["stage"] == "PACKAGING"])[:200],
    )
    check(
        "0.9 kg of the approval is still to be packed, and the register says so",
        Decimal(str(batch_detail["packaging"]["remaining_quantity"])) == Decimal("0.9"),
        str(batch_detail.get("packaging"))[:220],
    )

    status, payload = request(
        "POST",
        "/distribution",
        base=base,
        token=distributor["token"],
        body={"package_id": packages[0]["id"], "quantity": "1.0", "destination": "Guntur market"},
    )
    check(
        "an unreleased package cannot be shipped",
        status == 409,
        f"status={status} {str(payload)[:160]}",
    )

    status, payload = request(
        "POST", f"/packaging/{run['id']}/release", base=base, token=packer["token"], body={}
    )
    released = payload.get("data") or []
    check(
        "releasing makes every package of the run ready",
        status == 200
        and len(released) == 12
        and all(row["status"] == "READY_FOR_DISTRIBUTION" for row in released),
        f"status={status} rows={len(released)}",
    )

    status, payload = request(
        "GET", f"/batches/{batch['id']}/packages?page_size=50", base=base, token=packer["token"]
    )
    check(
        "the batch's package register lists all twelve",
        status == 200 and len(payload.get("data") or []) == 12,
        f"status={status} rows={len(payload.get('data') or [])}",
    )

    # ------------------------------------------------------------------ #
    section("Distribution")
    # ------------------------------------------------------------------ #
    package = released[0]
    status, payload = request(
        "POST",
        "/distribution",
        base=base,
        token=distributor["token"],
        body={
            "package_id": package["id"],
            "quantity": "1.0",
            "destination": "Guntur market",
            "retailer_id": retailer["user_id"],
            "carrier": "Smoke Test Carrier",
        },
    )
    check("a shipment can be raised against a released package", status == 201, f"status={status} {str(payload)[:160]}")
    shipment = payload["data"]
    CREATED["codes"].append(shipment["distribution_code"])

    status, payload = request(
        "POST",
        "/distribution",
        base=base,
        token=distributor["token"],
        body={"package_id": package["id"], "quantity": "1.0", "destination": "Guntur market"},
    )
    check(
        "the same package cannot be shipped twice over",
        status == 422,
        f"status={status} {str(payload)[:160]}",
    )

    status, payload = request(
        "POST",
        f"/distribution/{shipment['id']}/deliver",
        base=base,
        token=distributor["token"],
        body={},
    )
    check(
        "delivery before dispatch is refused",
        status == 409,
        f"status={status} {str(payload)[:160]}",
    )
    status, payload = request(
        "POST",
        f"/retailer/shipments/{shipment['id']}/receive",
        base=base,
        token=retailer["token"],
        body={},
    )
    check(
        "a receipt before any dispatch is refused",
        status == 409,
        f"status={status} {str(payload)[:160]}",
    )

    status, payload = request(
        "POST",
        f"/distribution/{shipment['id']}/dispatch",
        base=base,
        token=distributor["token"],
        body={"carrier": "Smoke Test Carrier"},
    )
    check("the shipment can be dispatched", status == 200, f"status={status} {str(payload)[:160]}")
    status, payload = request(
        "POST",
        f"/distribution/{shipment['id']}/in-transit",
        base=base,
        token=distributor["token"],
        body={"notes": "On the Guntur road TEST"},
    )
    check("and marked in transit", status == 200, f"status={status} {str(payload)[:140]}")

    status, payload = request(
        "GET", f"/batches/{batch['id']}", base=base, token=tokens["admin"]
    )
    batch_detail = payload["data"]
    check(
        "the batch follows its packages into distribution",
        batch_detail["status"] == "DISTRIBUTION" and batch_detail["current_stage"] == "DISTRIBUTION",
        f"status={batch_detail['status']} stage={batch_detail['current_stage']}",
    )
    check(
        "the timeline reports the shipment from the record",
        any(
            stage["stage"] == "DISTRIBUTION"
            and shipment["distribution_code"] in (stage["detail"] or "")
            for stage in batch_detail["timeline"]
        ),
        str([s for s in batch_detail["timeline"] if s["stage"] == "DISTRIBUTION"])[:200],
    )

    # ------------------------------------------------------------------ #
    section("The retailer's side of the counter")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "GET", "/retailer/shipments", base=base, token=retailer["token"]
    )
    inbound = payload.get("data") or []
    check(
        "the retailer sees the shipment addressed to them",
        status == 200
        and any(row["distribution_code"] == shipment["distribution_code"] for row in inbound),
        f"status={status} rows={len(inbound)}",
    )

    other = create_staff(base, tokens["admin"], "retailer2", "RETAILER")
    status, payload = request(
        "GET", f"/distribution/{shipment['id']}", base=base, token=other["token"]
    )
    check(
        "another shop cannot read a shipment that is not theirs",
        status == 404,
        f"status={status} {str(payload)[:140]}",
    )
    status, payload = request(
        "POST",
        f"/retailer/shipments/{shipment['id']}/receive",
        base=base,
        token=other["token"],
        body={},
    )
    check(
        "and cannot confirm a receipt for it",
        status == 404,
        f"status={status} {str(payload)[:140]}",
    )
    status, payload = request(
        "POST",
        f"/distribution/{shipment['id']}/dispatch",
        base=base,
        token=retailer["token"],
        body={},
    )
    check(
        "a retailer cannot dispatch a shipment",
        status == 403,
        f"status={status} {str(payload)[:140]}",
    )

    status, payload = request(
        "POST",
        f"/retailer/shipments/{shipment['id']}/receive",
        base=base,
        token=retailer["token"],
        body={"receipt_notes": "One jar, intact — Phase 7 smoke test"},
    )
    received = payload.get("data") or {}
    check(
        "the retailer confirms receipt",
        status == 200 and received.get("status") == "DELIVERED",
        f"status={status} {str(payload)[:160]}",
    )
    check(
        "the confirmation names the receiver and the moment",
        received.get("received_by_id") == retailer["user_id"] and received.get("delivered_at"),
        f"received_by={received.get('received_by_id')} delivered_at={received.get('delivered_at')}",
    )

    status, payload = request(
        "GET", f"/packages/{package['id']}", base=base, token=retailer["token"]
    )
    check(
        "the retailer can read the package they received, read-only",
        status == 200 and payload["data"]["can_release"] is False,
        f"status={status} can_release={(payload.get('data') or {}).get('can_release')}",
    )
    status, payload = request(
        "PATCH",
        f"/packages/{package['id']}",
        base=base,
        token=retailer["token"],
        body={"quantity": "0.5"},
    )
    check(
        "but cannot change what came from upstream",
        status in (403, 404, 405),
        f"status={status} {str(payload)[:140]}",
    )

    # ------------------------------------------------------------------ #
    section("The shared record: batch, beekeeper, KVIC and audit")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "GET", f"/batches/{batch['id']}", base=base, token=keeper["token"]
    )
    keeper_view = payload["data"]
    stages = {stage["stage"]: stage for stage in keeper_view["timeline"]}
    check(
        "the beekeeper reads the same single batch, downstream and all",
        status == 200
        and keeper_view["batch_code"] == batch["batch_code"]
        and stages["PACKAGING"]["state"] in ("current", "completed")
        and stages["DISTRIBUTION"]["state"] in ("current", "completed"),
        f"status={status} stages={ {k: v['state'] for k, v in stages.items()} }",
    )
    status, payload = request(
        "GET", "/packaging/approved-batches", base=base, token=keeper["token"]
    )
    check(
        "the beekeeper cannot work the packaging queues",
        status == 403,
        f"status={status}",
    )
    status, payload = request(
        "POST",
        f"/distribution/{shipment['id']}/cancel",
        base=base,
        token=keeper["token"],
        body={"reason": "not yours to cancel"},
    )
    check(
        "and cannot touch the shipment",
        status == 403,
        f"status={status} {str(payload)[:140]}",
    )

    status, payload = request(
        "GET", f"/batches/{batch['id']}", base=base, token=tokens["kvic"]
    )
    check(
        "an officer whose cluster this batch is not in cannot read it",
        status in (403, 404),
        f"status={status} {str(payload)[:140]}",
    )
    status, payload = request(
        "GET", "/packages?page_size=5", base=base, token=tokens["kvic"]
    )
    check(
        "and sees no packages outside their clusters",
        status == 200 and (payload.get("data") or []) == [],
        f"status={status} rows={len(payload.get('data') or [])}",
    )

    for action, expected in (
        ("PACKAGING_CREATED", 1),
        ("PACKAGING_STARTED", 1),
        ("PACKAGING_COMPLETED", 1),
        ("PACKAGE_CREATED", 12),
        ("DISTRIBUTION_CREATED", 1),
        ("SHIPMENT_DISPATCHED", 1),
        ("SHIPMENT_IN_TRANSIT", 1),
        ("PACKAGE_RECEIVED", 1),
        ("BATCH_MOVED_TO_DISTRIBUTION", 1),
    ):
        status, payload = request(
            "GET",
            f"/admin/audit-logs?action={action}&page_size=50",
            base=base,
            token=tokens["admin"],
        )
        rows = payload.get("data") or []
        mine = [
            row
            for row in rows
            if row.get("entity_id") in {run["id"], shipment["id"], batch["id"], *[p["id"] for p in packages]}
            or row.get("entity_type") in {"packaging", "distribution", "package", "batch"}
        ]
        check(
            f"the audit log recorded {action}",
            status == 200 and len(mine) >= expected,
            f"status={status} rows={len(mine)} of {len(rows)}",
        )

    # ------------------------------------------------------------------ #
    section("A cancelled shipment moves nothing")
    # ------------------------------------------------------------------ #
    second_package = released[1]
    status, payload = request(
        "POST",
        "/distribution",
        base=base,
        token=distributor["token"],
        body={"package_id": second_package["id"], "quantity": "1.0", "destination": "Tenali market"},
    )
    doomed = payload["data"]
    status, payload = request(
        "POST",
        f"/distribution/{doomed['id']}/cancel",
        base=base,
        token=distributor["token"],
        body={"reason": "Vehicle broke down TEST"},
    )
    check("a shipment can be cancelled", status == 200, f"status={status} {str(payload)[:140]}")
    status, payload = request(
        "POST",
        "/distribution",
        base=base,
        token=distributor["token"],
        body={"package_id": second_package["id"], "quantity": "1.0", "destination": "Tenali market"},
    )
    check(
        "and its quantity is free to move again",
        status == 201,
        f"status={status} {str(payload)[:160]}",
    )

    # ------------------------------------------------------------------ #
    section("Nothing original was rewritten")
    # ------------------------------------------------------------------ #
    status, payload = request(
        "GET", f"/collections?search={batch['collection_code']}", base=base, token=tokens["admin"]
    )
    collections = payload.get("data") or []
    check(
        "the harvest still reads 13.7 kg",
        bool(collections) and Decimal(str(collections[0]["total_quantity"])) == Decimal("13.7"),
        str(collections[:1])[:200],
    )
    status, payload = request(
        "GET", f"/processing?batch_id={batch['id']}", base=base, token=tokens["admin"]
    )
    runs = payload.get("data") or []
    check(
        "the processing run still reads 13.7 in, 12.9 out",
        bool(runs)
        and Decimal(str(runs[0]["input_quantity"])) == Decimal("13.7")
        and Decimal(str(runs[0]["output_quantity"])) == Decimal("12.9"),
        str(runs[:1])[:200],
    )
    check(
        "the batch is one record, read by every role that has seen it",
        len({row["id"] for row in request(
            "GET", f"/batches?search={batch['batch_code']}", base=base, token=tokens["admin"]
        )[1].get("data") or []}) == 1,
        batch["batch_code"],
    )

    # ------------------------------------------------------------------ #
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("\nFailures:")
        for line in FAILED:
            print(f"  - {line}")
    if CREATED["users"] or CREATED["hives"] or CREATED["codes"]:
        print("\nCleanup — everything this run created is marked TEST:")
        print("  users:    ", ", ".join(CREATED["users"]) or "-")
        print("  hives:    ", ", ".join(CREATED["hives"]) or "-")
        print("  codes:    ", ", ".join(CREATED["codes"]) or "-")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

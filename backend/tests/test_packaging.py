"""Phase 7 — packaging an approved batch into packages, and who may do it.

The claims this module defends, in the order the workflow makes them:

* only a laboratory-approved batch may be packed — a rejected batch, an
  inconclusive one and a batch still under test are all refused, and refused by
  the server rather than by a hidden button;
* the honey is accounted for — a run cannot pack more than the batch has left,
  cannot claim more packages than the honey it recorded, cannot take more from
  the batch than it put in, and a cancelled run consumes nothing;
* the batch moves because the packages exist — completion is what creates the
  package rows and what moves ``APPROVED`` → ``PACKAGED``, and a partial second
  run is allowed while honey remains;
* the packages are real, individually identified rows, each carrying its own
  stable code, its own size and the batch it came from;
* existence is not readiness — a package must be released before a shipment may
  name it;
* the collection, the processing run and the batch quantities are untouched by
  any of it;
* the roles stay in their lanes — a distributor, a beekeeper, a laboratory
  technician or a processor cannot pack, and a packaging unit cannot edit a
  laboratory result or a processing run;
* the beekeeper and the KVIC officer see the very same rows, read-only.

Every check goes through the HTTP API.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.enums import AuditAction, BatchStatus, PackageStatus, PackagingStatus, UserRole
from app.models.honey_batch import HoneyBatch
from app.models.packaging import HoneyPackage, PackagingRun

API = "/api/v1"

#: The source every configured limit in this project carries: a demonstration
#: limit for the pilot, not a regulatory or certification standard.
DEMO_SOURCE = "Project-configured demonstration limit for tests (not a regulatory standard)"

HIVE_PAYLOAD = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
}

LABORATORY_PAYLOAD = {
    "name": "Phase 7 Packaging Laboratory",
    "location": "Guntur",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "notes": "Phase 7 test fixture",
}

PACKAGING_UNIT_PAYLOAD = {
    "name": "Phase 7 Packing Unit",
    "registration_identifier": "REG-PHASE7-TEST",
    "location": "Guntur",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "notes": "Phase 7 test fixture",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def sign_in(client: TestClient, payload: dict) -> dict[str, str]:
    response = client.post(
        f"{API}/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def make_hive(client: TestClient, headers: dict) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json=HIVE_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_batch(client: TestClient, headers: dict, hive: dict, quantity: str = "13.7") -> dict:
    response = client.post(
        f"{API}/collections",
        headers=headers,
        json={
            "hives": [{"hive_id": hive["id"], "quantity": quantity}],
            "collection_date": date.today().isoformat(),
            "unit": "KG",
        },
    )
    assert response.status_code == 201, response.text
    collection = response.json()["data"]
    response = client.post(f"{API}/collections/{collection['id']}/complete", headers=headers)
    assert response.status_code == 200, response.text
    batch_id = response.json()["meta"]["batch"]["id"]
    response = client.get(f"{API}/batches/{batch_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def approve_batch(
    client: TestClient,
    headers: dict,
    lab_headers: dict,
    batch_id: str,
    *,
    measured: str,
    config_headers: dict,
) -> dict:
    """Take a collected batch all the way to APPROVED — the only way to get one."""
    run = client.post(
        f"{API}/processing",
        headers=headers,
        json={"batch_id": batch_id, "processing_type": "FILTERING"},
    ).json()["data"]
    client.post(f"{API}/processing/{run['id']}/start", headers=headers)
    client.post(
        f"{API}/processing/{run['id']}/complete",
        headers=headers,
        json={"input_quantity": "13.7", "output_quantity": measured},
    )
    laboratory = client.post(
        f"{API}/laboratories", headers=lab_headers, json=LABORATORY_PAYLOAD
    ).json()["data"]
    test_response = client.post(
        f"{API}/lab-tests",
        headers=lab_headers,
        json={
            "batch_id": batch_id,
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
        },
    )
    assert test_response.status_code == 201, test_response.text
    test = test_response.json()["data"]
    # A verdict needs a range to judge against, so the catalogue is configured
    # first — with the demonstration source the project always uses, never as a
    # regulatory standard. With the range in place, 17.2 passes and the batch is
    # approved by the laboratory's own rule engine rather than by an override.
    parameter = client.get(f"{API}/lab-parameters", headers=lab_headers).json()["data"][0]
    configured = client.patch(
        f"{API}/lab-parameters/{parameter['code']}",
        headers=config_headers,
        json={
            "reference_min": "10",
            "reference_max": "20",
            "reference_source": DEMO_SOURCE,
            "is_required": True,
        },
    )
    assert configured.status_code == 200, configured.text
    recorded = client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=lab_headers,
        json={"parameter_code": parameter["code"], "value": "17.2"},
    )
    assert recorded.status_code == 201, recorded.text
    completed = client.post(f"{API}/lab-tests/{test['id']}/complete", headers=lab_headers, json={})
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["overall_result"] == "PASS", completed.text
    return client.get(f"{API}/batches/{batch_id}", headers=headers).json()["data"]


def open_run(client: TestClient, headers: dict, batch_id: str, **payload) -> dict:
    body = {"batch_id": batch_id, "packaging_type": "JAR", **payload}
    response = client.post(f"{API}/packaging", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def packaging_row(db: Session, packaging_id) -> PackagingRun:
    record = db.get(PackagingRun, uuid.UUID(str(packaging_id)))
    assert record is not None
    db.refresh(record)
    return record


def packages_of(client: TestClient, headers: dict, batch_id, *, page_size: int = 100) -> list[dict]:
    """Every package of a batch, paged past the default page size on purpose."""
    response = client.get(
        f"{API}/packages?batch_id={batch_id}&page_size={page_size}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def package_row(db: Session, package_id) -> HoneyPackage:
    record = db.get(HoneyPackage, uuid.UUID(str(package_id)))
    assert record is not None
    db.refresh(record)
    return record


def audit_actions(db: Session, action: AuditAction) -> list[AuditLog]:
    db.expire_all()
    return db.query(AuditLog).filter(AuditLog.action == str(action)).all()


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def packer(client: TestClient, make_privileged_user, admin_payload):
    """A packing operator, working at a facility an administrator registered.

    The order matters and it is the platform's order: the **administrator** registers
    the facility and puts the operator to work at it, and only then can the operator
    open a run. An account with no facility is refused by the API (409) with the
    action that fixes it, which is asserted on its own in the unit tests below.
    """
    admin_login = client.post(
        f"{API}/auth/login",
        json={"email": admin_payload["email"], "password": admin_payload["password"]},
    )
    assert admin_login.status_code == 200, admin_login.text
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['data']['access_token']}"}

    unit = client.post(
        f"{API}/packaging-units", headers=admin_headers, json=PACKAGING_UNIT_PAYLOAD
    )
    assert unit.status_code == 201, unit.text
    unit_body = unit.json()["data"]

    payload = make_privileged_user(
        role=UserRole.PACKAGING_UNIT,
        name="Phase 7 Packer",
        password="PackPass123",
    )
    attached = client.post(
        f"{API}/packaging-units/{unit_body['id']}/members",
        headers=admin_headers,
        json={"user_id": str(payload["id"])},
    )
    assert attached.status_code == 200, attached.text

    payload["headers"] = sign_in(client, payload)
    payload["unit"] = unit_body
    return payload


@pytest.fixture()
def distributor(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.DISTRIBUTOR, name="Phase 7 Distributor", password="DistPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def retailer(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.RETAILER, name="Phase 7 Retailer", password="RetailPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def technician(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.LAB_TECHNICIAN, name="Phase 7 Technician", password="TechPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def processor(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.PROCESSOR, name="Phase 7 Processor", password="ProcPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def keeper(client: TestClient, register_user):
    """A beekeeper whose batch is approved and ready to pack."""
    payload = register_user(name="Phase 7 Beekeeper", email=None)
    payload["headers"] = {"Authorization": f"Bearer {payload['access_token']}"}
    payload["hive"] = make_hive(client, payload["headers"])
    payload["batch"] = make_batch(client, payload["headers"], payload["hive"])
    return payload


@pytest.fixture()
def approved(client: TestClient, admin_headers, technician, keeper):
    """The approved batch, plus the laboratory that decided it."""
    return approve_batch(
        client,
        admin_headers,
        technician["headers"],
        keeper["batch"]["id"],
        measured="12.9",
        config_headers=admin_headers,
    )


@pytest.fixture()
def packed(client: TestClient, packer, approved):
    """One completed packaging run and its packages, ready to be shipped."""
    run = open_run(
        client,
        packer["headers"],
        approved["id"],
        packaging_unit_id=packer["unit"]["id"],
        packaged_quantity="12.5",
        package_size="0.5",
        number_of_packages=25,
    )
    client.post(f"{API}/packaging/{run['id']}/start", headers=packer["headers"])
    completed = client.post(
        f"{API}/packaging/{run['id']}/complete", headers=packer["headers"], json={}
    )
    assert completed.status_code == 200, completed.text
    detail = completed.json()["data"]
    # The detail carries the first page of packages; the fixture hands the tests
    # the whole set, so a check on "all of them" is really about all of them.
    detail["packages"] = packages_of(client, packer["headers"], approved["id"])
    return detail


# --------------------------------------------------------------------------- #
# Eligibility: only an approved batch may be packed
# --------------------------------------------------------------------------- #
def test_a_collected_batch_cannot_be_packed(client, admin_headers, keeper, packer):
    response = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={"batch_id": keeper["batch"]["id"], "packaging_type": "JAR"},
    )
    assert response.status_code == 409, response.text
    assert "approved" in response.json()["error"]["message"].lower()


def test_a_batch_still_under_test_cannot_be_packed(client, admin_headers, keeper, packer):
    """Processing done, laboratory not finished: there is no verdict to act on."""
    run = client.post(
        f"{API}/processing",
        headers=admin_headers,
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    client.post(f"{API}/processing/{run['id']}/start", headers=admin_headers)
    client.post(
        f"{API}/processing/{run['id']}/complete",
        headers=admin_headers,
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    response = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={"batch_id": keeper["batch"]["id"], "packaging_type": "JAR"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["batch_status"] == "LAB_TESTING"


def test_a_batch_without_a_verdict_is_refused_with_its_own_reason(
    client, admin_headers, technician, keeper, packer
):
    """An undecided batch — not approved and not rejected — is still not packable.

    The laboratory is asked to decide a sample it has no range for, so the honest
    outcome is INCONCLUSIVE. The point of the check is that INCONCLUSIVE is not a
    quiet approval: the batch stays at the laboratory stage and the packing unit's
    attempt is refused, with the reason spelled out.
    """
    run = client.post(
        f"{API}/processing",
        headers=admin_headers,
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    client.post(f"{API}/processing/{run['id']}/start", headers=admin_headers)
    client.post(
        f"{API}/processing/{run['id']}/complete",
        headers=admin_headers,
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    laboratory = client.post(
        f"{API}/laboratories", headers=technician["headers"], json=LABORATORY_PAYLOAD
    ).json()["data"]
    test = client.post(
        f"{API}/lab-tests",
        headers=technician["headers"],
        json={
            "batch_id": keeper["batch"]["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
        },
    ).json()["data"]
    parameter = client.get(f"{API}/lab-parameters", headers=technician["headers"]).json()["data"][0]
    client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=technician["headers"],
        json={"parameter_code": parameter["code"], "value": "17.2"},
    )
    completed = client.post(
        f"{API}/lab-tests/{test['id']}/complete", headers=technician["headers"], json={}
    ).json()["data"]
    assert completed["overall_result"] == "INCONCLUSIVE", completed

    detail = client.get(
        f"{API}/batches/{keeper['batch']['id']}", headers=admin_headers
    ).json()["data"]
    # A test closed with no verdict is a *hold*, not a limbo: the batch is held
    # until somebody decides, and packaging is blocked rather than merely unready.
    assert detail["status"] == "LAB_HOLD"

    response = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={"batch_id": keeper["batch"]["id"], "packaging_type": "JAR"},
    )
    assert response.status_code == 409, response.text
    details = response.json()["error"]["details"]
    assert details["batch_status"] == "LAB_HOLD"
    assert "hold" in details["reason"].lower(), details["reason"]


def test_the_worklist_shows_only_approved_batches(client, admin_headers, keeper, approved, packer):
    response = client.get(f"{API}/packaging/approved-batches", headers=packer["headers"])
    assert response.status_code == 200, response.text
    codes = [row["batch_code"] for row in response.json()["data"]]
    assert approved["batch_code"] in codes
    assert keeper["batch"]["batch_code"] in codes
    # And a batch that is not approved is not merely filtered out of the page: it
    # is never in the answer, because the query asks for the packable statuses.
    collected = make_batch(client, keeper["headers"], keeper["hive"], quantity="4.0")
    response = client.get(f"{API}/packaging/approved-batches", headers=packer["headers"])
    assert collected["batch_code"] not in [row["batch_code"] for row in response.json()["data"]]


def test_the_worklist_carries_the_quantities_and_the_source(client, packer, approved):
    response = client.get(f"{API}/packaging/approved-batches", headers=packer["headers"])
    row = next(r for r in response.json()["data"] if r["batch_id"] == approved["id"])
    assert row["approved_quantity"] == "12.900"
    assert row["packaged_quantity"] == "0"
    assert row["remaining_quantity"] == "12.900"
    assert row["collection_quantity"] == "13.700"
    assert row["beekeeper_name"]
    assert row["laboratory_test_code"]


# --------------------------------------------------------------------------- #
# Quantities
# --------------------------------------------------------------------------- #
def test_packaging_more_than_the_batch_has_is_refused(client, packer, approved):
    response = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={
            "batch_id": approved["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "99.0",
            "package_size": "1.0",
            "number_of_packages": 99,
        },
    )
    assert response.status_code == 422, response.text
    details = response.json()["error"]["details"]
    assert details["approved_quantity"] == "12.900"
    assert details["remaining_quantity"] == "12.900"


def test_a_second_run_may_pack_what_the_first_left(client, packer, packed, approved):
    """96 approved, 40 packed, 56 left — and the remainder is packable."""
    remaining = client.get(
        f"{API}/packaging/approved-batches", headers=packer["headers"]
    ).json()["data"]
    row = next(r for r in remaining if r["batch_id"] == approved["id"])
    assert row["packaged_quantity"] == "12.500"
    assert row["remaining_quantity"] == "0.400"

    run = open_run(
        client,
        packer["headers"],
        approved["id"],
        packaged_quantity="0.4",
        package_size="0.4",
        number_of_packages=1,
    )
    client.post(f"{API}/packaging/{run['id']}/start", headers=packer["headers"])
    completed = client.post(
        f"{API}/packaging/{run['id']}/complete", headers=packer["headers"], json={}
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["quantities"]["remaining_quantity"] == "0.000"


def test_the_second_run_cannot_pack_more_than_the_remainder(client, packer, packed, approved):
    response = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={
            "batch_id": approved["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "5.0",
            "package_size": "1.0",
            "number_of_packages": 5,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["remaining_quantity"] == "0.400"


def test_the_package_count_must_add_up_to_the_honey(client, packer, approved):
    """Forty jars of 1 kg and 30 kg of honey cannot both be true."""
    run = open_run(
        client,
        packer["headers"],
        approved["id"],
        packaged_quantity="12.5",
        package_size="0.5",
        number_of_packages=25,
    )
    client.post(f"{API}/packaging/{run['id']}/start", headers=packer["headers"])
    response = client.post(
        f"{API}/packaging/{run['id']}/complete",
        headers=packer["headers"],
        json={"number_of_packages": 20},
    )
    assert response.status_code == 422, response.text
    details = response.json()["error"]["details"]
    assert details["package_size_x_count"] == "10.000"
    assert details["packaged_quantity"] == "12.500"


def test_a_run_cannot_complete_without_the_figures(client, packer, approved):
    run = open_run(client, packer["headers"], approved["id"])
    client.post(f"{API}/packaging/{run['id']}/start", headers=packer["headers"])
    response = client.post(f"{API}/packaging/{run['id']}/complete", headers=packer["headers"], json={})
    assert response.status_code == 422, response.text
    assert "missing" in response.json()["error"]["details"]


def test_a_cancelled_run_consumes_nothing(client, packer, approved, db):
    run = open_run(
        client,
        packer["headers"],
        approved["id"],
        packaged_quantity="12.5",
        package_size="0.5",
        number_of_packages=25,
    )
    client.post(
        f"{API}/packaging/{run['id']}/cancel",
        headers=packer["headers"],
        json={"reason": "Batch was repacked on another line"},
    )
    assert packaging_row(db, run["id"]).status is PackagingStatus.CANCELLED
    row = next(
        r
        for r in client.get(f"{API}/packaging/approved-batches", headers=packer["headers"]).json()["data"]
        if r["batch_id"] == approved["id"]
    )
    assert row["remaining_quantity"] == "12.900"


def test_the_original_quantities_are_never_touched(client, admin_headers, packer, packed, approved, db):
    """The harvest, the processing run and the batch are exactly as they were."""
    record = db.get(HoneyBatch, uuid.UUID(str(approved["id"])))
    db.refresh(record)
    assert str(record.quantity) == "13.700"
    runs = client.get(f"{API}/processing?batch_id={approved['id']}", headers=admin_headers).json()["data"]
    assert runs[0]["input_quantity"] == "13.700"
    assert runs[0]["output_quantity"] == "12.900"


# --------------------------------------------------------------------------- #
# Completion, the batch move and the packages
# --------------------------------------------------------------------------- #
def test_completing_packaging_creates_the_packages_and_moves_the_batch(
    client, admin_headers, packer, approved, db
):
    run = open_run(
        client,
        packer["headers"],
        approved["id"],
        packaged_quantity="12.5",
        package_size="0.5",
        number_of_packages=25,
    )
    client.post(f"{API}/packaging/{run['id']}/start", headers=packer["headers"])
    completed = client.post(
        f"{API}/packaging/{run['id']}/complete", headers=packer["headers"], json={}
    )
    assert completed.status_code == 200, completed.text
    detail = completed.json()["data"]
    assert detail["status"] == "COMPLETED"
    assert detail["package_count"] == 25
    packages = packages_of(client, packer["headers"], approved["id"])
    assert len(packages) == 25
    codes = {row["package_code"] for row in packages}
    assert len(codes) == 25, "every package needs its own stable code"
    assert all(code.startswith("HC-PKG-") for code in codes)

    record = db.get(HoneyBatch, uuid.UUID(str(approved["id"])))
    db.refresh(record)
    assert record.status is BatchStatus.PACKAGED
    assert record.current_stage.value == "PACKAGING"


def test_the_timeline_reports_packaging_from_the_records(client, admin_headers, packed, approved):
    """Partially packed: the stage is current, and its detail names the real run."""
    detail = client.get(f"{API}/batches/{approved['id']}", headers=admin_headers).json()["data"]
    stages = {stage["stage"]: stage for stage in detail["timeline"]}
    assert stages["PACKAGING"]["state"] == "current"
    assert packed["packaging_code"] in stages["PACKAGING"]["detail"]
    assert stages["DISTRIBUTION"]["module_available"] is True
    assert detail["current_stage"] == "PACKAGING"
    assert detail["packaging"]["completed_count"] == 1
    assert detail["packaging"]["package_count"] == 25
    assert detail["packaging"]["remaining_quantity"] == "0.400"


def test_a_package_keeps_its_own_identity_and_its_batch(client, packer, packed):
    package = packed["packages"][0]
    detail = client.get(f"{API}/packages/{package['id']}", headers=packer["headers"]).json()["data"]
    assert detail["package_code"] == package["package_code"]
    assert detail["batch_id"] == packed["batch_id"]
    assert detail["packaging_id"] == packed["id"]
    assert detail["package_size"] == "0.500"
    assert detail["quantity"] == "0.500"
    kinds = [node["kind"] for node in detail["traceability"]]
    assert kinds[0] == "PACKAGE"
    assert "BATCH" in kinds
    assert "COLLECTION" in kinds
    assert "HIVE" in kinds
    assert "BEEKEEPER" in kinds


def test_the_batch_package_endpoint_lists_them_in_order(client, packer, packed, approved):
    """Newest first, numbered without a gap — the register of a batch's packages."""
    response = client.get(
        f"{API}/batches/{approved['id']}/packages?page_size=100", headers=packer["headers"]
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    sequences = [row["sequence_number"] for row in rows]
    assert len(rows) == 25
    assert sequences == sorted(sequences, reverse=True)
    assert sorted(sequences) == list(range(1, 26))
    assert all(row["batch_id"] == approved["id"] for row in rows)


def test_a_package_must_be_released_before_it_can_be_shipped(
    client, packer, distributor, retailer, packed, db
):
    package = packed["packages"][0]
    assert package["status"] == "CREATED"
    response = client.post(
        f"{API}/distribution",
        headers=distributor["headers"],
        json={
            "package_id": package["id"],
            "quantity": "0.2",
            "destination": "Guntur market",
            # A named receiver, so the refusal under test is the one about the
            # package's readiness.
            "retailer_id": str(retailer["id"]),
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["package_status"] == "CREATED"

    released = client.post(
        f"{API}/packages/{package['id']}/release", headers=packer["headers"], json={}
    )
    assert released.status_code == 200, released.text
    assert released.json()["data"]["status"] == "READY_FOR_DISTRIBUTION"


def test_release_moves_every_package_of_the_run(client, packer, packed):
    response = client.post(f"{API}/packaging/{packed['id']}/release", headers=packer["headers"])
    assert response.status_code == 200, response.text
    released = response.json()["data"]
    assert len(released) == 25
    assert all(row["status"] == "READY_FOR_DISTRIBUTION" for row in released)
    assert all(row["released_at"] for row in released)


# --------------------------------------------------------------------------- #
# Status transitions
# --------------------------------------------------------------------------- #
def test_a_completed_run_cannot_be_restarted_or_completed_again(client, packer, packed):
    again = client.post(f"{API}/packaging/{packed['id']}/complete", headers=packer["headers"], json={})
    assert again.status_code == 409, again.text
    restart = client.post(f"{API}/packaging/{packed['id']}/start", headers=packer["headers"])
    assert restart.status_code == 409, restart.text


def test_a_completed_run_cannot_be_edited(client, packer, packed):
    response = client.patch(
        f"{API}/packaging/{packed['id']}", headers=packer["headers"], json={"packaged_quantity": "1.0"}
    )
    assert response.status_code == 409, response.text


def test_a_cancelled_run_cannot_be_started(client, packer, approved):
    run = open_run(client, packer["headers"], approved["id"])
    client.post(f"{API}/packaging/{run['id']}/cancel", headers=packer["headers"], json={})
    response = client.post(f"{API}/packaging/{run['id']}/start", headers=packer["headers"])
    assert response.status_code == 409, response.text


def test_only_one_run_may_be_open_per_batch(client, packer, approved):
    open_run(client, packer["headers"], approved["id"])
    response = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={"batch_id": approved["id"], "packaging_type": "JAR"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["packaging_code"].startswith("HC-PACK-")


def test_the_caller_cannot_set_a_status(client, packer, approved):
    response = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={"batch_id": approved["id"], "packaging_type": "JAR", "status": "COMPLETED"},
    )
    assert response.status_code == 422, response.text

    response = client.post(
        f"{API}/packaging",
        headers=packer["headers"],
        json={
            "batch_id": approved["id"],
            "packaging_type": "JAR",
            "packaged_quantity": "1.0",
            "package_size": "1.0",
            "number_of_packages": 1,
            "packaging_code": "HC-PACK-1999-000001",
        },
    )
    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# Who may do what
# --------------------------------------------------------------------------- #
def test_a_distributor_cannot_pack(client, distributor, approved):
    response = client.post(
        f"{API}/packaging",
        headers=distributor["headers"],
        json={"batch_id": approved["id"], "packaging_type": "JAR"},
    )
    assert response.status_code == 403, response.text


def test_a_beekeeper_cannot_pack_their_own_honey(client, keeper, approved):
    response = client.post(
        f"{API}/packaging",
        headers=keeper["headers"],
        json={"batch_id": approved["id"], "packaging_type": "JAR"},
    )
    assert response.status_code == 403, response.text


def test_a_processor_cannot_pack(client, processor, approved):
    response = client.post(
        f"{API}/packaging",
        headers=processor["headers"],
        json={"batch_id": approved["id"], "packaging_type": "JAR"},
    )
    assert response.status_code == 403, response.text


def test_a_technician_cannot_pack(client, technician, approved):
    response = client.post(
        f"{API}/packaging",
        headers=technician["headers"],
        json={"batch_id": approved["id"], "packaging_type": "JAR"},
    )
    assert response.status_code == 403, response.text


def test_a_packaging_unit_cannot_write_a_laboratory_result(client, packer, approved):
    tests = client.get(f"{API}/lab-tests?batch_id={approved['id']}", headers=packer["headers"])
    assert tests.status_code == 200, tests.text
    test = tests.json()["data"][0]
    response = client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=packer["headers"],
        json={"parameter_code": "MOISTURE", "value": "18.0"},
    )
    assert response.status_code == 403, response.text


def test_a_packaging_unit_cannot_change_a_processing_run(client, packer, approved):
    runs = client.get(f"{API}/processing?batch_id={approved['id']}", headers=packer["headers"])
    assert runs.status_code == 200, runs.text
    run = runs.json()["data"][0]
    response = client.patch(
        f"{API}/processing/{run['id']}", headers=packer["headers"], json={"output_quantity": "1.0"}
    )
    assert response.status_code == 403, response.text


def test_a_beekeeper_reads_the_packages_of_their_own_honey(client, keeper, packer, packed):
    assert len(packages_of(client, keeper["headers"], packed["batch_id"])) == 25


def test_a_beekeeper_cannot_reach_another_keepers_packages(client, register_user, packer, packed):
    other = register_user(name="Other Phase 7 Beekeeper", email=None)
    other["headers"] = {"Authorization": f"Bearer {other['access_token']}"}
    response = client.get(
        f"{API}/packages/{packed['packages'][0]['id']}", headers=other["headers"]
    )
    assert response.status_code == 404, response.text


def test_an_officer_reads_the_packages_of_the_clusters_they_may_open(
    client, admin_headers, make_privileged_user, keeper, packer, packed
):
    """A cluster officer reads the packages of the batches they can open.

    The list used to come back empty here: the officer's scope was taken from the
    district on their profile while the cluster registry — which the same officer
    may read in full — was not, so a batch they could open from one screen had no
    packages on the next. The registry rule now answers both questions the same way.
    """
    officer = make_privileged_user(
        role=UserRole.KVIC_OFFICER, name="Phase 7 Officer", password="OfficerPass123"
    )
    officer["headers"] = sign_in(client, officer)
    # page_size is explicit: this is a scope assertion, and the run is bigger
    # than the default page, so leaving it out would have tested pagination.
    response = client.get(
        f"{API}/packages?batch_id={packed['batch_id']}&page_size=100",
        headers=officer["headers"],
    )
    assert response.status_code == 200, response.text
    codes = [row["package_code"] for row in response.json()["data"]]
    # Every package of the run is here — and only this run's: the officer reads a
    # register, so packages of other batches in the same database may be present,
    # but none from this batch may be missing.
    assert codes == list(dict.fromkeys(codes)), "the officer's list repeats a package"
    assert {row["package_code"] for row in packed["packages"]} <= set(codes)
    assert {row["id"] for row in packed["packages"]} == {
        row["id"] for row in response.json()["data"] if row["batch_id"] == packed["batch_id"]
    }


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def test_the_packaging_events_are_written(client, packer, packed, db):
    assert audit_actions(db, AuditAction.PACKAGING_CREATED)
    assert audit_actions(db, AuditAction.PACKAGING_STARTED)
    assert audit_actions(db, AuditAction.PACKAGING_COMPLETED)
    created = audit_actions(db, AuditAction.PACKAGE_CREATED)
    assert len(created) == 25
    payload = created[0].event_metadata
    assert payload["batch_code"]
    assert payload["packaging_code"] == packed["packaging_code"]
    assert created[0].user_id is not None


def test_the_audit_row_names_the_actor_and_the_batch(client, packer, packed, db):
    completed = audit_actions(db, AuditAction.PACKAGING_COMPLETED)[0]
    payload = completed.event_metadata
    assert payload["batch_code"] == packed["batch_code"]
    assert payload["number_of_packages"] == 25
    assert payload["batch_status"] == "PACKAGED"
    assert str(completed.actor_role) == "PACKAGING_UNIT"

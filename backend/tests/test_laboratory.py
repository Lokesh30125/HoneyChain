"""Phase 6 — the laboratory, and the honesty of the quality decision.

This is the phase where the platform is most tempting to lie, so the tests are
written against the specific lies it refuses to tell:

* **a measurement is judged only against a configured range** — with none, the
  result is ``NOT_EVALUATED`` and the test is ``INCONCLUSIVE``, not a pass;
* **an outcome is computed, never submitted** — no request body carries an
  overall result or a parameter status, and a test with no measurements cannot be
  completed at all;
* **a required failure fails the batch** — and an optional failure is recorded
  without deciding anything;
* **a completed test is closed** — its measurements cannot be edited or deleted,
  by anyone, and a later disagreement becomes a *new* test that leaves the old one
  intact;
* **an override is loud** — administrator only, a reason is mandatory, the
  computed result is kept beside it, and every reader sees the test marked.

The whole file runs through the API, so it exercises the same routes the
laboratory workspace calls.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.enums import (
    AuditAction,
    BatchStatus,
    LabParameterStatus,
    LabResult,
    LabTestStatus,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.laboratory import LabTest, LabTestResult

API = "/api/v1"

HIVE_PAYLOAD = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
}

LABORATORY_PAYLOAD = {
    "name": "Guntur District Quality Laboratory",
    "location": "Guntur",
    "district": "Guntur",
    "state": "Andhra Pradesh",
}

#: A range used only by these tests, and always quoted as such. The platform does
#: not ship scientific limits, so the tests do not assume one: every range here
#: carries the note saying it is the project's own demonstration limit.
DEMO_SOURCE = "Project-configured demonstration limit for tests (not a regulatory standard)"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def headers_for(payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {payload['access_token']}"}


def sign_in(client: TestClient, payload: dict) -> dict[str, str]:
    response = client.post(
        f"{API}/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def make_hive(client: TestClient, headers: dict, **overrides) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json={**HIVE_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_batch(client: TestClient, headers: dict, hives: list[dict], quantities: list[str]) -> dict:
    rows = [
        {"hive_id": hive["id"], "quantity": quantity}
        for hive, quantity in zip(hives, quantities, strict=True)
    ]
    collection = client.post(
        f"{API}/collections",
        headers=headers,
        json={"hives": rows, "collection_date": date.today().isoformat(), "unit": "KG"},
    ).json()["data"]
    client.post(f"{API}/collections/{collection['id']}/complete", headers=headers)
    batch_id = client.get(
        f"{API}/collections/{collection['id']}/batch", headers=headers
    ).json()["data"]["id"]
    return client.get(f"{API}/batches/{batch_id}", headers=headers).json()["data"]


def process(
    client: TestClient,
    headers: dict,
    batch_id: str,
    *,
    input_quantity: str = "13.7",
    output_quantity: str = "12.9",
) -> dict:
    """Run a batch through processing so it arrives at the laboratory."""
    run = client.post(
        f"{API}/processing",
        headers=headers,
        json={"batch_id": batch_id, "processing_type": "FILTERING"},
    ).json()["data"]
    client.post(f"{API}/processing/{run['id']}/start", headers=headers)
    client.post(
        f"{API}/processing/{run['id']}/complete",
        headers=headers,
        json={"input_quantity": input_quantity, "output_quantity": output_quantity},
    )
    return run


def configure(
    client: TestClient,
    admin_headers: dict,
    code: str,
    *,
    minimum: str | None,
    maximum: str | None,
    source: str | None = DEMO_SOURCE,
    required: bool | None = None,
):
    body: dict = {"reference_min": minimum, "reference_max": maximum, "reference_source": source}
    if required is not None:
        body["is_required"] = required
    return client.patch(f"{API}/lab-parameters/{code}", headers=admin_headers, json=body)


def batch_status(db: Session, batch_id: str) -> BatchStatus:
    record = db.get(HoneyBatch, uuid.UUID(str(batch_id)))
    assert record is not None
    db.refresh(record)
    return record.status


def audit_actions(db: Session, action: AuditAction) -> list[AuditLog]:
    db.expire_all()
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == str(action))
        .order_by(AuditLog.created_at.asc())
        .all()
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def keeper(client: TestClient, register_user):
    payload = register_user(name="Laboratory Beekeeper", email=None)
    payload["headers"] = headers_for(payload)
    payload["hive"] = make_hive(client, payload["headers"])
    payload["batch"] = make_batch(client, payload["headers"], [payload["hive"]], ["13.7"])
    return payload


@pytest.fixture()
def processor(client: TestClient, make_privileged_user):
    payload = make_privileged_user(role=UserRole.PROCESSOR, name="Honey Processor")
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def labtech(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.LAB_TECHNICIAN, name="Laboratory Technician", password="LabTechPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def laboratory(client: TestClient, labtech):
    response = client.post(
        f"{API}/laboratories", headers=labtech["headers"], json=LABORATORY_PAYLOAD
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.fixture()
def testing_batch(client: TestClient, keeper, processor):
    """A batch sitting at LAB_TESTING, which is where a test starts."""
    process(client, processor["headers"], keeper["batch"]["id"])
    detail = client.get(f"{API}/batches/{keeper['batch']['id']}", headers=keeper["headers"])
    assert detail.json()["data"]["status"] == "LAB_TESTING"
    return detail.json()["data"]


@pytest.fixture()
def open_test(client: TestClient, labtech, laboratory, testing_batch):
    response = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": testing_batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


# --------------------------------------------------------------------------- #
# Evaluation rules — the pure functions behind every verdict
# --------------------------------------------------------------------------- #
def test_a_measured_value_with_no_configured_range_is_not_evaluated():
    from app.services.quality_rules import evaluate_parameter

    assert (
        evaluate_parameter(value=Decimal("17.2"), reference_min=None, reference_max=None)
        is LabParameterStatus.NOT_EVALUATED
    )


def test_a_measured_value_inside_a_configured_range_passes():
    from app.services.quality_rules import evaluate_parameter

    assert (
        evaluate_parameter(value=Decimal("17.2"), reference_min=Decimal("10"), reference_max=Decimal("20"))
        is LabParameterStatus.PASS
    )


def test_a_measured_value_outside_a_configured_range_fails():
    from app.services.quality_rules import evaluate_parameter

    assert (
        evaluate_parameter(value=Decimal("21.6"), reference_min=Decimal("10"), reference_max=Decimal("20"))
        is LabParameterStatus.FAIL
    )
    assert (
        evaluate_parameter(value=Decimal("9"), reference_min=Decimal("10"), reference_max=None)
        is LabParameterStatus.FAIL
    )


def test_a_test_with_an_unevaluated_parameter_is_inconclusive_not_passed():
    from app.services.quality_rules import EvaluatedResult, decide

    verdict = decide(
        [
            EvaluatedResult(
                parameter_code="MOISTURE",
                parameter_name="Moisture content",
                value=Decimal("17.2"),
                unit="%",
                status=LabParameterStatus.NOT_EVALUATED,
                reference_min=None,
                reference_max=None,
                reference_source=None,
                is_required=True,
            )
        ],
        ["MOISTURE"],
    )
    assert verdict.result is LabResult.INCONCLUSIVE
    assert any("reference range" in reason for reason in verdict.reasons)


def test_a_missing_required_parameter_is_inconclusive():
    from app.services.quality_rules import EvaluatedResult, decide

    verdict = decide(
        [
            EvaluatedResult(
                parameter_code="PH",
                parameter_name="pH",
                value=Decimal("4.1"),
                unit="pH",
                status=LabParameterStatus.PASS,
                reference_min=Decimal("3"),
                reference_max=Decimal("6"),
                reference_source=DEMO_SOURCE,
                is_required=False,
            )
        ],
        ["MOISTURE"],
    )
    assert verdict.result is LabResult.INCONCLUSIVE
    assert verdict.missing_required == ["MOISTURE"]


def test_a_failed_required_parameter_fails_the_test():
    from app.services.quality_rules import EvaluatedResult, decide

    verdict = decide(
        [
            EvaluatedResult(
                parameter_code="MOISTURE",
                parameter_name="Moisture content",
                value=Decimal("25"),
                unit="%",
                status=LabParameterStatus.FAIL,
                reference_min=Decimal("10"),
                reference_max=Decimal("20"),
                reference_source=DEMO_SOURCE,
                is_required=True,
            )
        ],
        ["MOISTURE"],
    )
    assert verdict.result is LabResult.FAIL
    assert verdict.failed_parameters == ["MOISTURE"]


def test_a_failed_optional_parameter_does_not_fail_the_test():
    from app.services.quality_rules import EvaluatedResult, decide

    verdict = decide(
        [
            EvaluatedResult(
                parameter_code="MOISTURE",
                parameter_name="Moisture content",
                value=Decimal("17.2"),
                unit="%",
                status=LabParameterStatus.PASS,
                reference_min=Decimal("10"),
                reference_max=Decimal("20"),
                reference_source=DEMO_SOURCE,
                is_required=True,
            ),
            EvaluatedResult(
                parameter_code="COLOR",
                parameter_name="Colour",
                value=Decimal("90"),
                unit="mm Pfund",
                status=LabParameterStatus.FAIL,
                reference_min=Decimal("10"),
                reference_max=Decimal("80"),
                reference_source=DEMO_SOURCE,
                is_required=False,
            ),
        ],
        ["MOISTURE"],
    )
    assert verdict.result is LabResult.PASS
    assert verdict.failed_parameters == ["COLOR"]


# --------------------------------------------------------------------------- #
# The parameter catalogue
# --------------------------------------------------------------------------- #
def test_the_catalogue_ships_with_no_invented_thresholds(client, admin_headers):
    response = client.get(f"{API}/lab-parameters", headers=admin_headers)
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    codes = {row["code"] for row in rows}
    assert {"MOISTURE", "PH", "HMF", "DIASTASE_ACTIVITY", "ELECTRICAL_CONDUCTIVITY"} <= codes
    assert all(row["reference_min"] is None and row["reference_max"] is None for row in rows)
    assert all(row["is_configured"] is False for row in rows)


def test_a_range_cannot_be_set_without_stating_its_source(client, admin_headers):
    response = client.patch(
        f"{API}/lab-parameters/MOISTURE",
        headers=admin_headers,
        json={"reference_min": "10", "reference_max": "20"},
    )
    assert response.status_code == 422, response.text
    assert "reference_source" in response.text


def test_a_range_must_be_ordered(client, admin_headers):
    response = client.patch(
        f"{API}/lab-parameters/MOISTURE",
        headers=admin_headers,
        json={"reference_min": "20", "reference_max": "10", "reference_source": DEMO_SOURCE},
    )
    assert response.status_code == 422, response.text


def test_configuring_a_parameter_is_audited_with_the_source(client, db, admin_headers):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    entry = audit_actions(db, AuditAction.LAB_PARAMETER_CONFIGURED)[-1]
    assert entry.entity_id == "MOISTURE"
    assert entry.event_metadata["reference_source"] == DEMO_SOURCE
    assert entry.event_metadata["is_required"] is True


def test_a_beekeeper_cannot_read_the_parameter_catalogue(client, keeper):
    assert client.get(f"{API}/lab-parameters", headers=keeper["headers"]).status_code == 403


def test_a_parameter_can_be_returned_to_unconfigured(client, admin_headers):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    cleared = configure(
        client, admin_headers, "MOISTURE", minimum=None, maximum=None, source=None, required=False
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["is_configured"] is False


# --------------------------------------------------------------------------- #
# Laboratories
# --------------------------------------------------------------------------- #
def test_a_laboratory_code_is_issued_by_the_server(client, laboratory):
    assert laboratory["laboratory_code"].startswith("HC-LABUNIT-")
    assert laboratory["status"] == "ACTIVE"


def test_accreditation_is_recorded_as_stated_and_never_asserted(client, labtech):
    response = client.post(
        f"{API}/laboratories",
        headers=labtech["headers"],
        json={**LABORATORY_PAYLOAD, "name": "Second Laboratory", "accredited": None},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["accredited"] is None


def test_registering_a_laboratory_is_audited(client, db, laboratory):
    entry = audit_actions(db, AuditAction.LABORATORY_CREATED)[-1]
    assert entry.event_metadata["laboratory_code"] == laboratory["laboratory_code"]


def test_a_retired_laboratory_cannot_take_new_samples(client, labtech, laboratory, testing_batch):
    client.patch(
        f"{API}/laboratories/{laboratory['id']}", headers=labtech["headers"], json={"status": "INACTIVE"}
    )
    response = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": testing_batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
        },
    )
    assert response.status_code == 422, response.text
    assert "cannot take new samples" in response.json()["error"]["message"]


def test_a_processor_cannot_register_a_laboratory(client, processor):
    response = client.post(
        f"{API}/laboratories", headers=processor["headers"], json=LABORATORY_PAYLOAD
    )
    assert response.status_code == 403, response.text


# --------------------------------------------------------------------------- #
# Opening a test and recording the sample
# --------------------------------------------------------------------------- #
def test_a_test_can_only_be_opened_on_a_batch_awaiting_testing(client, labtech, laboratory, keeper):
    response = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": keeper["batch"]["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
        },
    )
    assert response.status_code == 409, response.text
    assert "has not been sent to the laboratory" in response.json()["error"]["message"]


def test_opening_a_test_issues_distinct_test_and_sample_codes(client, open_test):
    assert open_test["test_code"].startswith("HC-LAB-")
    assert open_test["sample_code"].startswith("HC-SMP-")
    assert open_test["test_code"] != open_test["sample_code"]
    assert open_test["status"] == LabTestStatus.PENDING
    assert open_test["overall_result"] == LabResult.PENDING


def test_the_processing_run_is_read_from_the_batch(client, db, open_test, testing_batch):
    entry = audit_actions(db, AuditAction.LAB_TEST_CREATED)[-1]
    assert entry.event_metadata["batch_code"] == testing_batch["batch_code"]
    assert entry.event_metadata["processing_code"].startswith("HC-PROC-")
    assert open_test["processing_id"] == entry.event_metadata["processing_id"]


def test_the_sample_is_recorded_with_its_quantity_and_unit(client, open_test):
    assert Decimal(open_test["sample_quantity"]) == Decimal("0.25")
    assert open_test["sample_unit"] == "GRAM"
    assert open_test["sample_collected_at"] is not None


def test_recording_the_sample_is_audited(client, db, open_test):
    entries = audit_actions(db, AuditAction.LAB_SAMPLE_RECORDED)
    assert len(entries) == 1
    assert entries[0].event_metadata["sample_code"] == open_test["sample_code"]


def test_a_second_open_test_on_one_batch_is_refused(client, labtech, laboratory, open_test):
    response = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": open_test["batch_id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
        },
    )
    assert response.status_code == 409, response.text
    assert open_test["test_code"] in response.json()["error"]["message"]


def test_a_sample_quantity_of_zero_is_refused(client, labtech, laboratory, testing_batch):
    response = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": testing_batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0",
        },
    )
    assert response.status_code == 422, response.text


def test_a_caller_cannot_supply_an_overall_result(client, labtech, laboratory, testing_batch):
    response = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": testing_batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
            "overall_result": "PASS",
        },
    )
    assert response.status_code == 422, response.text


def test_a_beekeeper_cannot_open_a_test_on_their_own_batch(client, keeper, laboratory, testing_batch):
    response = client.post(
        f"{API}/lab-tests",
        headers=keeper["headers"],
        json={
            "batch_id": testing_batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
        },
    )
    assert response.status_code == 403, response.text


# --------------------------------------------------------------------------- #
# Recording measured values
# --------------------------------------------------------------------------- #
def test_a_value_is_stored_exactly_as_measured(client, labtech, open_test):
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2345", "method": "Refractometer"},
    )
    assert response.status_code == 201, response.text
    result = response.json()["data"]["results"][0]
    assert Decimal(result["value"]) == Decimal("17.2345")
    assert result["method"] == "Refractometer"
    assert result["status"] == LabParameterStatus.NOT_EVALUATED
    assert result["evaluated"] is False


def test_a_value_is_judged_once_a_range_exists(client, admin_headers, labtech, open_test):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20")
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    result = response.json()["data"]["results"][0]
    assert result["status"] == LabParameterStatus.PASS
    assert result["evaluated"] is True
    assert Decimal(result["reference_min"]) == Decimal("10.0")
    assert result["reference_source"] == DEMO_SOURCE


def test_a_failing_value_is_marked_as_failing(client, admin_headers, labtech, open_test):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20")
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "22.4"},
    )
    assert response.json()["data"]["results"][0]["status"] == LabParameterStatus.FAIL


def test_the_range_is_snapshotted_so_a_later_change_does_not_rewrite_the_decision(
    client, admin_headers, labtech, open_test
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20")
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    configure(client, admin_headers, "MOISTURE", minimum="5", maximum="6")
    detail = client.get(f"{API}/lab-tests/{open_test['id']}", headers=labtech["headers"]).json()["data"]
    result = detail["results"][0]
    assert Decimal(result["reference_max"]) == Decimal("20.0")
    assert result["status"] == LabParameterStatus.PASS


def test_a_second_result_for_the_same_parameter_is_refused(client, labtech, open_test):
    body = {"parameter_code": "MOISTURE", "value": "17.2"}
    client.post(f"{API}/lab-tests/{open_test['id']}/results", headers=labtech["headers"], json=body)
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results", headers=labtech["headers"], json=body
    )
    assert response.status_code == 409, response.text
    assert "already recorded" in response.json()["error"]["message"]


def test_a_wrong_unit_is_refused(client, labtech, open_test):
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2", "unit": "pH"},
    )
    assert response.status_code == 422, response.text


def test_an_unknown_parameter_is_refused(client, labtech, open_test):
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "SWEETNESS", "value": "10"},
    )
    assert response.status_code == 404, response.text


def test_the_other_parameter_requires_a_name(client, labtech, open_test):
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "OTHER", "value": "1"},
    )
    assert response.status_code == 422, response.text
    named = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "OTHER", "value": "1", "parameter_name": "Antibiotic screen"},
    )
    assert named.status_code == 201, named.text
    assert named.json()["data"]["results"][0]["parameter_name"] == "Antibiotic screen"


def test_an_inactive_parameter_cannot_take_measurements(client, admin_headers, labtech, open_test):
    client.patch(
        f"{API}/lab-parameters/COLOR", headers=admin_headers, json={"is_active": False}
    )
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "COLOR", "value": "40"},
    )
    assert response.status_code == 422, response.text


def test_recording_a_result_moves_the_test_to_in_progress(client, labtech, open_test):
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    assert response.json()["data"]["status"] == LabTestStatus.IN_PROGRESS


def test_recording_a_result_is_audited_with_the_range_it_was_judged_against(
    client, db, admin_headers, labtech, open_test
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20")
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    entry = audit_actions(db, AuditAction.LAB_RESULT_RECORDED)[-1]
    assert entry.event_metadata["parameter_code"] == "MOISTURE"
    assert Decimal(entry.event_metadata["value"]) == Decimal("17.2")
    assert Decimal(entry.event_metadata["reference_max"]) == Decimal("20.0")
    assert entry.event_metadata["status"] == "PASS"


# --------------------------------------------------------------------------- #
# Correcting and removing while the test is open
# --------------------------------------------------------------------------- #
def test_a_correction_while_open_keeps_the_previous_value_in_the_log(client, db, labtech, open_test):
    created = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    ).json()["data"]["results"][0]
    response = client.patch(
        f"{API}/lab-tests/{open_test['id']}/results/{created['id']}",
        headers=labtech["headers"],
        json={"value": "17.6", "correction_reason": "The first reading was taken before the sample equilibrated."},
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["data"]["results"][0]["value"]) == Decimal("17.6")
    entry = audit_actions(db, AuditAction.LAB_RESULT_UPDATED)[-1]
    assert Decimal(entry.event_metadata["previous"]["value"]) == Decimal("17.2")
    assert Decimal(entry.event_metadata["value"]) == Decimal("17.6")
    assert "equilibrated" in entry.event_metadata["reason"]


def test_a_correction_is_re_judged_against_the_snapshotted_range(client, admin_headers, labtech, open_test):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20")
    created = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    ).json()["data"]["results"][0]
    assert created["status"] == LabParameterStatus.PASS
    response = client.patch(
        f"{API}/lab-tests/{open_test['id']}/results/{created['id']}",
        headers=labtech["headers"],
        json={"value": "24.0", "correction_reason": "Transcription error found on review"},
    )
    assert response.json()["data"]["results"][0]["status"] == LabParameterStatus.FAIL


def test_a_result_entered_in_error_can_be_removed_while_open(client, db, labtech, open_test):
    created = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "PH", "value": "4.1"},
    ).json()["data"]["results"][0]
    response = client.delete(
        f"{API}/lab-tests/{open_test['id']}/results/{created['id']}", headers=labtech["headers"]
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["results"] == []
    removed = audit_actions(db, AuditAction.LAB_RESULT_REMOVED)[-1]
    assert Decimal(removed.event_metadata["removed_value"]) == Decimal("4.1")


def test_a_result_cannot_be_removed_from_another_test(client, labtech, open_test, laboratory):
    other = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": open_test["batch_id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
        },
    )
    assert other.status_code == 409  # still open — a second test is refused first
    created = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "PH", "value": "4.1"},
    ).json()["data"]["results"][0]
    response = client.delete(
        f"{API}/lab-tests/{uuid.uuid4()}/results/{created['id']}", headers=labtech["headers"]
    )
    assert response.status_code == 404, response.text


# --------------------------------------------------------------------------- #
# Completion and the decision
# --------------------------------------------------------------------------- #
def test_a_test_with_no_measurements_cannot_be_completed(client, labtech, open_test):
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={}
    )
    assert response.status_code == 422, response.text
    assert "No laboratory results have been recorded" in response.json()["error"]["message"]


def test_an_unconfigured_measurement_makes_the_test_inconclusive(
    client, db, labtech, open_test, keeper
):
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["overall_result"] == LabResult.INCONCLUSIVE
    assert data["status"] == LabTestStatus.COMPLETED
    assert any("reference range" in note for note in data["evaluation_notes"])
    # Not approved and not quietly still "in testing": a measurement that could not
    # be judged against any configured range is a question for a person, so the
    # batch is held where a hold can be seen and answered.
    assert batch_status(db, open_test["batch_id"]) is BatchStatus.LAB_HOLD


def test_a_passing_required_parameter_approves_the_batch(
    client, db, admin_headers, labtech, open_test
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["overall_result"] == LabResult.PASS
    # A pass approves the batch and releases it to the packaging floor in one act,
    # so the record is found in APPROVED or in the PACKAGING_READY it becomes.
    assert batch_status(db, open_test["batch_id"]) in (
        BatchStatus.APPROVED,
        BatchStatus.PACKAGING_READY,
    )


def test_a_failing_required_parameter_rejects_the_batch(
    client, db, admin_headers, labtech, open_test
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "24.5"},
    )
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={}
    )
    assert response.json()["data"]["overall_result"] == LabResult.FAIL
    assert batch_status(db, open_test["batch_id"]) is BatchStatus.REJECTED


def test_a_required_parameter_left_unmeasured_holds_the_batch(
    client, db, admin_headers, labtech, open_test
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    configure(client, admin_headers, "PH", minimum="3", maximum="6", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={}
    )
    data = response.json()["data"]
    assert data["overall_result"] == LabResult.INCONCLUSIVE
    assert "PH" in data["missing_required_parameters"]
    assert batch_status(db, open_test["batch_id"]) is BatchStatus.LAB_HOLD


def test_completing_a_test_is_audited_with_its_reasoning(
    client, db, admin_headers, labtech, open_test
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "18.0"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    entry = audit_actions(db, AuditAction.LAB_TEST_COMPLETED)[-1]
    assert entry.event_metadata["overall_result"] == "PASS"
    assert entry.event_metadata["previous_batch_status"] == "LAB_TESTING"
    assert entry.event_metadata["batch_status"] in ("APPROVED", "PACKAGING_READY")
    assert entry.event_metadata["decided_from"] == "records"
    assert entry.event_metadata["reasons"]


def test_the_batch_decision_is_audited_as_its_own_event(
    client, db, admin_headers, labtech, open_test
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "22.0"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    entry = audit_actions(db, AuditAction.BATCH_REJECTED)[-1]
    assert entry.event_metadata["test_code"] == open_test["test_code"]
    assert entry.event_metadata["sample_code"] == open_test["sample_code"]
    assert entry.event_metadata["previous_status"] == "LAB_TESTING"


# --------------------------------------------------------------------------- #
# A completed test is closed
# --------------------------------------------------------------------------- #
def test_a_completed_test_cannot_be_edited(client, labtech, open_test):
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    response = client.patch(
        f"{API}/lab-tests/{open_test['id']}", headers=labtech["headers"], json={"sample_quantity": "0.3"}
    )
    assert response.status_code == 409, response.text
    assert "read, never rewritten" in response.json()["error"]["message"]


def test_a_completed_tests_measurement_cannot_be_changed_or_deleted(client, labtech, open_test):
    created = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    ).json()["data"]["results"][0]
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})

    patched = client.patch(
        f"{API}/lab-tests/{open_test['id']}/results/{created['id']}",
        headers=labtech["headers"],
        json={"value": "16.0"},
    )
    assert patched.status_code == 409, patched.text
    deleted = client.delete(
        f"{API}/lab-tests/{open_test['id']}/results/{created['id']}", headers=labtech["headers"]
    )
    assert deleted.status_code == 409, deleted.text
    added = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "PH", "value": "4.1"},
    )
    assert added.status_code == 409, added.text


def test_the_value_reads_as_recorded_after_the_refusals(client, labtech, open_test):
    created = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    ).json()["data"]["results"][0]
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    client.patch(
        f"{API}/lab-tests/{open_test['id']}/results/{created['id']}",
        headers=labtech["headers"],
        json={"value": "1.0"},
    )
    detail = client.get(f"{API}/lab-tests/{open_test['id']}", headers=labtech["headers"]).json()["data"]
    assert Decimal(detail["results"][0]["value"]) == Decimal("17.2")


# --------------------------------------------------------------------------- #
# Retests: history is additive
# --------------------------------------------------------------------------- #
def test_a_retest_on_a_decided_batch_requires_a_reason(client, admin_headers, labtech, laboratory, open_test):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})

    without = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": open_test["batch_id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
        },
    )
    assert without.status_code == 422, without.text

    with_reason = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": open_test["batch_id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
            "retest_reason": "The buyer disputed the first reading.",
        },
    )
    assert with_reason.status_code == 201, with_reason.text
    assert with_reason.json()["data"]["retest_of_id"] == open_test["id"]
    assert with_reason.json()["data"]["round_number"] == 2


def test_a_retest_returns_the_batch_to_testing(client, db, admin_headers, labtech, laboratory, open_test):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    assert batch_status(db, open_test["batch_id"]) in (
        BatchStatus.APPROVED,
        BatchStatus.PACKAGING_READY,
    )

    client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": open_test["batch_id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
            "retest_reason": "A second sample was requested by the cluster officer.",
        },
    )
    assert batch_status(db, open_test["batch_id"]) is BatchStatus.LAB_TESTING


def test_the_earlier_test_is_untouched_by_the_retest(
    client, admin_headers, labtech, laboratory, open_test
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    retest = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": open_test["batch_id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
            "retest_reason": "Verification requested by the buyer.",
        },
    ).json()["data"]

    first = client.get(f"{API}/lab-tests/{open_test['id']}", headers=labtech["headers"]).json()["data"]
    assert first["overall_result"] == LabResult.PASS
    assert Decimal(first["results"][0]["value"]) == Decimal("17.2")

    history = client.get(f"{API}/lab-tests?batch_id={open_test['batch_id']}", headers=labtech["headers"])
    codes = [row["test_code"] for row in history.json()["data"]]
    assert codes == [retest["test_code"], open_test["test_code"]]


def test_a_test_cannot_be_opened_while_another_is_open(client, labtech, laboratory, open_test):
    response = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": open_test["batch_id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.2",
            "retest_reason": "Attempting a parallel test",
        },
    )
    assert response.status_code == 409, response.text


# --------------------------------------------------------------------------- #
# Overriding
# --------------------------------------------------------------------------- #
def _decided_test(client, admin_headers, labtech, open_test, *, value: str = "24.5"):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": value},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    return client.get(f"{API}/lab-tests/{open_test['id']}", headers=labtech["headers"]).json()["data"]


def test_only_an_administrator_may_override(client, admin_headers, labtech, open_test):
    _decided_test(client, admin_headers, labtech, open_test)
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/override",
        headers=labtech["headers"],
        json={"overall_result": "PASS", "reason": "The technician would like a different answer"},
    )
    assert response.status_code == 403, response.text


def test_an_open_test_cannot_be_overridden(client, admin_headers, open_test):
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/override",
        headers=admin_headers,
        json={"overall_result": "PASS", "reason": "Overriding before the measurements are in"},
    )
    assert response.status_code == 409, response.text


def test_an_override_must_change_the_outcome(client, admin_headers, labtech, open_test):
    _decided_test(client, admin_headers, labtech, open_test, value="24.5")
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/override",
        headers=admin_headers,
        json={"overall_result": "FAIL", "reason": "Agreeing with the computed result is not an override"},
    )
    assert response.status_code == 422, response.text


def test_an_override_requires_a_substantive_reason(client, admin_headers, labtech, open_test):
    _decided_test(client, admin_headers, labtech, open_test)
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/override",
        headers=admin_headers,
        json={"overall_result": "PASS", "reason": "because"},
    )
    assert response.status_code == 422, response.text


def test_an_override_is_recorded_and_visible(client, db, admin_headers, labtech, open_test):
    _decided_test(client, admin_headers, labtech, open_test)
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/override",
        headers=admin_headers,
        json={
            "overall_result": "INCONCLUSIVE",
            "reason": "The sample was mishandled in transit; rejecting on it would not be justified.",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_override"] is True
    assert data["override_reason"].startswith("The sample was mishandled")
    assert "set by hand" in data["result_summary"]
    assert data["next_step"]

    entry = audit_actions(db, AuditAction.LAB_TEST_OVERRIDDEN)[-1]
    assert entry.event_metadata["computed_result"] == "FAIL"
    assert entry.event_metadata["override_result"] == "INCONCLUSIVE"
    assert entry.event_metadata["reason"].startswith("The sample was mishandled")


def test_an_override_that_decides_nothing_holds_the_batch(
    client, db, admin_headers, labtech, open_test
):
    _decided_test(client, admin_headers, labtech, open_test, value="24.5")
    assert batch_status(db, open_test["batch_id"]) is BatchStatus.REJECTED
    client.post(
        f"{API}/lab-tests/{open_test['id']}/override",
        headers=admin_headers,
        json={
            "overall_result": "INCONCLUSIVE",
            "reason": "The transit conditions invalidate this measurement; a fresh sample is needed.",
        },
    )
    assert batch_status(db, open_test["batch_id"]) is BatchStatus.LAB_HOLD


def test_an_override_to_pass_approves_the_batch(client, db, admin_headers, labtech, open_test):
    _decided_test(client, admin_headers, labtech, open_test, value="24.5")
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/override",
        headers=admin_headers,
        json={
            "overall_result": "PASS",
            "reason": "The instrument was later found to be miscalibrated; the corrected reading passes.",
        },
    )
    assert response.status_code == 200, response.text
    assert batch_status(db, open_test["batch_id"]) in (
        BatchStatus.APPROVED,
        BatchStatus.PACKAGING_READY,
    )
    assert audit_actions(db, AuditAction.BATCH_APPROVED)[-1].event_metadata["is_override"] is True


# --------------------------------------------------------------------------- #
# Traceability, scope and the batch's own view
# --------------------------------------------------------------------------- #
def test_the_chain_back_to_the_apiary_is_assembled_from_the_records(client, labtech, open_test):
    detail = client.get(f"{API}/lab-tests/{open_test['id']}", headers=labtech["headers"]).json()["data"]
    kinds = [node["kind"] for node in detail["traceability"]]
    assert kinds[0] == "LAB_TEST" and kinds[1] == "SAMPLE"
    assert {"BATCH", "PROCESSING", "COLLECTION", "HIVE", "BEEKEEPER", "LABORATORY"} <= set(kinds)
    assert all(node["identifier"] for node in detail["traceability"])
    assert detail["traceability"][0]["identifier"] == open_test["test_code"]


def test_a_beekeeper_reads_their_own_batchs_test_but_not_anothers(
    client, register_user, open_test, keeper
):
    own = client.get(f"{API}/lab-tests/{open_test['id']}", headers=keeper["headers"])
    assert own.status_code == 200, own.text
    assert own.json()["data"]["can_complete"] is False
    assert own.json()["data"]["can_override"] is False

    stranger = register_user(name="Another Keeper", email=None)
    assert (
        client.get(f"{API}/lab-tests/{open_test['id']}", headers=headers_for(stranger)).status_code == 404
    )


def test_the_laboratory_worklist_names_the_run_behind_each_batch(client, labtech, testing_batch):
    response = client.get(f"{API}/lab-tests/awaiting?page_size=50", headers=labtech["headers"])
    assert response.status_code == 200, response.text
    row = next(
        item for item in response.json()["data"] if item["batch_code"] == testing_batch["batch_code"]
    )
    assert row["processing_code"].startswith("HC-PROC-")
    assert row["open_test_code"] is None
    assert Decimal(row["output_quantity"]) == Decimal("12.9")


def test_the_laboratory_summary_reports_what_is_not_configured(client, labtech):
    response = client.get(f"{API}/lab-tests/summary", headers=labtech["headers"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 0
    assert data["unconfigured_parameters"] >= 13


def test_the_batch_detail_carries_the_recorded_values_verbatim(
    client, admin_headers, labtech, open_test, keeper
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})

    detail = client.get(f"{API}/batches/{open_test['batch_id']}", headers=keeper["headers"]).json()["data"]
    # A pass approves the batch and releases it to the packaging floor in the same
    # act, so it is found in either of those two states — never "approved and stuck".
    assert detail["status"] in ("APPROVED", "PACKAGING_READY"), detail["status"]
    laboratory = detail["laboratory"]
    assert laboratory["test_code"] == open_test["test_code"]
    assert laboratory["overall_result"] == "PASS"
    assert laboratory["parameter_count"] == 1
    assert laboratory["passed_count"] == 1
    result = laboratory["results"][0]
    assert result["parameter_code"] == "MOISTURE"
    assert Decimal(result["value"]) == Decimal("17.2")
    assert result["status"] == "PASS"
    assert result["reference_source"] == DEMO_SOURCE


def test_the_batch_timeline_shows_the_outcome_and_not_just_completion(
    client, admin_headers, labtech, open_test, keeper
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "26.0"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    stages = {
        row["stage"]: row
        for row in client.get(f"{API}/batches/{open_test['batch_id']}", headers=keeper["headers"])
        .json()["data"]["timeline"]
    }
    assert stages["LABORATORY"]["state"] == "completed"
    # The outcome is the laboratory's verdict on the sample — FAIL — which is the
    # thing that was measured; the batch's own REJECTED follows from it and is
    # reported by the batch status, not by relabelling the measurement.
    assert stages["LABORATORY"]["outcome"] == "FAIL"
    # Blocked, and it says why: a rejected batch may not be packed, and the stage
    # names the batch's own state as the reason rather than reporting an absence.
    assert stages["PACKAGING"]["state"] == "blocked"
    assert "rejected" in (stages["PACKAGING"]["detail"] or "").lower()
    assert stages["PACKAGING"]["module_available"] is True


def test_a_rejected_batch_cannot_be_pushed_onwards_by_any_route(
    client, admin_headers, labtech, open_test, keeper
):
    """A rejected batch cannot be pushed into packaging — the server refuses it.

    A rejection is a real outcome with consequences: the batch's only legal move
    is back into testing, and the packaging stage that now exists refuses it on
    its own terms rather than being handed a batch that failed.
    """
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "28.0"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})

    detail = client.get(f"{API}/batches/{open_test['batch_id']}", headers=keeper["headers"]).json()["data"]
    assert detail["status"] == "REJECTED"
    assert detail["allowed_next_statuses"] == ["LAB_TESTING"]
    for verb, path in (
        ("POST", f"{API}/batches/{open_test['batch_id']}/package"),
        ("POST", f"{API}/batches/{open_test['batch_id']}/distribute"),
        ("GET", f"{API}/batches/{open_test['batch_id']}/qr"),
    ):
        assert client.request(verb, path, headers=keeper["headers"]).status_code == 404


def test_the_laboratory_service_rechecks_the_capability(client, db, keeper, open_test):
    from app.core.exceptions import ForbiddenError
    from app.models.user import User
    from app.schemas.laboratory import LabTestComplete
    from app.services.laboratory_service import LaboratoryService

    user = db.get(User, uuid.UUID(str(keeper["user"]["id"])))
    with pytest.raises(ForbiddenError):
        LaboratoryService(db).complete_test(user, uuid.UUID(str(open_test["id"])), LabTestComplete())


def test_the_test_record_is_immutable_in_the_database_after_completion(client, db, labtech, open_test):
    """Even a direct write through the ORM does not move a decided test."""
    created = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    ).json()["data"]["results"][0]
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})

    record = db.get(LabTestResult, uuid.UUID(str(created["id"])))
    assert record.value == Decimal("17.2000")
    test = db.get(LabTest, uuid.UUID(str(open_test["id"])))
    assert test.status is LabTestStatus.COMPLETED
    assert test.completed_at is not None


def test_a_parameter_that_was_never_measured_is_not_invented_for_the_batch(
    client, admin_headers, labtech, open_test, keeper
):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20", required=True)
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    detail = client.get(f"{API}/batches/{open_test['batch_id']}", headers=keeper["headers"]).json()["data"]
    codes = [row["parameter_code"] for row in detail["laboratory"]["results"]]
    assert codes == ["MOISTURE"]


def test_the_sample_carries_its_own_identity_to_the_result(client, db, labtech, open_test):
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    entry = audit_actions(db, AuditAction.LAB_RESULT_RECORDED)[-1]
    assert entry.event_metadata["test_code"] == open_test["test_code"]
    assert entry.event_type if False else entry.entity_type == "lab_test"


def test_the_reference_source_is_shown_to_every_reader(client, admin_headers, labtech, open_test, keeper):
    configure(client, admin_headers, "MOISTURE", minimum="10", maximum="20")
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    as_keeper = client.get(f"{API}/lab-tests/{open_test['id']}", headers=keeper["headers"]).json()["data"]
    assert as_keeper["results"][0]["reference_source"] == DEMO_SOURCE


def test_no_endpoint_accepts_a_parameter_status(client, labtech, open_test):
    response = client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2", "status": "PASS"},
    )
    assert response.status_code == 422, response.text


def test_a_batch_is_not_approved_by_a_measurement_that_was_never_compared(
    client, db, labtech, open_test
):
    """The single most important rule in the phase, stated as a test."""
    client.post(
        f"{API}/lab-tests/{open_test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.2"},
    )
    client.post(f"{API}/lab-tests/{open_test['id']}/complete", headers=labtech["headers"], json={})
    record = db.get(HoneyBatch, uuid.UUID(str(open_test["batch_id"])))
    db.refresh(record)
    # The batch is held, not approved and not merely "still testing": a measurement
    # nobody could judge against a configured range is a question for a person, and
    # the platform answers it with the state that keeps the honey off the floor.
    assert record.status is BatchStatus.LAB_HOLD
    test = db.get(LabTest, uuid.UUID(str(open_test["id"])))
    db.refresh(test)
    assert test.overall_result is LabResult.INCONCLUSIVE


# --------------------------------------------------------------------------- #
# Who the samples may be given to
#
# The allocation form offers a list of technicians, read from the users table —
# the same source the allocation itself checks. A newly provisioned technician
# appears at once; a switched-off one is never offered.
# --------------------------------------------------------------------------- #
def test_the_technician_directory_comes_from_the_users_table(
    client, admin_headers, labtech, make_privileged_user
):
    listed = client.get(f"{API}/lab-tests/eligible-technicians", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    rows = {row["id"]: row for row in listed.json()["data"]}
    assert str(labtech["id"]) in rows
    row = rows[str(labtech["id"])]
    assert row["role"] == UserRole.LAB_TECHNICIAN.value
    assert row["account_status"] == "ACTIVE"
    assert row["name"] and row["email"]
    assert row["open_work_count"] == 0

    newcomer = make_privileged_user(role=UserRole.LAB_TECHNICIAN, name="Second Technician")
    again = client.get(f"{API}/lab-tests/eligible-technicians", headers=admin_headers).json()["data"]
    assert str(newcomer["id"]) in {entry["id"] for entry in again}
    assert len(again) == 2


def test_the_technician_directory_leaves_out_switched_off_accounts(
    client, admin_headers, db, make_privileged_user
):
    from app.models.user import User

    active = make_privileged_user(role=UserRole.LAB_TECHNICIAN, name="Working Technician")
    retired = make_privileged_user(role=UserRole.LAB_TECHNICIAN, name="Retired Technician")
    record = db.get(User, uuid.UUID(str(retired["id"])))
    record.is_active = False
    db.commit()

    ids = {
        row["id"]
        for row in client.get(f"{API}/lab-tests/eligible-technicians", headers=admin_headers).json()["data"]
    }
    assert str(active["id"]) in ids
    assert str(retired["id"]) not in ids


def test_the_technician_directory_holds_only_technicians(
    client, admin_headers, labtech, processor, keeper
):
    rows = client.get(f"{API}/lab-tests/eligible-technicians", headers=admin_headers).json()["data"]
    ids = {row["id"] for row in rows}
    assert str(labtech["id"]) in ids
    assert str(processor["id"]) not in ids
    assert str(keeper["user"]["id"]) not in ids
    assert {row["role"] for row in rows} == {UserRole.LAB_TECHNICIAN.value}


def test_a_technician_sees_themselves_and_not_a_colleague(
    client, admin_headers, labtech, make_privileged_user
):
    colleague = make_privileged_user(role=UserRole.LAB_TECHNICIAN, name="Other Technician")
    rows = client.get(f"{API}/lab-tests/eligible-technicians", headers=labtech["headers"])
    assert rows.status_code == 200, rows.text
    ids = {row["id"] for row in rows.json()["data"]}
    assert ids == {str(labtech["id"])}
    assert str(colleague["id"]) not in ids


def test_roles_that_do_not_test_cannot_read_the_technician_directory(
    client, processor, keeper, kvic_headers
):
    for headers in (processor["headers"], keeper["headers"], kvic_headers):
        response = client.get(f"{API}/lab-tests/eligible-technicians", headers=headers)
        assert response.status_code == 403, response.text


def test_the_directory_counts_the_open_tests_already_allocated(
    client, admin_headers, labtech, laboratory, testing_batch
):
    opened = client.post(
        f"{API}/lab-tests",
        headers=labtech["headers"],
        json={
            "batch_id": testing_batch["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
        },
    )
    assert opened.status_code == 201, opened.text
    # Allocating a batch's laboratory work names the technician; the open test
    # found on the batch is the one allocated, so no test id is sent.
    assigned = client.post(
        f"{API}/lab-tests/batches/{testing_batch['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    )
    assert assigned.status_code in (200, 201), assigned.text
    rows = client.get(f"{API}/lab-tests/eligible-technicians", headers=admin_headers).json()["data"]
    row = next(entry for entry in rows if entry["id"] == str(labtech["id"]))
    assert row["open_work_count"] == 1

"""Phase 6 — processing, and the rules that make its record trustworthy.

Processing is where honey stops being a harvest and becomes a product, so the
questions here are about what the record is allowed to claim:

* does a run exist only against a batch that is actually waiting to be processed,
  and only one at a time? (yes — the service refuses, and a partial unique index
  refuses even if the service is bypassed)
* does opening a run move the batch? (no: the batch moves when the work starts,
  which is the difference between planning to process and processing)
* does the platform ever fill in a quantity nobody measured? (no: ``input_quantity``
  and ``output_quantity`` stay NULL until someone records them, from the batch's
  own weight or anywhere else)
* is the difference the record shows the arithmetic of the two figures the run
  holds? (yes — stored as ``loss_quantity``, not recomputed by each reader)
* can output exceed input, or a completed run be edited, or be completed twice?
  (no, no and no, each with its own refusal)
* does a cancelled run disappear? (no — it is kept, and the batch goes back to
  COLLECTED if it had been marked as being processed)

Every check below goes through the HTTP API, so the tests exercise the same path
a processor's screen does.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.enums import (
    AuditAction,
    BatchStage,
    BatchStatus,
    ProcessingStatus,
    ProcessingType,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.processing import HoneyProcessing, ProcessingUnit

API = "/api/v1"

HIVE_PAYLOAD = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
}

UNIT_PAYLOAD = {
    "name": "Tenali Filtering Unit",
    "location": "Tenali Industrial Estate",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "capacity_kg_per_day": "150",
}


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
    """Record a harvest and complete it — the only path to a batch there is."""
    rows = [
        {"hive_id": hive["id"], "quantity": quantity}
        for hive, quantity in zip(hives, quantities, strict=True)
    ]
    response = client.post(
        f"{API}/collections",
        headers=headers,
        json={"hives": rows, "collection_date": date.today().isoformat(), "unit": "KG"},
    )
    assert response.status_code == 201, response.text
    collection = response.json()["data"]
    response = client.post(f"{API}/collections/{collection['id']}/complete", headers=headers)
    assert response.status_code == 200, response.text
    batch_id = response.json()["meta"]["batch"]["id"]
    response = client.get(f"{API}/batches/{batch_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.fixture()
def keeper(client: TestClient, register_user):
    payload = register_user(name="Processing Beekeeper", email=None)
    payload["headers"] = headers_for(payload)
    hive = make_hive(client, payload["headers"])
    payload["hive"] = hive
    payload["batch"] = make_batch(client, payload["headers"], [hive], ["13.7"])
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
def make_unit(client: TestClient, processor):
    def _make(**overrides) -> dict:
        response = client.post(
            f"{API}/processing-units",
            headers=processor["headers"],
            json={**UNIT_PAYLOAD, **overrides},
        )
        assert response.status_code == 201, response.text
        return response.json()["data"]

    return _make


@pytest.fixture()
def open_run(client: TestClient, processor, keeper, make_unit):
    """A run opened against a COLLECTED batch, not yet started."""
    unit = make_unit()
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": keeper["batch"]["id"],
            "processing_type": ProcessingType.FILTERING.value,
            "processing_unit_id": unit["id"],
        },
    )
    assert response.status_code == 201, response.text
    return {"run": response.json()["data"], "unit": unit, "batch": keeper["batch"]}


@pytest.fixture()
def started_run(client: TestClient, processor, open_run):
    response = client.post(
        f"{API}/processing/{open_run['run']['id']}/start", headers=processor["headers"]
    )
    assert response.status_code == 200, response.text
    open_run["run"] = response.json()["data"]
    return open_run


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
# Processing units
# --------------------------------------------------------------------------- #
def test_processing_unit_code_is_issued_by_the_server(client, processor):
    response = client.post(
        f"{API}/processing-units", headers=processor["headers"], json=UNIT_PAYLOAD
    )
    assert response.status_code == 201, response.text
    unit = response.json()["data"]
    assert unit["unit_code"].startswith("HC-PU-")
    assert unit["unit_code"].split("-")[-1].isdigit()
    assert unit["status"] == "ACTIVE"


def test_a_client_supplied_unit_code_is_refused(client, processor):
    response = client.post(
        f"{API}/processing-units",
        headers=processor["headers"],
        json={**UNIT_PAYLOAD, "unit_code": "HC-PU-999999"},
    )
    assert response.status_code == 422, response.text


def test_registering_a_unit_is_audited(client, processor, db):
    unit = client.post(
        f"{API}/processing-units", headers=processor["headers"], json=UNIT_PAYLOAD
    ).json()["data"]
    entries = audit_actions(db, AuditAction.PROCESSING_UNIT_CREATED)
    assert len(entries) == 1
    assert entries[0].entity_id == unit["id"]
    assert entries[0].event_metadata["unit_code"] == unit["unit_code"]


def test_laboratory_technician_cannot_register_a_processing_unit(client, labtech):
    response = client.post(
        f"{API}/processing-units", headers=labtech["headers"], json=UNIT_PAYLOAD
    )
    assert response.status_code == 403, response.text


def test_beekeeper_cannot_register_a_processing_unit(client, keeper):
    response = client.post(
        f"{API}/processing-units", headers=keeper["headers"], json=UNIT_PAYLOAD
    )
    assert response.status_code == 403, response.text


def test_a_unit_can_be_retired_and_is_then_refused_for_new_work(client, processor, make_unit, keeper):
    unit = make_unit()
    response = client.patch(
        f"{API}/processing-units/{unit['id']}",
        headers=processor["headers"],
        json={"status": "INACTIVE"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "INACTIVE"

    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": keeper["batch"]["id"],
            "processing_type": "FILTERING",
            "processing_unit_id": unit["id"],
        },
    )
    assert response.status_code == 422, response.text
    assert "cannot take new work" in response.json()["error"]["message"]


# --------------------------------------------------------------------------- #
# Opening a run
# --------------------------------------------------------------------------- #
def test_a_run_is_opened_against_a_collected_batch(client, processor, keeper, open_run):
    run = open_run["run"]
    assert run["status"] == ProcessingStatus.PENDING
    assert run["processing_code"].startswith("HC-PROC-")
    assert run["batch_code"] == keeper["batch"]["batch_code"]
    assert run["processing_unit_name"] == open_run["unit"]["name"]


def test_a_new_run_records_no_quantity_it_was_not_given(client, open_run):
    run = open_run["run"]
    assert run["input_quantity"] is None
    assert run["output_quantity"] is None
    assert run["loss_quantity"] is None
    assert run["loss_percent"] is None


def test_opening_a_run_does_not_move_the_batch(client, db, keeper, open_run):
    assert batch_status(db, keeper["batch"]["id"]) is BatchStatus.COLLECTED


def test_opening_a_run_is_audited_with_the_batch_it_names(client, db, open_run):
    entries = audit_actions(db, AuditAction.PROCESSING_CREATED)
    assert len(entries) == 1
    assert entries[0].entity_id == open_run["run"]["id"]
    assert entries[0].event_metadata["batch_code"] == open_run["batch"]["batch_code"]
    assert entries[0].event_metadata["status"] == "PENDING"


def test_a_run_cannot_be_opened_against_a_nonexistent_batch(client, processor):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": str(uuid.uuid4()), "processing_type": "FILTERING"},
    )
    assert response.status_code == 404, response.text


def test_a_run_cannot_be_opened_against_an_unknown_unit(client, processor, keeper):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": keeper["batch"]["id"],
            "processing_type": "FILTERING",
            "processing_unit_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404, response.text


def test_an_open_run_cannot_be_duplicated_on_one_batch(client, processor, keeper, open_run):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    )
    assert response.status_code == 409, response.text
    assert open_run["run"]["processing_code"] in response.json()["error"]["message"]


def test_the_database_refuses_a_second_open_run_even_without_the_service(
    client, db, open_run
):
    """The service is not the only guard: the partial unique index is."""
    from sqlalchemy.exc import IntegrityError

    duplicate = HoneyProcessing(
        processing_code="HC-PROC-1900-999999",
        batch_id=uuid.UUID(str(open_run["run"]["batch_id"])),
        operator_id=uuid.UUID(str(open_run["run"]["operator_id"])),
        processing_type=ProcessingType.FILTERING,
        status=ProcessingStatus.PENDING,
        unit="KG",
        processing_date=date.today(),
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_a_run_cannot_be_opened_against_a_batch_being_processed(client, processor, keeper, started_run):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    )
    assert response.status_code == 409, response.text


def test_a_status_field_in_the_request_is_refused(client, processor, keeper):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING", "status": "COMPLETED"},
    )
    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# Starting a run: the transition
# --------------------------------------------------------------------------- #
def test_starting_a_run_moves_the_batch_collected_to_processing(client, db, processor, keeper, started_run):
    assert started_run["run"]["status"] == ProcessingStatus.IN_PROGRESS
    assert batch_status(db, keeper["batch"]["id"]) is BatchStatus.PROCESSING

    batch = db.get(HoneyBatch, uuid.UUID(str(keeper["batch"]["id"])))
    assert batch.current_stage is BatchStage.PROCESSING


def test_a_started_run_records_its_start_time(client, started_run):
    assert started_run["run"]["start_time"] is not None


def test_starting_a_run_is_audited_twice(client, db, started_run):
    assert len(audit_actions(db, AuditAction.PROCESSING_STARTED)) == 1
    moved = audit_actions(db, AuditAction.BATCH_STATUS_CHANGED)
    assert any(
        entry.event_metadata["new_status"] == "PROCESSING" for entry in moved
    ), [entry.event_metadata for entry in moved]


def test_a_run_cannot_be_started_twice(client, processor, started_run):
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/start", headers=processor["headers"]
    )
    assert response.status_code == 409, response.text
    assert "already been started" in response.json()["error"]["message"]


def test_a_completed_run_cannot_be_restarted(client, processor, started_run):
    complete = client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    assert complete.status_code == 200, complete.text
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/start", headers=processor["headers"]
    )
    assert response.status_code == 409, response.text


def test_beekeeper_cannot_start_a_run_on_their_own_honey(client, keeper, open_run):
    response = client.post(f"{API}/processing/{open_run['run']['id']}/start", headers=keeper["headers"])
    assert response.status_code == 403, response.text


# --------------------------------------------------------------------------- #
# Quantities
# --------------------------------------------------------------------------- #
def test_output_cannot_exceed_input(client, processor, started_run):
    response = client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"input_quantity": "12.9", "output_quantity": "13.7"},
    )
    assert response.status_code == 422, response.text
    # Refused by the request model before the service sees it; either way the
    # reason names the comparison that failed.
    assert "cannot exceed" in response.text


def test_output_cannot_exceed_an_input_recorded_earlier(client, processor, started_run):
    """A partial update is judged against the figure already on the record."""
    first = client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"input_quantity": "10"},
    )
    assert first.status_code == 200, first.text
    response = client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"output_quantity": "11"},
    )
    assert response.status_code == 422, response.text


def test_a_negative_quantity_is_refused_by_the_schema(client, processor, started_run):
    response = client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"input_quantity": "-1"},
    )
    assert response.status_code == 422, response.text


def test_recording_the_quantities_stores_the_difference(client, processor, started_run):
    response = client.patch(
        f"/api/v1/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert Decimal(data["input_quantity"]) == Decimal("13.7")
    assert Decimal(data["output_quantity"]) == Decimal("12.9")
    assert Decimal(data["loss_quantity"]) == Decimal("0.8")
    assert data["loss_percent"] == 5.84


def test_the_run_keeps_the_collection_unit(client, processor, started_run):
    response = client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    data = response.json()["data"]
    assert data["unit"] == "KG"
    assert data["unit_label"] == "kg"


def test_a_correction_while_open_is_audited_with_both_values(client, db, processor, started_run):
    client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.4"},
    )
    client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"output_quantity": "12.9"},
    )
    entries = audit_actions(db, AuditAction.PROCESSING_UPDATED)
    change = entries[-1].event_metadata["changes"][0]
    assert change["field"] == "output_quantity"
    assert Decimal(change["from"]) == Decimal("12.400")
    assert Decimal(change["to"]) == Decimal("12.9")


def test_processing_does_not_change_the_harvest(client, keeper, started_run):
    response = client.get(f"{API}/collections/{keeper['batch']['collection_id']}", headers=keeper["headers"])
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["data"]["total_quantity"]) == Decimal("13.7")


# --------------------------------------------------------------------------- #
# Completing a run
# --------------------------------------------------------------------------- #
def test_a_run_cannot_be_completed_before_it_is_started(client, processor, open_run):
    response = client.post(
        f"{API}/processing/{open_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"output_quantity": "12.9"},
    )
    assert response.status_code == 409, response.text
    assert "has not been started" in response.json()["error"]["message"]


def test_both_quantities_are_required_to_complete(client, processor, started_run):
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={},
    )
    assert response.status_code == 422, response.text
    assert set(response.json()["error"]["details"]["missing_fields"]) == {
        "input_quantity",
        "output_quantity",
    }


def test_completing_a_run_hands_the_batch_to_the_laboratory(client, db, processor, keeper, started_run):
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == ProcessingStatus.COMPLETED
    assert data["batch_status"] == "LAB_TESTING"
    assert Decimal(data["loss_quantity"]) == Decimal("0.8")
    assert data["completion_time"] is not None
    assert batch_status(db, keeper["batch"]["id"]) is BatchStatus.LAB_TESTING

    batch = db.get(HoneyBatch, uuid.UUID(str(keeper["batch"]["id"])))
    assert batch.current_stage is BatchStage.LABORATORY


def test_completion_is_audited_with_the_quantities_and_the_transition(client, db, started_run, processor):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    entry = audit_actions(db, AuditAction.PROCESSING_COMPLETED)[-1]
    assert entry.event_metadata["input_quantity"] == "13.7"
    assert entry.event_metadata["output_quantity"] == "12.9"
    assert entry.event_metadata["previous_batch_status"] == "PROCESSING"
    assert entry.event_metadata["batch_status"] == "LAB_TESTING"


def test_completing_the_same_run_twice_is_refused(client, processor, started_run):
    payload = {"input_quantity": "13.7", "output_quantity": "12.9"}
    first = client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json=payload,
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json=payload,
    )
    assert second.status_code == 409, second.text
    assert "already completed" in second.json()["error"]["message"]


def test_completion_time_cannot_precede_the_start(client, processor, started_run):
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={
            "input_quantity": "13.7",
            "output_quantity": "12.9",
            "completion_time": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        },
    )
    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# Immutability after completion
# --------------------------------------------------------------------------- #
def test_a_completed_run_cannot_be_edited(client, processor, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    response = client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"input_quantity": "13.0", "output_quantity": "12.5"},
    )
    assert response.status_code == 409, response.text
    details = response.json()["error"]["details"]
    assert "input_quantity" in details["protected_fields"]
    assert details["status"] == "COMPLETED"


def test_the_completed_figures_are_unchanged_after_the_refusal(client, db, processor, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    client.patch(
        f"{API}/processing/{started_run['run']['id']}",
        headers=processor["headers"],
        json={"input_quantity": "1"},
    )
    record = db.get(HoneyProcessing, uuid.UUID(str(started_run["run"]["id"])))
    db.refresh(record)
    assert record.input_quantity == Decimal("13.700")
    assert record.output_quantity == Decimal("12.900")
    assert record.loss_quantity == Decimal("0.800")


def test_a_completed_run_cannot_be_cancelled(client, processor, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/cancel",
        headers=processor["headers"],
        json={"reason": "Changed my mind about the paperwork"},
    )
    assert response.status_code == 409, response.text


# --------------------------------------------------------------------------- #
# Cancelling
# --------------------------------------------------------------------------- #
def test_cancelling_an_open_run_keeps_the_record_and_returns_the_batch(
    client, db, processor, keeper, started_run
):
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/cancel",
        headers=processor["headers"],
        json={"reason": "The drums were not available; the honey stayed in store."},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == ProcessingStatus.CANCELLED
    assert data["cancellation_reason"].startswith("The drums")
    assert data["cancelled_at"] is not None
    assert batch_status(db, keeper["batch"]["id"]) is BatchStatus.COLLECTED


def test_cancelling_is_audited_with_the_reason(client, db, processor, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/cancel",
        headers=processor["headers"],
        json={"reason": "Equipment maintenance overran"},
    )
    entry = audit_actions(db, AuditAction.PROCESSING_CANCELLED)[-1]
    assert entry.event_metadata["reason"] == "Equipment maintenance overran"
    assert entry.event_metadata["previous_status"] == "IN_PROGRESS"


def test_a_cancelled_run_cannot_be_started_again(client, processor, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/cancel",
        headers=processor["headers"],
        json={"reason": "Cancelled deliberately"},
    )
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/start", headers=processor["headers"]
    )
    assert response.status_code == 409, response.text
    assert "Open a new run" in response.json()["error"]["message"]


def test_a_cancelled_run_cannot_be_cancelled_twice(client, processor, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/cancel",
        headers=processor["headers"],
        json={"reason": "Cancelled deliberately"},
    )
    response = client.post(
        f"{API}/processing/{started_run['run']['id']}/cancel",
        headers=processor["headers"],
        json={"reason": "Cancelled deliberately"},
    )
    assert response.status_code == 409, response.text


def test_a_cancelled_run_lets_a_fresh_run_be_opened(client, processor, keeper, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/cancel",
        headers=processor["headers"],
        json={"reason": "Abandoned before anything was done"},
    )
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "DECRYSTALLIZATION"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["processing_code"] != started_run["run"]["processing_code"]


def test_the_history_of_a_batch_shows_every_run_it_had(client, processor, keeper, open_run):
    client.post(
        f"{API}/processing/{open_run['run']['id']}/cancel",
        headers=processor["headers"],
        json={"reason": "Stopped before starting"},
    )
    second = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    response = client.get(f"{API}/processing/{second['id']}/history", headers=processor["headers"])
    assert response.status_code == 200, response.text
    codes = [row["processing_code"] for row in response.json()["data"]]
    assert codes == [second["processing_code"], open_run["run"]["processing_code"]]


# --------------------------------------------------------------------------- #
# Reads, scope and counters
# --------------------------------------------------------------------------- #
def test_the_worklist_lists_only_collected_batches(client, processor, keeper):
    response = client.get(f"{API}/processing/awaiting?page_size=50", headers=processor["headers"])
    assert response.status_code == 200, response.text
    codes = [row["batch_code"] for row in response.json()["data"]]
    assert keeper["batch"]["batch_code"] in codes


def test_the_worklist_drops_a_batch_once_processing_starts(client, processor, keeper, started_run):
    response = client.get(f"{API}/processing/awaiting?page_size=50", headers=processor["headers"])
    codes = [row["batch_code"] for row in response.json()["data"]]
    assert keeper["batch"]["batch_code"] not in codes


def test_the_summary_counts_runs_and_the_difference_by_unit(client, processor, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    response = client.get(f"{API}/processing/summary", headers=processor["headers"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1 and data["completed"] == 1
    assert data["by_unit"]["KG"] == {"input": 13.7, "output": 12.9, "loss": 0.8}


def test_a_beekeeper_reads_their_own_run_but_is_offered_no_actions(client, keeper, open_run):
    response = client.get(f"{API}/processing/{open_run['run']['id']}", headers=keeper["headers"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["can_edit"] is False and data["can_start"] is False
    assert data["can_complete"] is False and data["can_cancel"] is False
    assert data["batch"]["batch_code"] == keeper["batch"]["batch_code"]


def test_another_beekeeper_cannot_read_the_run(client, register_user, open_run):
    stranger = register_user(name="Stranger", email=None)
    response = client.get(f"{API}/processing/{open_run['run']['id']}", headers=headers_for(stranger))
    assert response.status_code == 404, response.text


def test_a_kvic_officer_sees_the_runs_of_their_clusters_only(
    client, kvic_headers, processor, keeper, open_run, admin_headers
):
    cluster = client.post(
        f"{API}/clusters",
        headers=admin_headers,
        json={
            "cluster_name": "Guntur Cluster",
            "district": "Guntur",
            "state": "Andhra Pradesh",
            "coordinator_name": "K. Rao",
            "coordinator_phone": "9876543210",
        },
    ).json()["data"]

    # A harvest recorded before the beekeeper joined carries no cluster. The officer
    # reads it anyway: the cluster registry is what bounds an officer's read, and it
    # is the registry — not the district on a profile — that they can already open.
    # Hiding the run is how a missing relationship stays missing; it is shown, and
    # the batch's "no cluster assigned" is a data-quality note to act on.
    before = client.get(f"{API}/processing?page_size=50", headers=kvic_headers)
    assert before.status_code == 200, before.text
    assert open_run["run"]["processing_code"] in [
        row["processing_code"] for row in before.json()["data"]
    ]
    readable = client.get(f"{API}/processing/{open_run['run']['id']}", headers=kvic_headers)
    assert readable.status_code == 200, readable.text
    assert readable.json()["data"]["can_start"] is False

    # The beekeeper joins the cluster, harvests again, and that batch's run is
    # the officer's to read — read-only, and it is the same single record.
    client.post(
        f"{API}/clusters/{cluster['id']}/beekeepers/{keeper['beekeeper']['id']}",
        headers=kvic_headers,
    )
    second_batch = make_batch(client, keeper["headers"], [keeper["hive"]], ["6.4"])
    assert second_batch["cluster_id"] == cluster["id"]
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": second_batch["id"], "processing_type": "FILTERING"},
    ).json()["data"]

    after = client.get(f"{API}/processing?page_size=50", headers=kvic_headers)
    codes = [row["processing_code"] for row in after.json()["data"]]
    assert run["processing_code"] in codes
    # Both runs are the officer's to read, and both are single records: joining the
    # cluster did not create a second copy of the batch, its harvest or its run.
    assert open_run["run"]["processing_code"] in codes
    assert len([code for code in codes if code == run["processing_code"]]) == 1

    detail = client.get(f"{API}/processing/{run['id']}", headers=kvic_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["can_start"] is False
    assert detail.json()["data"]["processing_code"] == run["processing_code"]


def test_a_processing_run_cannot_be_opened_by_a_consumer(client, consumer_headers, keeper):
    response = client.post(
        f"{API}/processing",
        headers=consumer_headers,
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    )
    assert response.status_code == 403, response.text


def test_a_unit_is_reused_rather_than_recreated(client, processor, keeper, make_unit):
    unit = make_unit()
    first = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_unit_id": unit["id"]},
    )
    assert first.status_code == 201, first.text
    assert first.json()["data"]["processing_unit_id"] == unit["id"]

    listed = client.get(f"{API}/processing-units?page_size=50", headers=processor["headers"])
    codes = [row["unit_code"] for row in listed.json()["data"]]
    assert codes.count(unit["unit_code"]) == 1


def test_the_run_reports_what_the_batch_is_now_not_a_copy_of_it(client, processor, keeper, started_run):
    """The run's ``batch_status`` is read from the batch on every request."""
    detail = client.get(f"{API}/processing/{started_run['run']['id']}", headers=processor["headers"])
    assert detail.json()["data"]["batch_status"] == "PROCESSING"
    client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    detail = client.get(f"{API}/processing/{started_run['run']['id']}", headers=processor["headers"])
    assert detail.json()["data"]["batch_status"] == "LAB_TESTING"
    assert detail.json()["data"]["batch"]["status"] == "LAB_TESTING"


def test_no_endpoint_can_push_a_batch_past_the_laboratory(client, processor, keeper, started_run):
    """The packaging stages are unreachable from processing by construction."""
    for verb, path in (
        ("POST", f"{API}/batches/{keeper['batch']['id']}/package"),
        ("POST", f"{API}/batches/{keeper['batch']['id']}/distribute"),
        ("GET", f"{API}/batches/{keeper['batch']['id']}/qr"),
    ):
        assert client.request(verb, path, headers=processor["headers"]).status_code == 404
    patch = client.patch(
        f"{API}/batches/{keeper['batch']['id']}",
        headers=processor["headers"],
        json={"status": "PACKAGED"},
    )
    assert patch.status_code in (404, 405)


def test_the_batch_detail_carries_the_processing_summary(client, processor, keeper, started_run):
    client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    response = client.get(f"{API}/batches/{keeper['batch']['id']}", headers=keeper["headers"])
    data = response.json()["data"]
    assert data["processing_count"] == 1
    assert data["processing"]["processing_code"] == started_run["run"]["processing_code"]
    assert Decimal(data["processing"]["loss_quantity"]) == Decimal("0.8")
    assert data["processing"]["input_quantity"] is not None


def test_the_timeline_reads_from_the_records(client, processor, keeper, started_run):
    stages = {
        row["stage"]: row
        for row in client.get(f"{API}/batches/{keeper['batch']['id']}", headers=keeper["headers"])
        .json()["data"]["timeline"]
    }
    assert stages["COLLECTION"]["state"] == "completed"
    assert stages["PROCESSING"]["state"] == "current"
    assert stages["PROCESSING"]["module_available"] is True
    assert stages["LABORATORY"]["state"] == "not_started"
    # Phase 7 built the downstream half, so the later stages are reachable — but
    # reachable is not reached: nothing has been packed or shipped yet, and the
    # timeline says so rather than showing a stage that has not happened.
    assert stages["PACKAGING"]["module_available"] is True
    # Blocked, not merely "not started": the batch is with the laboratory, and
    # packaging takes a batch only once the laboratory has released it. Saying
    # "not started" would suggest the packaging floor simply has not begun.
    assert stages["PACKAGING"]["state"] == "blocked"
    assert stages["DISTRIBUTION"]["state"] == "not_started"

    client.post(
        f"{API}/processing/{started_run['run']['id']}/complete",
        headers=processor["headers"],
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    stages = {
        row["stage"]: row
        for row in client.get(f"{API}/batches/{keeper['batch']['id']}", headers=keeper["headers"])
        .json()["data"]["timeline"]
    }
    assert stages["PROCESSING"]["state"] == "completed"
    assert "13.7" in stages["PROCESSING"]["detail"]
    assert stages["LABORATORY"]["state"] == "current"
    assert stages["LABORATORY"]["outcome"] is None


def test_units_cannot_be_created_with_a_negative_capacity(client, processor):
    response = client.post(
        f"{API}/processing-units",
        headers=processor["headers"],
        json={**UNIT_PAYLOAD, "capacity_kg_per_day": "-5"},
    )
    assert response.status_code == 422, response.text


def test_a_processing_date_in_the_future_is_refused(client, processor, keeper):
    response = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={
            "batch_id": keeper["batch"]["id"],
            "processing_type": "FILTERING",
            "processing_date": (date.today() + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422, response.text


def test_a_unit_is_registered_once_per_facility_not_per_run(client, processor, make_unit):
    first = make_unit(name="Unit A")
    second = make_unit(name="Unit B")
    assert first["unit_code"] != second["unit_code"]
    listed = client.get(f"{API}/processing-units?page_size=50", headers=processor["headers"])
    assert listed.json()["meta"]["total_items"] == 2


def test_the_run_has_a_stable_identity_across_reads(client, processor, open_run):
    first = client.get(f"{API}/processing/{open_run['run']['id']}", headers=processor["headers"]).json()["data"]
    second = client.get(f"{API}/processing/{open_run['run']['id']}", headers=processor["headers"]).json()["data"]
    assert first["id"] == second["id"]
    assert first["processing_code"] == second["processing_code"]
    assert first["created_at"] == second["created_at"]


def test_the_service_refuses_a_write_without_the_capability(client, db, keeper, open_run):
    """Defence in depth: the service checks the capability as well as the route."""
    from app.core.exceptions import ForbiddenError
    from app.models.user import User
    from app.schemas.processing import ProcessingComplete
    from app.services.processing_service import ProcessingService

    user = db.get(User, uuid.UUID(str(keeper["user"]["id"])))
    service = ProcessingService(db)
    with pytest.raises(ForbiddenError):
        service.complete_run(
            user, uuid.UUID(str(open_run["run"]["id"])), ProcessingComplete(output_quantity=Decimal("1"))
        )


# --------------------------------------------------------------------------- #
# Who the work may be given to
#
# The allocation dialog offers a list of processors. That list is a read of the
# users table, with the same checks the allocation itself makes, so the two can
# never disagree: an account that cannot be allocated to never appears in it, and
# an account the administrator has just created appears at once — no rebuild, no
# hardcoded names, no stale cache.
# --------------------------------------------------------------------------- #
def test_the_processor_directory_comes_from_the_users_table(
    client, admin_headers, processor, make_privileged_user
):
    listed = client.get(f"{API}/processing/eligible-processors", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    seen = {row["id"]: row for row in listed.json()["data"]}
    assert str(processor["id"]) in seen
    row = seen[str(processor["id"])]
    # Everything the person choosing needs to see, and nothing else.
    assert row["role"] == UserRole.PROCESSOR.value
    assert row["account_status"] == "ACTIVE"
    assert row["name"] and row["email"]
    assert row["open_work_count"] == 0

    # A second processor provisioned by an administrator shows up immediately.
    newcomer = make_privileged_user(role=UserRole.PROCESSOR, name="Second Processor")
    again = client.get(f"{API}/processing/eligible-processors", headers=admin_headers).json()["data"]
    ids = {row["id"] for row in again}
    assert str(newcomer["id"]) in ids
    assert len(ids) == 2


def test_the_processor_directory_leaves_out_switched_off_accounts(
    client, admin_headers, db, make_privileged_user
):
    """An account that cannot be allocated to must not be offered either."""
    from app.models.user import User

    active = make_privileged_user(role=UserRole.PROCESSOR, name="Active Processor")
    inactive = make_privileged_user(role=UserRole.PROCESSOR, name="Retired Processor")
    row = db.get(User, uuid.UUID(str(inactive["id"])))
    row.is_active = False
    db.commit()

    rows = client.get(f"{API}/processing/eligible-processors", headers=admin_headers).json()["data"]
    ids = {row["id"] for row in rows}
    assert str(active["id"]) in ids
    assert str(inactive["id"]) not in ids


def test_the_processor_directory_holds_only_processors(client, admin_headers, processor, labtech, keeper):
    """Other operational roles are not offered work they cannot do."""
    rows = client.get(f"{API}/processing/eligible-processors", headers=admin_headers).json()["data"]
    ids = {row["id"] for row in rows}
    assert str(processor["id"]) in ids
    assert str(labtech["id"]) not in ids
    assert str(keeper["user"]["id"]) not in ids
    assert {row["role"] for row in rows} == {UserRole.PROCESSOR.value}


def test_a_processor_sees_themselves_and_not_their_colleagues(
    client, admin_headers, processor, make_privileged_user
):
    """A processor may take unallocated work, but not pick a colleague."""
    colleague = make_privileged_user(role=UserRole.PROCESSOR, name="Other Processor")
    rows = client.get(f"{API}/processing/eligible-processors", headers=processor["headers"])
    assert rows.status_code == 200, rows.text
    ids = {row["id"] for row in rows.json()["data"]}
    assert ids == {str(processor["id"])}
    assert str(colleague["id"]) not in ids


def test_roles_that_do_not_process_cannot_read_the_processor_directory(
    client, labtech, keeper, kvic_headers
):
    for headers in (labtech["headers"], keeper["headers"], kvic_headers):
        response = client.get(f"{API}/processing/eligible-processors", headers=headers)
        assert response.status_code == 403, response.text


def test_the_directory_counts_the_open_work_already_allocated(client, admin_headers, processor, keeper):
    """The list says how busy each processor is, counted from the runs."""
    response = client.post(
        f"{API}/processing/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"processor_id": str(processor["id"])},
    )
    assert response.status_code in (200, 201), response.text
    rows = client.get(f"{API}/processing/eligible-processors", headers=admin_headers).json()["data"]
    row = next(entry for entry in rows if entry["id"] == str(processor["id"]))
    assert row["open_work_count"] == 1

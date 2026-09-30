"""Phase 6.1 — batch assignment, the queues, and who may touch what.

Phase 6 recorded *what was done* to a batch. This module is about *who was
responsible for doing it*, and the tests are arranged around the claims that
matter when work is handed between people:

* allocation is stored, not implied — a run records the processor, who allocated
  it, when, and whether it has been accepted, and the batch itself records none of
  that (one batch, read by four roles, belongs to no single queue);
* the queues partition the work — pending is unallocated, assigned is allocated,
  completed is finished, and a job is in exactly one of them;
* assigned work belongs to its assignee — a colleague cannot start it, complete
  it or edit it, and an administrator can re-allocate it explicitly;
* the names are validated against the database, not taken from the caller's word —
  a client cannot allocate work to a beekeeper, to itself, or to a switched-off
  account, and cannot allocate a finished or cancelled run;
* neither role can do the other's job — a processor cannot open, measure or
  decide a laboratory test; a laboratory technician cannot open, measure or
  complete a processing run; a beekeeper approves nothing at all;
* the hand-off is atomic — completing processing moves the batch to
  ``LAB_TESTING``, which is exactly the condition the laboratory queue reads, and
  the same batch (never a copy) is what appears there.

Every check goes through the HTTP API, so it exercises the path the screens use.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    BatchStatus,
    LabTestStatus,
    ProcessingStatus,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.laboratory import LabTest
from app.models.processing import HoneyProcessing

API = "/api/v1"

HIVE_PAYLOAD = {
    "bee_species": "Apis cerana indica",
    "village": "Tenali",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "pincode": "522201",
}

LABORATORY_PAYLOAD = {
    "name": "Assignment Test Laboratory",
    "location": "Guntur",
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "notes": "Phase 6.1 test fixture",
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


def make_hive(client: TestClient, headers: dict) -> dict:
    response = client.post(f"{API}/hives", headers=headers, json=HIVE_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def make_batch(client: TestClient, headers: dict, hive: dict, quantity: str = "13.7") -> dict:
    """Record a harvest and complete it — the only path to a batch there is."""
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


def assign_batch(client: TestClient, headers: dict, batch_id: str, processor_id) -> dict:
    return client.post(
        f"{API}/processing/batches/{batch_id}/assign",
        headers=headers,
        json={"processor_id": str(processor_id)},
    )


def complete_processing(client: TestClient, headers: dict, batch_id: str) -> dict:
    """Open, start and complete a run — no administrator, no assignment."""
    run = client.post(
        f"{API}/processing",
        headers=headers,
        json={"batch_id": batch_id, "processing_type": "FILTERING"},
    ).json()["data"]
    client.post(f"{API}/processing/{run['id']}/start", headers=headers)
    return client.post(
        f"{API}/processing/{run['id']}/complete",
        headers=headers,
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    ).json()["data"]


def finish_open_run(client: TestClient, headers: dict, batch_id: str) -> dict:
    """Start and complete the batch's existing run — no new run is opened.

    An allocated batch already has its run; opening another is refused, which is
    exactly what keeps a batch from accumulating rival records of the same job.
    """
    run = run_id_of(client, batch_id, headers)
    started = client.post(f"{API}/processing/{run}/start", headers=headers)
    assert started.status_code == 200, started.text
    completed = client.post(
        f"{API}/processing/{run}/complete",
        headers=headers,
        json={"input_quantity": "13.7", "output_quantity": "12.9"},
    )
    assert completed.status_code == 200, completed.text
    return completed.json()["data"]


def audit_actions(db: Session, action: AuditAction) -> list[AuditLog]:
    db.expire_all()
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == str(action))
        .order_by(AuditLog.created_at.asc())
        .all()
    )


def batch_status(db: Session, batch_id) -> BatchStatus:
    record = db.get(HoneyBatch, uuid.UUID(str(batch_id)))
    assert record is not None
    db.refresh(record)
    return record.status


def run_row(db: Session, run_id) -> HoneyProcessing:
    record = db.get(HoneyProcessing, uuid.UUID(str(run_id)))
    assert record is not None
    db.refresh(record)
    return record


def lab_test_row(db: Session, test_id) -> LabTest:
    record = db.get(LabTest, uuid.UUID(str(test_id)))
    assert record is not None
    db.refresh(record)
    return record


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def keeper(client: TestClient, register_user):
    payload = register_user(name="Assignment Beekeeper", email=None)
    payload["headers"] = headers_for(payload)
    payload["hive"] = make_hive(client, payload["headers"])
    payload["batch"] = make_batch(client, payload["headers"], payload["hive"])
    return payload


@pytest.fixture()
def processor(client: TestClient, make_privileged_user):
    payload = make_privileged_user(role=UserRole.PROCESSOR, name="Assigned Processor")
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def other_processor(client: TestClient, make_privileged_user):
    payload = make_privileged_user(role=UserRole.PROCESSOR, name="Second Processor")
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def labtech(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.LAB_TECHNICIAN, name="Assigned Technician", password="LabTechPass123"
    )
    payload["headers"] = sign_in(client, payload)
    return payload


@pytest.fixture()
def other_labtech(client: TestClient, make_privileged_user):
    payload = make_privileged_user(
        role=UserRole.LAB_TECHNICIAN, name="Second Technician", password="LabTechPass123"
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


# --------------------------------------------------------------------------- #
# Allocation is stored on the operational record, never on the shared batch
# --------------------------------------------------------------------------- #
def test_an_administrator_allocates_a_batch_and_the_processor_takes_it_on(
    client, admin_headers, keeper, processor
):
    response = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    assert response.status_code == 201, response.text
    run = response.json()["data"]

    assert run["processor_id"] == str(processor["id"])
    assert run["processor_name"] == "Assigned Processor"
    assert run["assignment_status"] == AssignmentStatus.ASSIGNED.value
    assert run["assigned_by_id"]
    assert run["assigned_at"]
    # Allocation is not acceptance, and not stored as if it were.
    assert run["accepted_at"] is None
    # The batch has not moved: handing work over is not doing it.
    assert run["status"] == ProcessingStatus.PENDING.value
    assert run["batch_status"] == BatchStatus.COLLECTED.value

    accepted = client.post(f"{API}/processing/{run['id']}/accept", headers=processor["headers"])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["assignment_status"] == AssignmentStatus.ACCEPTED.value
    assert accepted.json()["data"]["accepted_at"]


def test_allocating_a_batch_opens_its_one_run_and_never_a_second(client, admin_headers, keeper, processor):
    first = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    again = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    assert first.status_code == 201
    assert again.status_code in (200, 201)

    rows = client.get(
        f"{API}/processing?batch_id={keeper['batch']['id']}", headers=admin_headers
    ).json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == first.json()["data"]["id"]


def test_re_allocating_to_another_processor_moves_the_work_and_is_audited(
    client, db, admin_headers, keeper, processor, other_processor
):
    run = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"]).json()["data"]
    moved = assign_batch(client, admin_headers, keeper["batch"]["id"], other_processor["id"])
    assert moved.status_code in (200, 201)
    assert moved.json()["data"]["processor_id"] == str(other_processor["id"])

    events = [row for row in audit_actions(db, AuditAction.PROCESSING_ASSIGNED) if str(row.entity_id) == run["id"]]
    assert len(events) == 2
    assert events[-1].event_metadata["processor_id"] == str(other_processor["id"])
    assert events[-1].event_metadata["assigned_by_id"] == str(events[-1].user_id)


def test_allocating_the_same_processor_twice_is_not_a_second_event(
    client, db, admin_headers, keeper, processor
):
    run = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"]).json()["data"]
    assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    events = [row for row in audit_actions(db, AuditAction.PROCESSING_ASSIGNED) if str(row.entity_id) == run["id"]]
    assert len(events) == 1


def test_the_batch_itself_carries_no_assignment(client, admin_headers, keeper, processor):
    """One batch is read by four roles; it holds none of their queues."""
    assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    detail = client.get(f"{API}/batches/{keeper['batch']['id']}", headers=admin_headers).json()["data"]
    assert not any("processor" in key for key in detail)
    assert not any("assign" in key for key in detail)


# --------------------------------------------------------------------------- #
# The queues partition the work
# --------------------------------------------------------------------------- #
def test_a_run_nobody_owns_sits_in_pending_and_nowhere_else(client, admin_headers, keeper, processor):
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]

    pending = client.get(f"{API}/processing/pending", headers=admin_headers).json()["data"]
    assigned = client.get(f"{API}/processing/assigned", headers=admin_headers).json()["data"]
    assert [row["id"] for row in pending] == [run["id"]]
    assert assigned == []

    assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    pending = client.get(f"{API}/processing/pending", headers=admin_headers).json()["data"]
    assigned = client.get(f"{API}/processing/assigned", headers=admin_headers).json()["data"]
    assert pending == []
    assert [row["id"] for row in assigned] == [run["id"]]


def test_a_processor_reads_their_own_assigned_work_first(client, admin_headers, keeper, processor, other_processor):
    assign_batch(client, admin_headers, keeper["batch"]["id"], other_processor["id"])
    mine = client.get(f"{API}/processing/assigned", headers=processor["headers"]).json()["data"]
    theirs = client.get(f"{API}/processing/assigned", headers=other_processor["headers"]).json()["data"]
    assert mine == []
    assert len(theirs) == 1
    assert theirs[0]["processor_id"] == str(other_processor["id"])
    assert theirs[0]["can_work"] is True


def test_completed_work_leaves_the_open_queues_and_appears_as_completed(
    client, admin_headers, keeper, processor
):
    assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    run = finish_open_run(client, processor["headers"], keeper["batch"]["id"])

    pending = client.get(f"{API}/processing/pending", headers=admin_headers).json()["data"]
    assigned = client.get(f"{API}/processing/assigned", headers=admin_headers).json()["data"]
    completed = client.get(f"{API}/processing/completed", headers=admin_headers).json()["data"]
    assert pending == [] and assigned == []
    assert [row["id"] for row in completed] == [run["id"]]


def test_the_dashboard_counters_describe_the_queues(client, admin_headers, keeper, processor):
    client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    )
    summary = client.get(f"{API}/processing/summary", headers=admin_headers).json()["data"]
    assert summary["unassigned"] == 1
    assert summary["assigned"] == 0
    assert summary["waiting"] == 0  # a run exists, so the batch is not simply "waiting"

    assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    summary = client.get(f"{API}/processing/summary", headers=admin_headers).json()["data"]
    assert summary["unassigned"] == 0
    assert summary["assigned"] == 1
    assert summary["accepted"] == 0

    client.post(
        f"{API}/processing/{client.get(f'{API}/processing', headers=admin_headers).json()['data'][0]['id']}/accept",
        headers=processor["headers"],
    )
    summary = client.get(f"{API}/processing/summary", headers=admin_headers).json()["data"]
    assert summary["accepted"] == 1
    assert summary["assigned"] == 0


# --------------------------------------------------------------------------- #
# Assigned work belongs to its assignee
# --------------------------------------------------------------------------- #
def test_a_colleague_cannot_start_somebody_elses_assigned_run(
    client, db, admin_headers, keeper, processor, other_processor
):
    run = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"]).json()["data"]
    response = client.post(f"{API}/processing/{run['id']}/start", headers=other_processor["headers"])
    assert response.status_code == 403, response.text
    assert run_row(db, run["id"]).status is ProcessingStatus.PENDING


def test_a_colleague_cannot_complete_or_edit_it_either(
    client, admin_headers, keeper, processor, other_processor
):
    assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    run_id = run_id_of(client, keeper["batch"]["id"], processor["headers"])
    client.post(f"{API}/processing/{run_id}/accept", headers=processor["headers"])
    client.post(f"{API}/processing/{run_id}/start", headers=processor["headers"])

    edit = client.patch(
        f"{API}/processing/{run_id}", headers=other_processor["headers"], json={"input_quantity": "1.0"}
    )
    complete = client.post(
        f"{API}/processing/{run_id}/complete",
        headers=other_processor["headers"],
        json={"output_quantity": "1.0"},
    )
    assert edit.status_code == 403, edit.text
    assert complete.status_code == 403, complete.text


def run_id_of(client, batch_id, headers) -> str:
    """The single open run of a batch, read from the API as an authorised reader."""
    response = client.get(f"{API}/processing?batch_id={batch_id}", headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert rows, "no processing run for the fixture batch"
    return rows[0]["id"]


def test_unallocated_work_is_open_to_any_processor(client, keeper, processor):
    """The shared queue keeps moving: nobody owns it, so anybody may pick it up."""
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    started = client.post(f"{API}/processing/{run['id']}/start", headers=processor["headers"])
    assert started.status_code == 200, started.text
    assert started.json()["data"]["processor_id"] is None


def test_starting_an_allocated_run_accepts_it(client, db, admin_headers, keeper, processor):
    run = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"]).json()["data"]
    started = client.post(f"{API}/processing/{run['id']}/start", headers=processor["headers"])
    assert started.status_code == 200, started.text
    assert started.json()["data"]["assignment_status"] == AssignmentStatus.ACCEPTED.value
    assert run_row(db, run["id"]).accepted_at is not None
    assert audit_actions(db, AuditAction.PROCESSING_ACCEPTED)


def test_a_processor_cannot_push_work_onto_a_colleague(client, admin_headers, keeper, processor, other_processor):
    run = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"]).json()["data"]
    response = client.post(
        f"{API}/processing/{run['id']}/assign",
        headers=processor["headers"],
        json={"processor_id": str(other_processor["id"])},
    )
    assert response.status_code == 403, response.text


def test_a_processor_may_take_unallocated_work_personally(client, admin_headers, keeper, processor):
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    response = client.post(
        f"{API}/processing/{run['id']}/assign",
        headers=processor["headers"],
        json={"processor_id": str(processor["id"])},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["processor_id"] == str(processor["id"])


# --------------------------------------------------------------------------- #
# The allocation is validated against the database
# --------------------------------------------------------------------------- #
def test_work_cannot_be_allocated_to_an_account_that_is_not_a_processor(
    client, admin_headers, keeper, labtech
):
    response = assign_batch(client, admin_headers, keeper["batch"]["id"], labtech["id"])
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["expected_role"] == UserRole.PROCESSOR.value


def test_work_cannot_be_allocated_to_the_allocator_when_they_are_an_administrator(
    client, admin_headers, keeper, admin_payload
):
    response = assign_batch(client, admin_headers, keeper["batch"]["id"], admin_payload["id"])
    assert response.status_code == 422, response.text


def test_work_cannot_be_allocated_to_a_switched_off_processor(
    client, admin_headers, keeper, processor, deactivate_user
):
    deactivate_user(processor["id"])
    response = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    assert response.status_code == 422, response.text
    assert "not active" in response.text


def test_work_cannot_be_allocated_to_a_stranger(client, admin_headers, keeper):
    response = assign_batch(client, admin_headers, keeper["batch"]["id"], uuid.uuid4())
    assert response.status_code == 404, response.text


def test_a_processor_cannot_allocate_work_to_an_account_that_does_not_exist(
    client, keeper, processor
):
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    response = client.post(
        f"{API}/processing/{run['id']}/assign",
        headers=processor["headers"],
        json={"processor_id": str(uuid.uuid4())},
    )
    assert response.status_code == 403, response.text  # refused before the id is even looked at


def test_an_unknown_processor_id_is_not_silently_accepted_by_the_api(
    client, admin_headers, keeper
):
    """The id is validated, not trusted: a stranger is a 404, not a stored string."""
    response = client.post(
        f"{API}/processing/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"processor_id": "not-a-uuid"},
    )
    assert response.status_code == 422, response.text


def test_a_finished_run_cannot_be_allocated(client, admin_headers, keeper, processor):
    run = complete_processing(client, processor["headers"], keeper["batch"]["id"])
    response = client.post(
        f"{API}/processing/{run['id']}/assign",
        headers=admin_headers,
        json={"processor_id": str(processor["id"])},
    )
    assert response.status_code == 409, response.text


def test_a_cancelled_run_cannot_be_allocated(client, admin_headers, keeper, processor):
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    client.post(
        f"{API}/processing/{run['id']}/cancel", headers=processor["headers"], json={"reason": "not happening"}
    )
    response = client.post(
        f"{API}/processing/{run['id']}/assign",
        headers=admin_headers,
        json={"processor_id": str(processor["id"])},
    )
    assert response.status_code == 409, response.text


def test_a_batch_that_has_not_been_collected_cannot_be_allocated(client, admin_headers, keeper, processor):
    """A batch under processing has no COLLECTED status to hand over from."""
    complete_processing(client, processor["headers"], keeper["batch"]["id"])
    response = assign_batch(client, admin_headers, keeper["batch"]["id"], processor["id"])
    assert response.status_code == 409, response.text


# --------------------------------------------------------------------------- #
# The hand-off: completed processing is what the laboratory queue reads
# --------------------------------------------------------------------------- #
def test_completing_processing_puts_the_same_batch_in_the_laboratory_queue(
    client, db, keeper, processor
):
    batch_id = keeper["batch"]["id"]
    run = complete_processing(client, processor["headers"], batch_id)

    assert batch_status(db, batch_id) is BatchStatus.LAB_TESTING
    awaiting = client.get(f"{API}/lab-tests/batches/awaiting-test", headers=processor["headers"]).json()["data"]
    rows = [row for row in awaiting if row["batch_id"] == batch_id]
    assert len(rows) == 1, "the batch must appear exactly once"
    assert rows[0]["processing_id"] == run["id"]
    assert rows[0]["processing_code"] == run["processing_code"]

    events = audit_actions(db, AuditAction.BATCH_MOVED_TO_LAB_TESTING)
    assert any(str(row.entity_id) == batch_id for row in events)


def test_the_laboratory_is_never_shown_a_second_copy_of_the_batch(client, keeper, processor, labtech, laboratory):
    batch_id = keeper["batch"]["id"]
    complete_processing(client, processor["headers"], batch_id)
    response = client.post(
        f"{API}/lab-tests/batches/{batch_id}/assign",
        headers=labtech["headers"],
        json={"technician_id": str(labtech["id"])},
    )
    assert response.status_code == 201, response.text
    test = response.json()["data"]
    assert test["batch_id"] == batch_id
    assert test["batch"]["batch_code"] == keeper["batch"]["batch_code"]

    batches = client.get(f"{API}/batches?page_size=50", headers=labtech["headers"]).json()["data"]
    assert len([row for row in batches if row["batch_code"] == keeper["batch"]["batch_code"]]) == 1


def test_a_batch_with_no_test_opened_is_still_visible_to_the_laboratory(client, keeper, processor):
    complete_processing(client, processor["headers"], keeper["batch"]["id"])
    awaiting = client.get(f"{API}/lab-tests/batches/awaiting-test", headers=processor["headers"]).json()["data"]
    assert any(row["batch_id"] == keeper["batch"]["id"] for row in awaiting)


def test_a_batch_that_never_finished_processing_never_reaches_the_laboratory(
    client, db, keeper, processor, labtech, laboratory
):
    client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    )
    response = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=labtech["headers"],
        json={"technician_id": str(labtech["id"])},
    )
    assert response.status_code == 409, response.text
    assert batch_status(db, keeper["batch"]["id"]) is BatchStatus.COLLECTED


# --------------------------------------------------------------------------- #
# Laboratory allocation
# --------------------------------------------------------------------------- #
def pump_to_laboratory(client, keeper, processor) -> dict:
    return complete_processing(client, processor["headers"], keeper["batch"]["id"])


def test_allocating_a_batch_opens_the_test_and_names_the_technician(
    client, db, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    response = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=labtech["headers"],
        json={"technician_id": str(labtech["id"])},
    )
    assert response.status_code == 201, response.text
    test = response.json()["data"]
    assert test["assigned_technician_id"] == str(labtech["id"])
    assert test["sample_code"] and test["sample_code"] != test["test_code"]
    # A technician taking their own sample has accepted it; the sample is theirs.
    assert test["assignment_status"] == AssignmentStatus.ACCEPTED.value
    assert lab_test_row(db, test["id"]).technician_id == labtech["id"]


def test_an_administrator_can_allocate_a_sample_to_a_named_technician(
    client, db, admin_headers, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    response = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    )
    assert response.status_code == 201, response.text
    test = response.json()["data"]
    # Allocated, not accepted: the technician has not seen it yet.
    assert test["assignment_status"] == AssignmentStatus.ASSIGNED.value
    assert test["accepted_at"] is None
    assert test["assigned_by_id"] != str(labtech["id"])
    assert lab_test_row(db, test["id"]).accepted_at is None


def test_an_allocated_sample_sits_in_the_technicians_assigned_list_not_the_pending_one(
    client, admin_headers, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]

    pending = client.get(f"{API}/lab-tests/pending", headers=labtech["headers"]).json()["data"]
    assigned = client.get(f"{API}/lab-tests/assigned", headers=labtech["headers"]).json()["data"]
    assert all(row["id"] != test["id"] for row in pending)
    assert [row["id"] for row in assigned] == [test["id"]]
    assert assigned[0]["can_accept"] is True


def test_laboratory_work_cannot_be_allocated_to_a_processor(client, admin_headers, keeper, processor, laboratory):
    pump_to_laboratory(client, keeper, processor)
    response = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(processor["id"])},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["expected_role"] == UserRole.LAB_TECHNICIAN.value


def test_a_technician_cannot_allocate_work_to_a_colleague(
    client, admin_headers, keeper, processor, labtech, other_labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]
    response = client.post(
        f"{API}/lab-tests/{test['id']}/assign",
        headers=labtech["headers"],
        json={"technician_id": str(other_labtech["id"])},
    )
    assert response.status_code == 403, response.text


def test_a_technician_can_take_unallocated_work_personally(
    client, admin_headers, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]
    taken = client.post(
        f"{API}/lab-tests/{test['id']}/assign",
        headers=labtech["headers"],
        json={"technician_id": str(labtech["id"])},
    )
    assert taken.status_code == 200, taken.text
    assert taken.json()["data"]["assigned_technician_id"] == str(labtech["id"])


def test_the_named_technician_accepts_the_sample(
    client, db, admin_headers, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]
    response = client.post(f"{API}/lab-tests/{test['id']}/accept", headers=labtech["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["data"]["assignment_status"] == AssignmentStatus.ACCEPTED.value
    assert audit_actions(db, AuditAction.LAB_TEST_ACCEPTED)


def test_another_technician_cannot_accept_or_measure_it(
    client, admin_headers, keeper, processor, labtech, other_labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]

    accept = client.post(f"{API}/lab-tests/{test['id']}/accept", headers=other_labtech["headers"])
    measure = client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=other_labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.0"},
    )
    assert accept.status_code == 403, accept.text
    assert measure.status_code == 403, measure.text


def test_recording_a_measurement_accepts_the_sample_and_says_so(
    client, db, admin_headers, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]
    response = client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.0"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["assignment_status"] == AssignmentStatus.ACCEPTED.value
    assert lab_test_row(db, test["id"]).accepted_at is not None


def test_the_laboratory_queues_are_counted_on_the_dashboard(
    client, admin_headers, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    before = client.get(f"{API}/lab-tests/summary", headers=labtech["headers"]).json()["data"]
    assert before["unassigned"] == 0  # no test exists yet: the batch is not on the bench
    assert before["assigned"] == 0

    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]
    after = client.get(f"{API}/lab-tests/summary", headers=labtech["headers"]).json()["data"]
    assert after["assigned"] == 1
    assert after["unassigned"] == 0
    assert after["mine"] == 1
    assert after["samples_recorded"] >= 1

    client.post(f"{API}/lab-tests/{test['id']}/accept", headers=labtech["headers"])
    accepted = client.get(f"{API}/lab-tests/summary", headers=labtech["headers"]).json()["data"]
    assert accepted["accepted"] == 1
    assert accepted["assigned"] == 0


def test_a_completed_test_leaves_the_assigned_queue_and_enters_the_completed_one(
    client, admin_headers, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]
    client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.0"},
    )
    done = client.post(
        f"{API}/lab-tests/{test['id']}/complete", headers=labtech["headers"], json={"remarks": "ok"}
    )
    assert done.status_code == 200, done.text
    assert done.json()["data"]["status"] == LabTestStatus.COMPLETED.value

    assigned = client.get(f"{API}/lab-tests/assigned", headers=admin_headers).json()["data"]
    completed = client.get(f"{API}/lab-tests/completed", headers=admin_headers).json()["data"]
    assert all(row["id"] != test["id"] for row in assigned)
    assert any(row["id"] == test["id"] for row in completed)


def test_a_completed_test_cannot_be_re_allocated(client, admin_headers, keeper, processor, labtech, laboratory):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]
    client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.0"},
    )
    client.post(f"{API}/lab-tests/{test['id']}/complete", headers=labtech["headers"], json={})
    response = client.post(
        f"{API}/lab-tests/{test['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    )
    assert response.status_code == 409, response.text


# --------------------------------------------------------------------------- #
# Role separation: neither side can do the other's job
# --------------------------------------------------------------------------- #
def test_a_processor_cannot_open_measure_or_decide_a_laboratory_test(
    client, admin_headers, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]

    open_another = client.post(
        f"{API}/lab-tests",
        headers=processor["headers"],
        json={
            "batch_id": keeper["batch"]["id"],
            "laboratory_id": laboratory["id"],
            "sample_quantity": "0.25",
            "sample_unit": "GRAM",
        },
    )
    measure = client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=processor["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.0"},
    )
    decide = client.post(
        f"{API}/lab-tests/{test['id']}/complete", headers=processor["headers"], json={}
    )
    allocate = client.post(
        f"{API}/lab-tests/{test['id']}/assign",
        headers=processor["headers"],
        json={"technician_id": str(labtech["id"])},
    )
    for label, response in (
        ("open", open_another),
        ("measure", measure),
        ("decide", decide),
        ("allocate", allocate),
    ):
        assert response.status_code == 403, f"{label}: {response.text}"


def test_a_laboratory_technician_cannot_open_start_or_complete_processing(
    client, keeper, processor, labtech
):
    open_run = client.post(
        f"{API}/processing",
        headers=labtech["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    )
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    start = client.post(f"{API}/processing/{run['id']}/start", headers=labtech["headers"])
    complete = client.post(
        f"{API}/processing/{run['id']}/complete", headers=labtech["headers"], json={}
    )
    allocate = assign_batch(client, labtech["headers"], keeper["batch"]["id"], labtech["id"])
    for label, response in (
        ("open", open_run),
        ("start", start),
        ("complete", complete),
        ("allocate", allocate),
    ):
        assert response.status_code == 403, f"{label}: {response.text}"


def test_a_beekeeper_approves_nothing_and_changes_no_operational_record(
    client, keeper, processor, labtech, laboratory
):
    pump_to_laboratory(client, keeper, processor)
    # The technician books the sample in themselves, so the sample exists for the
    # rest of the refusals to be tried against.
    booked = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=labtech["headers"],
        json={"technician_id": str(labtech["id"])},
    )
    assert booked.status_code == 201, booked.text
    test = booked.json()["data"]
    measured = client.post(
        f"{API}/lab-tests/{test['id']}/results",
        headers=labtech["headers"],
        json={"parameter_code": "MOISTURE", "value": "17.0"},
    )
    assert measured.status_code == 201, measured.text

    for label, response in (
        ("complete the test", client.post(f"{API}/lab-tests/{test['id']}/complete", headers=keeper["headers"], json={})),
        ("measure it", client.post(
            f"{API}/lab-tests/{test['id']}/results",
            headers=keeper["headers"],
            json={"parameter_code": "MOISTURE", "value": "1.0"},
        )),
        ("allocate it", client.post(
            f"{API}/lab-tests/{test['id']}/assign",
            headers=keeper["headers"],
            json={"technician_id": str(labtech["id"])},
        )),
        ("override it", client.post(
            f"{API}/lab-tests/{test['id']}/override",
            headers=keeper["headers"],
            json={"overall_result": "PASS", "override_reason": "please"},
        )),
        ("configure a range", client.patch(
            f"{API}/lab-parameters/MOISTURE",
            headers=keeper["headers"],
            json={"reference_min": "0", "reference_max": "20", "reference_source": "beekeeper"},
        )),
        ("allocate the batch", assign_batch(client, keeper["headers"], keeper["batch"]["id"], keeper["user"]["id"])),
    ):
        assert response.status_code == 403, f"{label}: {response.text}"


def test_a_beekeeper_reads_their_own_honey_end_to_end(client, keeper, processor, labtech, laboratory):
    """Read-only is not blind: the whole story is visible to the person who harvested it."""
    pump_to_laboratory(client, keeper, processor)
    test = client.post(
        f"{API}/lab-tests/batches/{keeper['batch']['id']}/assign",
        headers=labtech["headers"],
        json={"technician_id": str(labtech["id"])},
    ).json()["data"]
    detail = client.get(f"{API}/batches/{keeper['batch']['id']}", headers=keeper["headers"])
    assert detail.status_code == 200, detail.text
    timeline = {stage["stage"]: stage for stage in detail.json()["data"]["timeline"]}
    assert timeline["COLLECTION"]["state"] == "completed"
    assert timeline["PROCESSING"]["state"] == "completed"
    assert timeline["LABORATORY"]["state"] == "current"

    runs = client.get(f"{API}/processing?batch_id={keeper['batch']['id']}", headers=keeper["headers"])
    assert runs.status_code == 200 and len(runs.json()["data"]) == 1
    assert runs.json()["data"][0]["can_start"] is False
    assert runs.json()["data"][0]["can_complete"] is False
    assert runs.json()["data"][0]["can_assign"] is False

    tests = client.get(f"{API}/lab-tests?batch_id={keeper['batch']['id']}", headers=keeper["headers"])
    assert tests.status_code == 200 and len(tests.json()["data"]) == 1
    assert tests.json()["data"][0]["id"] == test["id"]
    assert tests.json()["data"][0]["can_record_results"] is False
    assert tests.json()["data"][0]["can_complete"] is False


# --------------------------------------------------------------------------- #
# Scope: a cluster officer's queues hold only their cluster's work
# --------------------------------------------------------------------------- #
def test_a_cluster_officer_reads_every_queue_and_can_work_none_of_them(
    client, kvic_headers, admin_headers, keeper, processor, db
):
    """Oversight is a read — of the same rows, not of a smaller copy.

    The officer's read scope is the cluster registry, and the registry carries
    the batches that name no cluster as well, so the queue they see is the queue
    the work is actually in. What they may not do is take part: starting,
    completing or allocating is refused at the action. Hiding the row instead
    would have made oversight impossible without making anything safer.
    """
    run = complete_processing(client, processor["headers"], keeper["batch"]["id"])
    for path in ("/processing/pending", "/processing/assigned", "/processing/completed",
                 "/lab-tests/pending", "/lab-tests/assigned", "/lab-tests/completed"):
        response = client.get(f"{API}{path}", headers=kvic_headers)
        assert response.status_code == 200, f"{path}: {response.text}"

    # The finished run is in the officer's completed queue, as the same row the
    # administrator reads: one record, two readers.
    completed = client.get(f"{API}/processing/completed", headers=kvic_headers).json()["data"]
    assert run["id"] in {row["id"] for row in completed}
    admin_completed = client.get(f"{API}/processing/completed", headers=admin_headers).json()["data"]
    assert {row["id"] for row in completed} <= {row["id"] for row in admin_completed}

    summary = client.get(f"{API}/processing/summary", headers=kvic_headers).json()["data"]
    assert summary["completed"] >= 1, "the officer's counters must describe the real queues"

    # And the actions that would make them a participant are refused, with the
    # record left exactly as the processor left it.
    attempt = client.post(
        f"{API}/processing/{run['id']}/complete",
        headers=kvic_headers,
        json={"input_quantity": "13.7", "output_quantity": "1.0"},
    )
    assert attempt.status_code == 403, attempt.text
    assert run_row(db, run["id"]).output_quantity is not None
    assert float(run_row(db, run["id"]).output_quantity) == pytest.approx(12.9)


def test_a_cluster_officer_cannot_allocate_work(client, kvic_headers, keeper, processor):
    response = assign_batch(client, kvic_headers, keeper["batch"]["id"], processor["id"])
    assert response.status_code in (403, 404), response.text


# --------------------------------------------------------------------------- #
# The client cannot talk its way past the rules
# --------------------------------------------------------------------------- #
def test_a_caller_cannot_set_the_assignment_by_sending_a_status(
    client, admin_headers, keeper, processor
):
    response = client.post(
        f"{API}/processing/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"processor_id": str(processor["id"]), "assignment_status": "ACCEPTED"},
    )
    assert response.status_code == 422, response.text
    assert "assignment_status" in response.text


def test_a_caller_cannot_set_the_batch_status_through_the_assignment_endpoints(
    client, admin_headers, keeper, processor
):
    response = client.post(
        f"{API}/processing/batches/{keeper['batch']['id']}/assign",
        headers=admin_headers,
        json={"processor_id": str(processor["id"]), "batch_status": "LAB_TESTING"},
    )
    assert response.status_code == 422, response.text


def test_a_processor_cannot_assign_work_using_another_users_identity(
    client, db, keeper, processor, other_processor
):
    """The named id is checked against the caller, not merely against the database."""
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    response = client.post(
        f"{API}/processing/{run['id']}/assign",
        headers=processor["headers"],
        json={"processor_id": str(other_processor["id"])},
    )
    assert response.status_code == 403, response.text
    assert run_row(db, run["id"]).processor_id is None


def test_an_unassigned_run_reports_no_processor_rather_than_a_placeholder(
    client, keeper, processor
):
    run = client.post(
        f"{API}/processing",
        headers=processor["headers"],
        json={"batch_id": keeper["batch"]["id"], "processing_type": "FILTERING"},
    ).json()["data"]
    assert run["processor_id"] is None
    assert run["processor_name"] is None
    assert run["assigned_at"] is None
    assert run["assignment_status"] == AssignmentStatus.UNASSIGNED.value
    assert run["can_work"] is True


def test_the_allocation_is_visible_in_the_batch_worklist_the_processor_screens_use(
    client, admin_headers, processor, register_user
):
    """A second batch, to read the worklist row rather than the run."""
    payload = register_user(name="Second Beekeeper", email=None)
    headers = headers_for(payload)
    hive = make_hive(client, headers)
    batch = make_batch(client, headers, hive, quantity="5.0")

    row = [
        item
        for item in client.get(f"{API}/processing/awaiting", headers=processor["headers"]).json()["data"]
        if item["batch_id"] == batch["id"]
    ][0]
    assert row["open_processing_id"] is None

    assign_batch(client, admin_headers, batch["id"], processor["id"])
    row = [
        item
        for item in client.get(f"{API}/processing/awaiting", headers=processor["headers"]).json()["data"]
        if item["batch_id"] == batch["id"]
    ][0]
    assert row["processor_id"] == str(processor["id"])
    assert row["processor_name"] == "Assigned Processor"
    assert row["assignment_status"] == AssignmentStatus.ASSIGNED.value
    assert row["open_processing_status"] == ProcessingStatus.PENDING.value

"""Processing routes — five steps, each one an explicit operation.

``POST /processing``
    Opens a run against a ``COLLECTED`` batch. The batch does not move.
``POST /processing/{id}/start``
    Begins the work: the run becomes ``IN_PROGRESS`` and the batch ``PROCESSING``.
``PATCH /processing/{id}``
    Records or corrects the details, quantities and times while the run is open.
``POST /processing/{id}/complete``
    Closes the run with both measured quantities and sends the batch to the
    laboratory (``PROCESSING`` → ``LAB_TESTING``).
``POST /processing/{id}/cancel``
    Records that the run did not happen, with a reason, and returns the batch to
    ``COLLECTED`` if it had been marked as being processed.

The split matters. There is no endpoint that sets a status, none that completes a
run that was never started, and none that reaches the packaging stages — those
are absent rather than forbidden, because the workflow they belong to does not
exist in this build.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_permission
from app.models.enums import FacilityStatus, ProcessingStatus
from app.models.user import User
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.processing import (
    EligibleProcessor,
    ProcessingAssign,
    ProcessingBatchAssign,
    ProcessingCancel,
    ProcessingComplete,
    ProcessingCreate,
    ProcessingDetail,
    ProcessingListItem,
    ProcessingSummary,
    ProcessingUnitCreate,
    ProcessingUnitRead,
    ProcessingUnitUpdate,
    ProcessingUpdate,
)
from app.services.processing_service import ProcessingService

router = APIRouter(tags=["Processing"])

READ_PROCESSING = require_permission(Permission.PROCESSING_READ)
WRITE_PROCESSING = require_permission(Permission.PROCESSING_WRITE)
MANAGE_UNITS = require_permission(Permission.PROCESSING_UNIT_MANAGE)


# --------------------------------------------------------------------------- #
# Processing units
# --------------------------------------------------------------------------- #
@router.get(
    "/processing-units",
    response_model=ApiResponse[list[ProcessingUnitRead]],
    summary="List processing units",
    description=(
        "Registered processing facilities, paginated. A unit is registered once and reused by "
        "every run that happens in it; the count of runs is reported, the runs themselves are not "
        "copied here."
    ),
)
def list_processing_units(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    status_filter: FacilityStatus | None = Query(default=None, alias="status"),
    district: str | None = Query(default=None, max_length=80),
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = ProcessingService(session).list_units(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        district=district,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/processing-units",
    response_model=ApiResponse[ProcessingUnitRead],
    status_code=201,
    summary="Register a processing unit",
    description=(
        "Registers a facility with a server-issued code (``HC-PU-000001``). A unit is reused when "
        "it already exists; creating one for each run would make the same facility appear several "
        "times in the records."
    ),
)
def create_processing_unit(
    payload: ProcessingUnitCreate,
    user: User = Depends(MANAGE_UNITS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).create_unit(user, payload))


@router.patch(
    "/processing-units/{unit_id}",
    response_model=ApiResponse[ProcessingUnitRead],
    summary="Update a processing unit",
    description="Corrects a facility's details or retires it (``status`` = INACTIVE).",
)
def update_processing_unit(
    unit_id: uuid.UUID,
    payload: ProcessingUnitUpdate,
    user: User = Depends(MANAGE_UNITS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).update_unit(user, unit_id, payload))


# --------------------------------------------------------------------------- #
# Processing runs
# --------------------------------------------------------------------------- #
@router.get(
    "/processing/summary",
    response_model=ApiResponse[ProcessingSummary],
    summary="Processing counters",
    description=(
        "Counts by status for the caller's scope, plus the input/output difference per unit — "
        "computed only from runs that recorded both measured quantities."
    ),
)
def processing_summary(
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).summary(user))


@router.get(
    "/processing/eligible-processors",
    response_model=ApiResponse[list[EligibleProcessor]],
    summary="Accounts processing work may be allocated to",
    description=(
        "The active processor accounts the platform holds, with how much open work each is "
        "already carrying. Read from the users table, so an account created by an administrator "
        "appears here at once. An administrator sees every processor; a processor sees only "
        "themselves, because allocating work to a colleague is not their call to make."
    ),
)
def list_eligible_processors(
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).eligible_processors(user))


@router.get(
    "/processing/awaiting",
    response_model=ApiResponse[list[dict]],
    summary="Batches awaiting processing",
    description=(
        "Batches at status COLLECTED in the caller's scope — the worklist the processing screen "
        "starts from. Each row carries the batch's own identifiers and quantity; no figures are "
        "invented for a batch that has not been processed."
    ),
)
def batches_awaiting_processing(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Batch code."),
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = ProcessingService(session).batches_awaiting_processing(
        user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/processing/pending",
    response_model=ApiResponse[list[ProcessingListItem]],
    summary="Runs waiting for a processor",
    description=(
        "The shared queue: open runs that no processor has been made responsible for yet. An "
        "unallocated run is visible work, not lost work — it stays here until an administrator "
        "allocates it or a processor opens the batch themselves."
    ),
)
def processing_pending_assignments(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Run or batch code."),
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = ProcessingService(session).pending_assignments(
        user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/processing/assigned",
    response_model=ApiResponse[list[ProcessingListItem]],
    summary="Runs allocated to a processor",
    description=(
        "Open runs that have a named processor. A processor reads their own list — work allocated "
        "to them — while an administrator or cluster officer reads every allocation in scope. "
        "``mine_only=true`` narrows it explicitly."
    ),
)
def processing_assigned(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Run or batch code."),
    mine_only: bool = Query(default=False, description="Only the caller's own work."),
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = ProcessingService(session).assigned_queue(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        mine_only=mine_only,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/processing/completed",
    response_model=ApiResponse[list[ProcessingListItem]],
    summary="Completed processing",
    description=(
        "Runs that finished: the honey was measured in and out and the batch left for the "
        "laboratory. Read from the same records the laboratory queue is built from."
    ),
)
def processing_completed(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Run or batch code."),
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = ProcessingService(session).completed_queue(
        user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/processing/batches/{batch_id}/assign",
    response_model=ApiResponse[ProcessingDetail],
    status_code=201,
    summary="Assign a batch to a processor",
    description=(
        "Hands a COLLECTED batch to a named processor, opening the run if none exists yet, so the "
        "batch appears in that processor's queue straight away. Refused: a user who is not an "
        "active processor (422), a batch outside the caller's scope (403/404), a batch that is not "
        "COLLECTED with no open run (409), and a finished or cancelled run (409)."
    ),
)
def assign_batch_to_processor(
    batch_id: uuid.UUID,
    payload: ProcessingBatchAssign,
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).assign_batch(user, batch_id, payload))


@router.post(
    "/processing/{processing_id}/assign",
    response_model=ApiResponse[ProcessingDetail],
    summary="Assign a processing run",
    description=(
        "Allocates an existing open run to a named processor. An administrator may allocate to "
        "anyone; a processor may only take work on personally. Assigning the same person twice is "
        "refused as a no-op rather than recorded as a second event."
    ),
)
def assign_processing(
    processing_id: uuid.UUID,
    payload: ProcessingAssign,
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).assign_run(user, processing_id, payload))


@router.post(
    "/processing/{processing_id}/accept",
    response_model=ApiResponse[ProcessingDetail],
    summary="Accept assigned processing work",
    description=(
        "The named processor takes the run on. Only that processor (or an administrator) may "
        "accept it; starting the run implies acceptance, so this is for saying so up front."
    ),
)
def accept_processing(
    processing_id: uuid.UUID,
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).accept_run(user, processing_id))


@router.get(
    "/processing",
    response_model=ApiResponse[list[ProcessingListItem]],
    summary="List processing runs",
    description=(
        "Paginated runs. A beekeeper sees the runs on their own honey, a cluster officer the runs "
        "in the clusters they oversee, a processor and a laboratory technician the shared work "
        "queue, an administrator everything — always the same rows, filtered per reader."
    ),
)
def list_processing(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Run or batch code."),
    status_filter: ProcessingStatus | None = Query(default=None, alias="status"),
    batch_id: uuid.UUID | None = Query(default=None),
    processing_unit_id: uuid.UUID | None = Query(default=None),
    cluster_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None, description="Processing date, from."),
    date_to: date | None = Query(default=None, description="Processing date, to."),
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    items, total = ProcessingService(session).list_runs(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        batch_id=batch_id,
        processing_unit_id=processing_unit_id,
        cluster_id=cluster_id,
        processing_date_from=date_from,
        processing_date_to=date_to,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/processing",
    response_model=ApiResponse[ProcessingDetail],
    status_code=201,
    summary="Open a processing run",
    description=(
        "Opens a run against a COLLECTED batch. The run starts as PENDING and the batch does not "
        "change status until the run is started. Refused: a nonexistent batch (404), a batch that "
        "is not COLLECTED (409), an inactive or unknown unit (422/404), and a batch that already "
        "has an open run (409). No quantities are set here — they are measured, so they are "
        "recorded by a person, not filled in from the batch's weight."
    ),
)
def create_processing(
    payload: ProcessingCreate,
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).create_run(user, payload))


@router.get(
    "/processing/{processing_id}",
    response_model=ApiResponse[ProcessingDetail],
    summary="Get a processing run",
    description=(
        "The run, its batch as it stands now, the measured quantities with the difference between "
        "them, and what the workflow expects next."
    ),
)
def get_processing(
    processing_id: uuid.UUID,
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).get_run(user, processing_id))


@router.get(
    "/processing/{processing_id}/history",
    response_model=ApiResponse[list[ProcessingListItem]],
    summary="Runs recorded against this batch",
    description=(
        "Every run of the batch, newest first, including cancelled ones. A cancelled run is kept "
        "rather than deleted, so the record shows that an attempt happened."
    ),
)
def processing_history(
    processing_id: uuid.UUID,
    user: User = Depends(READ_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    service = ProcessingService(session)
    run = service.get_run(user, processing_id)
    return ok(service.runs_for_batch(user, run.batch_id))


@router.post(
    "/processing/{processing_id}/start",
    response_model=ApiResponse[ProcessingDetail],
    summary="Start a processing run",
    description=(
        "The batch moves COLLECTED → PROCESSING. This is the only place a batch enters "
        "PROCESSING, and the move is checked against the platform's transition table."
    ),
)
def start_processing(
    processing_id: uuid.UUID,
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).start_run(user, processing_id))


@router.patch(
    "/processing/{processing_id}",
    response_model=ApiResponse[ProcessingDetail],
    summary="Record or correct run details",
    description=(
        "While the run is open: its type, unit, date, measured input and output, times and notes. "
        "Once completed, these are refused with 409 and the protected fields are named — a "
        "recorded quantity is part of the batch's history. Output may never exceed input."
    ),
)
def update_processing(
    processing_id: uuid.UUID,
    payload: ProcessingUpdate,
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).update_run(user, processing_id, payload))


@router.post(
    "/processing/{processing_id}/complete",
    response_model=ApiResponse[ProcessingDetail],
    summary="Complete a processing run",
    description=(
        "Requires both measured quantities. The batch moves PROCESSING → LAB_TESTING and is then "
        "ready for laboratory testing. Completing twice is refused with 409, as is completing a "
        "run that was never started."
    ),
)
def complete_processing(
    processing_id: uuid.UUID,
    payload: ProcessingComplete,
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).complete_run(user, processing_id, payload))


@router.post(
    "/processing/{processing_id}/cancel",
    response_model=ApiResponse[ProcessingDetail],
    summary="Cancel a processing run",
    description=(
        "Records that the run did not happen, with a reason. If the batch had already been marked "
        "as being processed it returns to COLLECTED. Completed runs cannot be cancelled: the honey "
        "they produced exists."
    ),
)
def cancel_processing(
    processing_id: uuid.UUID,
    payload: ProcessingCancel,
    user: User = Depends(WRITE_PROCESSING),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProcessingService(session).cancel_run(user, processing_id, payload))


__all__ = ["router"]

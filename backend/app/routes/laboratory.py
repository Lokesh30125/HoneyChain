"""Laboratory routes — the platform's quality-decision surface.

The endpoints are grouped by who uses them:

* **Recording the work** — opening a test with its sample, recording measured
  values, correcting them while the test is open, completing the test. A
  laboratory technician holds this, and nothing else here changes a batch's fate
  on its own: ``complete`` evaluates what was recorded.
* **Deciding against the records** — ``POST /lab-tests/{id}/override``. Only an
  administrator holds this, a reason is mandatory, and the test is marked as
  overridden for every reader afterwards.
* **Configuration** — ``PATCH /lab-parameters/{code}``. Ranges and required flags
  live here, separate from measurement, and a range cannot be set without stating
  where it came from.
* **Reading** — tests, their results, the catalogue, and the worklist of batches
  awaiting testing.

There is no endpoint that accepts an overall result, none that sets a parameter's
status by hand, and none that changes a batch's status directly. Those absences
are the enforcement.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import (
    Permission,
    require_any_permission,
    require_permission,
)
from app.models.enums import FacilityStatus, LabResult, LabTestStatus
from app.models.user import User
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.laboratory import (
    EligibleTechnician,
    LabAnalysisRequest,
    LabHoldRequest,
    LabParameterRead,
    LabRiskOverrideRequest,
    LabTestAssign,
    LabTestBatchAssign,
    LabParameterUpdate,
    LabResultCreate,
    LabResultUpdate,
    LabTestComplete,
    LabTestCreate,
    LabTestDetail,
    LabTestListItem,
    LabTestOverride,
    LabTestSummary,
    LabTestUpdate,
    LaboratoryCreate,
    LaboratoryRead,
    LaboratoryUpdate,
)
from app.services.laboratory_service import LaboratoryService

router = APIRouter(tags=["Laboratory & quality"])

READ_TESTS = require_any_permission(Permission.LAB_TEST_READ, Permission.LAB_TEST_WRITE)
WRITE_TESTS = require_permission(Permission.LAB_TEST_WRITE)
OVERRIDE_TESTS = require_permission(Permission.LAB_TEST_OVERRIDE)
MANAGE_LABS = require_permission(Permission.LABORATORY_MANAGE)
READ_LABS = require_any_permission(Permission.LABORATORY_READ, Permission.LABORATORY_MANAGE)
READ_PARAMETERS = require_any_permission(
    Permission.LAB_PARAMETER_READ, Permission.LAB_PARAMETER_CONFIGURE
)
CONFIGURE_PARAMETERS = require_permission(Permission.LAB_PARAMETER_CONFIGURE)


# --------------------------------------------------------------------------- #
# Laboratories
# --------------------------------------------------------------------------- #
@router.get(
    "/laboratories",
    response_model=ApiResponse[list[LaboratoryRead]],
    summary="List laboratories",
    description=(
        "Registered facilities, paginated. ``accredited`` is the value the facility stated when it "
        "was registered — it is NULL when nothing was stated, and the platform never verifies or "
        "asserts accreditation."
    ),
)
def list_laboratories(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120),
    status_filter: FacilityStatus | None = Query(default=None, alias="status"),
    district: str | None = Query(default=None, max_length=80),
    user: User = Depends(READ_LABS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = LaboratoryService(session).list_laboratories(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        district=district,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/laboratories",
    response_model=ApiResponse[LaboratoryRead],
    status_code=201,
    summary="Register a laboratory",
    description=(
        "Registers a facility with a server-issued code (``HC-LABUNIT-000001``). A facility is "
        "registered once and reused by every test it performs; there is no implicit default "
        "laboratory, because an unattributed result is not a result."
    ),
)
def create_laboratory(
    payload: LaboratoryCreate,
    user: User = Depends(MANAGE_LABS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).create_laboratory(user, payload))


@router.patch(
    "/laboratories/{laboratory_id}",
    response_model=ApiResponse[LaboratoryRead],
    summary="Update a laboratory",
    description="Corrects a facility's details or retires it (``status`` = INACTIVE).",
)
def update_laboratory(
    laboratory_id: uuid.UUID,
    payload: LaboratoryUpdate,
    user: User = Depends(MANAGE_LABS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).update_laboratory(user, laboratory_id, payload))


# --------------------------------------------------------------------------- #
# Parameter catalogue and configuration
# --------------------------------------------------------------------------- #
@router.get(
    "/lab-parameters",
    response_model=ApiResponse[list[LabParameterRead]],
    summary="Laboratory parameter catalogue",
    description=(
        "The measurement slots the platform can record: moisture, pH, sugar profile, HMF, "
        "diastase, conductivity, colour, purity and an open OTHER slot. ``is_configured`` reports "
        "whether a reference range exists; with no range, a measured value is recorded and "
        "reported as NOT_EVALUATED rather than assumed acceptable."
    ),
)
def list_lab_parameters(
    active_only: bool = Query(default=False, description="Only parameters currently in use."),
    user: User = Depends(READ_PARAMETERS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).list_parameters(user, active_only=active_only))


@router.patch(
    "/lab-parameters/{code}",
    response_model=ApiResponse[LabParameterRead],
    summary="Configure a parameter",
    description=(
        "Sets the reference range, the required flag, the display order or the active flag for one "
        "parameter. A range must state its source (``reference_source``): the platform records the "
        "source quoted to it and defines no scientific limits itself. Setting a range and later "
        "clearing both bounds are both audited."
    ),
)
def update_lab_parameter(
    code: str,
    payload: LabParameterUpdate,
    user: User = Depends(CONFIGURE_PARAMETERS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).update_parameter(user, code, payload))


# --------------------------------------------------------------------------- #
# Laboratory tests
# --------------------------------------------------------------------------- #
@router.get(
    "/lab-tests/summary",
    response_model=ApiResponse[LabTestSummary],
    summary="Laboratory counters",
    description=(
        "Counts by status and by outcome for the caller's scope, the sample weight recorded, the "
        "number of outcomes set by hand, and how many active parameters still have no configured "
        "range — reported rather than hidden, because it is the reason a test can be inconclusive."
    ),
)
def lab_test_summary(
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).summary(user))


@router.get(
    "/lab-tests/eligible-technicians",
    response_model=ApiResponse[list[EligibleTechnician]],
    summary="Accounts laboratory work may be allocated to",
    description=(
        "The active laboratory-technician accounts the platform holds, with how much open work "
        "each is already carrying. Read from the users table, so an account created by an "
        "administrator appears here at once. An administrator sees every technician; a technician "
        "sees only themselves."
    ),
)
def list_eligible_technicians(
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).eligible_technicians(user))


@router.get(
    "/lab-tests/awaiting",
    response_model=ApiResponse[list[dict]],
    summary="Batches awaiting laboratory testing",
    description=(
        "Batches at status LAB_TESTING in the caller's scope — the laboratory worklist. Each row "
        "names the completed processing run that produced the sample's honey, so a test is opened "
        "against a real run."
    ),
)
def batches_awaiting_testing(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Batch code."),
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = LaboratoryService(session).batches_awaiting_testing(
        user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/lab-tests/pending",
    response_model=ApiResponse[list[LabTestListItem]],
    summary="Samples waiting for a laboratory technician",
    description=(
        "Open tests that nobody is responsible for yet. A sample stays visible here until someone "
        "is made responsible for it, so unallocated work cannot quietly fall off the bench."
    ),
)
def lab_tests_pending(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Test, sample or batch code."),
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = LaboratoryService(session).pending_tests(
        user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/lab-tests/assigned",
    response_model=ApiResponse[list[LabTestListItem]],
    summary="Tests allocated to a laboratory technician",
    description=(
        "Open tests that have a named technician. A technician reads their own list; an "
        "administrator or cluster officer reads every allocation in scope. "
        "``mine_only=true`` narrows it explicitly."
    ),
)
def lab_tests_assigned(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Test, sample or batch code."),
    mine_only: bool = Query(default=False, description="Only the caller's own work."),
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = LaboratoryService(session).assigned_tests(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        mine_only=mine_only,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/lab-tests/completed",
    response_model=ApiResponse[list[LabTestListItem]],
    summary="Completed laboratory tests",
    description=(
        "Decided tests with their overall result — pass, fail or inconclusive — read from the "
        "stored decision rather than recomputed on the client."
    ),
)
def lab_tests_completed(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Test, sample or batch code."),
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = LaboratoryService(session).completed_tests(
        user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/lab-tests/held",
    response_model=ApiResponse[list[LabTestListItem]],
    summary="Tests on hold, with their reason",
    description=(
        "Tests the laboratory has parked. They are not bench work — each row names what is "
        "missing and who recorded the hold — and the way forward is a further test against the "
        "same batch."
    ),
)
def lab_tests_on_hold(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Test, sample or batch code."),
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = LaboratoryService(session).held_tests(
        user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/lab-tests/batches/awaiting-test",
    response_model=ApiResponse[list[dict]],
    summary="Batches at LAB_TESTING with no test opened",
    description=(
        "The gap between processing and the bench: batches whose processing is complete but for "
        "which no sample has been booked in yet. An administrator allocates these directly."
    ),
)
def batches_without_tests(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Batch code."),
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = LaboratoryService(session).unassigned_batches(
        user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/lab-tests/batches/{batch_id}/assign",
    response_model=ApiResponse[LabTestDetail],
    status_code=201,
    summary="Assign a batch's laboratory work",
    description=(
        "Allocates the batch's sample to a named laboratory technician, opening the test if none "
        "exists yet so the sample reaches the bench straight away. Refused: a user who is not an "
        "active technician (422), an unregistered laboratory (409), a batch that is not at "
        "LAB_TESTING (409), and a completed test (409)."
    ),
)
def assign_batch_to_technician(
    batch_id: uuid.UUID,
    payload: LabTestBatchAssign,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).assign_batch(user, batch_id, payload))


@router.post(
    "/lab-tests/{test_id}/assign",
    response_model=ApiResponse[LabTestDetail],
    summary="Assign a laboratory test",
    description=(
        "Allocates an open test to a named technician. An administrator may allocate to anyone; a "
        "technician may only take work on personally. The sample stays on the pending list until "
        "it is accepted, so an allocation cannot hide unstarted work."
    ),
)
def assign_lab_test(
    test_id: uuid.UUID,
    payload: LabTestAssign,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).assign_test(user, test_id, payload))


@router.post(
    "/lab-tests/{test_id}/accept",
    response_model=ApiResponse[LabTestDetail],
    summary="Accept assigned laboratory work",
    description=(
        "The named technician takes the test on. Only that technician (or an administrator) may "
        "accept it. Recording a measurement accepts the test implicitly."
    ),
)
def accept_lab_test(
    test_id: uuid.UUID,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).accept_test(user, test_id))


@router.get(
    "/lab-tests",
    response_model=ApiResponse[list[LabTestListItem]],
    summary="List laboratory tests",
    description=(
        "Paginated tests with their recorded-value counts. Every test ever taken is listed, "
        "including superseded ones: a retest adds a row, it does not replace one."
    ),
)
def list_lab_tests(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Test, sample or batch code."),
    status_filter: LabTestStatus | None = Query(default=None, alias="status"),
    overall_result: LabResult | None = Query(default=None),
    batch_id: uuid.UUID | None = Query(default=None),
    laboratory_id: uuid.UUID | None = Query(default=None),
    technician_id: uuid.UUID | None = Query(default=None),
    cluster_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    items, total = LaboratoryService(session).list_tests(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        result_filter=overall_result,
        batch_id=batch_id,
        laboratory_id=laboratory_id,
        technician_id=technician_id,
        cluster_id=cluster_id,
        test_date_from=date_from,
        test_date_to=date_to,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/lab-tests",
    response_model=ApiResponse[LabTestDetail],
    status_code=201,
    summary="Open a laboratory test and record its sample",
    description=(
        "Opens a test against a batch awaiting laboratory testing, with a server-issued test code "
        "(``HC-LAB-2026-000001``) and sample code (``HC-SMP-2026-000001``). The processing run is "
        "read from the batch, not supplied by the caller. A batch with an open test is refused "
        "(409), and so is a batch that has not been processed. For a batch already decided, "
        "``retest_reason`` is required and the batch returns to LAB_TESTING."
    ),
)
def create_lab_test(
    payload: LabTestCreate,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).create_test(user, payload))


@router.get(
    "/lab-tests/{test_id}",
    response_model=ApiResponse[LabTestDetail],
    summary="Get a laboratory test",
    description=(
        "The test with its recorded results (each with the range it was compared against and where "
        "that range came from), the reasoning behind the current outcome, and the sample's "
        "traceability chain: sample → test → batch → processing → collection → hives → beekeeper → "
        "cluster → laboratory."
    ),
)
def get_lab_test(
    test_id: uuid.UUID,
    user: User = Depends(READ_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).get_test(user, test_id))


@router.patch(
    "/lab-tests/{test_id}",
    response_model=ApiResponse[LabTestDetail],
    summary="Correct the sample details",
    description=(
        "Sample quantity, unit, collection time, notes and test date while the test is open. "
        "A completed test is refused with 409: its measurements are read, never rewritten."
    ),
)
def update_lab_test(
    test_id: uuid.UUID,
    payload: LabTestUpdate,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).update_test(user, test_id, payload))


@router.post(
    "/lab-tests/{test_id}/results",
    response_model=ApiResponse[LabTestDetail],
    status_code=201,
    summary="Record a measured value",
    description=(
        "Records one measurement against an open test. The value is stored as measured, with the "
        "configured range snapshotted beside it. The parameter's status is computed, never "
        "supplied; a parameter with no configured range is recorded as NOT_EVALUATED. A second "
        "result for the same parameter is refused (409) — a correction uses PATCH."
    ),
)
def record_lab_result(
    test_id: uuid.UUID,
    payload: LabResultCreate,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).record_result(user, test_id, payload))


@router.patch(
    "/lab-tests/{test_id}/results/{result_id}",
    response_model=ApiResponse[LabTestDetail],
    summary="Correct a recorded value",
    description=(
        "Changes a measurement on an open test. The previous value and the caller's reason are "
        "written to the audit log, and the measurement is re-evaluated against the range that was "
        "snapshotted when it was recorded — not against today's configuration."
    ),
)
def update_lab_result(
    test_id: uuid.UUID,
    result_id: uuid.UUID,
    payload: LabResultUpdate,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).update_result(user, test_id, result_id, payload))


@router.delete(
    "/lab-tests/{test_id}/results/{result_id}",
    response_model=ApiResponse[LabTestDetail],
    summary="Remove a recorded value",
    description=(
        "Removes a measurement entered in error, on an open test only. The removal is audited with "
        "the value it removed; a completed test's results cannot be deleted at all."
    ),
)
def delete_lab_result(
    test_id: uuid.UUID,
    result_id: uuid.UUID,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).remove_result(user, test_id, result_id))


@router.post(
    "/lab-tests/{test_id}/complete",
    response_model=ApiResponse[LabTestDetail],
    summary="Complete a test and decide",
    description=(
        "Evaluates every recorded result against the configured ranges and stores the outcome. "
        "A test with no results is refused (422). All required parameters passing ⇒ PASS, the "
        "batch becomes APPROVED and is then released as PACKAGING_READY; a required failure ⇒ "
        "FAIL and REJECTED; a missing required measurement or an unevaluated parameter ⇒ "
        "INCONCLUSIVE, and the batch moves to LAB_HOLD — the evaluation is finished, and what is "
        "missing is a person's decision, not more bench work. A test the quality analysis flagged "
        "is refused (409) until the caller holds it or records a decision to continue: completing "
        "it normally would release a batch whose risks were never answered. The request carries "
        "no outcome."
    ),
)
def complete_lab_test(
    test_id: uuid.UUID,
    payload: LabTestComplete,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).complete_test(user, test_id, payload))


@router.post(
    "/lab-tests/{test_id}/analyze",
    response_model=ApiResponse[LabTestDetail],
    summary="Run the AI quality analysis over the recorded measurements",
    description=(
        "Reads the measurements already on the test and the ranges configured for each parameter, "
        "and stores a structured analysis: overall status, risk level, vulnerabilities, abnormal, "
        "passed and inconclusive parameters, an explanation and a recommendation — together with "
        "the model, version and source that produced it. The response says plainly that this is "
        "development decision-support over configured values, not a validated instrument, and it "
        "lists the limitations it ran under. Nothing is invented: a parameter with no value is "
        "not analysed, and a parameter with no configured range is reported as such."
    ),
)
def analyze_lab_test(
    test_id: uuid.UUID,
    payload: LabAnalysisRequest | None = None,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).analyze_test(user, test_id, payload))


@router.post(
    "/lab-tests/{test_id}/hold",
    response_model=ApiResponse[LabTestDetail],
    summary="Hold the test and the batch for review",
    description=(
        "Closes the test without a decision and parks the batch: the test becomes HOLD, the batch "
        "becomes LAB_HOLD, and packaging is blocked. The measurements, their sources, their "
        "methods and the analysis are kept exactly as recorded — this adds the reason and the "
        "person. The hold is visible to the beekeeper, the officer and the packaging floor, and "
        "the way out is a further test, which the laboratory may open from the hold."
    ),
)
def hold_lab_test(
    test_id: uuid.UUID,
    payload: LabHoldRequest,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).hold_test(user, test_id, payload))


@router.post(
    "/lab-tests/{test_id}/proceed-with-risk",
    response_model=ApiResponse[LabTestDetail],
    summary="Continue with a flagged batch, on the record (development override)",
    description=(
        "TEMPORARY DEVELOPMENT/DEMO OVERRIDE. Refused unless the installation sets "
        "``LAB_ALLOW_RISK_OVERRIDE=true``; the caller must also echo the confirmation word "
        "returned by the test detail (default ``PROCEED``) and give a reason. The test closes "
        "with the outcome its own measurements produced — a FAIL stays a FAIL — and the batch "
        "moves LAB_TESTING → PROCEEDED_WITH_RISK → APPROVED → PACKAGING_READY, so the recorded "
        "risk is visible in the batch's history rather than only in a log. The user, the moment, "
        "the risks shown, the analysis behind them and the reason are stored on the test and "
        "written to the audit log as ``PROCEEDED_WITH_RISK``."
    ),
)
def proceed_with_risk(
    test_id: uuid.UUID,
    payload: LabRiskOverrideRequest,
    user: User = Depends(WRITE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).proceed_with_risk(user, test_id, payload))


@router.post(
    "/lab-tests/{test_id}/override",
    response_model=ApiResponse[LabTestDetail],
    summary="Override a completed test's outcome (administrator only)",
    description=(
        "Sets the outcome of a completed test by hand, with a mandatory reason. The computed "
        "result is kept beside the override, the action is audited, and every reader sees the test "
        "marked as overridden. This exists so a decision the configured rules cannot express has "
        "somewhere honest to live — never as a way to make a measurement say something it does not."
    ),
)
def override_lab_test(
    test_id: uuid.UUID,
    payload: LabTestOverride,
    user: User = Depends(OVERRIDE_TESTS),
    session: Session = Depends(db_session),
) -> dict:
    return ok(LaboratoryService(session).override_test(user, test_id, payload))


__all__ = ["router"]

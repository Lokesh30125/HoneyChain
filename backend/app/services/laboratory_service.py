"""Laboratory testing: measurement, evaluation, and the decision on a batch.

The shape of the phase in one file
---------------------------------
A test is opened against a batch that is at ``LAB_TESTING`` — which only a
completed processing run can produce. Opening it records the *sample*: how much,
in what unit, when it was taken. Then the technician records measured values, one
per parameter. Then the test is completed, and at that moment the platform
evaluates what was recorded against the ranges an administrator configured, and
decides.

Four properties are worth stating plainly, because they are what the code is
built around rather than decorations on top of it:

1. **Nothing here accepts a verdict.** There is no request field for an overall
   result, no way to mark a parameter as passing, and no endpoint that sets a
   batch's status directly. The only paths to ``APPROVED`` and ``REJECTED`` are
   :meth:`LaboratoryService.complete_test` and the admin-only
   :meth:`LaboratoryService.override_test`, and both go through
   :mod:`app.services.batch_lifecycle`.
2. **Evaluation uses what was configured, or says it could not.** A parameter with
   no configured range is recorded and reported as ``NOT_EVALUATED``; a test
   containing one is ``INCONCLUSIVE``, and the batch stays at ``LAB_TESTING``.
   The platform never supplies a limit of its own, and never implies that an
   unevaluated reading passed.
3. **History is additive.** A retest does not touch the earlier test. A
   correction to an open test is audited with its previous value. A completed
   test's measurements cannot be edited at all — only overridden by an
   administrator, with a reason, on the record.
4. **The chain is read, not copied.** The sample's path back to the apiary is
   assembled from the batch, its processing run, its collection, the collection's
   source hives, the beekeeper and the cluster. No step of that chain is
   duplicated onto the test, so a test can never contradict the records it came
   from.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.permissions import Permission, has_permission
from app.models.document_sequence import DocumentSequence
from app.models.enums import (
    AssignmentStatus,
    AuditAction,
    BatchStatus,
    FacilityStatus,
    LabMeasurementSource,
    LabParameterCode,
    LabParameterStatus,
    LabResult,
    LabTestStatus,
    ProcessingStatus,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.laboratory import LabParameter, Laboratory, LabTest, LabTestResult
from app.models.user import User
from app.repositories.batch_repository import BatchRepository
from app.repositories.user_repository import UserRepository
from app.repositories.laboratory_repository import (
    LabParameterRepository,
    LaboratoryRepository,
    LabTestRepository,
)
from app.repositories.processing_repository import ProcessingRepository
from app.schemas.laboratory import (
    EligibleTechnician,
    LabParameterRead,
    LabTestAssign,
    LabTestCreate,
    LabResultRead,
    LabTestBatchRef,
    LabTestDetail,
    LabTestListItem,
    LabTestProcessingRef,
    LabTestSummary,
    LaboratoryRead,
    TraceabilityNode,
)
from app.services import batch_lifecycle
from app.services.lab_demo_profile import is_demo_source
from app.services.ai.lab_quality import (
    ANALYSIS_SOURCE,
    MODEL_NAME,
    MODEL_VERSION,
    LabQualityAnalysis,
    MeasurementPoint,
    analyse_measurements,
    risk_override_available,
)
from app.services.audit_service import AuditService
from app.services.blockchain import BlockchainService
from app.services.collection_service import CollectionService
from app.services.names import beekeeper_name, cluster_name, person_name
from app.services.quality_rules import EvaluatedResult, Verdict, decide, evaluate_parameter

logger = logging.getLogger(__name__)

_SEQUENCE_YEAR = "%Y"

#: Fields a completed test must not lose. The reason a decision cannot be edited
#: after the fact is that it is a statement about the honey: what it said stays
#: said, and a later disagreement becomes a new test.
IMMUTABLE_WHEN_COMPLETED = (
    "batch_id",
    "processing_id",
    "laboratory_id",
    "sample_code",
    "sample_quantity",
    "sample_unit",
    "overall_result",
)


def build_test_code(sequence: str, *, when: datetime | None = None) -> str:
    """``HC-LAB-<YYYY>-<NNNNNN>``."""
    year = (when or datetime.now(tz=timezone.utc)).year
    return f"HC-LAB-{year}-{sequence}"


def build_sample_code(sequence: str, *, when: datetime | None = None) -> str:
    """``HC-SMP-<YYYY>-<NNNNNN>`` — the sample's own identity, distinct from the test's.

    A sample is a physical thing that travels with a label; the test is the work
    done on it. Keeping the two apart is what lets a dispute say "test this
    sample again" without pretending the first test never happened.
    """
    year = (when or datetime.now(tz=timezone.utc)).year
    return f"HC-SMP-{year}-{sequence}"


def build_laboratory_code(sequence: str) -> str:
    """``HC-LABUNIT-<NNNNNN>`` — a facility, not a document."""
    return f"HC-LABUNIT-{sequence}"


def _enum_value(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


def _label(enum_value) -> str:
    return getattr(enum_value, "label", None) or _enum_value(enum_value) or "Unknown"


class LaboratoryService:
    """Register laboratories, configure parameters, test samples, decide batches."""

    def __init__(self, session) -> None:  # noqa: ANN001 - Session from the dependency
        self.session = session
        self.laboratories = LaboratoryRepository(session)
        self.parameters = LabParameterRepository(session)
        self.tests = LabTestRepository(session)
        self.runs = ProcessingRepository(session)
        self.batches = BatchRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)
        # Traceability events are recorded through this service, in the same
        # transaction as the record change (import at module level, below).
        self.blockchain = BlockchainService(session)
        self.collections = CollectionService(session)

    # ------------------------------------------------------------------ #
    # Scope
    # ------------------------------------------------------------------ #
    def _scope_filters(self, user: User) -> dict:
        """Read scope for a laboratory listing — the same rules as processing.

        Deliberately identical to :meth:`ProcessingService._scope_filters`: a
        test and the run it came from must never fall into different scopes, or a
        reader would see half of a story.
        """
        if user.role == UserRole.BEEKEEPER:
            return {"beekeeper_id": self.collections.own_beekeeper(user).id}
        if user.role == UserRole.KVIC_OFFICER:
            # Same rule as processing, deliberately: a test and the run it came from
            # must never fall into different scopes.
            return {
                "cluster_ids": self.collections.officer_cluster_ids(user),
                "include_unclustered": True,
            }
        return self.collections.workflow_scope_filters(user)

    def _assert_can_read_test(self, user: User, test: LabTest) -> None:
        self.collections.assert_record_scope(
            user, record=test.batch, resource="Laboratory test", resource_id=test.id
        )

    # ------------------------------------------------------------------ #
    # Laboratories
    # ------------------------------------------------------------------ #
    def create_laboratory(self, user: User, payload) -> LaboratoryRead:
        """Register a facility — reused whenever it already exists.

        There is no "default laboratory" and none is created implicitly: a test
        always names the facility that produced it, because an unattributed
        result is not a result.
        """
        code = build_laboratory_code(
            DocumentSequence.next_value(self.session, "LABORATORY", width=6)
        )
        laboratory = Laboratory(
            laboratory_code=code,
            name=payload.name.strip(),
            registration_identifier=payload.registration_identifier,
            location=payload.location,
            district=payload.district,
            state=payload.state,
            contact_email=payload.contact_email,
            contact_phone=payload.contact_phone,
            # Recorded as stated. The platform does not verify accreditation, and
            # nothing in this build claims a facility is accredited.
            accredited=payload.accredited,
            status=FacilityStatus.ACTIVE,
            notes=payload.notes,
        )
        self.session.add(laboratory)
        try:
            self.session.flush()
        except IntegrityError as exc:  # pragma: no cover - the code is issued by us
            raise ConflictError("A laboratory with this code already exists") from exc
        self.audit.laboratory_created(laboratory, actor=user)
        self.session.commit()
        return self.to_laboratory_read(laboratory)

    def list_laboratories(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: FacilityStatus | None = None,
        district: str | None = None,
    ) -> tuple[list[LaboratoryRead], int]:
        rows, total = self.laboratories.search(
            page=page,
            page_size=page_size,
            search=search,
            status=_enum_value(status_filter),
            district=district,
        )
        return [self.to_laboratory_read(row) for row in rows], total

    def update_laboratory(
        self, user: User, laboratory_id: uuid.UUID, payload
    ) -> LaboratoryRead:
        laboratory = self.laboratories.get(laboratory_id)
        if laboratory is None:
            raise NotFoundError(
                f"Laboratory {laboratory_id} not found", details={"resource": "laboratory"}
            )
        changes = []
        for field, value in payload.model_dump(exclude_unset=True).items():
            current = getattr(laboratory, field)
            if current == value:
                continue
            changes.append({"field": field, "from": _enum_value(current), "to": _enum_value(value)})
            setattr(laboratory, field, value)
        if not changes:
            return self.to_laboratory_read(laboratory)
        self.session.flush()
        self.audit.laboratory_updated(
            laboratory, actor=user, fields=[change["field"] for change in changes]
        )
        self.session.commit()
        return self.to_laboratory_read(laboratory)

    def to_laboratory_read(self, laboratory: Laboratory) -> LaboratoryRead:
        _rows, total = self.tests.search(page=1, page_size=1, laboratory_id=laboratory.id)
        return LaboratoryRead(
            id=laboratory.id,
            laboratory_code=laboratory.laboratory_code,
            name=laboratory.name,
            registration_identifier=laboratory.registration_identifier,
            location=laboratory.location,
            district=laboratory.district,
            state=laboratory.state,
            contact_email=laboratory.contact_email,
            contact_phone=laboratory.contact_phone,
            accredited=laboratory.accredited,
            status=laboratory.status,
            status_label=_label(laboratory.status),
            is_demo=bool(laboratory.is_demo),
            notes=laboratory.notes,
            test_count=total,
            created_at=laboratory.created_at,
            updated_at=laboratory.updated_at,
        )

    # ------------------------------------------------------------------ #
    # Parameter catalogue and configuration
    # ------------------------------------------------------------------ #
    def list_parameters(
        self, user: User, *, active_only: bool = False
    ) -> list[LabParameterRead]:
        return [
            self.to_parameter_read(row)
            for row in self.parameters.all_parameters(active_only=active_only)
        ]

    def update_parameter(
        self, user: User, code: str, payload
    ) -> LabParameterRead:
        """Set what "acceptable" means for one measurement.

        The service refuses a range with no stated source: the platform repeats
        the source to every reader and vouches for nothing itself, so an
        unsourced limit would be an invented standard with the platform's name on
        it. The whole update is one audit entry.
        """
        parameter = self.parameters.get_by_code(code)
        if parameter is None:
            raise NotFoundError(
                f"Laboratory parameter {code} not found", details={"resource": "lab_parameter"}
            )

        data = payload.model_dump(exclude_unset=True)
        if not data:
            return self.to_parameter_read(parameter)

        setting_range = "reference_min" in data or "reference_max" in data
        resulting_min = data.get("reference_min", parameter.reference_min)
        resulting_max = data.get("reference_max", parameter.reference_max)
        if resulting_min is not None and resulting_max is not None and resulting_min > resulting_max:
            raise ValidationError(
                "The lower bound of a reference range cannot exceed the upper bound.",
                details={"reference_min": str(resulting_min), "reference_max": str(resulting_max)},
            )
        source = data.get("reference_source", parameter.reference_source)
        if setting_range and (resulting_min is not None or resulting_max is not None) and not (
            source or ""
        ).strip():
            raise ValidationError(
                "A reference range must state where it came from: the platform records the "
                "source you give it and does not define scientific limits itself.",
                details={"parameter_code": parameter.code, "missing_field": "reference_source"},
            )

        if "methods" in data and data["methods"] is not None:
            # Stored as plain dictionaries: what is written is exactly what a
            # reader gets back, with no model class in between that could drift.
            data["methods"] = [
                option.model_dump() if hasattr(option, "model_dump") else dict(option)
                for option in data["methods"]
            ]

        changes = []
        for field, value in data.items():
            current = getattr(parameter, field)
            if current == value:
                continue
            changes.append(
                {"field": field, "from": _enum_value(current), "to": _enum_value(value)}
            )
            setattr(parameter, field, value)
        if not changes:
            return self.to_parameter_read(parameter)

        if setting_range:
            parameter.reference_updated_by_id = user.id
            parameter.reference_updated_at = datetime.now(tz=timezone.utc)
        self.session.flush()
        self.audit.lab_parameter_configured(parameter, actor=user, changes=changes)
        self.session.commit()
        return self.to_parameter_read(parameter)

    def to_parameter_read(self, parameter: LabParameter) -> LabParameterRead:
        configured = parameter.reference_min is not None or parameter.reference_max is not None
        return LabParameterRead(
            id=parameter.id,
            code=parameter.code,
            name=parameter.name,
            unit=parameter.unit,
            unit_label=_label(parameter.unit),
            description=parameter.description,
            is_required=bool(parameter.is_required),
            is_active=bool(parameter.is_active),
            display_order=int(parameter.display_order or 0),
            reference_min=parameter.reference_min,
            reference_max=parameter.reference_max,
            reference_source=parameter.reference_source,
            reference_updated_at=parameter.reference_updated_at,
            is_configured=configured,
            configured_by=getattr(parameter.reference_updated_by, "full_name", None),
            methods=list(parameter.methods or []),
            development_value=parameter.development_value,
            # The range's provenance, restated as a flag: a development range is
            # shown as one, everywhere it appears.
            is_demo_configuration=is_demo_source(parameter.reference_source),
        )

    # ------------------------------------------------------------------ #
    # Laboratory tests — opening, sampling
    # ------------------------------------------------------------------ #
    def eligible_technicians(self, user: User) -> list[EligibleTechnician]:
        """The accounts laboratory work may be allocated to, read from the database.

        Active accounts holding the laboratory-technician role — never a hardcoded
        list. An administrator sees every technician; a technician sees only
        themselves, because allocating a sample to a colleague is an
        administrator's decision. The open-work count travels with each name.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        people = self.users.active_by_role(UserRole.LAB_TECHNICIAN)
        if user.role is not UserRole.ADMIN:
            people = [person for person in people if person.id == user.id]
        workload = self.tests.open_counts_by_technician()
        return [
            EligibleTechnician(
                id=person.id,
                name=person.name,
                email=person.email,
                role=str(person.role),
                role_label=person.role.label,
                is_active=person.is_active,
                account_status="ACTIVE" if person.is_active else "INACTIVE",
                open_work_count=workload.get(person.id, 0),
            )
            for person in people
        ]

    def create_test(
        self, user: User, payload, *, technician_id: uuid.UUID | None = None
    ) -> LabTestDetail:
        """Open a test against a batch awaiting laboratory testing.

        The batch must be at ``LAB_TESTING``, which means a processing run has
        been completed against it. That is where the processing run for the test
        comes from — it is read from the batch's own record, never supplied by the
        caller, so a test cannot be attributed to a run that did not produce the
        honey.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)

        batch = self.batches.get_with_relations(payload.batch_id)
        if batch is None:
            raise NotFoundError(
                f"Batch {payload.batch_id} not found", details={"resource": "batch"}
            )
        self.collections.assert_record_scope(
            user, record=batch, resource="Batch", resource_id=payload.batch_id
        )

        testable = (
            BatchStatus.LAB_TESTING,
            BatchStatus.LAB_HOLD,
            BatchStatus.APPROVED,
            BatchStatus.PACKAGING_READY,
            BatchStatus.REJECTED,
        )
        if batch.status not in testable:
            raise ConflictError(
                f"Batch {batch.batch_code} is "
                f"{batch_lifecycle.STATUS_LABEL.get(batch.status, batch.status)} and has not been "
                "sent to the laboratory. Processing must be completed first.",
                details={
                    "batch_code": batch.batch_code,
                    "batch_status": str(batch.status),
                    "required_status": str(BatchStatus.LAB_TESTING),
                },
            )

        # The processing run comes from the batch's own record — the caller names a
        # batch, never a run.
        run = self._completed_run_for(batch)

        is_retest = batch.status in (
            BatchStatus.APPROVED,
            BatchStatus.PACKAGING_READY,
            BatchStatus.REJECTED,
        )
        is_hold_release = batch.status is BatchStatus.LAB_HOLD
        if is_retest and self._open_packaging_run(batch) is not None:
            # Packaging is packing this approval right now. Re-opening the verdict
            # under it would let packages be created for a batch that may end up
            # rejected; the run is finished or cancelled first.
            open_run = self._open_packaging_run(batch)
            raise ConflictError(
                f"Batch {batch.batch_code} has an open packaging run "
                f"({open_run.packaging_code}). Complete or cancel it before retesting.",
                details={
                    "batch_code": batch.batch_code,
                    "packaging_code": open_run.packaging_code,
                    "packaging_status": str(open_run.status),
                },
            )
        if (is_retest or is_hold_release) and not (payload.retest_reason or "").strip():
            raise ValidationError(
                f"Batch {batch.batch_code} is "
                f"{batch_lifecycle.STATUS_LABEL.get(batch.status, batch.status)}. A further test "
                "needs a reason (retest_reason): what is being examined this time — a dispute, a "
                "verification, a fresh sample, or the value the hold was waiting for.",
                details={"batch_code": batch.batch_code, "batch_status": str(batch.status)},
            )

        # Bench work in progress blocks a second test; a *held* one does not, or a
        # hold would be a dead end. The held test keeps its measurements, its
        # analysis and its reason, and the new round is numbered after it.
        open_test = self._open_test_for(batch)
        if open_test is not None:
            raise ConflictError(
                f"Batch {batch.batch_code} already has an open laboratory test "
                f"({open_test.test_code}, {open_test.status}). Complete it before opening another.",
                details={
                    "batch_code": batch.batch_code,
                    "open_test_code": open_test.test_code,
                    "open_test_status": str(open_test.status),
                },
            )

        laboratory = self._resolve_laboratory(payload.laboratory_id)

        previous_tests = self.tests.for_batch(batch.id)
        round_number = self.tests.max_round(batch.id) + 1
        retest_of_id = previous_tests[0].id if previous_tests else None

        # Whoever the test belongs to is named at creation, so the sample is never
        # in the queue with nobody responsible for it. Normally that is the caller:
        # a technician taking a sample. When an administrator allocates the work on
        # somebody's behalf, ``technician_id`` names the person who will do it and
        # the administrator is recorded as the allocator instead. Either way the
        # name is validated against the database — an administrator cannot become a
        # technician by asking to be one.
        technician = self._resolve_technician(technician_id or user.id)

        test = LabTest(
            test_code=self._next_test_code(),
            sample_code=self._next_sample_code(),
            batch_id=batch.id,
            processing_id=run.id,
            laboratory_id=laboratory.id,
            technician_id=technician.id,
            assigned_technician_id=technician.id,
            assigned_by_id=user.id,
            assigned_at=datetime.now(tz=timezone.utc),
            # The technician taking their own sample has plainly accepted it; one who
            # was allocated the work by somebody else has not, so it waits in their
            # assigned list until they pick it up.
            accepted_at=(
                datetime.now(tz=timezone.utc) if technician.id == user.id else None
            ),
            assignment_status=(
                AssignmentStatus.ACCEPTED
                if technician.id == user.id
                else AssignmentStatus.ASSIGNED
            ),
            sample_quantity=payload.sample_quantity,
            sample_unit=payload.sample_unit,
            sample_collected_at=payload.sample_collected_at or datetime.now(tz=timezone.utc),
            sample_notes=payload.sample_notes,
            test_date=payload.test_date or date.today(),
            status=LabTestStatus.PENDING,
            overall_result=LabResult.PENDING,
            remarks=payload.remarks,
            round_number=round_number,
            retest_of_id=retest_of_id if (is_retest or is_hold_release) else None,
            retest_reason=payload.retest_reason if (is_retest or is_hold_release) else None,
        )
        self.session.add(test)
        try:
            self.session.flush()
        except IntegrityError as exc:  # pragma: no cover - the codes are issued by us
            raise ConflictError(
                "A laboratory test with this code already exists; please retry."
            ) from exc

        self._prefill_development_measurements(test)
        self.audit.lab_test_created(test, actor=user, batch=batch, processing=run)
        self.audit.lab_test_assigned(test, actor=user, technician=technician, batch=batch)
        self.audit.lab_sample_recorded(
            test,
            actor=user,
            previous={"sample_quantity": None, "sample_unit": None, "reason": "initial record"},
        )

        # A further test puts the batch back on the bench — from a decision, from
        # the packaging floor, or out of a hold. The transition table allows
        # exactly those moves and nothing else.
        if is_retest or is_hold_release:
            previous_status = str(batch.status)
            batch_lifecycle.advance(
                batch,
                BatchStatus.LAB_TESTING,
                action=(
                    f"Opening retest {test.test_code}"
                    if is_retest
                    else f"Releasing the hold on {batch.batch_code} with {test.test_code}"
                ),
            )
            self.session.flush()
            self.audit.batch_status_changed(
                batch,
                actor=user,
                previous=previous_status,
                new_stage=batch_lifecycle.STAGE_FOR_STATUS.get(batch.status, batch.current_stage),
            )
            logger.info(
                "A further test opened on this batch",
                extra={
                    "test_code": test.test_code,
                    "batch": batch.batch_code,
                    "previous_status": previous_status,
                },
            )

        # The sample is on the bench: a traceability event of its own, so the
        # ledger knows testing began even if the result only arrives days later.
        self.blockchain.lab_test_started(test, actor=user)
        self.session.commit()
        committed = self.tests.get_with_relations(test.id)
        return self.to_detail(committed, user)

    def update_test(self, user: User, test_id: uuid.UUID, payload) -> LabTestDetail:
        """Correct the sample's details while the test is open."""
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        test = self._load_test(test_id)
        self._assert_open(test, action="editing the sample")
        self._assert_may_work(user, test, action="editing the sample")

        data = payload.model_dump(exclude_unset=True)
        if not data:
            return self.get_test(user, test_id)

        previous = {
            "sample_quantity": str(test.sample_quantity),
            "sample_unit": str(test.sample_unit),
            "sample_collected_at": test.sample_collected_at.isoformat()
            if test.sample_collected_at
            else None,
            "test_date": test.test_date.isoformat() if test.test_date else None,
        }
        for field, value in data.items():
            setattr(test, field, value)
        self.session.flush()
        self.audit.lab_sample_recorded(test, actor=user, previous=previous)
        self.session.commit()
        return self.get_test(user, test_id)

    # ------------------------------------------------------------------ #
    # Results — recorded values only
    # ------------------------------------------------------------------ #
    def record_result(self, user: User, test_id: uuid.UUID, payload) -> LabTestDetail:
        """Record one measured value against an open test.

        The value is stored exactly as measured, with a *snapshot* of the range it
        was compared against and where that range came from. Snapshotting matters:
        if the limits are reconfigured next month, this result still explains the
        decision that was taken today.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        test = self._load_test(test_id)
        self._assert_open(test, action="recording results")
        self._assert_may_work(user, test, action="recording results")
        self._note_work_started(user, test)

        parameter = self._resolve_parameter(payload.parameter_code)
        unit = payload.unit or parameter.unit
        if payload.unit is not None and payload.unit != parameter.unit:
            raise ValidationError(
                f"{parameter.name} is measured in {_label(parameter.unit)}; "
                f"{_label(payload.unit)} was supplied.",
                details={
                    "parameter_code": parameter.code,
                    "expected_unit": str(parameter.unit),
                    "supplied_unit": str(payload.unit),
                },
            )
        if parameter.code == LabParameterCode.OTHER.value and not (
            payload.parameter_name or ""
        ).strip():
            raise ValidationError(
                'The OTHER parameter must name the measurement it is recording (parameter_name).',
                details={"parameter_code": parameter.code, "missing_field": "parameter_name"},
            )

        if self.tests.result_for_parameter(test.id, parameter.code) is not None:
            raise ConflictError(
                f"A result for {parameter.code} is already recorded on test {test.test_code}. "
                "Correct the existing measurement rather than adding a second one.",
                details={
                    "test_code": test.test_code,
                    "parameter_code": parameter.code,
                    "correction_endpoint": f"/api/v1/lab-tests/{test.id}/results",
                },
            )

        status = evaluate_parameter(
            value=payload.value,
            reference_min=parameter.reference_min,
            reference_max=parameter.reference_max,
        )
        result = LabTestResult(
            lab_test_id=test.id,
            parameter_code=parameter.code,
            parameter_name=(payload.parameter_name or parameter.name).strip(),
            value=payload.value,
            unit=unit,
            reference_min=parameter.reference_min,
            reference_max=parameter.reference_max,
            reference_source=parameter.reference_source,
            status=status,
            # Where the number came from. A value typed here is MANUAL; the
            # caller may say DEMO only for a value it is re-storing from the
            # development profile, and REAL_DEVICE for an instrument.
            measurement_source=(
                payload.measurement_source
                if getattr(payload, "measurement_source", None) is not None
                else LabMeasurementSource.MANUAL
            ),
            method=payload.method,
            remarks=payload.remarks,
            measured_at=payload.measured_at or datetime.now(tz=timezone.utc),
            recorded_by_id=user.id,
        )
        # Appended to the test's own collection rather than inserted behind its
        # back: the response is built from this object, and the session does not
        # expire it on commit, so the in-memory record must be the true one.
        test.results.append(result)
        if test.status is LabTestStatus.PENDING:
            # The work has begun: the sample is in the laboratory and a
            # measurement exists. The status says so; the caller did not set it.
            test.status = LabTestStatus.IN_PROGRESS
        self.session.flush()
        self.audit.lab_result_recorded(result, actor=user, test=test)
        self.session.commit()
        return self.get_test(user, test_id)

    def update_result(
        self, user: User, test_id: uuid.UUID, result_id: uuid.UUID, payload
    ) -> LabTestDetail:
        """Correct a recorded value on an open test, keeping the old one in the log."""
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        test = self._load_test(test_id)
        self._assert_open(test, action="correcting results")
        self._assert_may_work(user, test, action="correcting results")

        result = self.session.get(LabTestResult, result_id)
        if result is None or result.lab_test_id != test.id:
            raise NotFoundError(
                f"Result {result_id} not found on test {test.test_code}",
                details={"resource": "lab_result", "test_code": test.test_code},
            )

        data = payload.model_dump(exclude_unset=True)
        if not data:
            return self.get_test(user, test_id)

        previous = {
            "value": str(result.value),
            "unit": str(result.unit),
            "status": str(result.status),
            "parameter_name": result.parameter_name,
            "method": result.method,
            "remarks": result.remarks,
        }

        if "unit" in data and data["unit"] is not None and data["unit"] != result.unit:
            raise ValidationError(
                f"A result for {result.parameter_code} is recorded in {_label(result.unit)}; "
                "changing the unit would change what the number means. Record the value in the "
                "unit the catalogue defines.",
                details={
                    "parameter_code": result.parameter_code,
                    "recorded_unit": str(result.unit),
                    "supplied_unit": str(data["unit"]),
                },
            )
        data.pop("unit", None)

        if "value" in data:
            previous["value"] = str(result.value)
            result.value = data["value"]
            # Re-evaluated against the range snapshotted when it was recorded, so
            # a correction cannot pick up a different standard.
            result.status = evaluate_parameter(
                value=result.value,
                reference_min=result.reference_min,
                reference_max=result.reference_max,
            )
        for field in ("parameter_name", "method", "remarks", "measured_at"):
            if field in data:
                setattr(result, field, data[field])

        # Correcting a value makes it the person's own: a development default that
        # has been replaced is no longer a development default, and the record has
        # to say so. An explicit source in the request wins over that rule.
        if "value" in data or "measurement_source" in data:
            result.measurement_source = (
                data["measurement_source"]
                if data.get("measurement_source") is not None
                else LabMeasurementSource.MANUAL
            )

        self.session.flush()
        self.audit.lab_result_updated(
            result, actor=user, test=test, previous=previous, reason=payload.correction_reason
        )
        self.session.commit()
        return self.get_test(user, test_id)

    def remove_result(
        self, user: User, test_id: uuid.UUID, result_id: uuid.UUID
    ) -> LabTestDetail:
        """Remove a recorded value that was entered in error on an open test."""
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        test = self._load_test(test_id)
        self._assert_open(test, action="removing results")
        self._assert_may_work(user, test, action="removing results")

        result = self.session.get(LabTestResult, result_id)
        if result is None or result.lab_test_id != test.id:
            raise NotFoundError(
                f"Result {result_id} not found on test {test.test_code}",
                details={"resource": "lab_result", "test_code": test.test_code},
            )
        self.audit.lab_result_removed(result, actor=user, test=test)
        # Removed from the test's own collection, which the cascade turns into the
        # delete: the loaded relationship then matches the table, rather than
        # holding a row that no longer exists.
        test.results.remove(result)
        self.session.flush()
        self.session.commit()
        return self.get_test(user, test_id)

    # ------------------------------------------------------------------ #
    # Completion and the decision
    # ------------------------------------------------------------------ #
    def complete_test(self, user: User, test_id: uuid.UUID, payload) -> LabTestDetail:
        """Evaluate what was recorded and decide the batch.

        A test with no results is refused, so the one thing that can never happen
        is a verdict with nothing behind it. An ``INCONCLUSIVE`` outcome is a real
        outcome: the test is completed and recorded, and the batch stays where it
        is until the missing information exists.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        test = self._load_test(test_id)
        self._assert_open(test, action="completing the test")
        self._assert_may_work(user, test, action="completing the test")

        results = self.tests.results_for_test(test.id)
        if not results:
            raise ValidationError(
                f"No laboratory results have been recorded on test {test.test_code}. "
                "A test is completed by recording measurements, not by declaring an outcome.",
                details={"test_code": test.test_code, "results": 0},
            )

        # A flagged test must be decided on, not completed past. If the analysis
        # found something, the two ways forward are the hold and the (development)
        # override — both of which record what the person saw. Completing normally
        # would release a batch whose risks were never answered.
        if self._blocks_plain_completion(test):
            analysis = LabQualityAnalysis.from_dict(test.ai_analysis)
            raise ConflictError(
                f"Test {test.test_code} has been analysed and the analysis flagged it "
                f"({analysis.overall_status}, risk {analysis.risk_level}). Choose what happens to "
                "the batch: hold it for review, or record the decision to continue.",
                details={
                    "test_code": test.test_code,
                    "ai_status": analysis.overall_status,
                    "risk_level": analysis.risk_level,
                    "vulnerabilities": analysis.vulnerabilities,
                    "abnormal_parameters": analysis.abnormal_parameters,
                    "options": ["hold", "proceed_with_risk"] if self._risk_override_available(test) else ["hold"],
                },
            )

        verdict = self._verdict_for(test, results)
        batch = test.batch
        previous_batch_status = str(batch.status)

        test.status = LabTestStatus.COMPLETED
        test.overall_result = verdict.result
        test.result_summary = verdict.summary
        test.completed_at = datetime.now(tz=timezone.utc)
        test.decided_by_id = user.id
        if payload.remarks is not None:
            test.remarks = payload.remarks
        self.session.flush()

        decided_status = self._apply_decision(
            user, test, verdict.result, previous_batch_status
        )
        if verdict.result is LabResult.PASS:
            decided_status = self._release_to_packaging(user, test, previous_batch_status)
        self.audit.lab_test_completed(
            test,
            actor=user,
            batch=batch,
            previous_batch_status=previous_batch_status,
            verdict=verdict,
            resulting_batch_status=decided_status,
        )
        # The laboratory's verdict, on the ledger as the event it is: a pass, a
        # failure and a hold are three different things with three different
        # consequences, and the summary carries the measured values the decision
        # was taken on — not the full result set, which stays here.
        self.blockchain.quality_decision(test, results=results, actor=user)
        self.session.commit()
        logger.info(
            "Laboratory test completed",
            extra={
                "test_code": test.test_code,
                "overall_result": str(test.overall_result),
                "batch": batch.batch_code,
            },
        )
        return self.get_test(user, test_id)

    # ------------------------------------------------------------------ #
    # The AI quality analysis, the hold and the risk override
    # ------------------------------------------------------------------ #
    def analyze_test(self, user: User, test_id: uuid.UUID, payload=None) -> LabTestDetail:
        """Run the quality analysis over this test's measurements and store it.

        Explicit rather than automatic: a stored analysis is a claim about the
        honey, and it should be something a person asked for. It reads only what
        is on the test — the measured values, their units and the ranges
        configured for them — and it is stored with the model, version and source
        that produced it, so a later, better model cannot silently rewrite what
        was concluded.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        settings = get_settings()
        if not settings.LAB_QUALITY_ANALYSIS_ENABLED:
            raise ForbiddenError(
                "Quality analysis is disabled on this installation",
                details={"setting": "LAB_QUALITY_ANALYSIS_ENABLED"},
            )
        test = self._load_test(test_id)
        self._assert_may_work(user, test, action="analysing the test")
        results = self.tests.results_for_test(test.id)
        if not results:
            raise ValidationError(
                f"Test {test.test_code} has no measurements to analyse. Record the measured "
                "values first: the analysis reads what is on the record, it does not invent it.",
                details={"test_code": test.test_code, "results": 0},
            )

        analysis, points = self._analysis_for(test, results)
        self._store_analysis(user, test, analysis)
        self.audit.record(
            action=AuditAction.LAB_QUALITY_ANALYSED,
            entity_type="lab_test",
            entity_id=test.id,
            actor=user,
            description=(
                f"Quality analysis run on {test.test_code}: {analysis.overall_status} "
                f"(risk {analysis.risk_level})"
            ),
            metadata={
                "test_code": test.test_code,
                "batch_code": test.batch.batch_code,
                "overall_status": analysis.overall_status,
                "risk_level": analysis.risk_level,
                "vulnerabilities": analysis.vulnerabilities,
                "abnormal_parameters": analysis.abnormal_parameters,
                "inconclusive_parameters": analysis.inconclusive_parameters,
                "isolation_score": analysis.isolation_score,
                "model": analysis.model,
                "model_version": analysis.model_version,
                "source": analysis.source,
                "measurement_reference": {
                    "lab_test_id": str(test.id),
                    "result_ids": [str(row.id) for row in results],
                    "measured_values": {row.parameter_code: str(row.value) for row in results},
                    "measurement_sources": analysis.measurement_sources,
                },
            },
        )
        self.session.commit()
        logger.info(
            "Laboratory quality analysis stored",
            extra={
                "test_code": test.test_code,
                "overall_status": analysis.overall_status,
                "risk_level": analysis.risk_level,
            },
        )
        return self.get_test(user, test_id)

    def hold_test(self, user: User, test_id: uuid.UUID, payload) -> LabTestDetail:
        """Park the test and the batch: measured, analysed, and waiting on a person.

        Nothing is thrown away. The measurements, their sources, their methods and
        the analysis stay exactly as recorded — this action adds the reason and the
        person, moves the test to ``HOLD`` and the batch to ``LAB_HOLD``, and that
        status is what blocks packaging. The way out is a new test, which the
        laboratory opens from the hold.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        test = self._load_test(test_id)
        self._assert_open(test, action="putting the test on hold")
        self._assert_may_work(user, test, action="putting the test on hold")

        reason = (getattr(payload, "reason", None) or "").strip()
        if not reason:
            raise ValidationError(
                "A hold needs a reason. It is what the beekeeper, the officer and the packaging "
                "floor are shown, and the next person to look at this batch starts from it.",
                details={"test_code": test.test_code},
            )

        results = self.tests.results_for_test(test.id)
        analysis = self._ensure_analysis(user, test, results, payload=payload)

        batch = test.batch
        previous_batch_status = str(batch.status)
        now = datetime.now(tz=timezone.utc)

        test.status = LabTestStatus.HOLD
        test.hold_reason = reason
        test.held_at = now
        test.held_by_id = user.id
        if getattr(payload, "remarks", None):
            test.remarks = payload.remarks
        self.session.flush()

        hold_target = BatchStatus.LAB_HOLD
        if batch.status in (BatchStatus.APPROVED, BatchStatus.REJECTED, BatchStatus.PACKAGING_READY):
            # Withdraw the earlier decision first: the transition table allows one
            # step at a time, and a batch coming off an approval is retested, not
            # re-held from a state it is no longer in.
            withdrawn = str(batch.status)
            batch_lifecycle.advance(
                batch,
                BatchStatus.LAB_TESTING,
                action=f"Reopening the laboratory decision on {batch.batch_code}",
            )
            self.session.flush()
            self.audit.batch_status_changed(
                batch,
                actor=user,
                previous=withdrawn,
                new_stage=batch_lifecycle.STAGE_FOR_STATUS.get(batch.status, batch.current_stage),
            )
            previous_batch_status = str(batch.status)
        if batch.status is BatchStatus.LAB_TESTING:
            batch_lifecycle.advance(
                batch,
                hold_target,
                action=f"Holding {batch.batch_code} for review ({test.test_code})",
            )
            self.session.flush()

        self.audit.record(
            action=AuditAction.LAB_HOLD,
            entity_type="lab_test",
            entity_id=test.id,
            actor=user,
            description=f"{test.test_code} held: {reason}",
            metadata={
                "test_code": test.test_code,
                "batch_code": batch.batch_code,
                "batch_status": str(batch.status),
                "previous_batch_status": previous_batch_status,
                "reason": reason,
                "hold_reason": reason,
                "ai_status": test.ai_status,
                "risk_level": test.ai_risk_level,
                "vulnerabilities": (test.ai_analysis or {}).get("vulnerabilities", []),
                "abnormal_parameters": (test.ai_analysis or {}).get("abnormal_parameters", []),
                "overall_status": (test.ai_analysis or {}).get("overall_status"),
                "measurement_sources": self._source_counts(results),
                "held_at": now.isoformat(),
                "packaging": "blocked",
            },
        )
        self.audit.batch_status_changed(
            batch,
            actor=user,
            previous=previous_batch_status,
            new_stage=batch_lifecycle.STAGE_FOR_STATUS.get(batch.status, batch.current_stage),
        )
        # A hold is a decision the platform made: measured, analysed, and stopped
        # until a person answers. It goes on the ledger as itself — the packaging
        # floor can see why the batch is not on their queue.
        self.blockchain.quality_decision(test, results=results, actor=user)
        self.session.commit()
        logger.warning(
            "Laboratory test held",
            extra={"test_code": test.test_code, "batch": batch.batch_code, "reason": reason},
        )
        return self.get_test(user, test_id)

    def proceed_with_risk(self, user: User, test_id: uuid.UUID, payload) -> LabTestDetail:
        """Close the test and release the batch **with the risk recorded**.

        This is the development/demo override, and it is built so that it cannot
        happen by accident:

        * the installation must have ``LAB_ALLOW_RISK_OVERRIDE`` on, or the action
          is refused (and not offered in the UI);
        * the caller must echo the confirmation word, so a stray click on a button
          cannot release a flagged batch;
        * the analysis, the detected risks, the reason, the user and the moment are
          all stored on the test and written to the audit log as
          ``PROCEEDED_WITH_RISK``.

        The test keeps the outcome the measurements actually produced — a FAIL
        stays a FAIL. What the override changes is the *batch's* fate, and the
        record of that decision sits beside the measurement that prompted it.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)
        settings = get_settings()
        if not settings.LAB_ALLOW_RISK_OVERRIDE:
            raise ForbiddenError(
                "Continuing with a flagged batch is disabled on this installation",
                details={
                    "setting": "LAB_ALLOW_RISK_OVERRIDE",
                    "reason": (
                        "This is a development/demo override. With it off, a flagged batch can "
                        "only be held, rejected, or retested after the measurements are corrected."
                    ),
                },
            )

        expected = (settings.LAB_RISK_OVERRIDE_CONFIRMATION or "PROCEED").strip()
        confirmation = (getattr(payload, "confirmation", None) or "").strip()
        if confirmation.upper() != expected.upper():
            raise ValidationError(
                f"Continuing with a flagged batch requires an explicit confirmation. Type "
                f"\"{expected}\" to record that the risks shown were reviewed and accepted.",
                details={"confirmation_required": expected},
            )
        reason = (getattr(payload, "reason", None) or "").strip()
        if not reason:
            raise ValidationError(
                "An override needs a reason. It is stored with the risks the user was shown and "
                "is what an auditor reads first.",
                details={"test_code": "reason"},
            )

        test = self._load_test(test_id)
        self._assert_open(test, action="continuing with the batch")
        self._assert_may_work(user, test, action="continuing with the batch")

        results = self.tests.results_for_test(test.id)
        if not results:
            raise ValidationError(
                f"Test {test.test_code} has no measurements. There is nothing to review and "
                "nothing to proceed with.",
                details={"test_code": test.test_code, "results": 0},
            )
        analysis = self._ensure_analysis(user, test, results, payload=payload)

        batch = test.batch
        previous_batch_status = str(batch.status)
        now = datetime.now(tz=timezone.utc)

        # The test closes with the outcome its own measurements produced.
        verdict = self._verdict_for(test, results)
        test.status = LabTestStatus.COMPLETED
        test.overall_result = verdict.result
        test.result_summary = (
            f"{verdict.summary} Released to packaging with a recorded risk by "
            f"{person_name(user) or 'a named user'}: {reason}"
        )
        test.completed_at = now
        test.decided_by_id = user.id
        test.risk_override = {
            "reason": reason,
            "user_id": str(user.id),
            "user_name": person_name(user),
            "user_role": str(user.role),
            "at": now.isoformat(),
            "batch_id": str(batch.id),
            "laboratory_test_id": str(test.id),
            "override_action": "PROCEEDED_WITH_RISK",
            "confirmation": confirmation,
            "detected_risks": list(analysis.vulnerabilities),
            "abnormal_parameters": list(analysis.abnormal_parameters),
            "ai_result": analysis.as_dict(),
            "batch_status_before": previous_batch_status,
        }
        test.overridden_by_id = user.id
        test.overridden_at = now
        if getattr(payload, "remarks", None):
            test.remarks = payload.remarks
        self.session.flush()

        # LAB_TESTING/LAB_HOLD/REJECTED → PROCEEDED_WITH_RISK → APPROVED →
        # PACKAGING_READY. Each step is in the transition table; none is skipped,
        # so the traceability timeline shows the risk being recorded *before* the
        # approval rather than instead of it.
        if batch.status is BatchStatus.PACKAGING_READY:
            batch_lifecycle.advance(
                batch, BatchStatus.APPROVED, action=f"Withdrawing the release of {batch.batch_code}"
            )
            self.session.flush()
        if batch.status is not BatchStatus.LAB_TESTING:
            batch_lifecycle.advance(
                batch,
                BatchStatus.LAB_TESTING,
                action=f"Reopening {batch.batch_code} for the risk decision",
            )
            self.session.flush()
        batch_lifecycle.advance(
            batch,
            BatchStatus.PROCEEDED_WITH_RISK,
            action=f"Recording the risk on {test.test_code}",
        )
        self.session.flush()
        batch_lifecycle.advance(
            batch,
            BatchStatus.APPROVED,
            action=f"Releasing {batch.batch_code} with a recorded risk",
        )
        self.session.flush()
        batch_lifecycle.advance(
            batch,
            BatchStatus.PACKAGING_READY,
            action=f"Offering {batch.batch_code} to packaging under a recorded risk",
        )
        self.session.flush()

        self.audit.record(
            action=AuditAction.PROCEEDED_WITH_RISK,
            entity_type="lab_test",
            entity_id=test.id,
            actor=user,
            description=(
                f"{person_name(user) or 'A user'} released {batch.batch_code} to packaging with a "
                f"recorded risk after {test.test_code} was flagged: {reason}"
            ),
            metadata={
                "batch_id": str(batch.id),
                "batch_code": batch.batch_code,
                "laboratory_test_id": str(test.id),
                "test_code": test.test_code,
                "user_id": str(user.id),
                "user_name": person_name(user),
                "user_role": str(user.role),
                "detected_risks": list(analysis.vulnerabilities),
                "abnormal_parameters": list(analysis.abnormal_parameters),
                "vulnerabilities": list(analysis.vulnerabilities),
                "ai_result": analysis.as_dict(),
                "override_action": "PROCEEDED_WITH_RISK",
                "confirmation": confirmation,
                "reason": reason,
                "timestamp": now.isoformat(),
                "previous_batch_status": previous_batch_status,
                "resulting_batch_status": str(batch.status),
                "laboratory_result": str(test.overall_result),
                "measurement_sources": self._source_counts(results),
            },
        )
        self.audit.batch_status_changed(
            batch,
            actor=user,
            previous=previous_batch_status,
            new_stage=batch_lifecycle.STAGE_FOR_STATUS.get(batch.status, batch.current_stage),
        )
        # A separate event, never a replacement: the ledger keeps the failure or
        # the hold that was measured, and adds the decision to continue beside it.
        # An auditor reading only the chain sees, in order, what was found and
        # who chose to proceed anyway.
        self.blockchain.quality_decision(test, results=results, actor=user)
        self.blockchain.proceeded_with_risk(test, actor=user, reason=reason)
        self.session.commit()
        logger.warning(
            "Batch released with a recorded risk",
            extra={
                "test_code": test.test_code,
                "batch": batch.batch_code,
                "user": user.email,
                "risks": len(analysis.vulnerabilities),
            },
        )
        return self.get_test(user, test_id)

    def override_test(self, user: User, test_id: uuid.UUID, payload) -> LabTestDetail:
        """An administrator decides against the recorded measurements, on the record.

        This exists because the alternative is worse. A real dispute sometimes
        needs a human decision, and if the platform offered no place for one, the
        decision would be made by editing a measurement. Here it is a named
        action: administrator only, a reason is required, the computed result is
        kept beside the override, and every reader sees the test marked as
        overridden.
        """
        _assert_can_write(user, Permission.LAB_TEST_OVERRIDE)
        test = self._load_test(test_id)

        if test.status is not LabTestStatus.COMPLETED:
            raise ConflictError(
                f"Test {test.test_code} is {test.status}. Record the measurements and complete the "
                "test first: an override changes a decision that exists, it does not replace making one.",
                details={"test_code": test.test_code, "status": str(test.status)},
            )

        results = self.tests.results_for_test(test.id)
        computed = self._verdict_for(test, results).result
        if payload.overall_result is computed:
            raise ValidationError(
                f"Test {test.test_code} already reads {computed}. An override must change the outcome; "
                "if the records are right, nothing needs overriding.",
                details={"test_code": test.test_code, "overall_result": str(computed)},
            )

        batch = test.batch
        previous_batch_status = str(batch.status)
        test.overall_result = payload.overall_result
        test.is_override = True
        test.override_reason = payload.reason.strip()
        test.decided_by_id = user.id
        test.result_summary = (
            f"Outcome set by hand by an administrator ({payload.reason.strip()}). "
            f"The recorded measurements produced {computed}."
        )
        self.session.flush()

        self.audit.lab_test_overridden(
            test, actor=user, computed=str(computed), reason=payload.reason.strip()
        )
        self._apply_decision(user, test, payload.overall_result, previous_batch_status)
        self.blockchain.quality_decision(
            test,
            results=self.tests.results_for_test(test.id),
            actor=user,
            previous_result=str(computed),
            is_override=True,
        )
        self.session.commit()
        logger.warning(
            "Laboratory test overridden",
            extra={"test_code": test.test_code, "from": str(computed), "to": str(payload.overall_result)},
        )
        return self.get_test(user, test_id)

    def _blocks_plain_completion(self, test: LabTest) -> bool:
        """Whether the stored analysis says this test needs a decision first."""
        if not test.ai_analysis:
            return False
        analysis = LabQualityAnalysis.from_dict(test.ai_analysis)
        return analysis.overall_status != "PASS" or bool(analysis.vulnerabilities)

    def _release_to_packaging(
        self, user: User, test: LabTest, previous_batch_status: str
    ) -> str:
        """Hand an approved batch to the packaging floor, on the record.

        Approval and release are two statements: the laboratory decided the honey
        passed, and the batch has been offered to the people who pack it. Keeping
        them apart is what lets a batch be approved and *not* packed — held for a
        buyer's confirmation, say — without any screen having to guess which of the
        two it is looking at.
        """
        batch = test.batch
        if batch.status is BatchStatus.APPROVED:
            batch_lifecycle.advance(
                batch,
                BatchStatus.PACKAGING_READY,
                action=f"Releasing {batch.batch_code} to packaging after {test.test_code}",
            )
            self.session.flush()
            self.audit.record(
                action=AuditAction.BATCH_PACKAGING_READY,
                entity_type="batch",
                entity_id=batch.id,
                actor=user,
                description=f"{batch.batch_code} is ready for packaging",
                metadata={
                    "batch_code": batch.batch_code,
                    "test_code": test.test_code,
                    "previous_batch_status": previous_batch_status,
                    "batch_status": str(batch.status),
                    "laboratory_result": str(test.overall_result),
                },
            )
        return str(batch.status)

    def _apply_decision(
        self, user: User, test: LabTest, result: LabResult, previous_batch_status: str
    ) -> str | None:
        """Move the batch for a decision — and only through the lifecycle.

        Returns the status the batch ends up in, which the caller passes to the
        audit entry so the log records the outcome of the test rather than the
        state the batch happened to be in while the decision was being made.

        One rule does all the work here: **a decision is withdrawn before a
        different one is applied.** A batch that is APPROVED or REJECTED has only
        one legal move in the transition table — back to LAB_TESTING — so an
        override that changes the outcome goes through testing on the way, and a
        retest has already done the same thing by opening. Nothing in the platform
        jumps an approved batch straight to rejected or the reverse.
        """
        batch = test.batch
        if batch.status is BatchStatus.PACKAGING_READY:
            batch_lifecycle.advance(
                batch,
                BatchStatus.APPROVED,
                action=f"Withdrawing the release of {batch.batch_code}",
            )
            self.session.flush()
        if batch.status is BatchStatus.LAB_HOLD:
            # The hold has been answered — a value was corrected, a range was
            # configured — so the batch returns to the bench for this decision.
            batch_lifecycle.advance(
                batch,
                BatchStatus.LAB_TESTING,
                action=f"Lifting the hold on {batch.batch_code} for {test.test_code}",
            )
            self.session.flush()
        if batch.status in (BatchStatus.APPROVED, BatchStatus.REJECTED):
            withdrawn = str(batch.status)
            batch_lifecycle.advance(
                batch,
                BatchStatus.LAB_TESTING,
                action=f"Withdrawing the decision carried by {test.test_code}",
            )
            self.session.flush()
            self.audit.batch_status_changed(
                batch,
                actor=user,
                previous=withdrawn,
                new_stage=batch_lifecycle.STAGE_FOR_STATUS.get(batch.status, batch.current_stage),
            )
            previous_batch_status = str(batch.status)

        target = None
        if result is LabResult.PASS:
            target = BatchStatus.APPROVED
        elif result is LabResult.FAIL:
            target = BatchStatus.REJECTED
        if target is None:
            # INCONCLUSIVE decides nothing, and the batch must not pretend the work
            # is still going on: the technician has finished the evaluation, so the
            # batch moves to LAB_HOLD — waiting on a person to correct a
            # measurement, configure a range or open a further test. That is what
            # blocks packaging, and it is a state a reader can act on, unlike
            # LAB_TESTING, which suggests somebody is at the bench.
            logger.info(
                "Test inconclusive; the batch is held",
                extra={"test_code": test.test_code, "batch": batch.batch_code},
            )
            if batch.status is BatchStatus.LAB_TESTING:
                batch_lifecycle.advance(
                    batch,
                    BatchStatus.LAB_HOLD,
                    action=f"No decision was possible on {test.test_code}",
                )
                self.session.flush()
                self.audit.batch_status_changed(
                    batch,
                    actor=user,
                    previous=previous_batch_status,
                    new_stage=batch_lifecycle.STAGE_FOR_STATUS.get(
                        batch.status, batch.current_stage
                    ),
                )
            return str(batch.status)

        batch_lifecycle.advance(
            batch,
            target,
            action=f"Applying laboratory result for {test.test_code}",
        )
        self.session.flush()
        self.audit.batch_decided(
            batch,
            actor=user,
            decision=str(target),
            test=test,
            previous_status=previous_batch_status,
        )
        self.audit.batch_status_changed(
            batch,
            actor=user,
            previous=previous_batch_status,
            new_stage=batch_lifecycle.STAGE_FOR_STATUS.get(batch.status, batch.current_stage),
        )
        return str(batch.status)

    # ------------------------------------------------------------------ #
    # Analysis plumbing
    # ------------------------------------------------------------------ #
    def _prefill_development_measurements(self, test: LabTest) -> int:
        """Give a freshly opened test a starting value for every configured parameter.

        This is **development behaviour**, controlled by
        ``LAB_DEMO_MEASUREMENTS_ENABLED`` and off in production. Each pre-filled
        row is stored with ``measurement_source=DEMO`` and is labelled as a
        development value everywhere it is read, so it can never be mistaken for a
        reading somebody took. The catalogue's own method list supplies the method,
        and the value is evaluated against the configured range exactly as a typed
        one would be.

        A technician confirms or replaces each value; replacing one makes it
        ``MANUAL``. Nothing here is required for the workflow to run — with the
        setting off, the test opens empty and every value is entered by hand.
        """
        settings = get_settings()
        if not settings.LAB_DEMO_MEASUREMENTS_ENABLED:
            return 0

        created = 0
        for parameter in self.parameters.all_parameters(active_only=True):
            if parameter.development_value is None:
                continue
            if self.tests.result_for_parameter(test.id, parameter.code) is not None:
                continue
            method = None
            for option in parameter.methods or []:
                label = option.get("label") if isinstance(option, dict) else None
                if label:
                    method = label
                    break
            status = evaluate_parameter(
                value=parameter.development_value,
                reference_min=parameter.reference_min,
                reference_max=parameter.reference_max,
            )
            self.session.add(
                LabTestResult(
                    lab_test_id=test.id,
                    parameter_code=parameter.code,
                    parameter_name=parameter.name,
                    value=parameter.development_value,
                    unit=parameter.unit,
                    reference_min=parameter.reference_min,
                    reference_max=parameter.reference_max,
                    reference_source=parameter.reference_source,
                    status=status,
                    measurement_source=LabMeasurementSource.DEMO,
                    method=method,
                    measured_at=None,
                    recorded_by_id=None,
                    remarks=(
                        "Development value supplied by the platform for demonstration. "
                        "Confirm or replace it before completing the test."
                    ),
                )
            )
            created += 1
        if created:
            self.session.flush()
            logger.info(
                "Development measurements pre-filled",
                extra={"test_code": test.test_code, "count": created},
            )
        return created

    def _measurement_points(self, results: list[LabTestResult]) -> list[MeasurementPoint]:
        """The measured values, paired with the configuration they are judged by."""
        catalogue = {row.code: row for row in self.parameters.all_parameters()}
        points: list[MeasurementPoint] = []
        for row in results:
            parameter = catalogue.get(row.parameter_code)
            points.append(
                MeasurementPoint(
                    code=row.parameter_code,
                    name=row.parameter_name
                    or (parameter.name if parameter else row.parameter_code),
                    unit=_enum_value(row.unit) or "",
                    value=row.value,
                    # The range recorded *with the result* is the one it was judged
                    # against when it was taken, so a later configuration change
                    # cannot rewrite what a stored analysis concluded.
                    reference_min=row.reference_min,
                    reference_max=row.reference_max,
                    reference_source=row.reference_source,
                    is_required=bool(parameter.is_required) if parameter else False,
                    measurement_source=str(row.measurement_source),
                    method=row.method,
                )
            )
        return points

    def _analysis_for(
        self, test: LabTest, results: list[LabTestResult]
    ) -> tuple[LabQualityAnalysis, list[MeasurementPoint]]:
        points = self._measurement_points(results)
        return analyse_measurements(points), points

    def _store_analysis(
        self, user: User, test: LabTest, analysis: LabQualityAnalysis
    ) -> None:
        settings = get_settings()
        test.ai_analysis = analysis.as_dict()
        test.ai_status = analysis.overall_status
        test.ai_risk_level = analysis.risk_level
        # The identity travels with the result, exactly as the hive engine does it.
        test.ai_model = settings.LAB_QUALITY_MODEL or MODEL_NAME
        test.ai_model_version = settings.LAB_QUALITY_MODEL_VERSION or MODEL_VERSION
        test.ai_source = ANALYSIS_SOURCE
        test.ai_analysed_at = datetime.now(tz=timezone.utc)
        test.ai_analysed_by_id = user.id
        self.session.flush()

    def _ensure_analysis(
        self, user: User, test: LabTest, results: list[LabTestResult], *, payload=None
    ) -> LabQualityAnalysis:
        """The stored analysis, or a fresh one when the caller asked to run it again.

        Holding or overriding a flagged test needs an analysis to point at, so one
        is computed and stored when the test has none. It only reads the test's own
        measurements — nothing is invented to fill the gap.
        """
        if getattr(payload, "run_analysis", False) or not test.ai_analysis:
            analysis, _points = self._analysis_for(test, results)
            self._store_analysis(user, test, analysis)
            return analysis
        return LabQualityAnalysis.from_dict(test.ai_analysis)

    def _source_counts(self, results: list[LabTestResult]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in results:
            key = str(row.measurement_source)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _risk_override_available(self, test: LabTest) -> bool:
        settings = get_settings()
        if not settings.LAB_ALLOW_RISK_OVERRIDE:
            return False
        analysis = test.ai_analysis
        if not analysis:
            return False
        return risk_override_available(LabQualityAnalysis.from_dict(analysis), enabled=True)

    def _verdict_for(self, test: LabTest, results: list[LabTestResult]) -> Verdict:
        required = [row.code for row in self.parameters.required_parameters()]
        evaluated = [
            EvaluatedResult(
                parameter_code=row.parameter_code,
                parameter_name=row.parameter_name,
                value=row.value,
                unit=_enum_value(row.unit) or "",
                status=row.status,
                reference_min=row.reference_min,
                reference_max=row.reference_max,
                reference_source=row.reference_source,
                is_required=row.parameter_code in required,
            )
            for row in results
        ]
        return decide(evaluated, required)

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def list_tests(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: LabTestStatus | None = None,
        result_filter: LabResult | None = None,
        batch_id: uuid.UUID | None = None,
        laboratory_id: uuid.UUID | None = None,
        technician_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
        test_date_from: date | None = None,
        test_date_to: date | None = None,
    ) -> tuple[list[LabTestListItem], int]:
        scope = self._scope_filters(user)
        if cluster_id is not None:
            allowed = self.collections.officer_cluster_ids(user)
            if user.role == UserRole.KVIC_OFFICER and cluster_id not in allowed:
                return [], 0
            scope["cluster_id"] = cluster_id
        rows, total = self.tests.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            overall_result=result_filter,
            batch_id=batch_id,
            laboratory_id=laboratory_id,
            technician_id=technician_id,
            date_from=test_date_from,
            date_to=test_date_to,
            **scope,
        )
        return [self.to_list_item(row, user) for row in rows], total

    def get_test(self, user: User, test_id: uuid.UUID) -> LabTestDetail:
        test = self.tests.get_with_relations(test_id)
        if test is None:
            raise NotFoundError(
                f"Laboratory test {test_id} not found", details={"resource": "lab_test"}
            )
        self._assert_can_read_test(user, test)
        return self.to_detail(test, user)

    def tests_for_batch(self, user: User, batch_id: uuid.UUID) -> list[LabTestListItem]:
        """Every test of a batch, newest first — the full history, nothing overwritten."""
        batch = self.batches.get_with_relations(batch_id)
        if batch is None:
            raise NotFoundError(f"Batch {batch_id} not found", details={"resource": "batch"})
        self.collections.assert_record_scope(user, record=batch, resource="Batch", resource_id=batch_id)
        return [self.to_list_item(row, user) for row in self.tests.for_batch(batch_id)]

    def batches_awaiting_testing(
        self, user: User, *, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[dict], int]:
        """The laboratory worklist: batches at ``LAB_TESTING`` in the caller's scope."""
        scope = self._scope_filters(user)
        rows, total = self.batches.search(
            page=page,
            page_size=page_size,
            search=search,
            status=BatchStatus.LAB_TESTING,
            **scope,
        )
        worklist = []
        for batch in rows:
            open_test = self._open_test_for(batch)
            completed_run = self._completed_run_for(batch, required=False)
            worklist.append(
                {
                    "batch_id": batch.id,
                    "batch_code": batch.batch_code,
                    "status": str(batch.status),
                    "status_label": _label(batch.status),
                    "quantity": batch.quantity,
                    "unit": str(batch.unit),
                    "unit_label": _label(batch.unit),
                    "collection_id": batch.collection_id,
                    "collection_code": getattr(batch.collection, "collection_code", None),
                    "collection_date": batch.collection_date,
                    "beekeeper_id": batch.beekeeper_id,
                    "beekeeper_code": getattr(batch.beekeeper, "beekeeper_code", None),
                    "cluster_id": batch.cluster_id,
                    "cluster_code": getattr(batch.cluster, "cluster_code", None),
                    "processing_id": completed_run.id if completed_run else None,
                    "processing_code": completed_run.processing_code if completed_run else None,
                    "output_quantity": completed_run.output_quantity if completed_run else None,
                    "test_count": len(self.tests.for_batch(batch.id)),
                    "open_test_id": open_test.id if open_test else None,
                    "open_test_code": open_test.test_code if open_test else None,
                    "open_test_status": str(open_test.status) if open_test else None,
                }
            )
        return worklist, total

    def summary(self, user: User) -> LabTestSummary:
        scope = self._scope_filters(user)
        by_status, by_result = self.tests.count_by_status_and_result(**scope)
        sample_totals = self.tests.sample_totals(**scope)
        _rows, awaiting = self.batches.search(
            page=1, page_size=1, status=BatchStatus.LAB_TESTING, **scope
        )
        overridden = self.tests.count_overrides(**scope)
        queues = self.tests.count_by_assignment(**scope)
        mine = self.tests.search(
            page=1,
            page_size=1,
            assigned_technician_id=user.id,
            statuses=LabTestStatus.open_statuses(),
        )[1]
        mine_accepted = self.tests.search(
            page=1,
            page_size=1,
            assigned_technician_id=user.id,
            assignment_status=AssignmentStatus.ACCEPTED,
        )[1]
        return LabTestSummary(
            total=sum(by_status.values()),
            by_status=by_status,
            by_result=by_result,
            pending=by_status.get(LabTestStatus.PENDING.value, 0),
            in_progress=by_status.get(LabTestStatus.IN_PROGRESS.value, 0),
            completed=by_status.get(LabTestStatus.COMPLETED.value, 0),
            held=by_status.get(LabTestStatus.HOLD.value, 0),
            passed=by_result.get(LabResult.PASS.value, 0),
            failed=by_result.get(LabResult.FAIL.value, 0),
            inconclusive=by_result.get(LabResult.INCONCLUSIVE.value, 0),
            overridden=overridden,
            sample_totals={unit: float(value) for unit, value in sample_totals.items()},
            awaiting_testing=awaiting,
            unconfigured_parameters=sum(
                1
                for parameter in self.parameters.all_parameters(active_only=True)
                if parameter.reference_min is None and parameter.reference_max is None
            ),
            unassigned=queues["unassigned"],
            assigned=queues["assigned"],
            accepted=queues["accepted"],
            mine=mine,
            mine_accepted=mine_accepted,
            samples_recorded=queues["total"],
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _load_test(self, test_id: uuid.UUID) -> LabTest:
        test = self.tests.get_with_relations(test_id)
        if test is None:
            raise NotFoundError(
                f"Laboratory test {test_id} not found", details={"resource": "lab_test"}
            )
        return test

    def _assert_open(self, test: LabTest, *, action: str) -> None:
        if test.status is LabTestStatus.COMPLETED:
            raise ConflictError(
                f"Test {test.test_code} is completed, so {action} is not possible. A completed "
                "test is a statement about the honey: its measurements are read, never rewritten. "
                "Open a retest to examine the sample again.",
                details={
                    "test_code": test.test_code,
                    "status": str(test.status),
                    "protected_fields": list(IMMUTABLE_WHEN_COMPLETED),
                },
            )

    def _completed_run_for(self, batch: HoneyBatch, *, required: bool = True):
        """The completed processing run that produced the honey under test."""
        runs = self.runs.for_batch(batch.id)
        completed = [row for row in runs if row.status is ProcessingStatus.COMPLETED]
        if not completed:
            if not required:
                return None
            raise ConflictError(
                f"Batch {batch.batch_code} has no completed processing run, so there is nothing to "
                "test against.",
                details={"batch_code": batch.batch_code, "processing_runs": len(runs)},
            )
        return completed[0]

    def _open_test_for(self, batch: HoneyBatch) -> LabTest | None:
        for test in self.tests.for_batch(batch.id):
            if test.status in (LabTestStatus.PENDING, LabTestStatus.IN_PROGRESS):
                return test
        return None

    def _resolve_laboratory(self, laboratory_id: uuid.UUID) -> Laboratory:
        """Reuse the facility that exists; never create one on the caller's behalf."""
        laboratory = self.laboratories.get(laboratory_id)
        if laboratory is None:
            raise NotFoundError(
                f"Laboratory {laboratory_id} not found", details={"resource": "laboratory"}
            )
        if laboratory.status is not FacilityStatus.ACTIVE:
            raise ValidationError(
                f"Laboratory {laboratory.laboratory_code} is {laboratory.status} and cannot take "
                "new samples.",
                details={"laboratory_code": laboratory.laboratory_code, "status": str(laboratory.status)},
            )
        return laboratory

    def _resolve_parameter(self, code: str) -> LabParameter:
        parameter = self.parameters.get_by_code(code)
        if parameter is None:
            raise NotFoundError(
                f"Laboratory parameter {code} not found",
                details={"resource": "lab_parameter", "hint": "/api/v1/lab-parameters lists the catalogue"},
            )
        if not parameter.is_active:
            raise ValidationError(
                f"Laboratory parameter {code} is not active and cannot receive new measurements.",
                details={"parameter_code": code, "is_active": False},
            )
        return parameter

    def _next_test_code(self) -> str:
        scope = f"LAB_TEST:{datetime.now(tz=timezone.utc).strftime(_SEQUENCE_YEAR)}"
        return build_test_code(DocumentSequence.next_value(self.session, scope, width=6))

    def _next_sample_code(self) -> str:
        scope = f"LAB_SAMPLE:{datetime.now(tz=timezone.utc).strftime(_SEQUENCE_YEAR)}"
        return build_sample_code(DocumentSequence.next_value(self.session, scope, width=6))

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Laboratory assignment
    # ------------------------------------------------------------------ #
    def assign_test(self, user: User, test_id: uuid.UUID, payload) -> LabTestDetail:
        """Allocate an open test to a named laboratory technician.

        The rule mirrors the processor's: an administrator may allocate to any
        active technician, a technician may only take work on personally. The
        *sample* stays on the pending list while it is allocated but not accepted,
        so allocated work cannot hide unstarted work from the rest of the bench.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)

        test = self._load_test(test_id)
        self.collections.assert_record_scope(
            user, record=test.batch, resource="Laboratory test", resource_id=test.id
        )
        self._assert_assignable(test)

        if user.role is not UserRole.ADMIN and payload.technician_id != user.id:
            raise ForbiddenError(
                "A laboratory technician can only take work on personally; ask an "
                "administrator to allocate tests to other people.",
                details={"action": "assign_lab_test", "test": test.test_code},
            )
        technician = self._resolve_technician(payload.technician_id)

        already = (
            test.assigned_technician_id == technician.id
            and test.assignment_status is AssignmentStatus.ASSIGNED
        )
        test.assigned_technician = technician
        test.assigned_by = user
        test.assigned_at = datetime.now(tz=timezone.utc)
        test.assignment_status = AssignmentStatus.ASSIGNED
        test.accepted_at = None
        if already:
            self.session.commit()
            return self.to_detail(self._load_test(test_id), user)

        self.session.flush()
        self.audit.lab_test_assigned(test, actor=user, technician=technician, batch=test.batch)
        self.session.commit()
        return self.to_detail(self._load_test(test_id), user)

    def assign_batch(
        self, user: User, batch_id: uuid.UUID, payload
    ) -> LabTestDetail:
        """Allocate a batch's laboratory work, opening the test when there is none.

        An administrator should not have to know that a *test* is the unit of work:
        they hand the batch over, and this method opens the test through
        :meth:`create_test` so the batch rules stay in one place.
        """
        _assert_can_write(user, Permission.LAB_TEST_WRITE)

        batch = self.batches.get_with_relations(batch_id)
        if batch is None:
            raise NotFoundError(f"Batch {batch_id} not found", details={"resource": "batch"})
        self.collections.assert_record_scope(
            user, record=batch, resource="Batch", resource_id=batch_id
        )
        open_test = self._open_test_for(batch)
        if open_test is None:
            if batch.status is not BatchStatus.LAB_TESTING:
                raise ConflictError(
                    f"Batch {batch.batch_code} is "
                    f"{batch_lifecycle.STATUS_LABEL.get(batch.status, batch.status)} and has no "
                    "open laboratory test to allocate. Processing must be completed first.",
                    details={
                        "batch_code": batch.batch_code,
                        "batch_status": str(batch.status),
                        "required_status": str(BatchStatus.LAB_TESTING),
                    },
                )
            technician = self._resolve_technician(payload.technician_id)
            laboratory = self._default_laboratory()
            return self.create_test(
                user,
                LabTestCreate(
                    batch_id=batch.id,
                    laboratory_id=laboratory.id,
                    sample_quantity=self._sample_quantity_for(batch),
                    sample_unit=batch.unit,
                    remarks=payload.remarks,
                ),
                technician_id=technician.id,
            )
        return self.assign_test(
            user, open_test.id, LabTestAssign(technician_id=payload.technician_id, remarks=payload.remarks)
        )

    def accept_test(self, user: User, test_id: uuid.UUID) -> LabTestDetail:
        """The named technician takes the test on."""
        _assert_can_write(user, Permission.LAB_TEST_WRITE)

        test = self._load_test(test_id)
        self.collections.assert_record_scope(
            user, record=test.batch, resource="Laboratory test", resource_id=test.id
        )
        if test.assigned_technician_id is None:
            raise ConflictError(
                f"Laboratory test {test.test_code} has not been assigned to anyone yet.",
                details={"test_code": test.test_code},
            )
        if user.role is not UserRole.ADMIN and test.assigned_technician_id != user.id:
            raise ForbiddenError(
                f"Laboratory test {test.test_code} is assigned to another technician.",
                details={"test_code": test.test_code},
            )
        if test.assignment_status is AssignmentStatus.ACCEPTED:
            return self.to_detail(test, user)
        self._assert_open(test, action="accepting the test")

        test.assignment_status = AssignmentStatus.ACCEPTED
        test.accepted_at = datetime.now(tz=timezone.utc)
        self.session.flush()
        self.audit.lab_test_accepted(test, actor=user, batch=test.batch)
        self.session.commit()
        return self.to_detail(self._load_test(test_id), user)

    def _note_work_started(self, user: User, test: LabTest) -> None:
        """Picking up an unallocated sample allocates it; working on your own
        allocation accepts it.

        Both are one plain fact — a person is working on this sample — recorded
        here so the queues stay true without the technician pressing a separate
        button before touching the honey.
        """
        now = datetime.now(tz=timezone.utc)
        if test.assigned_technician_id is None:
            test.assigned_technician = user
            test.assigned_by = user
            test.assigned_at = now
            test.assignment_status = AssignmentStatus.ACCEPTED
            test.accepted_at = now
            self.session.flush()
            self.audit.lab_test_assigned(
                test, actor=user, technician=user, batch=test.batch
            )
            self.audit.lab_test_accepted(test, actor=user, batch=test.batch)
            return
        if (
            test.assigned_technician_id == user.id
            and test.assignment_status is AssignmentStatus.ASSIGNED
        ):
            test.assignment_status = AssignmentStatus.ACCEPTED
            test.accepted_at = now
            self.session.flush()
            self.audit.lab_test_accepted(test, actor=user, batch=test.batch)

    def _assert_may_work(self, user: User, test: LabTest, *, action: str) -> None:
        """Only the test's own technician (or an administrator) may work on it.

        The same rule as processing: unallocated work is anybody's, work that has
        been allocated belongs to the person it was allocated to. A colleague
        measuring somebody else's sample would make the allocation a label rather
        than a fact.
        """
        if user.role is UserRole.ADMIN:
            return
        if test.assigned_technician_id is None or test.assigned_technician_id == user.id:
            return
        raise ForbiddenError(
            f"Laboratory test {test.test_code} is assigned to another technician. "
            "Ask an administrator to re-allocate it.",
            details={
                "action": action,
                "test_code": test.test_code,
                "assigned_technician_id": str(test.assigned_technician_id),
            },
        )

    def _assert_assignable(self, test: LabTest) -> None:
        if test.status is LabTestStatus.COMPLETED:
            raise ConflictError(
                f"Laboratory test {test.test_code} is completed; assigning it would put "
                "decided work in somebody's queue.",
                details={"test_code": test.test_code, "status": str(test.status)},
            )

    def _resolve_technician(self, technician_id: uuid.UUID) -> User:
        """The named technician must exist, be active, and hold the laboratory role."""
        technician = self.users.get(technician_id)
        if technician is None:
            raise NotFoundError(
                f"User {technician_id} not found", details={"resource": "lab_technician"}
            )
        if technician.role is not UserRole.LAB_TECHNICIAN:
            raise ValidationError(
                "Laboratory work can only be allocated to an account with the "
                "laboratory technician role.",
                details={
                    "field": "technician_id",
                    "role": str(technician.role),
                    "expected_role": str(UserRole.LAB_TECHNICIAN),
                },
            )
        if not technician.is_active:
            raise ValidationError(
                "That laboratory technician account is not active.",
                details={"field": "technician_id", "is_active": False},
            )
        return technician

    def _default_laboratory(self) -> Laboratory:
        """The active laboratory a batch's sample is booked into when a caller
        allocates a batch without naming one — chosen by code so it is stable."""
        facilities = self.laboratories.active_facilities()
        if not facilities:
            raise ConflictError(
                "No active laboratory is registered, so no test can be opened. An "
                "administrator registers a laboratory first.",
                details={"resource": "laboratory"},
            )
        return facilities[0]

    @staticmethod
    def _sample_quantity_for(batch) -> Decimal:  # noqa: ANN001 - HoneyBatch
        """A sensible default sample size: 0.5 % of the batch, clamped to 0.25–2 kg."""
        try:
            quantity = Decimal(str(batch.quantity or 0))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            quantity = Decimal("0")
        sample = (quantity / Decimal("200")).quantize(Decimal("0.001"))
        return min(max(sample, Decimal("0.25")), Decimal("2"))

    # ------------------------------------------------------------------ #
    # Queues
    # ------------------------------------------------------------------ #
    def pending_tests(
        self, user: User, *, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[LabTestListItem], int]:
        """The shared queue: open tests that nobody has been made responsible for.

        Work allocated to a named technician lives in their assigned list instead —
        the two lists partition the bench, so a sample is in exactly one of them and
        never in neither. (Batches whose processing is complete but for which no
        sample has been booked in yet are a third kind of waiting work, and have
        their own list: ``GET /lab-tests/batches/awaiting-test``.)
        """
        _assert_can_read(user)
        scope = self._scope_filters(user)
        rows, total = self.tests.search(
            page=page,
            page_size=page_size,
            search=search,
            # A held test is waiting on a decision, not on laboratory work, so it
            # is listed in its own queue rather than in the work a technician can
            # pick up now.
            statuses=LabTestStatus.work_statuses(),
            assignment_status=AssignmentStatus.UNASSIGNED,
            **scope,
        )
        return [self.to_list_item(test, user) for test in rows], total

    def assigned_tests(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        mine_only: bool = False,
    ) -> tuple[list[LabTestListItem], int]:
        """Tests with a named technician, not yet completed."""
        _assert_can_read(user)
        scope = self._scope_filters(user)
        technician_id = user.id if (mine_only or user.role is UserRole.LAB_TECHNICIAN) else None
        rows, total = self.tests.search(
            page=page,
            page_size=page_size,
            search=search,
            statuses=LabTestStatus.work_statuses(),
            assigned_technician_id=technician_id,
            unassigned=False if technician_id is None else None,
            **scope,
        )
        return [self.to_list_item(test, user) for test in rows], total

    def completed_tests(
        self, user: User, *, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[LabTestListItem], int]:
        """Decided tests — the laboratory's own history, pass, fail or inconclusive."""
        _assert_can_read(user)
        scope = self._scope_filters(user)
        rows, total = self.tests.search(
            page=page,
            page_size=page_size,
            search=search,
            status=LabTestStatus.COMPLETED,
            **scope,
        )
        return [self.to_list_item(test, user) for test in rows], total

    def held_tests(
        self, user: User, *, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[LabTestListItem], int]:
        """Tests the laboratory has parked, with the reason and who parked them.

        This is not a dead end and it is not a queue of work: each row names what
        is missing, and the way forward is a further test against the same batch.
        """
        _assert_can_read(user)
        scope = self._scope_filters(user)
        rows, total = self.tests.search(
            page=page,
            page_size=page_size,
            search=search,
            status=LabTestStatus.HOLD,
            **scope,
        )
        return [self.to_list_item(test, user) for test in rows], total

    def unassigned_batches(
        self, user: User, *, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[dict], int]:
        """Batches at ``LAB_TESTING`` with no test opened against them yet."""
        _assert_can_read(user)
        scope = self._scope_filters(user)
        rows, total = self.batches.search(
            page=page, page_size=page_size, search=search, status=BatchStatus.LAB_TESTING, **scope
        )
        worklist = []
        for batch in rows:
            if self._open_test_for(batch) is not None:
                continue
            run = self._completed_run_for(batch, required=False)
            worklist.append(
                {
                    "batch_id": batch.id,
                    "batch_code": batch.batch_code,
                    "status": str(batch.status),
                    "status_label": _label(batch.status),
                    "quantity": batch.quantity,
                    "unit": str(batch.unit),
                    "unit_label": _label(batch.unit),
                    "collection_code": getattr(batch.collection, "collection_code", None),
                    "collection_date": batch.collection_date,
                    "beekeeper_id": batch.beekeeper_id,
                    "beekeeper_code": getattr(batch.beekeeper, "beekeeper_code", None),
                    "beekeeper_name": beekeeper_name(batch.beekeeper),
                    "cluster_id": batch.cluster_id,
                    "cluster_code": getattr(batch.cluster, "cluster_code", None),
                    "cluster_name": cluster_name(batch.cluster),
                    "processing_id": run.id if run else None,
                    "processing_code": run.processing_code if run else None,
                    "processing_type_label": _label(run.processing_type) if run else None,
                    "input_quantity": run.input_quantity if run else None,
                    "output_quantity": run.output_quantity if run else None,
                    "completion_time": run.completion_time if run else None,
                    "awaiting_test": True,
                }
            )
        return worklist, len(worklist)

    def to_list_item(self, test: LabTest, user: User | None = None) -> LabTestListItem:
        results = list(getattr(test, "results", []) or [])
        batch = test.batch
        technician = test.technician
        may_write = user is not None and has_permission(user.role, Permission.LAB_TEST_WRITE)
        may_override = user is not None and has_permission(user.role, Permission.LAB_TEST_OVERRIDE)
        open_test = test.status in (LabTestStatus.PENDING, LabTestStatus.IN_PROGRESS)
        return LabTestListItem(
            id=test.id,
            test_code=test.test_code,
            sample_code=test.sample_code,
            status=test.status,
            status_label=_label(test.status),
            overall_result=test.overall_result,
            overall_result_label=_label(test.overall_result),
            result_summary=test.result_summary,
            is_override=bool(test.is_override),
            round_number=int(test.round_number or 1),
            retest_of_id=test.retest_of_id,
            batch_id=test.batch_id,
            batch_code=batch.batch_code,
            collection_code=getattr(batch.collection, "collection_code", None),
            processing_id=test.processing_id,
            processing_code=getattr(test.processing, "processing_code", ""),
            laboratory_id=test.laboratory_id,
            laboratory_code=getattr(test.laboratory, "laboratory_code", None),
            laboratory_name=getattr(test.laboratory, "name", None),
            technician_id=test.technician_id,
            technician_name=person_name(technician),
            assigned_technician_id=test.assigned_technician_id,
            assigned_technician_name=person_name(test.assigned_technician),
            assigned_by_id=test.assigned_by_id,
            assigned_by_name=person_name(test.assigned_by),
            assigned_at=test.assigned_at,
            accepted_at=test.accepted_at,
            assignment_status=test.assignment_status,
            assignment_status_label=test.assignment_status.label,
            sample_quantity=test.sample_quantity,
            sample_unit=test.sample_unit,
            sample_unit_label=_label(test.sample_unit),
            test_date=test.test_date,
            completed_at=test.completed_at,
            cluster_id=batch.cluster_id,
            cluster_code=getattr(batch.cluster, "cluster_code", None),
            beekeeper_code=getattr(batch.beekeeper, "beekeeper_code", None),
            created_at=test.created_at,
            parameter_count=len(results),
            passed_count=sum(1 for row in results if row.status is LabParameterStatus.PASS),
            failed_count=sum(1 for row in results if row.status is LabParameterStatus.FAIL),
            unevaluated_count=sum(
                1 for row in results if row.status is LabParameterStatus.NOT_EVALUATED
            ),
            can_record_results=(
                may_write and open_test and self._may_work(user, test)
            ),
            can_complete=may_write and open_test and self._may_work(user, test),
            can_override=may_override and test.status is LabTestStatus.COMPLETED,
            can_hold=may_write and open_test and self._may_work(user, test),
            can_proceed_with_risk=(
                may_write
                and open_test
                and self._may_work(user, test)
                and self._risk_override_available(test)
            ),
            can_analyse=(
                may_write and open_test and self._may_work(user, test) and bool(results)
            ),
            can_assign=may_write and test.status is not LabTestStatus.COMPLETED,
            can_accept=(
                may_write
                and test.assigned_technician_id is not None
                and test.assignment_status is AssignmentStatus.ASSIGNED
                and test.status is not LabTestStatus.COMPLETED
                and user is not None
                and (user.role is UserRole.ADMIN or test.assigned_technician_id == user.id)
            ),
            can_work=user is not None and self._may_work(user, test),
            ai_status=test.ai_status,
            ai_risk_level=test.ai_risk_level,
            on_hold=test.status is LabTestStatus.HOLD,
            hold_reason=test.hold_reason,
            released_with_risk=bool(test.risk_override),
        )

    @staticmethod
    def _may_work(user: User | None, test: LabTest) -> bool:
        """Whether this caller is the person the test belongs to.

        An unallocated sample is anyone's to pick up — that is what keeps the bench
        moving — but work allocated to a colleague is not silently workable by
        whoever is signed in.
        """
        if user is None:
            return False
        if user.role is UserRole.ADMIN:
            return True
        if test.assigned_technician_id is None:
            return True
        return test.assigned_technician_id == user.id

    def to_detail(self, test: LabTest, user: User | None = None) -> LabTestDetail:
        item = self.to_list_item(test, user)
        results = list(getattr(test, "results", []) or [])
        required = [row.code for row in self.parameters.required_parameters()]
        verdict = self._verdict_for(test, results) if results else None
        # The list row already carries the analysis summary, so the detail is built
        # *on* it and only adds what the row does not have — passing the same keys
        # twice would be a duplicate-keyword error rather than a merge.
        fields = item.model_dump()
        fields.update(
            ai_analysis=test.ai_analysis,
            ai_status=test.ai_status,
            ai_risk_level=test.ai_risk_level,
            ai_model=test.ai_model,
            ai_model_version=test.ai_model_version,
            ai_source=test.ai_source,
            ai_analysed_at=test.ai_analysed_at,
            ai_analysed_by=person_name(test.ai_analysed_by),
            risk_override=test.risk_override,
            hold_reason=test.hold_reason,
            held_at=test.held_at,
            held_by=person_name(test.held_by),
        )
        return LabTestDetail(
            **fields,
            batch=self._batch_ref(test.batch),
            processing=self._processing_ref(test.processing),
            results=[self.to_result_read(row) for row in results],
            required_parameters=required,
            missing_required_parameters=list(verdict.missing_required) if verdict else required,
            evaluation_notes=list(verdict.reasons) if verdict else [
                "No measurements recorded yet — nothing to evaluate."
            ],
            sample_collected_at=test.sample_collected_at,
            sample_notes=test.sample_notes,
            remarks=test.remarks,
            override_reason=test.override_reason,
            decided_by_id=test.decided_by_id,
            decided_by_name=person_name(test.decided_by),
            traceability=self.traceability(test),
            updated_at=test.updated_at,
            next_step=self._next_step(test),
            risk_override_available=self._risk_override_available(test),
            demo_measurements_enabled=get_settings().LAB_DEMO_MEASUREMENTS_ENABLED,
            risk_override_enabled=get_settings().LAB_ALLOW_RISK_OVERRIDE,
            confirmation_word=get_settings().LAB_RISK_OVERRIDE_CONFIRMATION,
        )

    def to_result_read(self, result: LabTestResult) -> LabResultRead:
        return LabResultRead(
            id=result.id,
            parameter_code=result.parameter_code,
            parameter_name=result.parameter_name,
            value=result.value,
            unit=result.unit,
            unit_label=_label(result.unit),
            status=result.status,
            status_label=_label(result.status),
            evaluated=result.status is not LabParameterStatus.NOT_EVALUATED,
            measurement_source=result.measurement_source,
            measurement_source_label=LabMeasurementSource(result.measurement_source).label,
            is_development_value=result.measurement_source is LabMeasurementSource.DEMO,
            reference_min=result.reference_min,
            reference_max=result.reference_max,
            reference_source=result.reference_source,
            method=result.method,
            remarks=result.remarks,
            measured_at=result.measured_at,
            recorded_by_id=result.recorded_by_id,
            recorded_by_name=getattr(result.recorded_by, "full_name", None),
            created_at=result.created_at,
            updated_at=result.updated_at,
        )

    @staticmethod
    def _batch_ref(batch: HoneyBatch) -> LabTestBatchRef:
        collection = batch.collection
        beekeeper = batch.beekeeper
        cluster = batch.cluster
        return LabTestBatchRef(
            id=batch.id,
            batch_code=batch.batch_code,
            status=str(batch.status),
            status_label=_label(batch.status),
            quantity=batch.quantity,
            unit=str(batch.unit),
            unit_label=_label(batch.unit),
            collection_id=batch.collection_id,
            collection_code=getattr(collection, "collection_code", None),
            collection_date=batch.collection_date,
            beekeeper_id=batch.beekeeper_id,
            beekeeper_code=getattr(beekeeper, "beekeeper_code", None),
            beekeeper_name=beekeeper_name(beekeeper),
            cluster_id=batch.cluster_id,
            cluster_code=getattr(cluster, "cluster_code", None),
            cluster_name=cluster_name(cluster),
        )

    @staticmethod
    def _processing_ref(run) -> LabTestProcessingRef:
        return LabTestProcessingRef(
            id=run.id,
            processing_code=run.processing_code,
            status=str(run.status),
            status_label=_label(run.status),
            processing_type=str(run.processing_type),
            processing_type_label=_label(run.processing_type),
            input_quantity=run.input_quantity,
            output_quantity=run.output_quantity,
            loss_quantity=run.loss_quantity,
            unit=str(run.unit),
            unit_label=_label(run.unit),
            processing_date=run.processing_date,
            completion_time=run.completion_time,
            operator_name=getattr(run.operator, "full_name", None),
            processing_unit_name=getattr(run.unit_ref, "name", None),
        )

    def _open_packaging_run(self, batch):
        """The batch's packaging run that is still being worked, if any."""
        from sqlalchemy import select

        from app.models.enums import PackagingStatus
        from app.models.packaging import PackagingRun

        return self.session.execute(
            select(PackagingRun)
            .where(
                PackagingRun.batch_id == batch.id,
                PackagingRun.status.in_((PackagingStatus.PENDING, PackagingStatus.IN_PROGRESS)),
            )
            .limit(1)
        ).scalars().first()

    def traceability(self, test: LabTest) -> list[TraceabilityNode]:
        """The chain from the sample back to the apiary, assembled from the records.

        Test → Batch → Processing run → Collection → Hive(s) → Beekeeper → Cluster.
        Every node carries the identifier of the real record and a relative path to
        it, so a reader can walk the chain themselves instead of trusting a
        summary. Nothing here is stored on the test: adding a hive to the
        collection tomorrow cannot make an old test's chain wrong, because there is
        no second copy to fall out of date.
        """
        batch = test.batch
        collection = batch.collection
        run = test.processing
        nodes: list[TraceabilityNode] = [
            TraceabilityNode(
                kind="LAB_TEST",
                label="Laboratory test",
                identifier=test.test_code,
                detail=(
                    f"{_label(test.status)} — {_label(test.overall_result)}"
                    + (" (outcome set by hand)" if test.is_override else "")
                ),
                recorded_at=test.test_date,
                href=f"/api/v1/lab-tests/{test.id}",
            ),
            TraceabilityNode(
                kind="SAMPLE",
                label="Sample",
                identifier=test.sample_code,
                detail=f"{test.sample_quantity} {_label(test.sample_unit)} taken for testing",
                recorded_at=test.sample_collected_at,
                href=f"/api/v1/lab-tests/{test.id}",
            ),
            TraceabilityNode(
                kind="BATCH",
                label="Honey batch",
                identifier=batch.batch_code,
                detail=(
                    f"{batch.quantity} {_label(batch.unit)} — {_label(batch.status)}"
                ),
                recorded_at=batch.created_at,
                href=f"/api/v1/batches/{batch.id}",
            ),
        ]
        if run is not None:
            nodes.append(
                TraceabilityNode(
                    kind="PROCESSING",
                    label="Processing run",
                    identifier=run.processing_code,
                    detail=(
                        f"{_label(run.processing_type)}: {run.input_quantity} → "
                        f"{run.output_quantity} {_label(run.unit)}"
                    ),
                    recorded_at=run.completion_time or run.created_at,
                    href=f"/api/v1/processing/{run.id}",
                )
            )
        if collection is not None:
            nodes.append(
                TraceabilityNode(
                    kind="COLLECTION",
                    label="Honey collection",
                    identifier=getattr(collection, "collection_code", str(batch.collection_id)),
                    detail=(
                        f"Harvest of {collection.total_quantity} {_label(collection.unit)} "
                        f"on {collection.collection_date.isoformat()}"
                    ),
                    recorded_at=collection.collection_date,
                    href=f"/api/v1/collections/{collection.id}",
                )
            )
            # Each contributing hive, with the quantity it gave — reported in the
            # collection's unit, because the contribution row records the amount
            # and the harvest records the unit it is counted in.
            for source in list(getattr(collection, "sources", []) or []):
                nodes.append(
                    TraceabilityNode(
                        kind="HIVE",
                        label="Source hive",
                        identifier=source.hive_code,
                        detail=f"{source.quantity} {_label(collection.unit)} contributed",
                        recorded_at=collection.collection_date,
                        href=f"/api/v1/hives/{source.hive_id}",
                    )
                )
        beekeeper = batch.beekeeper
        if beekeeper is not None:
            nodes.append(
                TraceabilityNode(
                    kind="BEEKEEPER",
                    label="Beekeeper",
                    identifier=getattr(beekeeper, "beekeeper_code", str(batch.beekeeper_id)),
                    detail=getattr(beekeeper, "full_name", None) or getattr(beekeeper, "name", None),
                    href=f"/api/v1/beekeepers/{beekeeper.id}",
                )
            )
        cluster = batch.cluster
        if cluster is not None:
            nodes.append(
                TraceabilityNode(
                    kind="CLUSTER",
                    label="KVIC cluster",
                    identifier=getattr(cluster, "cluster_code", str(batch.cluster_id)),
                    detail=getattr(cluster, "name", None),
                    href=f"/api/v1/clusters/{cluster.id}",
                )
            )
        nodes.append(
            TraceabilityNode(
                kind="LABORATORY",
                label="Laboratory",
                identifier=getattr(test.laboratory, "laboratory_code", str(test.laboratory_id)),
                detail=getattr(test.laboratory, "name", None),
                href=f"/api/v1/laboratories/{test.laboratory_id}",
            )
        )
        return nodes

    @staticmethod
    def _next_step(test: LabTest) -> str | None:
        if test.status is LabTestStatus.HOLD:
            return (
                "This test is on hold and the batch cannot be packed. Open a further test when "
                "the missing information exists — the measurements recorded here stay as they are."
            )
        if test.status is LabTestStatus.COMPLETED:
            if test.risk_override:
                return "The batch was released to packaging with a recorded risk."
            if test.overall_result is LabResult.PASS:
                return "The batch is approved and has been offered to packaging."
            if test.overall_result is LabResult.FAIL:
                return "The batch is rejected and cannot be packed."
            return (
                "No decision was possible, so the batch is held for review. Open a further test "
                "once the outstanding values or ranges exist."
            )
        if test.status is LabTestStatus.PENDING:
            return (
                "Record the measured values. Nothing is judged until the test is completed, and "
                "nothing is judged at all for a parameter with no configured range."
            )
        if test.status is LabTestStatus.IN_PROGRESS:
            return (
                "Complete the test when the measurements are in. The outcome is computed from what "
                "was recorded."
            )
        if test.overall_result is LabResult.PASS:
            return "The batch is APPROVED. Later phases will take it from here."
        if test.overall_result is LabResult.FAIL:
            return (
                "The batch is REJECTED and cannot proceed. A retest may be opened to examine the "
                "sample again; the records of both tests are kept."
            )
        return (
            "No decision was possible: some measurement is missing, or nothing is configured to "
            "compare it against. Record the outstanding values or configure the parameter, then "
            "open a further test — the records of this one stay as they are."
        )

    def batch_status_for_test(self, test: LabTest) -> BatchStatus | None:
        """Which status a completed test's outcome implies, for callers that ask."""
        results = self.tests.results_for_test(test.id)
        verdict = self._verdict_for(test, results)
        from app.services.quality_rules import batch_status_for

        return batch_status_for(verdict)


def _assert_can_read(user: User) -> None:
    """Defence in depth for the read-only queue endpoints."""
    if not has_permission(user.role, Permission.LAB_TEST_READ):
        raise ForbiddenError(
            "Your role does not permit this action",
            details={
                "required_permission": str(Permission.LAB_TEST_READ),
                "your_role": str(user.role),
            },
        )


def _assert_can_write(user: User, permission: Permission) -> None:
    """Defence in depth: the route declares the permission, the service re-checks it."""
    if not has_permission(user.role, permission):
        raise ForbiddenError(
            "Your role does not permit this action",
            details={"required_permission": str(permission), "your_role": str(user.role)},
        )


__all__ = [
    "IMMUTABLE_WHEN_COMPLETED",
    "LaboratoryService",
    "build_laboratory_code",
    "build_sample_code",
    "build_test_code",
]

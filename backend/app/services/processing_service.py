"""Processing: the work between a stored harvest and a laboratory sample.

What this service is responsible for
------------------------------------
A batch of honey leaves the apiary as ``COLLECTED``. Something happens to it — it
is filtered, decanted, warmed, blended — and the platform has to be able to say
what happened, to how much honey, and what was left at the end. That record is a
:class:`~app.models.processing.HoneyProcessing` run, and this service is the only
thing that writes one.

The rules that are enforced here rather than described
------------------------------------------------------
* **The quantities are measured, never inferred.** A run starts with no input and
  no output figure. Nothing in this file fills them in from the batch's weight or
  from the previous run: an unmeasured quantity stays ``NULL`` and the run cannot
  be completed until a person records one. Where the collection recorded 13.7 kg
  and the run records 12.9 kg out, the difference of 0.8 kg is shown as the
  difference — not as a loss the platform decided on.
* **A batch is in one place at a time.** Starting a run moves ``COLLECTED`` →
  ``PROCESSING`` through :mod:`app.services.batch_lifecycle`, so the transition is
  checked against the one table of permitted moves. Two runs cannot be open on the
  same batch: the service refuses, and a partial unique index in PostgreSQL
  refuses even if the service is bypassed.
* **Completion closes the record.** Once a run is ``COMPLETED`` its batch, input,
  output, operator and dates stop being writable, and an attempt answers 409 with
  the fields named — not a silent no-op.
* **A completed run hands the batch to the laboratory.** ``PROCESSING`` →
  ``LAB_TESTING`` happens here and nowhere else. Nothing in this phase can move a
  batch past ``LAB_TESTING``; the packaging stages are not reachable from this
  code because they are not in the transition table.
* **The batch is never copied.** A run points at ``batch_id``; the batch's weight,
  collection and beekeeper are read through that pointer every time they are
  reported, so the two can never disagree.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

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
    BatchStatus,
    CollectionUnit,
    FacilityStatus,
    ProcessingStatus,
    ProcessingType,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.processing import HoneyProcessing, ProcessingUnit
from app.models.user import User
from app.repositories.batch_repository import BatchRepository
from app.repositories.processing_repository import ProcessingRepository, ProcessingUnitRepository
from app.repositories.user_repository import UserRepository
from app.schemas.processing import (
    EligibleProcessor,
    ProcessingAssign,
    ProcessingBatchAssign,
    ProcessingBatchRef,
    ProcessingCreate,
    ProcessingDetail,
    ProcessingListItem,
    ProcessingSummary,
    ProcessingUnitRead,
)
from app.services import batch_lifecycle
from app.schemas.common import display_choice
from app.services.audit_service import AuditService
from app.services.blockchain import BlockchainService
from app.services.collection_service import CollectionService
from app.services.names import beekeeper_name, cluster_name, person_name

logger = logging.getLogger(__name__)


def display_processing_type(run) -> str:
    """What to print for a run's type: its listed name, or the recorded operation."""
    return display_choice(run.processing_type, getattr(run, "processing_type_other", None))

_SEQUENCE_YEAR = "%Y"

#: Fields a completed run must not lose. Named individually so the refusal can
#: tell the caller exactly what is protected instead of "cannot edit".
IMMUTABLE_WHEN_COMPLETED = (
    "batch_id",
    "input_quantity",
    "output_quantity",
    "loss_quantity",
    "processing_unit_id",
    "operator_id",
    "start_time",
    "completion_time",
)

#: Fields a cancellation does not reopen. A cancelled run is a record of something
#: that did not happen; it is kept, not deleted, and cannot be resumed — a fresh
#: run is opened instead, which is what keeps the history honest.
_IMMUTABLE_WHEN_CANCELLED = IMMUTABLE_WHEN_COMPLETED + ("status",)


def build_processing_code(sequence: str, *, when: datetime | None = None) -> str:
    """``HC-PROC-<YYYY>-<NNNNNN>``, e.g. ``HC-PROC-2026-000001``."""
    year = (when or datetime.now(tz=timezone.utc)).year
    return f"HC-PROC-{year}-{sequence}"


def build_processing_unit_code(sequence: str) -> str:
    """``HC-PU-<NNNNNN>`` — a facility, not a document, so no year segment."""
    return f"HC-PU-{sequence}"


def _enum_value(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


def _label(enum_value) -> str:
    return getattr(enum_value, "label", None) or _enum_value(enum_value) or "Unknown"


def _money(value: Decimal | None) -> str:
    return "not recorded" if value is None else str(value)


class ProcessingService:
    """Open, run, correct, complete and cancel processing runs."""

    def __init__(self, session) -> None:  # noqa: ANN001 - Session from the dependency
        self.session = session
        self.runs = ProcessingRepository(session)
        self.units = ProcessingUnitRepository(session)
        self.batches = BatchRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)
        # Traceability events are recorded through this service, in the same
        # transaction as the record change (import at module level, below).
        self.blockchain = BlockchainService(session)
        # Scope resolution is shared with collections and batches, so a KVIC
        # officer's view of processing is filtered by exactly the same cluster
        # rule as their view of the harvest it came from.
        self.collections = CollectionService(session)

    # ------------------------------------------------------------------ #
    # Scope
    # ------------------------------------------------------------------ #
    def _scope_filters(self, user: User) -> dict:
        """Read scope for a processing listing.

        A beekeeper reads the runs on their own honey; a KVIC officer reads the
        runs of the batches whose **stored cluster** is one of theirs — the same
        snapshot Phase 5 already shows on the cluster screen, so the listing and
        the single-record check agree rather than applying two different rules;
        the operational roles read the shared work queue; an administrator reads
        everything.

        An officer with no clusters in scope gets ``cluster_ids=[]``, which
        matches nothing — a filter that is empty rather than absent.
        """
        if user.role == UserRole.BEEKEEPER:
            return {"beekeeper_id": self.collections.own_beekeeper(user).id}
        if user.role == UserRole.KVIC_OFFICER:
            # The officer's cluster scope, plus the runs whose batch names no cluster
            # — the rows that need attention rather than rows to hide.
            return {
                "cluster_ids": self.collections.officer_cluster_ids(user),
                "include_unclustered": True,
            }
        return self.collections.workflow_scope_filters(user)

    def _assert_can_read_run(self, user: User, run: HoneyProcessing) -> None:
        batch = getattr(run, "batch", None)
        if batch is not None:
            self.collections.assert_record_scope(
                user, record=batch, resource="Processing run", resource_id=run.id
            )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def list_runs(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: ProcessingStatus | None = None,
        statuses: list[ProcessingStatus] | None = None,
        batch_id: uuid.UUID | None = None,
        processing_unit_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
        processing_date_from: date | None = None,
        processing_date_to: date | None = None,
    ) -> tuple[list[ProcessingListItem], int]:
        scope = self._scope_filters(user)
        if cluster_id is not None:
            allowed = self.collections.officer_cluster_ids(user)
            if user.role == UserRole.KVIC_OFFICER and cluster_id not in allowed:
                return [], 0
            scope["cluster_id"] = cluster_id
        rows, total = self.runs.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            statuses=statuses,
            batch_id=batch_id,
            processing_unit_id=processing_unit_id,
            date_from=processing_date_from,
            date_to=processing_date_to,
            **scope,
        )
        # The caller is passed through: the per-row flags ("may I start this?") are
        # computed from their permission and their identity, and a list that drops
        # the caller renders every action as unavailable — a queue nobody can work.
        return [self.to_list_item(row, user) for row in rows], total

    def get_run(self, user: User, run_id: uuid.UUID) -> ProcessingDetail:
        run = self.runs.get_with_relations(run_id)
        if run is None:
            raise NotFoundError(f"Processing run {run_id} not found", details={"resource": "processing"})
        self._assert_can_read_run(user, run)
        return self.to_detail(run, user)

    def runs_for_batch(self, user: User, batch_id: uuid.UUID) -> list[ProcessingListItem]:
        """Every run of a batch, newest first — nothing is hidden or overwritten."""
        batch = self.batches.get_with_relations(batch_id)
        if batch is None:
            raise NotFoundError(f"Batch {batch_id} not found", details={"resource": "batch"})
        self.collections.assert_record_scope(user, record=batch, resource="Batch", resource_id=batch_id)
        return [self.to_list_item(row, user) for row in self.runs.for_batch(batch_id)]

    def batches_awaiting_processing(
        self, user: User, *, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[dict], int]:
        """The worklist: batches at ``COLLECTED`` in the caller's scope.

        Returned in the batch's own vocabulary because that is what the screen is
        about — these are harvests waiting for the next step, not runs.
        """
        scope = self._scope_filters(user)
        rows, total = self.batches.search(
            page=page,
            page_size=page_size,
            search=search,
            status=BatchStatus.COLLECTED,
            **scope,
        )
        return [self._worklist_row(batch) for batch in rows], total

    def _worklist_row(self, batch: HoneyBatch) -> dict:
        open_run = self.runs.open_for_batch(batch.id)
        return {
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
            "source_hive_count": batch.source_hive_count,
            "beekeeper_id": batch.beekeeper_id,
            "beekeeper_code": getattr(batch.beekeeper, "beekeeper_code", None),
            "cluster_id": batch.cluster_id,
            "cluster_code": getattr(batch.cluster, "cluster_code", None),
            "beekeeper_name": beekeeper_name(batch.beekeeper),
            "cluster_name": cluster_name(batch.cluster),
            "open_processing_id": open_run.id if open_run else None,
            "open_processing_code": open_run.processing_code if open_run else None,
            "open_processing_status": str(open_run.status) if open_run else None,
            "open_processing_status_label": _label(open_run.status) if open_run else None,
            "open_processing_type_label": _label(open_run.processing_type) if open_run else None,
            "assignment_status": str(open_run.assignment_status) if open_run else None,
            "assignment_status_label": open_run.assignment_status.label if open_run else None,
            "processor_id": open_run.processor_id if open_run else None,
            "processor_name": person_name(open_run.processor) if open_run else None,
            "assigned_at": open_run.assigned_at if open_run else None,
            "processing_unit_name": getattr(open_run.unit_ref, "name", None) if open_run else None,
        }

    def summary(self, user: User) -> ProcessingSummary:
        scope = self._scope_filters(user)
        counts = self.runs.count_by_status(**scope)
        totals = self.runs.totals(**scope)
        _awaiting_rows, awaiting = self.batches.search(
            page=1, page_size=1, status=BatchStatus.COLLECTED, **scope
        )
        _lab_rows, in_lab = self.batches.search(
            page=1, page_size=1, status=BatchStatus.LAB_TESTING, **scope
        )
        queues = self.runs.count_by_assignment(**scope)
        mine = self.runs.search(
            page=1, page_size=1, processor_id=user.id, statuses=ProcessingStatus.open_statuses()
        )[1]
        mine_accepted = self.runs.search(
            page=1,
            page_size=1,
            processor_id=user.id,
            assignment_status=AssignmentStatus.ACCEPTED,
        )[1]
        return ProcessingSummary(
            total=sum(counts.values()),
            by_status=counts,
            pending=counts.get(ProcessingStatus.PENDING.value, 0),
            in_progress=counts.get(ProcessingStatus.IN_PROGRESS.value, 0),
            completed=counts.get(ProcessingStatus.COMPLETED.value, 0),
            cancelled=counts.get(ProcessingStatus.CANCELLED.value, 0),
            by_unit=totals,
            awaiting_processing=awaiting,
            awaiting_laboratory=in_lab,
            unassigned=queues["unassigned"],
            assigned=queues["assigned"],
            accepted=queues["accepted"],
            mine=mine,
            mine_accepted=mine_accepted,
        )

    # ------------------------------------------------------------------ #
    # Processing units
    # ------------------------------------------------------------------ #
    def create_unit(self, user: User, payload) -> ProcessingUnitRead:
        code = build_processing_unit_code(
            DocumentSequence.next_value(self.session, "PROCESSING_UNIT", width=6)
        )
        operator_id = payload.operator_user_id
        unit = ProcessingUnit(
            unit_code=code,
            name=payload.name.strip(),
            registration_identifier=payload.registration_identifier,
            location=payload.location,
            district=payload.district,
            state=payload.state,
            contact_email=payload.contact_email,
            contact_phone=payload.contact_phone,
            operator_user_id=operator_id,
            capacity_kg_per_day=payload.capacity_kg_per_day,
            status=FacilityStatus.ACTIVE,
            notes=payload.notes,
        )
        self.session.add(unit)
        try:
            self.session.flush()
        except IntegrityError as exc:  # pragma: no cover - the code is issued by us
            raise ConflictError("A processing unit with this code already exists") from exc
        self.audit.processing_unit_created(unit, actor=user)
        self.session.commit()
        return self.to_unit_read(unit)

    def list_units(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: FacilityStatus | None = None,
        district: str | None = None,
    ) -> tuple[list[ProcessingUnitRead], int]:
        rows, total = self.units.search(
            page=page,
            page_size=page_size,
            search=search,
            status=_enum_value(status_filter),
            district=district,
        )
        return [self.to_unit_read(row) for row in rows], total

    def update_unit(self, user: User, unit_id: uuid.UUID, payload) -> ProcessingUnitRead:
        unit = self.units.get(unit_id)
        if unit is None:
            raise NotFoundError(
                f"Processing unit {unit_id} not found", details={"resource": "processing_unit"}
            )
        changes = []
        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            current = getattr(unit, field)
            if current == value:
                continue
            changes.append({"field": field, "from": _enum_value(current), "to": _enum_value(value)})
            setattr(unit, field, value)
        if not changes:
            return self.to_unit_read(unit)
        self.session.flush()
        self.audit.processing_unit_updated(unit, actor=user, fields=[c["field"] for c in changes])
        self.session.commit()
        return self.to_unit_read(unit)

    def to_unit_read(self, unit: ProcessingUnit) -> ProcessingUnitRead:
        runs, total = self.runs.search(page=1, page_size=1, processing_unit_id=unit.id)
        del runs
        return ProcessingUnitRead(
            id=unit.id,
            unit_code=unit.unit_code,
            name=unit.name,
            registration_identifier=unit.registration_identifier,
            location=unit.location,
            district=unit.district,
            state=unit.state,
            contact_email=unit.contact_email,
            contact_phone=unit.contact_phone,
            operator_user_id=unit.operator_user_id,
            operator_name=getattr(getattr(unit, "operator", None), "full_name", None),
            status=unit.status,
            status_label=_label(unit.status),
            capacity_kg_per_day=unit.capacity_kg_per_day,
            is_demo=bool(unit.is_demo),
            notes=unit.notes,
            processing_run_count=total,
            created_at=unit.created_at,
            updated_at=unit.updated_at,
        )

    # ------------------------------------------------------------------ #
    # Runs — the workflow
    # ------------------------------------------------------------------ #
    def eligible_processors(self, user: User) -> list[EligibleProcessor]:
        """The accounts processing work may be allocated to, read from the database.

        Only active accounts holding the processor role, and only for a caller who
        may allocate at all — an administrator, or a processor allocating to
        themselves (which the API allows and the dialog offers as "take it on").

        Nothing here is a hardcoded list of names: create a processor in
        Administration → Users and they appear; switch their account off and they
        do not. The open-work count is carried alongside so the person allocating
        can see who is already carrying something.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)
        people = self.users.active_by_role(UserRole.PROCESSOR)
        if user.role is not UserRole.ADMIN:
            # A processor allocates to themselves and to nobody else, so that is
            # the only name they are shown.
            people = [person for person in people if person.id == user.id]
        workload = self.runs.open_counts_by_processor()
        return [
            EligibleProcessor(
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

    def create_run(self, user: User, payload) -> ProcessingDetail:
        """Open a run against a ``COLLECTED`` batch.

        Opening is deliberately *not* starting: the batch stays ``COLLECTED`` and
        the honey has not moved. Requirement 5's sequence is honoured by the two
        separate steps, and a run that is opened and then abandoned leaves the
        batch exactly where it was.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)

        batch = self._load_batch_for_run(user, payload.batch_id)

        if batch.status is not BatchStatus.COLLECTED:
            raise ConflictError(
                f"Batch {batch.batch_code} cannot be processed: it is "
                f"{batch_lifecycle.STATUS_LABEL.get(batch.status, batch.status)}. "
                "Only a COLLECTED batch can start processing.",
                details={
                    "batch_code": batch.batch_code,
                    "batch_status": str(batch.status),
                    "allowed_batch_status": str(BatchStatus.COLLECTED),
                },
            )

        existing = self.runs.open_for_batch(batch.id)
        if existing is not None:
            raise ConflictError(
                f"Batch {batch.batch_code} already has an open processing run "
                f"({existing.processing_code}, {existing.status}). Complete or cancel it first.",
                details={
                    "batch_code": batch.batch_code,
                    "open_processing_code": existing.processing_code,
                    "open_processing_status": str(existing.status),
                },
            )

        unit = self._resolve_unit(user, payload.processing_unit_id)

        run = HoneyProcessing(
            processing_code=self._next_code(),
            batch_id=batch.id,
            processing_unit_id=unit.id if unit else None,
            operator_id=user.id,
            processing_type=payload.processing_type,
            # Kept only when the operation is recorded as "Other"; the schema has
            # already refused a description attached to a listed type.
            processing_type_other=payload.processing_type_other,
            status=ProcessingStatus.PENDING,
            # The unit is the batch's own unit: honey does not change unit because
            # it was filtered.
            unit=batch.unit,
            processing_date=payload.processing_date or date.today(),
            notes=payload.notes,
        )
        self.session.add(run)
        try:
            self.session.flush()
        except IntegrityError as exc:  # pragma: no cover - guarded above and in the DB
            raise ConflictError(
                "A processing run is already open for this batch",
                details={"batch_code": batch.batch_code},
            ) from exc
        self.audit.processing_created(run, actor=user, batch=batch)
        self.session.commit()
        logger.info(
            "Processing run opened",
            extra={"processing_code": run.processing_code, "batch": batch.batch_code},
        )
        return self.to_detail(run, user)

    # ------------------------------------------------------------------ #
    # Batch assignment
    # ------------------------------------------------------------------ #
    def assign_run(self, user: User, run_id: uuid.UUID, payload) -> ProcessingDetail:
        """Allocate a run to a named processor.

        An administrator may allocate any run in their scope to any active
        processor. A processor may only take work on themselves — the facility is
        for picking work up, not for pushing it onto colleagues. Either way the
        *named processor* is a user id the backend validates against the database:
        the caller cannot become a processor by sending a role, and a lab
        technician cannot be allocated processing work.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)

        run = self._load_run(run_id)
        batch = run.batch
        self.collections.assert_record_scope(
            user, record=batch, resource="Processing run", resource_id=run.id
        )
        self._assert_assignable(user, run)

        if user.role is not UserRole.ADMIN and payload.processor_id != user.id:
            raise ForbiddenError(
                "A processor can only take work on personally; ask an administrator "
                "to allocate runs to other people.",
                details={"action": "assign_processing", "run": run.processing_code},
            )
        processor = self._resolve_processor(payload.processor_id)

        changed = (
            run.processor_id != processor.id
            or run.assignment_status is not AssignmentStatus.ASSIGNED
        )
        run.processor = processor
        run.assigned_by = user
        run.assigned_at = datetime.now(tz=timezone.utc)
        run.assignment_status = AssignmentStatus.ASSIGNED
        run.accepted_at = None
        if not changed:
            # Allocating the same person twice is not an error, but it is also not a
            # second event: the record would otherwise gain a duplicate audit line.
            self.session.commit()
            return self.to_detail(self._load_run(run_id), user)

        self.session.flush()
        self.audit.processing_assigned(run, actor=user, processor=processor, batch=batch)
        self.session.commit()
        return self.to_detail(self._load_run(run_id), user)

    def assign_batch(
        self, user: User, batch_id: uuid.UUID, payload
    ) -> ProcessingDetail:
        """Allocate a *batch* — opening the run first when there is none.

        This is the administrator's screen: the batch is the thing being handed
        over, and requiring them to open a run before allocating it would leave the
        batch invisible to the processor in the meantime. The run is created by
        :meth:`create_run`, so the batch rules (must be ``COLLECTED``, one open run)
        are enforced in exactly one place.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)

        batch = self._load_batch_for_run(user, batch_id)
        run = self.runs.open_for_batch(batch.id)
        if run is None:
            if batch.status is not BatchStatus.COLLECTED:
                raise ConflictError(
                    f"Batch {batch.batch_code} is "
                    f"{batch_lifecycle.STATUS_LABEL.get(batch.status, batch.status)} and has "
                    "no open processing run to allocate.",
                    details={
                        "batch_code": batch.batch_code,
                        "batch_status": str(batch.status),
                    },
                )
            detail = self.create_run(
                user,
                ProcessingCreate(
                    batch_id=batch.id,
                    processing_type=payload.processing_type or ProcessingType.FILTERING,
                    notes=payload.notes,
                ),
            )
            run_id = detail.id
        else:
            run_id = run.id

        return self.assign_run(
            user, run_id, ProcessingAssign(processor_id=payload.processor_id, notes=payload.notes)
        )

    def accept_run(self, user: User, run_id: uuid.UUID) -> ProcessingDetail:
        """The named processor takes the work on.

        Allocation says who *should* do it; acceptance says who *is* doing it, and
        the difference is recorded rather than assumed. Only the named processor (or
        an administrator acting for them) may accept.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)

        run = self._load_run(run_id)
        self.collections.assert_record_scope(
            user, record=run.batch, resource="Processing run", resource_id=run.id
        )
        if run.processor_id is None:
            raise ConflictError(
                f"Processing run {run.processing_code} has not been assigned to anyone yet.",
                details={"processing_code": run.processing_code},
            )
        if user.role is not UserRole.ADMIN and run.processor_id != user.id:
            raise ForbiddenError(
                f"Processing run {run.processing_code} is assigned to another processor.",
                details={"processing_code": run.processing_code},
            )
        if run.assignment_status is AssignmentStatus.ACCEPTED:
            return self.to_detail(run, user)
        if not run.status.is_open:
            raise ConflictError(
                f"Processing run {run.processing_code} is {run.status.label} and cannot be accepted.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )

        run.assignment_status = AssignmentStatus.ACCEPTED
        run.accepted_at = datetime.now(tz=timezone.utc)
        self.session.flush()
        self.audit.processing_accepted(run, actor=user, batch=run.batch)
        self.session.commit()
        return self.to_detail(self._load_run(run_id), user)

    def _assert_assignable(self, user: User, run: HoneyProcessing) -> None:
        """Refuse to allocate work that is already finished or cancelled."""
        if run.status is ProcessingStatus.COMPLETED:
            raise ConflictError(
                f"Processing run {run.processing_code} is completed; assigning it "
                "would put finished work in somebody's queue.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )
        if run.status is ProcessingStatus.CANCELLED:
            raise ConflictError(
                f"Processing run {run.processing_code} was cancelled and cannot be assigned.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )

    def _resolve_processor(self, processor_id: uuid.UUID) -> User:
        """The named processor must exist, be active, and actually be a processor."""
        processor = self.users.get(processor_id)
        if processor is None:
            raise NotFoundError(
                f"User {processor_id} not found", details={"resource": "processor"}
            )
        if processor.role is not UserRole.PROCESSOR:
            raise ValidationError(
                "Work can only be allocated to an account with the processor role.",
                details={
                    "field": "processor_id",
                    "role": str(processor.role),
                    "expected_role": str(UserRole.PROCESSOR),
                },
            )
        if not processor.is_active:
            raise ValidationError(
                "That processor account is not active.",
                details={"field": "processor_id", "is_active": False},
            )
        return processor

    # ------------------------------------------------------------------ #
    # Queues
    # ------------------------------------------------------------------ #
    def pending_assignments(
        self, user: User, *, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[ProcessingListItem], int]:
        """Runs nobody is responsible for yet: the shared pending queue.

        They stay here until an administrator allocates them — an unallocated run is
        visible work, not lost work.
        """
        _assert_can_read(user)
        scope = self._scope_filters(user)
        rows, total = self.runs.search(
            page=page,
            page_size=page_size,
            search=search,
            statuses=ProcessingStatus.open_statuses(),
            unassigned=True,
            **scope,
        )
        return [self.to_list_item(run, user) for run in rows], total

    def assigned_queue(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        mine_only: bool = False,
    ) -> tuple[list[ProcessingListItem], int]:
        """Runs allocated to a named processor and not yet completed."""
        _assert_can_read(user)
        scope = self._scope_filters(user)
        processor_id = user.id if (mine_only or user.role is UserRole.PROCESSOR) else None
        rows, total = self.runs.search(
            page=page,
            page_size=page_size,
            search=search,
            statuses=ProcessingStatus.open_statuses(),
            processor_id=processor_id,
            unassigned=False if processor_id is None else None,
            **scope,
        )
        return [self.to_list_item(run, user) for run in rows], total

    def completed_queue(
        self, user: User, *, page: int = 1, page_size: int = 20, search: str | None = None
    ) -> tuple[list[ProcessingListItem], int]:
        """Finished runs — the honey has left processing for the laboratory."""
        _assert_can_read(user)
        scope = self._scope_filters(user)
        rows, total = self.runs.search(
            page=page,
            page_size=page_size,
            search=search,
            status=ProcessingStatus.COMPLETED,
            **scope,
        )
        return [self.to_list_item(run, user) for run in rows], total

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _assert_may_work(self, user: User, run: HoneyProcessing, *, action: str) -> None:
        """Only the run's own processor (or an administrator) may work on it.

        Unallocated work stays open to any processor — that is what keeps the shared
        queue moving — but once somebody has been made responsible, a colleague
        cannot quietly take the run over. The batch's beekeeper and the cluster
        officer read the same row and write none of it.
        """
        if user.role is UserRole.ADMIN:
            return
        if run.processor_id is None or run.processor_id == user.id:
            return
        raise ForbiddenError(
            f"Processing run {run.processing_code} is assigned to another processor. "
            "Ask an administrator to re-allocate it.",
            details={
                "action": action,
                "processing_code": run.processing_code,
                "assigned_processor_id": str(run.processor_id),
            },
        )

    def start_run(self, user: User, run_id: uuid.UUID) -> ProcessingDetail:
        """Begin work: the run becomes ``IN_PROGRESS`` and the batch ``PROCESSING``.

        This is the only place a batch enters ``PROCESSING``, and it does not do so
        by assignment — :func:`batch_lifecycle.advance` checks the move against the
        transition table, so an impossible move is refused here rather than stored.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)

        run = self._load_run(run_id)
        batch = run.batch
        self.collections.assert_record_scope(user, record=batch, resource="Processing run", resource_id=run.id)
        self._assert_may_work(user, run, action="starting processing")

        if run.status is ProcessingStatus.COMPLETED:
            raise ConflictError(
                f"Processing run {run.processing_code} is already completed and cannot be restarted.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )
        if run.status is ProcessingStatus.CANCELLED:
            raise ConflictError(
                f"Processing run {run.processing_code} was cancelled. Open a new run instead of "
                "resuming a cancelled one, so the history stays truthful.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )
        if run.status is ProcessingStatus.IN_PROGRESS:
            raise ConflictError(
                f"Processing run {run.processing_code} has already been started.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )

        previous_batch_status = str(batch.status)
        batch_lifecycle.advance(
            batch,
            BatchStatus.PROCESSING,
            action=f"Starting processing run {run.processing_code}",
        )
        # Starting a run that is allocated to you is acceptance in the plainest
        # sense — you are doing it — so the record says so rather than leaving the
        # allocation looking untouched.
        accepted = False
        if run.processor_id == user.id and run.assignment_status is AssignmentStatus.ASSIGNED:
            run.assignment_status = AssignmentStatus.ACCEPTED
            run.accepted_at = datetime.now(tz=timezone.utc)
            accepted = True

        run.status = ProcessingStatus.IN_PROGRESS
        run.start_time = run.start_time or datetime.now(tz=timezone.utc)
        self.session.flush()

        if accepted:
            self.audit.processing_accepted(run, actor=user, batch=batch)

        self.audit.processing_started(
            run, actor=user, batch=batch, previous_batch_status=previous_batch_status
        )
        self._audit_batch_move(batch, previous_batch_status, user)
        self.blockchain.processing_started(run, actor=user)
        self.session.commit()
        # Re-read so the response is built from committed state, not from an
        # object still holding a pending transaction's identity map.
        return self.to_detail(self._load_run(run_id), user)

    def update_run(self, user: User, run_id: uuid.UUID, payload) -> ProcessingDetail:
        """Record or correct the run's details while it is open.

        Completed runs are closed to changes of substance (requirement 8). The
        refusal names the protected fields and points at the auditable path, so a
        caller is never left guessing why nothing happened.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)

        run = self._load_run(run_id)
        self.collections.assert_record_scope(
            user, record=run.batch, resource="Processing run", resource_id=run.id
        )
        self._assert_may_work(user, run, action="editing processing")
        if run.status in (ProcessingStatus.COMPLETED, ProcessingStatus.CANCELLED):
            protected = (
                IMMUTABLE_WHEN_COMPLETED
                if run.status is ProcessingStatus.COMPLETED
                else _IMMUTABLE_WHEN_CANCELLED
            )
            raise ConflictError(
                f"Processing run {run.processing_code} is {run.status} and can no longer be edited. "
                "Recorded quantities are part of the batch's history; a correction is made by "
                "opening a new run, which keeps both records.",
                details={
                    "processing_code": run.processing_code,
                    "status": str(run.status),
                    "protected_fields": list(protected),
                },
            )

        data = payload.model_dump(exclude_unset=True)
        if not data:
            return self.to_detail(run, user)

        unit_id = data.pop("processing_unit_id", None) if "processing_unit_id" in data else None
        if "processing_unit_id" in payload.model_fields_set:
            unit = self._resolve_unit(user, unit_id)
            data["processing_unit_id"] = unit.id if unit else None

        # The type and its description move together. Changing the type to a listed
        # operation drops a description that no longer applies, and choosing "Other"
        # requires one — so an edit cannot leave the pair disagreeing.
        if "processing_type" in data or "processing_type_other" in data:
            resulting_type = data.get("processing_type", run.processing_type)
            resulting_other = data.get("processing_type_other", run.processing_type_other)
            if str(resulting_type) == ProcessingType.OTHER.value:
                if not resulting_other:
                    raise ValidationError(
                        "Describe the operation: with the type set to Other, the record has "
                        "to say what the other operation was.",
                        details={"processing_code": run.processing_code, "field": "processing_type_other"},
                    )
            else:
                resulting_other = None
            data["processing_type"] = resulting_type
            data["processing_type_other"] = resulting_other

        # The comparison below is done on the values the record will hold, so a
        # partial update can never leave output above input.
        candidate_input = data.get("input_quantity", run.input_quantity)
        candidate_output = data.get("output_quantity", run.output_quantity)
        if (
            candidate_input is not None
            and candidate_output is not None
            and candidate_output > candidate_input
        ):
            raise ValidationError(
                "The output quantity cannot exceed the input quantity.",
                details={
                    "input_quantity": str(candidate_input),
                    "output_quantity": str(candidate_output),
                    "difference": str(candidate_output - candidate_input),
                },
            )
        self._assert_times_ordered(
            data.get("start_time", run.start_time),
            data.get("completion_time", run.completion_time),
        )

        changes = []
        for field, value in data.items():
            current = getattr(run, field)
            if current == value:
                continue
            changes.append(
                {"field": field, "from": _enum_value(current), "to": _enum_value(value)}
            )
            setattr(run, field, value)

        if not changes:
            return self.to_detail(run, user)

        self._recompute_loss(run)
        self.session.flush()
        self.audit.processing_updated(run, actor=user, changed=changes)
        self.session.commit()
        return self.to_detail(self._load_run(run_id), user)

    def complete_run(self, user: User, run_id: uuid.UUID, payload) -> ProcessingDetail:
        """Close the run and hand the batch to the laboratory.

        Three things are refused here, each with its own reason: completing twice,
        completing without both measured quantities, and completing when the batch
        is not actually in ``PROCESSING``.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)

        run = self._load_run(run_id)
        batch = run.batch
        self.collections.assert_record_scope(user, record=batch, resource="Processing run", resource_id=run.id)
        self._assert_may_work(user, run, action="completing processing")

        if run.status is ProcessingStatus.COMPLETED:
            raise ConflictError(
                f"Processing run {run.processing_code} is already completed "
                f"({run.output_quantity} {_label(run.unit)} recorded at completion).",
                details={
                    "processing_code": run.processing_code,
                    "status": str(run.status),
                    "completion_time": run.completion_time.isoformat()
                    if run.completion_time
                    else None,
                },
            )
        if run.status is ProcessingStatus.CANCELLED:
            raise ConflictError(
                f"Processing run {run.processing_code} was cancelled and cannot be completed.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )
        if run.status is not ProcessingStatus.IN_PROGRESS:
            raise ConflictError(
                f"Processing run {run.processing_code} has not been started. Start it before "
                "completing it, so the run has a real start time and the batch a real status.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )

        data = payload.model_dump(exclude_unset=True)
        input_quantity = data.get("input_quantity", run.input_quantity)
        output_quantity = data.get("output_quantity", run.output_quantity)

        if input_quantity is None or output_quantity is None:
            missing = [
                name
                for name, value in (("input_quantity", input_quantity), ("output_quantity", output_quantity))
                if value is None
            ]
            raise ValidationError(
                "Both quantities must be recorded before the run can be completed: the input the "
                "run started with and the output it produced.",
                details={"missing_fields": missing, "processing_code": run.processing_code},
            )
        if output_quantity > input_quantity:
            raise ValidationError(
                "The output quantity cannot exceed the input quantity.",
                details={
                    "input_quantity": str(input_quantity),
                    "output_quantity": str(output_quantity),
                    "difference": str(output_quantity - input_quantity),
                },
            )

        completion_time = data.get("completion_time") or datetime.now(tz=timezone.utc)
        if run.start_time is not None and completion_time < run.start_time:
            raise ValidationError(
                "The completion time cannot be earlier than the start time.",
                details={
                    "start_time": run.start_time.isoformat(),
                    "completion_time": completion_time.isoformat(),
                },
            )

        changes = []
        for field, value in (
            ("input_quantity", input_quantity),
            ("output_quantity", output_quantity),
            ("completion_time", completion_time),
        ):
            if getattr(run, field) != value:
                changes.append(
                    {"field": field, "from": _enum_value(getattr(run, field)), "to": _enum_value(value)}
                )
            setattr(run, field, value)
        if data.get("notes") is not None:
            run.notes = data["notes"]

        run.status = ProcessingStatus.COMPLETED
        self._recompute_loss(run)

        previous_batch_status = str(batch.status)
        batch_lifecycle.advance(
            batch,
            BatchStatus.LAB_TESTING,
            action=f"Completing processing run {run.processing_code}",
        )
        self.session.flush()

        if changes:
            self.audit.processing_updated(run, actor=user, changed=changes)
        self.audit.processing_completed(
            run, actor=user, batch=batch, previous_batch_status=previous_batch_status
        )
        self._audit_batch_move(batch, previous_batch_status, user)
        # Recorded as its own event as well, because "the completed run really did
        # put this batch in the laboratory queue" is the hand-off the whole
        # processor → laboratory workflow turns on.
        self.audit.batch_moved_to_lab_testing(
            run, actor=user, batch=batch, previous_batch_status=previous_batch_status
        )
        self.blockchain.processing_completed(run, actor=user)
        self.session.commit()
        logger.info(
            "Processing completed",
            extra={
                "processing_code": run.processing_code,
                "input": str(run.input_quantity),
                "output": str(run.output_quantity),
            },
        )
        return self.to_detail(self._load_run(run_id), user)

    def cancel_run(self, user: User, run_id: uuid.UUID, payload) -> ProcessingDetail:
        """Abandon a run that did not happen, keeping the record of it.

        If the honey had already been marked as being processed, the batch returns
        to ``COLLECTED`` — a move the transition table permits precisely for this
        case — so the batch's state never claims work that was stopped.
        """
        _assert_can_write(user, Permission.PROCESSING_WRITE)

        run = self._load_run(run_id)
        batch = run.batch
        self.collections.assert_record_scope(user, record=batch, resource="Processing run", resource_id=run.id)

        if run.status is ProcessingStatus.COMPLETED:
            raise ConflictError(
                f"Processing run {run.processing_code} is completed; completed work is not "
                "cancelled, because the honey it produced exists.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )
        if run.status is ProcessingStatus.CANCELLED:
            raise ConflictError(
                f"Processing run {run.processing_code} has already been cancelled.",
                details={"processing_code": run.processing_code, "status": str(run.status)},
            )

        previous_batch_status = str(batch.status)
        previous_run_status = str(run.status)
        run.status = ProcessingStatus.CANCELLED
        run.cancellation_reason = payload.reason.strip()
        run.cancelled_at = datetime.now(tz=timezone.utc)

        if batch.status is BatchStatus.PROCESSING:
            batch_lifecycle.advance(
                batch,
                BatchStatus.COLLECTED,
                action=f"Cancelling processing run {run.processing_code}",
            )
        self.session.flush()

        self.audit.processing_cancelled(
            run,
            actor=user,
            reason=payload.reason.strip(),
            batch=batch,
            previous_batch_status=previous_batch_status,
            previous_run_status=previous_run_status,
        )
        if previous_batch_status != str(batch.status):
            self._audit_batch_move(batch, previous_batch_status, user)
        self.session.commit()
        return self.to_detail(self._load_run(run_id), user)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _load_run(self, run_id: uuid.UUID) -> HoneyProcessing:
        run = self.runs.get_with_relations(run_id)
        if run is None:
            raise NotFoundError(
                f"Processing run {run_id} not found", details={"resource": "processing"}
            )
        return run

    def _load_batch_for_run(self, user: User, batch_id: uuid.UUID) -> HoneyBatch:
        batch = self.batches.get_with_relations(batch_id)
        if batch is None:
            raise NotFoundError(f"Batch {batch_id} not found", details={"resource": "batch"})
        self.collections.assert_record_scope(user, record=batch, resource="Batch", resource_id=batch_id)
        return batch

    def _resolve_unit(
        self, user: User, unit_id: uuid.UUID | None
    ) -> ProcessingUnit | None:
        """Reuse the unit that exists; never invent one silently."""
        if unit_id is None:
            return None
        unit = self.units.get(unit_id)
        if unit is None:
            raise NotFoundError(
                f"Processing unit {unit_id} not found", details={"resource": "processing_unit"}
            )
        if unit.status is not FacilityStatus.ACTIVE:
            raise ValidationError(
                f"Processing unit {unit.unit_code} is {unit.status} and cannot take new work.",
                details={"unit_code": unit.unit_code, "status": str(unit.status)},
            )
        return unit

    def _next_code(self) -> str:
        scope = f"PROCESSING:{datetime.now(tz=timezone.utc).strftime(_SEQUENCE_YEAR)}"
        return build_processing_code(DocumentSequence.next_value(self.session, scope, width=6))

    @staticmethod
    def _assert_times_ordered(start, completion) -> None:
        if start is not None and completion is not None and completion < start:
            raise ValidationError(
                "The completion time cannot be earlier than the start time.",
                details={"start_time": start.isoformat(), "completion_time": completion.isoformat()},
            )

    @staticmethod
    def _recompute_loss(run: HoneyProcessing) -> None:
        """Store the difference the record already implies — nothing more.

        ``loss_quantity`` is derived from the two measured figures, so the screen
        that shows "13.7 → 12.9 = 0.8 kg" is reading a stored, queryable value
        rather than a number the interface computed for itself. If either figure is
        unknown, so is the difference.
        """
        if run.input_quantity is None or run.output_quantity is None:
            run.loss_quantity = None
            return
        run.loss_quantity = run.input_quantity - run.output_quantity

    def _audit_batch_move(self, batch: HoneyBatch, previous_status: str, actor: User) -> None:
        if previous_status == str(batch.status):
            return
        self.audit.batch_status_changed(
            batch,
            actor=actor,
            previous=previous_status,
            new_stage=batch_lifecycle.STAGE_FOR_STATUS.get(batch.status, batch.current_stage),
        )

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #
    def to_list_item(self, run: HoneyProcessing, user: User | None = None) -> ProcessingListItem:
        """One run in list shape, including what this caller may do to it.

        The flags are computed from the *permission*, not from the status alone, so
        a beekeeper looking at their own honey is told the truth: the run is
        theirs to see and not theirs to change.
        """
        batch = run.batch
        unit = run.unit_ref
        may_write = user is not None and has_permission(user.role, Permission.PROCESSING_WRITE)
        open_run = run.status in (ProcessingStatus.PENDING, ProcessingStatus.IN_PROGRESS)
        return ProcessingListItem(
            id=run.id,
            processing_code=run.processing_code,
            status=run.status,
            status_label=_label(run.status),
            processing_type=run.processing_type,
            processing_type_label=_label(run.processing_type),
            processing_type_other=run.processing_type_other,
            processing_type_display=display_processing_type(run),
            batch_id=run.batch_id,
            batch_code=batch.batch_code,
            collection_code=getattr(batch.collection, "collection_code", None),
            processing_unit_id=run.processing_unit_id,
            processing_unit_code=getattr(unit, "unit_code", None),
            processing_unit_name=getattr(unit, "name", None),
            operator_id=run.operator_id,
            operator_name=person_name(run.operator),
            input_quantity=run.input_quantity,
            output_quantity=run.output_quantity,
            loss_quantity=run.loss_quantity,
            loss_percent=_loss_percent(run),
            unit=run.unit,
            unit_label=_label(run.unit),
            processing_date=run.processing_date,
            start_time=run.start_time,
            completion_time=run.completion_time,
            cluster_id=batch.cluster_id,
            cluster_code=getattr(batch.cluster, "cluster_code", None),
            beekeeper_code=getattr(batch.beekeeper, "beekeeper_code", None),
            created_at=run.created_at,
            processor_id=run.processor_id,
            processor_name=person_name(run.processor),
            assigned_by_id=run.assigned_by_id,
            assigned_by_name=person_name(run.assigned_by),
            assigned_at=run.assigned_at,
            accepted_at=run.accepted_at,
            assignment_status=run.assignment_status,
            assignment_status_label=run.assignment_status.label,
            can_edit=may_write and open_run,
            can_start=(
                may_write
                and run.status is ProcessingStatus.PENDING
                and self._may_work(user, run)
            ),
            can_complete=(
                may_write
                and run.status is ProcessingStatus.IN_PROGRESS
                and self._may_work(user, run)
            ),
            can_cancel=may_write and open_run,
            can_assign=may_write and open_run,
            can_accept=(
                may_write
                and open_run
                and run.processor_id is not None
                and run.assignment_status is AssignmentStatus.ASSIGNED
                and (user is not None and (user.role is UserRole.ADMIN or run.processor_id == user.id))
            ),
            can_work=user is not None and self._may_work(user, run),
        )

    @staticmethod
    def _may_work(user: User | None, run: HoneyProcessing) -> bool:
        """Whether this caller is the person the run belongs to.

        Work allocated to somebody else is not silently workable by whoever is
        signed in: a processor who is not the assignee is refused until an
        administrator re-allocates it. Unallocated work is everybody's, which is
        what keeps the shared queue moving.
        """
        if user is None:
            return False
        if user.role is UserRole.ADMIN:
            return True
        if run.processor_id is None:
            return True
        return run.processor_id == user.id

    def to_detail(self, run: HoneyProcessing, user: User | None = None) -> ProcessingDetail:
        item = self.to_list_item(run, user)
        batch = run.batch
        return ProcessingDetail(
            **item.model_dump(),
            batch=self._batch_ref(batch),
            notes=run.notes,
            cancellation_reason=run.cancellation_reason,
            cancelled_at=run.cancelled_at,
            updated_at=run.updated_at,
            batch_status=str(batch.status),
            batch_status_label=_label(batch.status),
            next_step=self._next_step(run),
        )

    @staticmethod
    def _batch_ref(batch: HoneyBatch) -> ProcessingBatchRef:
        collection = batch.collection
        return ProcessingBatchRef(
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
            beekeeper_code=getattr(batch.beekeeper, "beekeeper_code", None),
            cluster_id=batch.cluster_id,
            cluster_code=getattr(batch.cluster, "cluster_code", None),
        )

    @staticmethod
    def _next_step(run: HoneyProcessing) -> str | None:
        """What the workflow expects next, said plainly and only when it is true."""
        if run.status is ProcessingStatus.PENDING:
            return "Start the run when the honey is actually being processed."
        if run.status is ProcessingStatus.IN_PROGRESS:
            if run.input_quantity is None or run.output_quantity is None:
                return (
                    "Record the input and output quantities, then complete the run — the batch "
                    "then becomes ready for laboratory testing."
                )
            return "Complete the run to send the batch to the laboratory."
        if run.status is ProcessingStatus.COMPLETED:
            return (
                "The batch is ready for laboratory testing. A laboratory technician opens a test "
                "against this run."
            )
        if run.status is ProcessingStatus.CANCELLED:
            return "This run did not happen. Open a new run if the honey is to be processed."
        return None


def _loss_percent(run: HoneyProcessing) -> float | None:
    """The difference as a percentage of input, or None when either is unknown."""
    if run.input_quantity in (None, 0) or run.output_quantity is None:
        return None
    return round(float(run.loss_quantity or 0) / float(run.input_quantity) * 100, 2)


def _assert_can_read(user: User) -> None:
    """Defence in depth for the read-only queue endpoints."""
    if not has_permission(user.role, Permission.PROCESSING_READ):
        raise ForbiddenError(
            "Your role does not permit this action",
            details={
                "required_permission": str(Permission.PROCESSING_READ),
                "your_role": str(user.role),
            },
        )


def _assert_can_write(user: User, permission: Permission) -> None:
    """Defence in depth: the route already requires the permission.

    A service is the last place a business rule can be enforced, so the
    capability is checked again here. If a future route forgets its dependency,
    the write still does not happen.
    """
    if not has_permission(user.role, permission):
        raise ForbiddenError(
            "Your role does not permit this action",
            details={"required_permission": str(permission), "your_role": str(user.role)},
        )


__all__ = [
    "IMMUTABLE_WHEN_COMPLETED",
    "ProcessingService",
    "build_processing_code",
    "build_processing_unit_code",
]

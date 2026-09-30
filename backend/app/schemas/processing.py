"""Request and response models for processing units and processing runs.

Two shapes are deliberately absent from every request model: ``processing_code``
and ``status``. The code is issued by the platform, and the status is a
consequence of the operations the endpoints perform — a caller starts a run, it
does not declare one started. ``extra="forbid"`` means an attempt to send either
is a 422 rather than a silently ignored field.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.common import check_other_pair
from app.models.enums import (
    AssignmentStatus,
    CollectionUnit,
    FacilityStatus,
    ProcessingStatus,
    ProcessingType,
)

#: A processing run cannot take in more honey than a batch holds, and a batch is
#: bounded at 20 000 kg by the collection rules — this is a mistyped-figure guard,
#: not a business limit.
MAX_PROCESSING_QUANTITY = Decimal("20000")


class ProcessingUnitCreate(BaseModel):
    """``POST /api/v1/processing-units``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    registration_identifier: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=200)
    district: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=20)
    operator_user_id: uuid.UUID | None = None
    capacity_kg_per_day: Decimal | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)


class ProcessingUnitUpdate(BaseModel):
    """``PATCH /api/v1/processing-units/{id}`` — every field optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    registration_identifier: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=200)
    district: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=20)
    operator_user_id: uuid.UUID | None = None
    capacity_kg_per_day: Decimal | None = Field(default=None, gt=0)
    status: FacilityStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ProcessingUnitRead(BaseModel):
    id: uuid.UUID
    unit_code: str
    name: str
    registration_identifier: str | None = None
    location: str | None = None
    district: str | None = None
    state: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    operator_user_id: uuid.UUID | None = None
    operator_name: str | None = None
    status: FacilityStatus
    status_label: str
    capacity_kg_per_day: Decimal | None = None
    is_demo: bool = False
    notes: str | None = None
    processing_run_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProcessingCreate(BaseModel):
    """``POST /api/v1/processing`` — open a run against a collected batch.

    A run is opened as ``PENDING``: naming the batch does not touch the honey. It
    starts when ``POST /processing/{id}/start`` is called, which is also the moment
    the batch becomes ``PROCESSING``.
    """

    model_config = ConfigDict(extra="forbid")

    batch_id: uuid.UUID = Field(description="The COLLECTED batch this run will process.")
    processing_type: ProcessingType = ProcessingType.FILTERING
    processing_type_other: str | None = Field(
        default=None,
        max_length=120,
        description=(
            "What the operation was, in the operator's own words. Required when "
            "`processing_type` is OTHER, and refused otherwise."
        ),
    )
    processing_unit_id: uuid.UUID | None = Field(
        default=None,
        description="Where the work will be done. Optional — an apiary-scale run has no facility.",
    )
    processing_date: date | None = Field(
        default=None, description="Business date; defaults to today."
    )
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("processing_type_other")
    @classmethod
    def _trim_other(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    @model_validator(mode="after")
    def _other_matches_the_type(self):
        """The operation and its description always agree — one shared rule."""
        check_other_pair(
            kind="operation",
            value=self.processing_type,
            other=self.processing_type_other,
            other_option=ProcessingType.OTHER.value,
        )
        return self

    @field_validator("processing_date")
    @classmethod
    def _not_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("A processing date cannot be in the future")
        return value


class ProcessingUpdate(BaseModel):
    """``PATCH /api/v1/processing/{id}`` — corrections while the run is open.

    The quantities are the reason this model exists: a run in progress is where
    the input and output are entered as they are measured. Everything a completed
    run must not lose is refused once the run is completed (409), not merely
    guarded by the UI.
    """

    model_config = ConfigDict(extra="forbid")

    processing_type: ProcessingType | None = None
    processing_type_other: str | None = Field(default=None, max_length=120)
    processing_unit_id: uuid.UUID | None = None
    processing_date: date | None = None
    input_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_PROCESSING_QUANTITY)
    output_quantity: Decimal | None = Field(default=None, ge=0, le=MAX_PROCESSING_QUANTITY)
    start_time: datetime | None = None
    completion_time: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("processing_type_other")
    @classmethod
    def _trim_other(cls, value: str | None) -> str | None:
        """A description typed with padding is stored as the words themselves."""
        return value.strip() if value else None

    @field_validator("processing_date")
    @classmethod
    def _not_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("A processing date cannot be in the future")
        return value

    @model_validator(mode="after")
    def _output_cannot_exceed_input(self) -> "ProcessingUpdate":
        if (
            self.input_quantity is not None
            and self.output_quantity is not None
            and self.output_quantity > self.input_quantity
        ):
            raise ValueError("Output quantity cannot exceed the input quantity")
        return self


class ProcessingComplete(BaseModel):
    """``POST /api/v1/processing/{id}/complete``."""

    model_config = ConfigDict(extra="forbid")

    input_quantity: Decimal | None = Field(
        default=None,
        gt=0,
        le=MAX_PROCESSING_QUANTITY,
        description="May be supplied here instead of by a separate correction.",
    )
    output_quantity: Decimal | None = Field(
        default=None,
        ge=0,
        le=MAX_PROCESSING_QUANTITY,
        description="The measured output. Required, here or already recorded on the run.",
    )
    completion_time: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ProcessingCancel(BaseModel):
    """``POST /api/v1/processing/{id}/cancel``."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500, description="Why the run did not happen.")


class EligibleProcessor(BaseModel):
    """A person work may be allocated to, read from the users table.

    Deliberately small and safe: an identifier, a name, the sign-in address and
    whether the account is switched on. No password material, no tokens, no
    profile contents — the assignment dropdown needs to identify a person, not to
    administer them.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    role: str
    role_label: str = ""
    is_active: bool = True
    account_status: str = "ACTIVE"
    #: How much open work this person is already carrying, so a dispatcher can
    #: see a fair spread rather than guess from a list of names.
    open_work_count: int = 0


class ProcessingAssign(BaseModel):
    """Allocate a run to a named processor.

    The processor is named by id (never by name or by the client's own session):
    the backend checks that the id belongs to an active processor, so a client
    cannot hand work to an arbitrary account. ``assignment_id`` lets an
    administrator allocate the whole batch in one call **without an open run
    existing yet** — the run is created by the service, so the work appears in the
    processor's queue immediately and the batch never sits in limbo.
    """

    model_config = ConfigDict(extra="forbid")

    processor_id: uuid.UUID
    assignment_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional existing run to allocate. Omit it and a PENDING run is opened "
            "for the batch, which is what the administrator screen does."
        ),
    )
    notes: str | None = Field(default=None, max_length=500)


class ProcessingBatchAssign(BaseModel):
    """Allocate a whole batch to a processor, opening the run if needed."""

    model_config = ConfigDict(extra="forbid")

    processor_id: uuid.UUID
    processing_type: ProcessingType | None = None
    notes: str | None = Field(default=None, max_length=500)


class ProcessingBatchRef(BaseModel):
    """The batch a run belongs to, in the batch's own vocabulary."""

    id: uuid.UUID
    batch_code: str
    status: str
    status_label: str
    quantity: Decimal
    unit: str
    unit_label: str
    collection_id: uuid.UUID
    collection_code: str | None = None
    collection_date: date
    beekeeper_id: uuid.UUID | None = None
    beekeeper_code: str | None = None
    cluster_id: uuid.UUID | None = None
    cluster_code: str | None = None


class ProcessingListItem(BaseModel):
    id: uuid.UUID
    processing_code: str
    status: ProcessingStatus
    status_label: str
    processing_type: ProcessingType
    processing_type_label: str
    #: The operation's own name, when the type is OTHER — so a reader sees what was
    #: actually done rather than only that it was not one of the listed operations.
    processing_type_other: str | None = None
    processing_type_display: str | None = Field(
        default=None, description="What to show for the type: the listed name, or the recorded one."
    )
    batch_id: uuid.UUID
    batch_code: str
    collection_code: str | None = None
    processing_unit_id: uuid.UUID | None = None
    processing_unit_code: str | None = None
    processing_unit_name: str | None = None
    operator_id: uuid.UUID | None = None
    operator_name: str | None = None
    input_quantity: Decimal | None = None
    output_quantity: Decimal | None = None
    loss_quantity: Decimal | None = None
    loss_percent: float | None = None
    unit: CollectionUnit
    unit_label: str
    processing_date: date
    start_time: datetime | None = None
    completion_time: datetime | None = None
    cluster_id: uuid.UUID | None = None
    cluster_code: str | None = None
    beekeeper_code: str | None = None
    created_at: datetime
    #: Who is responsible for the run, and how that came about. ``processor_id`` is
    #: null while the work sits unallocated in the shared queue.
    processor_id: uuid.UUID | None = None
    processor_name: str | None = None
    assigned_by_id: uuid.UUID | None = None
    assigned_by_name: str | None = None
    assigned_at: datetime | None = None
    accepted_at: datetime | None = None
    assignment_status: AssignmentStatus = AssignmentStatus.UNASSIGNED
    assignment_status_label: str = "Unassigned"
    #: What the caller may do to this record, stated so the UI does not guess.
    can_edit: bool = False
    can_start: bool = False
    can_complete: bool = False
    can_cancel: bool = False
    can_assign: bool = False
    can_accept: bool = False
    can_work: bool = Field(
        default=False,
        description="True when this run is this caller's own assigned work.",
    )


class ProcessingDetail(ProcessingListItem):
    model_config = ConfigDict(extra="forbid")

    batch: ProcessingBatchRef
    notes: str | None = None
    cancellation_reason: str | None = None
    cancelled_at: datetime | None = None
    updated_at: datetime
    #: The batch's status, read from the batch itself — the run never holds a copy.
    batch_status: str
    batch_status_label: str
    next_step: str | None = Field(
        default=None, description="What the workflow expects next, as a sentence."
    )


class ProcessingSummary(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    cancelled: int = 0
    #: Input, output and loss per unit — only from runs that recorded both figures.
    by_unit: dict[str, dict[str, float]] = Field(default_factory=dict)
    #: Batches sitting at COLLECTED in the caller's scope: the worklist a
    #: processing user works from.
    awaiting_processing: int = 0
    #: Batches already handed to the laboratory — visible, but not this module's work.
    awaiting_laboratory: int = 0
    #: The queue counters the processor dashboard shows. ``waiting`` counts batches
    #: at COLLECTED with no run opened against them yet; the rest count open runs by
    #: how they are allocated.
    waiting: int = 0
    unassigned: int = 0
    assigned: int = 0
    accepted: int = 0
    in_progress: int = 0
    #: Runs allocated to the caller and not yet taken on — their own to-do list.
    mine: int = 0
    #: Runs allocated to the caller and accepted (includes the ones under way).
    mine_accepted: int = 0


__all__ = [
    "ProcessingAssign",
    "ProcessingBatchAssign",
    "ProcessingCancel",
    "ProcessingComplete",
    "ProcessingCreate",
    "ProcessingBatchRef",
    "ProcessingDetail",
    "ProcessingListItem",
    "ProcessingSummary",
    "ProcessingUnitCreate",
    "ProcessingUnitRead",
    "ProcessingUnitUpdate",
    "ProcessingUpdate",
]

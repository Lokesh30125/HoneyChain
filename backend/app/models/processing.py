"""``processing_units`` and ``honey_processing_records`` — what happened to a batch.

The processing run
------------------
A batch is the physical lot; a processing run is the operation performed on it.
They are separate rows because they are separate things, and because a run has
its own facts to record — what was done, where, by whom, when, and what came out.

Quantities are recorded, never assumed
--------------------------------------
``input_quantity`` is how much honey went in and ``output_quantity`` how much came
out. They are **not** the same number and the platform never pretends they are:
``loss_quantity`` is stored as the arithmetic difference between the two recorded
figures (and a CHECK constraint keeps it consistent), so a screen can show
"13.7 kg in, 12.9 kg out, 0.8 kg lost" as three measurable facts. Nothing here
alters the collection or the batch quantity: what was harvested stays harvested.

Immutability
------------
``batch_id``, ``processing_code``, ``input_quantity``, ``output_quantity``, the
start and completion times and the operator are frozen once the run is
``COMPLETED``. A completed run cannot be edited at all in this phase — the
service refuses — and a correction means a new run, which is exactly how the
later blockchain phase needs it to behave.

One open run per batch
----------------------
A partial unique index allows at most one non-cancelled run per batch while an
operation is under way, so a double submission cannot leave two rival records of
the same operation. History is kept: cancelled runs stay in the table and remain
readable.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy import Enum as SAEnum

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, UUID_TYPE
from app.models.enums import (
    AssignmentStatus,
    FacilityStatus,
    ProcessingStatus,
    ProcessingType,
)
from app.models.honey_collection import COLLECTION_UNIT_ENUM, QUANTITY_PRECISION, QUANTITY_SCALE

#: PostgreSQL types created by the Phase-6 migration. ``values_callable`` keeps the
#: stored value equal to the enum value, so a raw SQL reader sees the same word the
#: API returns.
PROCESSING_STATUS_ENUM = SAEnum(
    ProcessingStatus,
    name="processing_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
PROCESSING_TYPE_ENUM = SAEnum(
    ProcessingType,
    name="processing_type",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
ASSIGNMENT_STATUS_ENUM = SAEnum(
    AssignmentStatus,
    name="assignment_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
FACILITY_STATUS_ENUM = SAEnum(
    FacilityStatus,
    name="facility_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)


class ProcessingUnit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A place where honey is processed.

    Deliberately small: a name, where it is, who runs it and whether it is
    operating. This phase needs a facility *reference* so a processing record can
    say where the work happened — it does not need a facility-management system,
    and building one now would be inventing requirements.
    """

    __tablename__ = "processing_units"

    unit_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc="Platform-issued reference, e.g. HC-PUNIT-2026-000001.",
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    registration_identifier: Mapped[str | None] = mapped_column(
        String(80), nullable=True, doc="External registration number, when the unit has one."
    )
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    operator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="A stand-in for the responsible operator's linked account, until assignment is modelled.",
    )
    status: Mapped[FacilityStatus] = mapped_column(
        FACILITY_STATUS_ENUM,
        nullable=False,
        default=FacilityStatus.ACTIVE,
        server_default=FacilityStatus.ACTIVE.value,
    )
    capacity_kg_per_day: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=True,
        doc="Recorded capacity, when the unit states one. Not used to validate anything.",
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc=(
            "True only for reference data created by a demonstration seed. Demo "
            "facilities may never be attached to a real processing record."
        ),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    processing_records: Mapped[list["HoneyProcessing"]] = relationship(back_populates="unit_ref")
    #: The account responsible for the unit, when one has been named. Nullable —
    #: a facility can be registered before the staff member using it is.
    operator: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[operator_user_id]
    )

    @property
    def is_active(self) -> bool:
        return self.status is FacilityStatus.ACTIVE

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProcessingUnit {self.unit_code} {self.name!r}>"


class HoneyProcessing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One processing run performed on exactly one honey batch."""

    __tablename__ = "honey_processing_records"
    __table_args__ = (
        # The pair travels together or not at all: "Other" without a description
        # would record that something happened and nothing about what it was, and a
        # listed value with a leftover description could contradict it.
        CheckConstraint(
            "(processing_type <> 'OTHER' AND processing_type_other IS NULL) "
            "OR (processing_type = 'OTHER' AND processing_type_other IS NOT NULL "
            "AND length(btrim(processing_type_other)) > 0)",
            name="ck_processing_type_other",
        ),
        CheckConstraint(
            "input_quantity IS NULL OR input_quantity > 0",
            name="ck_processing_input_quantity_positive",
        ),
        CheckConstraint(
            "output_quantity IS NULL OR output_quantity >= 0",
            name="ck_processing_output_quantity_non_negative",
        ),
        CheckConstraint(
            "output_quantity IS NULL OR input_quantity IS NULL OR output_quantity <= input_quantity",
            name="ck_processing_output_not_above_input",
        ),
        CheckConstraint(
            "output_quantity IS NULL OR loss_quantity = input_quantity - output_quantity",
            name="ck_processing_loss_matches_quantities",
        ),
        # At most one run under way per batch: a retry cannot create a rival record
        # of the same operation. Cancelled and completed runs are history and are
        # excluded from the index.
        Index(
            "uq_processing_open_per_batch",
            "batch_id",
            unique=True,
            postgresql_where="status IN ('PENDING', 'IN_PROGRESS')",
        ),
        Index("ix_processing_batch_created", "batch_id", "created_at"),
    )

    processing_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc="Platform-issued reference, e.g. HC-PROC-2026-000001.",
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("honey_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="RESTRICT: a batch with processing history cannot be deleted out from under it.",
    )
    processing_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("processing_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Where the work happened. Optional: a beekeeper-scale extraction has no facility.",
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="The signed-in operator who ran it. RESTRICT, so the record keeps its actor.",
    )
    processor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        doc=(
            "The processor the run is allocated to. Null until someone is made "
            "responsible for it — the work then sits in the shared pending queue."
        ),
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Who allocated the run. SET NULL: the allocation survives the allocator.",
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When the run was allocated."
    )
    assignment_status: Mapped[AssignmentStatus] = mapped_column(
        ASSIGNMENT_STATUS_ENUM,
        nullable=False,
        default=AssignmentStatus.UNASSIGNED,
        server_default=AssignmentStatus.UNASSIGNED.value,
        index=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the named processor took the run on. Starting a run implies this.",
    )
    #: What the run did, when ``processing_type`` is ``OTHER``. The platform keeps
    #: the operation name the operator recorded instead of forcing a described
    #: operation into a category that misdescribes it; the column stays NULL for
    #: every run whose type is one of the listed operations.
    processing_type_other: Mapped[str | None] = mapped_column(String(120), nullable=True)
    processing_type: Mapped[ProcessingType] = mapped_column(
        PROCESSING_TYPE_ENUM, nullable=False, default=ProcessingType.FILTERING
    )
    status: Mapped[ProcessingStatus] = mapped_column(
        PROCESSING_STATUS_ENUM,
        nullable=False,
        default=ProcessingStatus.PENDING,
        server_default=ProcessingStatus.PENDING.value,
        index=True,
    )

    # -- What went in and what came out -------------------------------------
    input_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=True,
        doc="Honey that entered the run. Never assumed to equal the output.",
    )
    output_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=True,
        doc="Honey that came out of the run, as measured. Required to complete the run.",
    )
    loss_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=True,
        doc="Recorded input minus recorded output. Stored, not computed on read.",
    )
    unit: Mapped[str] = mapped_column(
        COLLECTION_UNIT_ENUM,
        nullable=False,
        doc="The batch's own unit. Nothing converts between units anywhere in the platform.",
    )

    # -- When ---------------------------------------------------------------
    start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When the operation actually began."
    )
    completion_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When it finished. Frozen once completed."
    )
    processing_date: Mapped[date] = mapped_column(
        nullable=False, index=True, doc="Business date of the run, for listing and reporting."
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # -- Relationships -------------------------------------------------------
    batch: Mapped["HoneyBatch"] = relationship(back_populates="processing_records")  # noqa: F821
    unit_ref: Mapped[ProcessingUnit | None] = relationship(back_populates="processing_records")
    #: Who performed the work. Named explicitly because ``users`` is reached from
    #: this table by one foreign key today and by more later — being explicit now
    #: means a future column cannot silently repoint this relationship.
    operator: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[operator_id]
    )
    processor: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[processor_id]
    )
    assigned_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[assigned_by_id]
    )

    @property
    def is_open(self) -> bool:
        return self.status.is_open

    @property
    def is_assigned(self) -> bool:
        """True once a named processor is responsible for the run."""
        return self.processor_id is not None and self.assignment_status.is_allocated

    @property
    def is_pending_assignment(self) -> bool:
        """In the shared queue: nobody has been made responsible for it yet."""
        return self.assignment_status is AssignmentStatus.UNASSIGNED and self.status.is_open

    @property
    def loss_percent(self) -> float | None:
        """Loss as a percentage of the recorded input — only when both are known."""
        if self.input_quantity in (None, 0) or self.output_quantity is None:
            return None
        return float(self.loss_quantity / self.input_quantity * 100)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<HoneyProcessing {self.processing_code} {self.status}>"


__all__ = ["ProcessingUnit", "HoneyProcessing"]

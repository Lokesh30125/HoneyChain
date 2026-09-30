"""``laboratories``, ``lab_parameters``, ``lab_tests`` and ``lab_test_results``.

Four tables, split along the lines the requirement draws:

``laboratories``
    The facility that performed the test. Small on purpose — a name, where it is,
    a registration identifier and whether it is operating. This phase needs a
    reference, not a laboratory-management platform.

``lab_parameters``
    The catalogue of measurements a test may record, **and** the configured
    reference range for each. The catalogue ships populated (names and units only,
    which are facts about what the instrument reads); the ranges ship **empty**
    and are configured through the API. That split is the whole honesty story of
    this phase: nothing in this codebase asserts that a honey moisture of 17.2 %
    is acceptable, because that claim belongs to a standard the operator must
    enter, naming its source. With no range configured a measurement is recorded
    and reported as ``NOT_EVALUATED``, and the test's overall result is
    ``INCONCLUSIVE`` — never a pass it did not earn.

``lab_tests``
    One test of one batch. Many tests may exist for a batch (a first run, a
    retest, a dispute sample); nothing overwrites anything, and every test keeps
    its own code, its own sample code and its own results forever.

``lab_test_results``
    The measurements themselves, one row per parameter — a keyed table rather than
    a wide table of fixed columns, so adding a parameter is a catalogue row rather
    than a migration. Each row stores the value **and** the reference range that
    was in force when it was recorded, so a result stays interpretable even after
    the range is reconfigured: the comparison that was actually made is preserved.

Nothing here holds a "trust score", a QR payload or a ledger entry. Those belong
to later phases; what this phase leaves behind for them is stable identifiers,
timestamps and audit rows.
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
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, UUID_TYPE
from app.models.enums import (
    AssignmentStatus,
    FacilityStatus,
    LabMeasureUnit,
    LabMeasurementSource,
    LabParameterStatus,
    LabResult,
    LabTestStatus,
)
from app.models.honey_collection import COLLECTION_UNIT_ENUM, QUANTITY_PRECISION, QUANTITY_SCALE
from app.models.processing import ASSIGNMENT_STATUS_ENUM, FACILITY_STATUS_ENUM

#: The catalogue code is a *value*, not a PostgreSQL enum: adding a parameter is
#: a catalogue row rather than a migration. Validity is guaranteed by the foreign
#: key into ``lab_parameters.code``, which is stronger than a fixed list — a
#: result can only name a parameter the catalogue actually defines.
LAB_MEASURE_UNIT_ENUM = SAEnum(
    LabMeasureUnit,
    name="lab_measure_unit",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
LAB_MEASUREMENT_SOURCE_ENUM = SAEnum(
    LabMeasurementSource,
    name="lab_measurement_source",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
LAB_TEST_STATUS_ENUM = SAEnum(
    LabTestStatus,
    name="lab_test_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
LAB_RESULT_ENUM = SAEnum(
    LabResult,
    name="lab_result",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
LAB_PARAMETER_STATUS_ENUM = SAEnum(
    LabParameterStatus,
    name="lab_parameter_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)


class Laboratory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A laboratory that performs honey quality tests."""

    __tablename__ = "laboratories"

    laboratory_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc="Platform-issued reference, e.g. HC-LABUNIT-2026-000001.",
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    registration_identifier: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        doc="Accreditation or registration number as supplied by the laboratory. Not verified here.",
    )
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    accredited: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        doc=(
            "As recorded by the facility itself. The platform does not verify accreditation "
            "and never claims it on a facility's behalf; NULL means it was not stated."
        ),
    )
    status: Mapped[FacilityStatus] = mapped_column(
        FACILITY_STATUS_ENUM,
        nullable=False,
        default=FacilityStatus.ACTIVE,
        server_default=FacilityStatus.ACTIVE.value,
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc="True only for reference data created by a demonstration seed.",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_active(self) -> bool:
        return self.status is FacilityStatus.ACTIVE

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Laboratory {self.laboratory_code} {self.name!r}>"


class LabParameter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One measurable honey quality parameter — and the range configured for it.

    ``reference_min`` / ``reference_max`` are **NULL on a fresh installation**.
    Nothing in this project asserts a scientific limit it was not given: to
    evaluate a measurement, an administrator must configure the range and record
    where it came from (``reference_source``). Until then, results are stored and
    reported as ``NOT_EVALUATED``.
    """

    __tablename__ = "lab_parameters"
    __table_args__ = (
        CheckConstraint(
            "reference_min IS NULL OR reference_max IS NULL OR reference_min <= reference_max",
            name="ck_lab_parameters_reference_range_ordered",
        ),
        UniqueConstraint("code", name="uq_lab_parameters_code"),
        Index("ix_lab_parameters_order", "display_order"),
    )

    code: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True, doc="Stable code, e.g. MOISTURE."
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(
        LAB_MEASURE_UNIT_ENUM,
        nullable=False,
        doc="The unit the instrument reports in, e.g. % or mg/kg. Stored, never converted.",
    )
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc=(
            "Platform policy, not a scientific claim: a required parameter must have a "
            "result before the test can reach a passing or failing decision."
        ),
    )
    reference_min: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, doc="Lower bound of the configured acceptable range."
    )
    reference_max: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, doc="Upper bound of the configured acceptable range."
    )
    reference_source: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
        doc=(
            "Where the range came from, as entered by the administrator who configured it "
            "(a standard, a buyer specification, an internal sop). The platform quotes this "
            "text; it does not vouch for it."
        ),
    )
    reference_updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reference_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: The methods that are valid for *this* parameter, as configured:
    #: ``[{"code": "KARL_FISCH", "label": "Karl Fischer titration"}, …]``. A
    #: dropdown is rendered from this list, so a laboratory cannot be asked to
    #: choose a method that does not apply to what it is measuring — and adding a
    #: method is a configuration change, not a code change. "Other" is always
    #: offered on top of the list, and the words typed for it are stored verbatim.
    methods: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True, doc="Configured method options for this parameter."
    )
    #: The value the platform pre-fills for this parameter when a test is opened in
    #: development/demo mode. It is a **starting point somebody must confirm**, not
    #: a measurement: it is stored with ``measurement_source=DEMO`` and every screen
    #: that shows it says so. NULL means "no development default", which is the
    #: production setting.
    development_value: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, doc="Demo-mode starting value, never a reading."
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
        doc="Inactive parameters stay in the catalogue and out of new tests.",
    )

    #: Who last set the reference range. Read-only sugar over the id column; the
    #: audit trail holds the history of every change.
    reference_updated_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[reference_updated_by_id]
    )

    @property
    def is_configured(self) -> bool:
        """True once a range exists, so a measurement can actually be judged."""
        return self.reference_min is not None or self.reference_max is not None

    def evaluate(self, value: Decimal) -> LabParameterStatus:
        """Compare a measured value against the configured range.

        With no range configured the honest answer is ``NOT_EVALUATED``: the
        platform has been told what was measured, not what is acceptable.
        """
        if not self.is_configured:
            return LabParameterStatus.NOT_EVALUATED
        if self.reference_min is not None and value < self.reference_min:
            return LabParameterStatus.FAIL
        if self.reference_max is not None and value > self.reference_max:
            return LabParameterStatus.FAIL
        return LabParameterStatus.PASS

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LabParameter {self.code}>"


class LabTest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One laboratory test of one batch, with its own sample and results."""

    __tablename__ = "lab_tests"
    __table_args__ = (
        CheckConstraint("sample_quantity > 0", name="ck_lab_tests_sample_quantity_positive"),
        Index("ix_lab_tests_batch_created", "batch_id", "created_at"),
        Index("ix_lab_tests_status", "status"),
    )

    test_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc="Platform-issued test reference, e.g. HC-LAB-2026-000001.",
    )
    sample_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc=(
            "Platform-issued sample reference, e.g. HC-SMP-2026-000001 — separate from the "
            "test code so the physical sample and the test performed on it are both addressable."
        ),
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("honey_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    processing_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("honey_processing_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="The run that produced the honey being tested. A test is never anonymous.",
    )
    laboratory_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("laboratories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    technician_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="The technician who recorded the test.",
    )

    assigned_technician_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        doc=(
            "The technician the test is allocated to. Null until someone is made "
            "responsible for it — the sample then waits in the shared pending queue."
        ),
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Who allocated the test. SET NULL: the allocation survives the allocator.",
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When the test was allocated."
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
        doc="When the named technician took the test on.",
    )
    sample_quantity: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE), nullable=False
    )
    sample_unit: Mapped[str] = mapped_column(
        COLLECTION_UNIT_ENUM,
        nullable=False,
        doc="A sample is a mass. The same two units the harvest was recorded in, unconverted.",
    )
    sample_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sample_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    test_date: Mapped[date] = mapped_column(nullable=False, index=True)
    status: Mapped[LabTestStatus] = mapped_column(
        LAB_TEST_STATUS_ENUM,
        nullable=False,
        default=LabTestStatus.PENDING,
        server_default=LabTestStatus.PENDING.value,
    )
    overall_result: Mapped[LabResult] = mapped_column(
        LAB_RESULT_ENUM,
        nullable=False,
        default=LabResult.PENDING,
        server_default=LabResult.PENDING.value,
        index=True,
        doc=(
            "Derived, never supplied: computed from the recorded results and the configured "
            "ranges when the test is completed (see ``LaboratoryService._evaluate``)."
        ),
    )
    result_summary: Mapped[str | None] = mapped_column(
        String(500), doc="Plain-language explanation of the overall result, generated on completion."
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- Retests: a new test, never an edit of an old one --------------------
    retest_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("lab_tests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="The earlier test this one re-runs, when the sample is a retest.",
    )
    retest_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    round_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        doc="1 for the first test of a batch, 2 for the next, and so on. History only.",
    )

    # -- The decision --------------------------------------------------------
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc=(
            "True when an administrator set the overall result explicitly instead of it being "
            "derived. An override always carries a reason and an audit entry."
        ),
    )
    override_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # -- AI quality analysis (stored with its provenance) -------------------
    #: The structured analysis last run over this test's measurements: overall
    #: status, risk level, vulnerabilities, abnormal/passed/inconclusive
    #: parameters, the explanation and the recommendation — together with the
    #: model, version and source that produced it. Stored rather than recomputed
    #: so a later, better model cannot silently rewrite what was concluded.
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_model_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_source: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc="DEVELOPMENT / DEMO / PRODUCTION — what the analysis was allowed to rely on.",
    )
    ai_analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_analysed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # -- Hold ---------------------------------------------------------------
    #: Why the test was parked, in the words of the person who parked it. Kept on
    #: the test so the beekeeper, the officer and the packaging floor all read the
    #: same sentence rather than being told only that something is on hold.
    hold_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    held_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # -- Risk override (development/demo) -----------------------------------
    #: The record of a decision to continue with a flagged batch: who, when, why,
    #: and the risks and analysis they were shown. NULL when no override was used.
    risk_override: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    overridden_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list["LabTestResult"]] = relationship(
        back_populates="test", cascade="all, delete-orphan", order_by="LabTestResult.created_at"
    )
    batch: Mapped["HoneyBatch"] = relationship(back_populates="lab_tests")  # noqa: F821
    #: The run that produced the honey under test. The test reads it rather than
    #: copying the processing figures, so the two can never disagree.
    processing: Mapped["HoneyProcessing"] = relationship()  # noqa: F821
    laboratory: Mapped[Laboratory] = relationship()
    #: Both foreign keys into ``users`` are declared explicitly: omitting them
    #: would leave SQLAlchemy guessing which one a relationship means.
    technician: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[technician_id]
    )
    #: The technician the test is allocated to. Null until somebody is made
    #: responsible for it; the sample then waits in the shared pending queue.
    assigned_technician: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[assigned_technician_id]
    )
    assigned_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[assigned_by_id]
    )
    held_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[held_by_id]
    )
    ai_analysed_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[ai_analysed_by_id]
    )
    overridden_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[overridden_by_id]
    )
    decided_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[decided_by_id]
    )
    #: The earlier test this one re-examines, when it is a retest.
    retest_of: Mapped["LabTest | None"] = relationship(remote_side="LabTest.id")

    @property
    def is_completed(self) -> bool:
        return self.status is LabTestStatus.COMPLETED

    @property
    def is_assigned(self) -> bool:
        """True once a named technician is responsible for the test."""
        return (
            self.assigned_technician_id is not None
            and self.assignment_status.is_allocated
        )

    @property
    def is_pending_assignment(self) -> bool:
        """In the shared queue: nobody has been made responsible for it yet."""
        return (
            self.assignment_status is AssignmentStatus.UNASSIGNED
            and self.status is not LabTestStatus.CANCELLED
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LabTest {self.test_code} {self.status}/{self.overall_result}>"


class LabTestResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One measured parameter of one laboratory test."""

    __tablename__ = "lab_test_results"
    __table_args__ = (
        # One row per parameter per test — except OTHER, which may describe more
        # than one unlisted measurement. A partial index expresses exactly that.
        Index(
            "uq_lab_results_test_parameter",
            "lab_test_id",
            "parameter_code",
            unique=True,
            postgresql_where="parameter_code <> 'OTHER'",
        ),
        Index("ix_lab_results_test_created", "lab_test_id", "created_at"),
    )

    lab_test_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("lab_tests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parameter_code: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("lab_parameters.code", ondelete="RESTRICT"),
        nullable=False,
        doc="Catalogue code (see ``lab_parameters``). 'OTHER' rows must name themselves.",
    )
    parameter_name: Mapped[str] = mapped_column(
        String(120), nullable=False, doc="Display name; for OTHER, the name given by the technician."
    )
    value: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, doc="The measurement as recorded. Never derived or filled in."
    )
    unit: Mapped[str] = mapped_column(LAB_MEASURE_UNIT_ENUM, nullable=False)

    # -- The comparison actually made, preserved with the result -------------
    reference_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    reference_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    reference_source: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
        doc="The range's source text as it stood when this result was recorded.",
    )
    status: Mapped[LabParameterStatus] = mapped_column(
        LAB_PARAMETER_STATUS_ENUM,
        nullable=False,
        default=LabParameterStatus.NOT_EVALUATED,
        server_default=LabParameterStatus.NOT_EVALUATED.value,
    )
    #: Where this number came from — a development default, a person, or an
    #: instrument. The value is never presented without it.
    measurement_source: Mapped[LabMeasurementSource] = mapped_column(
        LAB_MEASUREMENT_SOURCE_ENUM,
        nullable=False,
        default=LabMeasurementSource.MANUAL,
        server_default=LabMeasurementSource.MANUAL.value,
        doc="DEMO (platform-supplied starting point), MANUAL (typed), REAL_DEVICE (instrument).",
    )
    method: Mapped[str | None] = mapped_column(
        String(120), nullable=True, doc="Instrument or method as stated by the technician."
    )
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    test: Mapped[LabTest] = relationship(back_populates="results")
    #: Who entered this measurement. Part of the record, not commentary on it.
    recorded_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[recorded_by_id]
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LabTestResult {self.parameter_code}={self.value}{self.unit} {self.status}>"


__all__ = ["Laboratory", "LabParameter", "LabTest", "LabTestResult"]

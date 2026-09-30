"""``packaging_units``, ``packaging_records`` and ``packages``.

Three tables, split along the lines the supply chain actually draws:

``packaging_units``
    The place where packing happens, registered the same way a processing unit
    and a laboratory are — a name, where it is, who runs it, and whether it is
    operating. Deliberately small: packaging needs a facility *reference*, not a
    facility-management system.

``packaging_records``
    One packing operation performed on one approved batch: how much honey went
    in, how much came out as packages, what the packages are and what they
    weigh. A batch may be packed in several runs (the first run clears part of
    the approved quantity, a later run the rest), which is why this is a table
    rather than a column on the batch.

``packages``
    One row per physical package, created when a packaging run completes. These
    rows are the stable identity the rest of the chain moves: a distribution
    names packages, not batches, and the identifier printed on a package is the
    one the platform will keep for its whole life.

What is *not* here
------------------
Nothing in this module alters the batch, the collection or the processing run.
Quantities are recorded next to each other and never overwritten: what was
harvested stays harvested, what was processed stays processed, and what was
packed is a third fact. No ledger entry, no hash and no QR payload is written
here — those belong to later phases; what this phase leaves behind for them is
stable identifiers and timestamps.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUID_TYPE, UUIDPrimaryKeyMixin
from app.models.enums import (
    FacilityStatus,
    PackageStatus,
    PackagingStatus,
    PackagingType,
)
from app.models.honey_collection import COLLECTION_UNIT_ENUM, QUANTITY_PRECISION, QUANTITY_SCALE
from app.models.processing import FACILITY_STATUS_ENUM

PACKAGING_STATUS_ENUM = SAEnum(
    PackagingStatus,
    name="packaging_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
PACKAGING_TYPE_ENUM = SAEnum(
    PackagingType,
    name="packaging_type",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
PACKAGE_STATUS_ENUM = SAEnum(
    PackageStatus,
    name="package_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)


class PackagingUnit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A place where approved honey is packed into packages."""

    __tablename__ = "packaging_units"

    unit_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc="Platform-issued reference, e.g. HC-PKUNIT-2026-000001.",
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    registration_identifier: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        doc="External registration number, when the unit states one. Not verified here.",
    )
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: The facility's postal address. Separate from ``location`` because they are
    #: separate facts: "Guntur" is where it is, "12 Market Road, Guntur 522001" is
    #: where a shipment goes.
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="The packaging-unit account responsible for this facility, once one is named.",
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
        doc="True only for reference data created by a demonstration seed.",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    packaging_records: Mapped[list["PackagingRun"]] = relationship(back_populates="unit_ref")
    #: The account responsible for the unit, when one has been named.
    owner: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[owner_user_id]
    )
    #: The accounts that work at this facility. ``User.packaging_unit_id`` is the
    #: single place the relationship is stored — the unit does not keep a second
    #: copy of it, so the two can never disagree.
    members: Mapped[list["User"]] = relationship(  # noqa: F821
        back_populates="packaging_unit",
        foreign_keys="User.packaging_unit_id",
    )

    @property
    def member_count(self) -> int:
        return len(self.members or [])

    @property
    def is_active(self) -> bool:
        return self.status is FacilityStatus.ACTIVE

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PackagingUnit {self.unit_code} {self.name!r}>"


class PackagingRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One packing operation performed on one approved honey batch.

    ``packaged_quantity`` is what actually left the table as packages and
    ``input_quantity`` what was drawn from the batch for it. They are separate
    columns because they are separate measurements: honey clings to a vessel, a
    jar is overfilled, and the platform records what was weighed instead of
    assuming the two agree.

    The package count is checked against the quantities at the service boundary:
    ``package_size × number_of_packages`` must equal ``packaged_quantity`` before
    the run can complete, so a record cannot claim forty packages of 1 kg and
    30 kg of honey at the same time.
    """

    __tablename__ = "packaging_records"
    __table_args__ = (
        # The pair travels together or not at all: "Other" without a description
        # would record that something happened and nothing about what it was, and a
        # listed value with a leftover description could contradict it.
        CheckConstraint(
            "(packaging_type <> 'OTHER' AND packaging_type_other IS NULL) "
            "OR (packaging_type = 'OTHER' AND packaging_type_other IS NOT NULL "
            "AND length(btrim(packaging_type_other)) > 0)",
            name="ck_packaging_type_other",
        ),
        CheckConstraint(
            "input_quantity IS NULL OR input_quantity > 0",
            name="ck_packaging_input_quantity_positive",
        ),
        CheckConstraint(
            "packaged_quantity IS NULL OR packaged_quantity > 0",
            name="ck_packaging_packaged_quantity_positive",
        ),
        CheckConstraint(
            "packaged_quantity IS NULL OR input_quantity IS NULL OR packaged_quantity <= input_quantity",
            name="ck_packaging_packaged_not_above_input",
        ),
        CheckConstraint(
            "package_size IS NULL OR package_size > 0",
            name="ck_packaging_package_size_positive",
        ),
        CheckConstraint(
            "number_of_packages IS NULL OR number_of_packages > 0",
            name="ck_packaging_package_count_positive",
        ),
        # At most one packing operation under way per batch, so a double
        # submission cannot leave two rival records of the same work.
        Index(
            "uq_packaging_open_per_batch",
            "batch_id",
            unique=True,
            postgresql_where="status IN ('PENDING', 'IN_PROGRESS')",
        ),
        Index("ix_packaging_batch_created", "batch_id", "created_at"),
    )

    packaging_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc="Platform-issued reference, e.g. HC-PACK-2026-000001.",
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("honey_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="The batch being packed. RESTRICT: packing history is never orphaned.",
    )
    packaging_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("packaging_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Where the packing happened. Optional: a small producer packs on their own premises.",
    )
    packaged_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="The signed-in packaging-unit operator who ran it. RESTRICT, so the record keeps its actor.",
    )
    # The KVIC cluster the packed batch belongs to, carried here as well so a
    # cluster's packing history is one indexed query rather than a join through
    # three tables. Copied from the batch at creation; never supplied by a caller.
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("kvic_clusters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="The KVIC cluster of the packed batch, copied from the batch record.",
    )
    status: Mapped[PackagingStatus] = mapped_column(
        PACKAGING_STATUS_ENUM,
        nullable=False,
        default=PackagingStatus.PENDING,
        server_default=PackagingStatus.PENDING.value,
        index=True,
    )
    #: The container described in the operator's own words, when
    #: ``packaging_type`` is ``OTHER``; NULL otherwise.
    packaging_type_other: Mapped[str | None] = mapped_column(String(120), nullable=True)
    packaging_type: Mapped[PackagingType] = mapped_column(
        PACKAGING_TYPE_ENUM,
        nullable=False,
        default=PackagingType.JAR,
    )
    packaging_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        doc="The date the packing was performed, as recorded by the operator.",
    )

    # -- What went in and what came out --------------------------------------
    input_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=True,
        doc="Approved honey drawn from the batch for this run.",
    )
    packaged_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=True,
        doc="Honey that left as packages, as weighed. Required to complete the run.",
    )
    package_size: Mapped[Decimal | None] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=True,
        doc="The labelled size of one package, in the batch's own unit. No conversion is applied.",
    )
    number_of_packages: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="How many packages this run produced."
    )
    unit: Mapped[str] = mapped_column(
        COLLECTION_UNIT_ENUM,
        nullable=False,
        doc="The batch's own unit. Nothing converts between units anywhere in the platform.",
    )

    # -- When ---------------------------------------------------------------
    start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When packing actually began."
    )
    completion_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When it finished. Frozen once completed."
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When the run was abandoned."
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped["HoneyBatch"] = relationship()  # noqa: F821
    unit_ref: Mapped["PackagingUnit | None"] = relationship(back_populates="packaging_records")
    packaged_by: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[packaged_by_id]
    )
    packages: Mapped[list["HoneyPackage"]] = relationship(
        back_populates="packaging", cascade="save-update, merge"
    )

    @property
    def is_completed(self) -> bool:
        return self.status is PackagingStatus.COMPLETED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PackagingRun {self.packaging_code} {self.status}>"


class HoneyPackage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One physical package produced by one packaging run.

    The row is small on purpose. Everything a consumer, a distributor or a
    verifier will want to know about this package — the batch, the apiary, the
    laboratory result — is one hop away through ``packaging_id`` and
    ``batch_id``, and is *read* from those records rather than copied here. That
    is what keeps the chain a chain instead of a set of parallel claims.
    """

    __tablename__ = "packages"
    __table_args__ = (
        UniqueConstraint("package_code", name="uq_packages_package_code"),
        CheckConstraint("quantity > 0", name="ck_packages_quantity_positive"),
        CheckConstraint("package_size > 0", name="ck_packages_package_size_positive"),
        # A package inherits the container its run was described as, and the same
        # rule applies to it: "Other" says nothing on its own. Should the pair ever
        # be written directly, the database refuses the half-recorded row.
        CheckConstraint(
            "(packaging_type <> 'OTHER' AND packaging_type_other IS NULL) "
            "OR (packaging_type = 'OTHER' AND packaging_type_other IS NOT NULL "
            "AND length(btrim(packaging_type_other)) > 0)",
            name="ck_package_type_other",
        ),
        Index("ix_packages_batch_created", "batch_id", "created_at"),
        Index("ix_packages_packaging_sequence", "packaging_id", "sequence_number"),
    )

    package_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
        doc="Stable public identifier, e.g. HC-PKG-2026-000001. Printed and never reused.",
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer, nullable=False, doc="1-based position of this package within its packaging run."
    )
    packaging_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("packaging_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("honey_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="Denormalised from the packaging run on purpose: a package's batch is a fact about it.",
    )
    # The KVIC cluster, copied from the batch like the run's is. Denormalised on
    # purpose: "the packages of this cluster" is a question the cluster screens
    # ask, and it should not cost three joins to answer.
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("kvic_clusters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="The KVIC cluster of the batch this package came from.",
    )
    package_size: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=False,
        doc="Labelled size of this package, in the batch's own unit.",
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=False,
        doc="Measured contents of this package, in the batch's own unit.",
    )
    unit: Mapped[str] = mapped_column(COLLECTION_UNIT_ENUM, nullable=False)
    packaging_type: Mapped[PackagingType] = mapped_column(PACKAGING_TYPE_ENUM, nullable=False)
    #: The container in the operator's own words, copied from the run when
    #: ``packaging_type`` is ``OTHER``; NULL otherwise. The package travels further
    #: than the run does, so it carries the description with it.
    packaging_type_other: Mapped[str | None] = mapped_column(String(120), nullable=True)
    packaging_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PackageStatus] = mapped_column(
        PACKAGE_STATUS_ENUM,
        nullable=False,
        default=PackageStatus.CREATED,
        server_default=PackageStatus.CREATED.value,
        index=True,
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the packing unit released the package for distribution.",
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When the retailer confirmed receipt."
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # -- The package's public identity (Phase 8) ---------------------------- #
    #: The string encoded in this package's QR code: a link to its traceability
    #: page, and nothing else. Written once, when the identity is first issued,
    #: so the same physical package always resolves to the same page and the
    #: printed code keeps working after the record changes underneath it.
    qr_payload: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
        doc="URL encoded in the package QR. NULL until an identity is issued.",
    )
    qr_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the QR identity was issued. NULL means no QR exists yet.",
    )
    #: How many times the traceability page for this package has been opened,
    #: and when it was last opened. A count on the package rather than a table
    #: of every scan: the platform records that a customer verified the package,
    #: not a browsing history of who scanned what.
    qr_scan_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    qr_last_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    packaging: Mapped["PackagingRun"] = relationship(back_populates="packages")
    batch: Mapped["HoneyBatch"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<HoneyPackage {self.package_code} {self.status}>"

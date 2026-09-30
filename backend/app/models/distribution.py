"""``distributions`` — shipments of packages from a packer to a retailer.

A distribution record is a *shipment line*: one package (or part of one), a
destination, who is carrying it and where it has got to. Several shipments may
reference the same package, which is how partial distribution works without a
second table: what has been dispatched against a package is the sum of its
shipments, and what remains is arithmetic on recorded figures.

The journey is one-way and enforced here and in the service:

``READY_FOR_DISPATCH`` → ``DISPATCHED`` → ``IN_TRANSIT`` → ``DELIVERED``

``DELIVERED`` requires a recorded dispatch, because a delivery without a
dispatch would be a claim about a journey that never started. A retailer
confirms receipt (``received_by_id`` / ``received_at``) and that confirmation,
not the carrier's word, is what closes the shipment; the timestamps are kept
separately so "when did it leave" and "when was it accepted" remain two facts.

Nothing here rewrites the package, the batch or anything upstream of it. A
delivery is recorded *about* a package; the package's own provenance is read
from the records that produced it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUID_TYPE, UUIDPrimaryKeyMixin
from app.models.enums import DistributionStatus
from app.models.honey_collection import COLLECTION_UNIT_ENUM, QUANTITY_PRECISION, QUANTITY_SCALE

DISTRIBUTION_STATUS_ENUM = SAEnum(
    DistributionStatus,
    name="distribution_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)


class Distribution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One shipment of one package towards one destination."""

    __tablename__ = "distributions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_distributions_quantity_positive"),
        CheckConstraint(
            "status <> 'DELIVERED' OR dispatched_at IS NOT NULL",
            name="ck_distributions_delivered_requires_dispatch",
        ),
        CheckConstraint(
            "delivered_at IS NULL OR dispatched_at IS NULL OR delivered_at >= dispatched_at",
            name="ck_distributions_delivered_after_dispatch",
        ),
        Index("ix_distributions_batch_created", "batch_id", "created_at"),
        Index("ix_distributions_package_status", "package_id", "status"),
        Index("ix_distributions_retailer_status", "retailer_id", "status"),
    )

    distribution_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc="Platform-issued reference, e.g. HC-DIST-2026-000001.",
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("packages.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="The package being moved. RESTRICT: shipment history is never orphaned.",
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("honey_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="Denormalised from the package: a shipment's batch is a fact about it.",
    )
    distributor_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="The distributor account that owns the shipment.",
    )
    retailer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc=(
            "The receiving retailer account, when the destination is a platform "
            "user. SET NULL: the shipment survives the account, its destination "
            "text survives with it."
        ),
    )
    destination: Mapped[str] = mapped_column(
        String(200), nullable=False, doc="Where it is going, as written on the shipment."
    )
    destination_district: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    status: Mapped[DistributionStatus] = mapped_column(
        DISTRIBUTION_STATUS_ENUM,
        nullable=False,
        default=DistributionStatus.READY_FOR_DISPATCH,
        server_default=DistributionStatus.READY_FOR_DISPATCH.value,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=False,
        doc="How much of the package this shipment carries. Never converted between units.",
    )
    unit: Mapped[str] = mapped_column(COLLECTION_UNIT_ENUM, nullable=False)
    carrier: Mapped[str | None] = mapped_column(
        String(160), nullable=True, doc="Who is moving it, when a carrier is named."
    )
    tracking_reference: Mapped[str | None] = mapped_column(
        String(80), nullable=True, doc="The carrier's own reference, if one was given."
    )

    dispatch_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, doc="The date dispatch was recorded."
    )
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When it left. Required before a delivery."
    )
    in_transit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When it was last reported as moving."
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When it arrived and was accepted."
    )
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="The retailer account that confirmed receipt.",
    )
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc=(
            "When the retailer accepted the shipment. Kept separately from "
            "``delivered_at``: the carrier's delivery and the receiver's acceptance "
            "are two different facts about the same journey."
        ),
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    package: Mapped["HoneyPackage"] = relationship()  # noqa: F821
    batch: Mapped["HoneyBatch"] = relationship()  # noqa: F821
    distributor: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[distributor_id]
    )
    retailer: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[retailer_id]
    )
    received_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[received_by_id]
    )

    @property
    def is_delivered(self) -> bool:
        return self.status is DistributionStatus.DELIVERED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Distribution {self.distribution_code} {self.status}>"

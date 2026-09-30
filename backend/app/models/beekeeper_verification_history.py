"""``beekeeper_verification_history`` — append-only verification audit trail.

Every status change writes a row here. History is never updated or deleted, so
the sequence of decisions survives disputes: who moved a beekeeper to
``VERIFIED``, when, on what basis, and what the previous state was.

The beekeeper's *current* status is denormalised onto ``beekeepers`` for fast
filtering; this table is the record of how it got there.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUID_TYPE, UUIDPrimaryKeyMixin
from app.models.enums import VerificationStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.beekeeper import Beekeeper
    from app.models.user import User


class BeekeeperVerificationHistory(UUIDPrimaryKeyMixin, Base):
    """One immutable entry per verification decision."""

    __tablename__ = "beekeeper_verification_history"

    beekeeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("beekeepers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: ``None`` for the initial entry created with the beekeeper record.
    previous_status: Mapped[VerificationStatus | None] = mapped_column(
        SAEnum(
            VerificationStatus,
            name="verification_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            create_type=False,  # the enum type is created by the beekeepers table
            native_enum=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    new_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(
            VerificationStatus,
            name="verification_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            create_type=False,
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
    )

    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: ``SET NULL`` keeps the trail if the officer's account is later removed —
    #: the decision happened and must remain visible even so.
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Snapshot of the actor's name and role at decision time, so the trail stays
    #: readable even after the account is gone or the role changes.
    changed_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    changed_by_role: Mapped[str | None] = mapped_column(String(40), nullable=True)

    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("ix_beekeeper_verification_beekeeper_changed", "beekeeper_id", "changed_at"),
    )

    beekeeper: Mapped["Beekeeper"] = relationship(back_populates="verification_history")
    changed_by: Mapped["User | None"] = relationship(foreign_keys=[changed_by_id])

    @property
    def is_initial(self) -> bool:
        return self.previous_status is None

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<VerificationHistory {self.previous_status} -> {self.new_status} "
            f"at={self.changed_at}>"
        )

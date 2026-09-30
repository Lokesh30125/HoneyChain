"""``audit_logs`` — append-only record of significant platform events.

Written through :class:`app.services.audit_service.AuditService`, which the
service layer calls at the end of a successful operation. The log answers the
questions a traceability platform is eventually asked: who did this, to what,
when, and from where.

Phase 2 records identity, beekeeper and cluster events. Later phases append
their own actions (``HIVE_REGISTERED``, ``BATCH_ANCHORED``) using the same
``AuditAction`` vocabulary.

**Never store secrets here.** ``AuditService`` runs metadata through the same
redaction used by the logging layer, so a password or token cannot reach this
table even if a caller passes one by mistake.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUID_TYPE, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """A single audited action."""

    __tablename__ = "audit_logs"

    #: ``SET NULL``: the log outlives the account it refers to. The actor's
    #: name and role are snapshotted below so the entry stays meaningful.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)

    #: An ``AuditAction`` value. Stored as a string rather than a PostgreSQL
    #: enum so new phases can add actions without a migration.
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    #: Structured context: changed fields, previous and new values, reasons.
    #: Attribute named ``event_metadata`` because ``metadata`` is reserved by
    #: SQLAlchemy's declarative API; the database column keeps the plain name.
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )

    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])

    @property
    def summary(self) -> str:
        """One-line rendering for the admin audit view."""
        subject = f"{self.entity_type}:{self.entity_id}" if self.entity_type else "platform"
        actor = self.actor_email or "system"
        return f"{self.action} on {subject} by {actor}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.action} entity={self.entity_type}>"

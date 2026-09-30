"""``ai_alerts`` — risk signals raised by the AI engine.

An alert is the bridge between a stored analysis and a beekeeper's attention, so
two rules shape it:

1. **It points at the analysis that produced it.** ``analysis_id`` is a real
   foreign key, so every alert can be explained ("why did I get this?") by
   reading the assessment behind it. If the analysis is deleted, the alert goes
   with it rather than becoming an orphan claim.
2. **It is de-duplicated, not repeated.** A hive whose humidity stays high for a
   week must not produce a hundred identical alerts. Alerts carry a
   ``dedupe_key`` (hive + type + severity); while a matching alert is still
   active inside the cooldown window the engine *updates* it — bumping
   ``occurrences`` and ``last_seen_at`` — instead of inserting another row.

Status is deliberately small (OPEN → ACKNOWLEDGED → RESOLVED) because there is
no notification system in this phase: acknowledging is a record the beekeeper
makes in the app, and it is what stops an alert shouting on every page load.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Enum as SAEnum,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, UUID_TYPE
from app.models.enums import AiAlertSeverity, AiAlertStatus, AiAlertType

ALERT_TYPE_ENUM = SAEnum(
    AiAlertType,
    name="ai_alert_type",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
ALERT_SEVERITY_ENUM = SAEnum(
    AiAlertSeverity,
    name="ai_alert_severity",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
ALERT_STATUS_ENUM = SAEnum(
    AiAlertStatus,
    name="ai_alert_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)

AI_ALERT_ENUMS = (ALERT_TYPE_ENUM, ALERT_SEVERITY_ENUM, ALERT_STATUS_ENUM)


class AiAlert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One risk signal, de-duplicated per hive/type/severity while active."""

    __tablename__ = "ai_alerts"

    hive_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("hives.id", ondelete="CASCADE"), nullable=False, index=True
    )
    beekeeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("beekeepers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("hive_ai_analyses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    alert_type: Mapped[AiAlertType] = mapped_column(ALERT_TYPE_ENUM, nullable=False)
    severity: Mapped[AiAlertSeverity] = mapped_column(
        ALERT_SEVERITY_ENUM,
        nullable=False,
        default=AiAlertSeverity.WARNING,
        server_default=AiAlertSeverity.WARNING.value,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str | None] = mapped_column(
        String(60), nullable=True, doc="The measurement that triggered it, when there is one."
    )

    #: ``hive:type:severity`` — what the cooldown window is keyed on.
    dedupe_key: Mapped[str] = mapped_column(String(140), nullable=False, index=True)
    occurrences: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
        doc="How many analyses have confirmed this signal while it stayed active.",
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[AiAlertStatus] = mapped_column(
        ALERT_STATUS_ENUM,
        nullable=False,
        default=AiAlertStatus.OPEN,
        server_default=AiAlertStatus.OPEN.value,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    context: Mapped[dict] = mapped_column(
        "context",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        doc="Indicator values behind the alert, so the message can be explained later.",
    )

    __table_args__ = (
        CheckConstraint("occurrences >= 1", name="ai_alert_occurrences_min"),
        # De-duplication is enforced in ``AlertService`` (one *active* alert per
        # key, updated in place while it keeps recurring) rather than by a unique
        # constraint, because the rule depends on the window and on the status —
        # not on the column values alone. A partial unique index would express it
        # on PostgreSQL but not on the SQLite fallback the test suite supports for
        # laptops without a database server.
        Index("ix_ai_alerts_dedupe", "dedupe_key", "status"),
        Index("ix_ai_alerts_hive_status", "hive_id", "status"),
        Index("ix_ai_alerts_beekeeper_status", "beekeeper_id", "status"),
        Index("ix_ai_alerts_created", "created_at"),
    )

    analysis: Mapped["HiveAiAnalysis | None"] = relationship(back_populates="alerts")  # noqa: F821
    hive: Mapped["Hive"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AiAlert {self.alert_type} {self.severity} {self.status} x{self.occurrences}>"


__all__ = ["AiAlert", "AI_ALERT_ENUMS"]

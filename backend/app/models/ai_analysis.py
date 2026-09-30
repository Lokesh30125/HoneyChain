"""``hive_ai_analyses`` — one stored AI assessment of one hive.

Why the result is persisted rather than recomputed on every page view
---------------------------------------------------------------------
An assessment is not a cheap derived property; it is an *event* with a
provenance that has to stay understandable months later:

* **which model produced it** (``model_type`` + ``model_version``, so a later,
  better model does not silently rewrite history);
* **which telemetry it consumed** (``window_start``/``window_end``,
  ``sample_count``, ``newest_reading_at``, ``analysis_source``);
* **how much it can be trusted** (``data_quality``, ``overall_confidence``);
* **what it concluded** (the score columns) and **why** (``detail`` JSONB).

The scalar columns exist because KVIC/cluster analytics will aggregate them
(average colony health per district, count of high-risk hives) with plain SQL;
the JSONB columns exist because the *explanation* — contributing factors,
detected anomalies, recommendations — is variable-length and must be read back
exactly as it was produced.

Only the projection columns are indexed. ``detail`` is payload, never a filter.
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
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, UUID_TYPE
from app.models.enums import (
    AiAnalysisSource,
    AiDataQuality,
    AiHealthStatus,
    AiRiskLevel,
    AiTrend,
)

HEALTH_STATUS_ENUM = SAEnum(
    AiHealthStatus,
    name="ai_health_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
RISK_LEVEL_ENUM = SAEnum(
    AiRiskLevel,
    name="ai_risk_level",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
TREND_ENUM = SAEnum(
    AiTrend,
    name="ai_trend",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
DATA_QUALITY_ENUM = SAEnum(
    AiDataQuality,
    name="ai_data_quality",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
ANALYSIS_SOURCE_ENUM = SAEnum(
    AiAnalysisSource,
    name="ai_analysis_source",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)

#: All enum types this module introduces, in creation order. The migration uses
#: the same list so ``downgrade`` drops exactly what ``upgrade`` created.
AI_ANALYSIS_ENUMS = (
    HEALTH_STATUS_ENUM,
    RISK_LEVEL_ENUM,
    TREND_ENUM,
    DATA_QUALITY_ENUM,
    ANALYSIS_SOURCE_ENUM,
)


class HiveAiAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single stored AI assessment of a hive."""

    __tablename__ = "hive_ai_analyses"

    # -- What was analysed ----------------------------------------------------
    hive_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("hives.id", ondelete="CASCADE"), nullable=False, index=True
    )
    beekeeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("beekeepers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner at analysis time — the column every beekeeper-scoped query filters on.",
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="When the analysis ran (UTC).",
    )

    # -- Which data it consumed ----------------------------------------------
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        doc="Readings actually used. Zero is a valid, recorded outcome.",
    )
    newest_reading_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Newest reading consumed. Used to decide whether a stored analysis is stale.",
    )
    data_quality: Mapped[AiDataQuality] = mapped_column(
        DATA_QUALITY_ENUM,
        nullable=False,
        default=AiDataQuality.INSUFFICIENT,
        server_default=AiDataQuality.INSUFFICIENT.value,
    )
    analysis_source: Mapped[AiAnalysisSource] = mapped_column(
        ANALYSIS_SOURCE_ENUM,
        nullable=False,
        default=AiAnalysisSource.NO_DATA,
        server_default=AiAnalysisSource.NO_DATA.value,
        doc="Derived from the readings' own source column, never asserted by the client.",
    )

    # -- Model identity -------------------------------------------------------
    model_type: Mapped[str] = mapped_column(String(60), nullable=False)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # -- Colony health --------------------------------------------------------
    health_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    health_status: Mapped[AiHealthStatus] = mapped_column(
        HEALTH_STATUS_ENUM,
        nullable=False,
        default=AiHealthStatus.INSUFFICIENT_DATA,
        server_default=AiHealthStatus.INSUFFICIENT_DATA.value,
    )
    health_confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    health_trend: Mapped[AiTrend] = mapped_column(
        TREND_ENUM, nullable=False, default=AiTrend.UNKNOWN, server_default=AiTrend.UNKNOWN.value
    )

    # -- Disease risk (a risk, never a diagnosis) -----------------------------
    disease_risk_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    disease_risk_level: Mapped[AiRiskLevel] = mapped_column(
        RISK_LEVEL_ENUM, nullable=False, default=AiRiskLevel.UNKNOWN, server_default=AiRiskLevel.UNKNOWN.value
    )
    disease_confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # -- Swarming risk --------------------------------------------------------
    swarming_risk_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    swarming_risk_level: Mapped[AiRiskLevel] = mapped_column(
        RISK_LEVEL_ENUM, nullable=False, default=AiRiskLevel.UNKNOWN, server_default=AiRiskLevel.UNKNOWN.value
    )
    swarming_confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # -- Yield projection -----------------------------------------------------
    predicted_yield_kg: Mapped[float | None] = mapped_column(
        Numeric(8, 2),
        nullable=True,
        doc="Projected stored-honey mass over the forecast period, from the measured weight trend.",
    )
    yield_confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    yield_trend: Mapped[AiTrend] = mapped_column(
        TREND_ENUM, nullable=False, default=AiTrend.UNKNOWN, server_default=AiTrend.UNKNOWN.value
    )
    yield_period_days: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # -- Overall --------------------------------------------------------------
    overall_confidence: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    detail: Mapped[dict] = mapped_column(
        "detail",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        doc="Full explanation: contributing factors, anomalies, recommendations, "
        "feature summary and data-quality issues, exactly as produced.",
    )

    __table_args__ = (
        CheckConstraint(
            "health_score IS NULL OR (health_score >= 0 AND health_score <= 100)",
            name="ai_analysis_health_score_range",
        ),
        CheckConstraint(
            "disease_risk_score IS NULL OR (disease_risk_score >= 0 AND disease_risk_score <= 100)",
            name="ai_analysis_disease_score_range",
        ),
        CheckConstraint(
            "swarming_risk_score IS NULL OR (swarming_risk_score >= 0 AND swarming_risk_score <= 100)",
            name="ai_analysis_swarming_score_range",
        ),
        CheckConstraint(
            "overall_confidence >= 0 AND overall_confidence <= 100",
            name="ai_analysis_confidence_range",
        ),
        CheckConstraint("sample_count >= 0", name="ai_analysis_sample_count_non_negative"),
        # The two access shapes: "latest for this hive" and "history for this
        # hive", plus the owner scope used by list screens and the future
        # cluster aggregates.
        Index("ix_ai_analyses_hive_analyzed", "hive_id", "analyzed_at"),
        Index("ix_ai_analyses_beekeeper_analyzed", "beekeeper_id", "analyzed_at"),
        Index("ix_ai_analyses_status_analyzed", "health_status", "analyzed_at"),
    )

    hive: Mapped["Hive"] = relationship()  # noqa: F821
    alerts: Mapped[list["AiAlert"]] = relationship(  # noqa: F821
        back_populates="analysis", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<HiveAiAnalysis hive={self.hive_id} at={self.analyzed_at:%Y-%m-%d %H:%M} "
            f"health={self.health_status} v{self.model_version}>"
        )


__all__ = ["HiveAiAnalysis", "AI_ANALYSIS_ENUMS"]

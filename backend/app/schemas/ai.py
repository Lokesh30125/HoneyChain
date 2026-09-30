"""AI schemas — the response contract for the analysis, alert and insight screens.

The stored analysis is a row with a handful of scalar columns and one JSONB
``detail`` blob. These schemas turn that row into something a screen can render
without reinterpreting it, and they are the reason the honesty rules survive all
the way to the UI:

* every assessment carries its ``confidence`` *and* the factors/indicators that
  produced it, so a number is never shown on its own;
* the disease and swarming payloads carry their ``disclaimer`` field, so a client
  cannot display the risk band without the sentence that qualifies it;
* the yield payload carries ``available`` and ``reason``, so "no projection" is a
  first-class state rather than a missing number;
* ``data_quality``, ``analysis_source`` and ``sample_count`` travel with every
  assessment, so a screen can always say what the score was computed from — and
  ``SIMULATOR``/``MANUAL``/``NO_DATA`` can never be mistaken for hardware.

Nothing in this module computes anything: the converters read the engine's own
``as_dict()`` output back out of the stored row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AiAlertSeverity,
    AiAlertStatus,
    AiDataQuality,
    AiHealthStatus,
    AiRiskLevel,
    AiTrend,
)

#: Text that must appear next to any colony-health number. It is returned by the
#: API rather than written into the frontend, so a client cannot drop it.
HEALTH_DISCLAIMER = (
    "Colony health is a monitoring indicator derived from sensor patterns against reference "
    "bands. It is not a veterinary assessment and does not confirm the presence or absence of "
    "any disease."
)

#: Text that must appear next to any risk band.
RISK_DISCLAIMER = (
    "Risk indicators are produced by a rule-based baseline model from recorded sensor patterns. "
    "They are prompts to inspect, not diagnoses."
)


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class AnalysisRequest(BaseModel):
    """``POST /api/v1/ai/hives/{hive_id}/analyze``.

    There is deliberately nothing to configure: the window, the thresholds and the
    model version are platform settings, not client parameters, so a caller
    cannot widen the window until a thin dataset produces a confident answer.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(
        default=None,
        max_length=200,
        description="Optional free-text note recorded in the audit entry.",
    )


class AlertActionRequest(BaseModel):
    """``POST /api/v1/ai/alerts/{alert_id}/acknowledge`` and ``/resolve``."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(
        default=None,
        max_length=500,
        description="Optional note stored with the alert for the record.",
    )


class AlertQuery(BaseModel):
    """Filters accepted by ``GET /api/v1/ai/alerts``."""

    model_config = ConfigDict(extra="forbid")

    status: AiAlertStatus | None = None
    severity: AiAlertSeverity | None = None
    alert_type: str | None = Field(default=None, max_length=40)
    hive_id: uuid.UUID | None = None
    include_resolved: bool = False

    @field_validator("alert_type")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


# --------------------------------------------------------------------------- #
# Explanation pieces (read from the stored ``detail`` payload)
# --------------------------------------------------------------------------- #
class AiFactor(BaseModel):
    """One contributing factor behind a score, with the points it contributed."""

    code: str
    label: str
    detail: str
    direction: str = Field(description="POSITIVE, NEGATIVE or NEUTRAL.")
    delta: float = Field(description="Points this factor added to (or removed from) the score.")
    sensors: list[str] = Field(default_factory=list)
    value: float | None = None
    reference: str | None = None


class AiAnomaly(BaseModel):
    """A measured pattern outside its reference band."""

    code: str
    label: str
    detail: str
    severity: AiAlertSeverity
    sensors: list[str] = Field(default_factory=list)
    value: float | None = None
    reference: str | None = None
    weight: float = 0.0


class AiRecommendation(BaseModel):
    """A suggested action, tied to the finding that produced it."""

    code: str
    title: str
    detail: str
    priority: str = Field(description="ROUTINE, SOON or PRIORITY.")
    reason: str = ""
    sensors: list[str] = Field(default_factory=list)


class AiHealthAssessment(BaseModel):
    score: int | None = Field(
        default=None, description="0–100 indicator, or null when the telemetry cannot support one."
    )
    status: AiHealthStatus
    status_label: str
    confidence: int
    trend: AiTrend
    summary: str
    basis: str
    disclaimer: str = HEALTH_DISCLAIMER
    factors: list[AiFactor] = Field(default_factory=list)
    anomalies: list[AiAnomaly] = Field(default_factory=list)


class AiRiskAssessment(BaseModel):
    score: int | None = None
    level: AiRiskLevel
    level_label: str
    confidence: int
    summary: str
    disclaimer: str
    indicators: list[AiFactor] = Field(default_factory=list)
    anomalies: list[AiAnomaly] = Field(default_factory=list)
    recommendation: AiRecommendation | None = None


class AiYieldPrediction(BaseModel):
    available: bool = Field(
        description="False when there is no projection — read ``reason`` before showing a number."
    )
    predicted_yield: float | None = Field(
        default=None, description="Projected stored-weight change over ``period_days``, in kg."
    )
    unit: str = "kg"
    confidence: int = 0
    trend: AiTrend = AiTrend.UNKNOWN
    trend_label: str = "Unknown"
    period_days: int | None = None
    gain_per_day: float | None = None
    fit: float | None = Field(default=None, description="r² of the fitted weight line.")
    completeness: float | None = None
    observed_days: float | None = None
    samples: int = 0
    reason: str | None = Field(
        default=None, description="Why there is no projection, in plain language."
    )
    notes: list[str] = Field(default_factory=list)
    summary: str = ""
    basis: str = ""


class AiQualityReport(BaseModel):
    """What the analysis could and could not support, in words as well as flags."""

    level: AiDataQuality
    source: str
    sample_count: int
    covered_hours: float
    expected_samples: int | None = None
    coverage: float | None = None
    newest_reading_at: datetime | None = None
    newest_age_minutes: float | None = None
    is_stale: bool = False
    device_online: bool | None = None
    device_status: str | None = None
    missing_sensors: list[str] = Field(default_factory=list)
    suspect_jumps: int = 0
    confidence_factor: float | None = None
    issues: list[str] = Field(default_factory=list)
    summary: str = ""


class AiModelInfo(BaseModel):
    type: str
    version: str
    baseline: bool = True
    note: str = ""


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
class HiveAiAnalysisPublic(BaseModel):
    """One stored analysis, exactly as it will be shown."""

    id: uuid.UUID
    hive_id: uuid.UUID
    hive_code: str | None = None
    analyzed_at: datetime
    window_start: datetime | None = None
    window_end: datetime | None = None
    sample_count: int
    newest_reading_at: datetime | None = None
    data_quality: AiDataQuality
    data_quality_label: str
    analysis_source: str
    analysis_source_label: str

    model_type: str
    model_version: str

    health: AiHealthAssessment
    disease_risk: AiRiskAssessment
    swarming_risk: AiRiskAssessment
    yield_prediction: AiYieldPrediction

    recommendations: list[AiRecommendation] = Field(default_factory=list)
    quality: AiQualityReport

    overall_confidence: int
    summary: str
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="The full stored explanation, including the feature summary and model block.",
    )


class HiveAiInsight(BaseModel):
    """``GET /api/v1/ai/hives/{hive_id}`` — the hive's insight plus how it was obtained.

    Every assessment section is optional on purpose: a hive that has never been
    analysed (auto-analysis disabled, or the caller may only read) returns
    ``analyzed: false`` with ``null`` sections and a plain-language summary. The
    alternative — an empty-but-present assessment — is exactly the kind of
    placeholder this module exists to avoid.
    """

    hive_id: uuid.UUID
    hive_code: str | None = None
    analyzed: bool = Field(
        default=False, description="False when no assessment has been stored for this hive yet."
    )
    analysis_id: uuid.UUID | None = None
    analyzed_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    sample_count: int = 0
    newest_reading_at: datetime | None = None
    data_quality: AiDataQuality = AiDataQuality.INSUFFICIENT
    data_quality_label: str = "Insufficient"
    analysis_source: str = "NO_DATA"
    analysis_source_label: str = "No telemetry"
    model_type: str = ""
    model_version: str = ""

    health: AiHealthAssessment | None = None
    disease_risk: AiRiskAssessment | None = None
    swarming_risk: AiRiskAssessment | None = None
    yield_prediction: AiYieldPrediction | None = None
    recommendations: list[AiRecommendation] = Field(default_factory=list)
    quality: AiQualityReport | None = None
    overall_confidence: int = 0
    summary: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)

    computed: bool = Field(
        default=False,
        description="True when this response triggered a fresh analysis instead of reading a "
        "stored one.",
    )
    compute_reason: str = Field(
        default="read_only",
        description="no_analysis | stale | new_telemetry | forced | read_only | auto_disabled | fresh",
    )
    auto_analysis_enabled: bool = True
    freshness: dict[str, Any] = Field(
        default_factory=dict,
        description="Analysis age, reading age and the staleness verdict with its thresholds.",
    )


class HiveAiSummaryRow(BaseModel):
    """The dashboard row for one hive: enough to render a card without a second call."""

    hive_id: uuid.UUID
    hive_code: str
    status: str
    analyzed: bool = False
    analyzed_at: datetime | None = None
    is_stale: bool = True
    data_quality: AiDataQuality | None = None
    data_quality_label: str | None = None
    analysis_source: str | None = None
    analysis_source_label: str | None = None
    sample_count: int | None = None
    health_score: int | None = None
    health_status: AiHealthStatus | None = None
    health_status_label: str | None = None
    health_confidence: int | None = None
    disease_risk_level: AiRiskLevel | None = None
    disease_risk_score: int | None = None
    swarming_risk_level: AiRiskLevel | None = None
    swarming_risk_score: int | None = None
    predicted_yield_kg: float | None = None
    yield_period_days: int | None = None
    open_alerts: int = 0
    summary: str | None = None


class AiEngineSummary(BaseModel):
    """``GET /api/v1/ai/summary`` — fleet counters for the AI screens."""

    total_hives: int
    analysed_hives: int
    hives_without_analysis: int
    hives_with_telemetry: int
    health: dict[str, int] = Field(default_factory=dict)
    disease_risk: dict[str, int] = Field(default_factory=dict)
    swarming_risk: dict[str, int] = Field(default_factory=dict)
    yield_projection: dict[str, Any] = Field(
        default_factory=dict, description="Aggregate of the per-hive weight projections."
    )
    open_alerts: int = 0
    alerts_by_severity: dict[str, int] = Field(default_factory=dict)
    model: AiModelInfo
    auto_analysis_enabled: bool = True
    analysis_window_hours: int = 168
    generated_at: datetime


class AiAlertPublic(BaseModel):
    id: uuid.UUID
    hive_id: uuid.UUID
    hive_code: str | None = None
    analysis_id: uuid.UUID | None = None
    alert_type: str
    alert_type_label: str
    severity: AiAlertSeverity
    severity_label: str
    title: str
    message: str
    metric: str | None = None
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    status: AiAlertStatus
    status_label: str
    acknowledged_at: datetime | None = None
    acknowledged_by: uuid.UUID | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = RISK_DISCLAIMER


class AiAlertSummary(BaseModel):
    open_total: int
    by_severity: dict[str, int] = Field(default_factory=dict)
    acknowledged: int = 0
    resolved: int = 0
    note: str = (
        "Alerts are recorded in the app. HoneyChain does not send notifications (SMS, email or "
        "push) in this phase."
    )


class AiAnalysisRunResult(BaseModel):
    """Outcome of a manual analysis run."""

    hive_id: uuid.UUID
    hive_code: str
    analysis_id: uuid.UUID
    data_quality: AiDataQuality
    analysis_source: str
    sample_count: int
    health_status: AiHealthStatus
    health_score: int | None = None
    disease_risk_level: AiRiskLevel
    swarming_risk_level: AiRiskLevel
    alerts_created: int = 0
    alerts_bumped: int = 0
    alerts_resolved: int = 0
    summary: str
    computed_at: datetime


class AiBulkRunResult(BaseModel):
    hives_analyzed: int
    hives_with_insufficient_data: int
    alerts_created: int
    model: AiModelInfo


# --------------------------------------------------------------------------- #
# Converters — stored row → response model
# --------------------------------------------------------------------------- #
def _detail(analysis) -> dict[str, Any]:
    return analysis.detail or {}


def _as_dict(value) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def to_health_assessment(analysis) -> AiHealthAssessment:
    payload = _as_dict(_detail(analysis).get("health"))
    if not payload:
        # A row written before a schema change, or one whose payload was trimmed:
        # report the stored scalar columns rather than inventing a full shape.
        return AiHealthAssessment(
            score=analysis.health_score,
            status=analysis.health_status,
            status_label=analysis.health_status.label,
            confidence=analysis.health_confidence or 0,
            trend=analysis.health_trend,
            summary="Stored analysis has no factor detail.",
            basis="",
            factors=[],
            anomalies=[],
        )
    return AiHealthAssessment(
        score=payload.get("score"),
        status=payload.get("status") or analysis.health_status,
        status_label=payload.get("status_label") or analysis.health_status.label,
        confidence=payload.get("confidence", 0),
        trend=payload.get("trend") or analysis.health_trend,
        summary=payload.get("summary", ""),
        basis=payload.get("basis", ""),
        factors=[AiFactor(**item) for item in payload.get("factors", [])],
        anomalies=[AiAnomaly(**item) for item in payload.get("anomalies", [])],
    )


def to_risk_assessment(analysis, key: str) -> AiRiskAssessment:
    payload = _as_dict(_detail(analysis).get(key))
    stored_level = (
        analysis.disease_risk_level if key == "disease_risk" else analysis.swarming_risk_level
    )
    stored_score = (
        analysis.disease_risk_score if key == "disease_risk" else analysis.swarming_risk_score
    )
    if not payload:
        return AiRiskAssessment(
            score=stored_score,
            level=stored_level,
            level_label=stored_level.label,
            confidence=0,
            summary="Stored analysis has no indicator detail.",
            disclaimer=RISK_DISCLAIMER,
        )
    recommendation = payload.get("recommendation")
    return AiRiskAssessment(
        score=payload.get("score"),
        level=payload.get("level") or stored_level,
        level_label=payload.get("level_label") or stored_level.label,
        confidence=payload.get("confidence", 0),
        summary=payload.get("summary", ""),
        disclaimer=payload.get("disclaimer") or RISK_DISCLAIMER,
        indicators=[AiFactor(**item) for item in payload.get("indicators", [])],
        anomalies=[AiAnomaly(**item) for item in payload.get("anomalies", [])],
        recommendation=AiRecommendation(**recommendation) if recommendation else None,
    )


def to_yield_prediction(analysis) -> AiYieldPrediction:
    payload = _as_dict(_detail(analysis).get("yield_prediction"))
    if not payload:
        return AiYieldPrediction(
            available=analysis.predicted_yield_kg is not None,
            predicted_yield=float(analysis.predicted_yield_kg)
            if analysis.predicted_yield_kg is not None
            else None,
            confidence=analysis.yield_confidence or 0,
            trend=analysis.yield_trend,
            trend_label=analysis.yield_trend.label,
            period_days=analysis.yield_period_days,
            reason=None if analysis.predicted_yield_kg is not None else "No projection stored.",
        )
    return AiYieldPrediction(**payload)


def to_quality_report(analysis) -> AiQualityReport:
    payload = _as_dict(_detail(analysis).get("quality"))
    if not payload:
        return AiQualityReport(
            level=analysis.data_quality,
            source=str(analysis.analysis_source),
            sample_count=analysis.sample_count,
            covered_hours=0.0,
            newest_reading_at=analysis.newest_reading_at,
        )
    return AiQualityReport(**payload)


def to_analysis_public(analysis, *, hive_code: str | None = None) -> HiveAiAnalysisPublic:
    """Convert one stored analysis row into the public response model."""
    detail = _detail(analysis)
    return HiveAiAnalysisPublic(
        id=analysis.id,
        hive_id=analysis.hive_id,
        hive_code=hive_code,
        analyzed_at=analysis.analyzed_at,
        window_start=analysis.window_start,
        window_end=analysis.window_end,
        sample_count=analysis.sample_count,
        newest_reading_at=analysis.newest_reading_at,
        data_quality=analysis.data_quality,
        data_quality_label=analysis.data_quality.label,
        analysis_source=str(analysis.analysis_source),
        analysis_source_label=analysis.analysis_source.label,
        model_type=analysis.model_type,
        model_version=analysis.model_version,
        health=to_health_assessment(analysis),
        disease_risk=to_risk_assessment(analysis, "disease_risk"),
        swarming_risk=to_risk_assessment(analysis, "swarming_risk"),
        yield_prediction=to_yield_prediction(analysis),
        recommendations=[AiRecommendation(**item) for item in detail.get("recommendations", [])],
        quality=to_quality_report(analysis),
        overall_confidence=analysis.overall_confidence,
        summary=detail.get("summary") or "",
        detail=detail,
    )


def to_insight(analysis, *, hive, meta: dict, freshness: dict) -> HiveAiInsight:
    """The read-through response for one hive, built from a stored analysis."""
    payload = to_analysis_public(analysis, hive_code=hive.hive_code)
    return HiveAiInsight(
        hive_id=hive.id,
        hive_code=hive.hive_code,
        analyzed=True,
        analysis_id=payload.id,
        analyzed_at=payload.analyzed_at,
        window_start=payload.window_start,
        window_end=payload.window_end,
        sample_count=payload.sample_count,
        newest_reading_at=payload.newest_reading_at,
        data_quality=payload.data_quality,
        data_quality_label=payload.data_quality_label,
        analysis_source=payload.analysis_source,
        analysis_source_label=payload.analysis_source_label,
        model_type=payload.model_type,
        model_version=payload.model_version,
        health=payload.health,
        disease_risk=payload.disease_risk,
        swarming_risk=payload.swarming_risk,
        yield_prediction=payload.yield_prediction,
        recommendations=payload.recommendations,
        quality=payload.quality,
        overall_confidence=payload.overall_confidence,
        summary=payload.summary,
        detail=payload.detail,
        computed=meta.get("computed", False),
        compute_reason=meta.get("reason", "read_only"),
        auto_analysis_enabled=meta.get("auto", True),
        freshness=freshness,
    )


def empty_insight(
    hive, *, meta: dict, freshness: dict, model_type: str, model_version: str
) -> HiveAiInsight:
    """The honest empty state: no assessment exists yet, and here is why.

    Used when auto-analysis is disabled or the caller may read but not analyse.
    No zeros are manufactured for the missing sections.
    """
    reason = meta.get("reason")
    summary = (
        "No AI analysis has been produced for this hive yet."
        if reason != "auto_disabled"
        else "Automatic analysis is disabled on this deployment, and no assessment has been "
        "generated for this hive yet."
    )
    return HiveAiInsight(
        hive_id=hive.id,
        hive_code=hive.hive_code,
        analyzed=False,
        model_type=model_type,
        model_version=model_version,
        summary=summary,
        computed=False,
        compute_reason=reason or "read_only",
        auto_analysis_enabled=meta.get("auto", True),
        freshness=freshness,
    )


def to_alert_public(alert, *, hive_code: str | None = None) -> AiAlertPublic:
    return AiAlertPublic(
        id=alert.id,
        hive_id=alert.hive_id,
        hive_code=hive_code,
        analysis_id=alert.analysis_id,
        alert_type=str(alert.alert_type),
        alert_type_label=alert.alert_type.label,
        severity=alert.severity,
        severity_label=alert.severity.label,
        title=alert.title,
        message=alert.message,
        metric=alert.metric,
        occurrences=alert.occurrences,
        first_seen_at=alert.first_seen_at,
        last_seen_at=alert.last_seen_at,
        status=alert.status,
        status_label=alert.status.label,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        context=alert.context or {},
    )


def to_summary_row(hive, analysis, *, open_alerts: int = 0, hive_code: str | None = None) -> HiveAiSummaryRow:
    """Row for the AI list screen: stored columns only, no payload parsing."""
    code = hive_code or getattr(hive, "hive_code", "") or str(hive.id)
    if analysis is None:
        return HiveAiSummaryRow(
            hive_id=hive.id,
            hive_code=code,
            status=str(getattr(hive, "status", "")),
            analyzed=False,
            open_alerts=open_alerts,
        )
    detail = _detail(analysis)
    return HiveAiSummaryRow(
        hive_id=hive.id,
        hive_code=code,
        status=str(getattr(hive, "status", "")),
        analyzed=True,
        analyzed_at=analysis.analyzed_at,
        is_stale=False,
        data_quality=analysis.data_quality,
        data_quality_label=analysis.data_quality.label,
        analysis_source=str(analysis.analysis_source),
        analysis_source_label=analysis.analysis_source.label,
        sample_count=analysis.sample_count,
        health_score=analysis.health_score,
        health_status=analysis.health_status,
        health_status_label=analysis.health_status.label,
        health_confidence=analysis.health_confidence,
        disease_risk_level=analysis.disease_risk_level,
        disease_risk_score=analysis.disease_risk_score,
        swarming_risk_level=analysis.swarming_risk_level,
        swarming_risk_score=analysis.swarming_risk_score,
        predicted_yield_kg=float(analysis.predicted_yield_kg)
        if analysis.predicted_yield_kg is not None
        else None,
        yield_period_days=analysis.yield_period_days,
        open_alerts=open_alerts,
        summary=detail.get("summary"),
    )


def to_run_result(hive, analysis, counters: dict) -> AiAnalysisRunResult:
    return AiAnalysisRunResult(
        hive_id=hive.id,
        hive_code=hive.hive_code,
        analysis_id=analysis.id,
        data_quality=analysis.data_quality,
        analysis_source=str(analysis.analysis_source),
        sample_count=analysis.sample_count,
        health_status=analysis.health_status,
        health_score=analysis.health_score,
        disease_risk_level=analysis.disease_risk_level,
        swarming_risk_level=analysis.swarming_risk_level,
        alerts_created=counters.get("created", 0),
        alerts_bumped=counters.get("bumped", 0),
        alerts_resolved=counters.get("resolved", 0),
        summary=(_detail(analysis).get("summary") or ""),
        computed_at=analysis.analyzed_at,
    )


__all__ = [
    "HEALTH_DISCLAIMER",
    "RISK_DISCLAIMER",
    "AiAlertPublic",
    "AiAlertSummary",
    "AiAnalysisRunResult",
    "AiAnomaly",
    "AiBulkRunResult",
    "AiEngineSummary",
    "AiFactor",
    "AiHealthAssessment",
    "AiModelInfo",
    "AiQualityReport",
    "AiRecommendation",
    "AiRiskAssessment",
    "AiYieldPrediction",
    "AlertActionRequest",
    "AlertQuery",
    "AnalysisRequest",
    "HiveAiAnalysisPublic",
    "HiveAiInsight",
    "HiveAiSummaryRow",
    "empty_insight",
    "to_alert_public",
    "to_analysis_public",
    "to_insight",
    "to_health_assessment",
    "to_quality_report",
    "to_risk_assessment",
    "to_run_result",
    "to_summary_row",
    "to_yield_prediction",
]

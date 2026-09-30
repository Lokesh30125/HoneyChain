"""Data types shared by the AI engine.

Everything here is a plain dataclass: the engine is a pure function from a set of
readings to an assessment, and nothing in it touches the database, FastAPI or the
session. That is what makes the scoring testable with hand-written series, and
what lets a trained model replace any one stage later without moving data around.

The vocabulary is deliberately hedged: an ``Anomaly`` is a *pattern outside the
reference band*, a ``RiskAssessment`` is a *risk*, and every result carries the
confidence and the evidence that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import (
    AiAlertSeverity,
    AiAlertType,
    AiAnalysisSource,
    AiDataQuality,
    AiHealthStatus,
    AiRiskLevel,
    AiTrend,
)

#: Sensor keys the engine reads. ``battery_level``/``signal_strength`` are device
#: health, not colony measurements, so they are used for data quality only.
COLONY_SENSORS = ("temperature", "humidity", "weight", "vibration", "acoustic_level")

#: Human labels used in factors, anomalies and alert messages.
SENSOR_LABELS = {
    "temperature": "Temperature",
    "humidity": "Humidity",
    "weight": "Hive weight",
    "vibration": "Vibration",
    "acoustic_level": "Acoustic activity",
}


@dataclass(slots=True)
class SensorStats:
    """Descriptive statistics for one sensor over the analysis window.

    Every field is derived from stored readings. ``current`` is the newest
    non-null value, not a carried-forward or interpolated one.
    """

    key: str
    unit: str
    samples: int = 0
    current: float | None = None
    mean: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    spread: float | None = None  # population standard deviation
    trend_per_hour: float | None = None  # least-squares slope
    change_over_window: float | None = None  # last - first
    change_last_24h: float | None = None
    deviation_from_mean: float | None = None  # current - mean
    baseline: float | None = None  # mean of everything before the recent slice
    recent_mean: float | None = None  # mean of the most recent 6 hours
    recent_vs_baseline: float | None = None  # recent_mean / baseline, ratio
    diurnal_amplitude: float | None = None  # max-min over daily buckets
    first_at: datetime | None = None
    last_at: datetime | None = None

    @property
    def has_data(self) -> bool:
        return self.samples > 0 and self.current is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "unit": self.unit,
            "samples": self.samples,
            "current": _round(self.current),
            "mean": _round(self.mean),
            "minimum": _round(self.minimum),
            "maximum": _round(self.maximum),
            "spread": _round(self.spread),
            "trend_per_hour": _round(self.trend_per_hour, 4),
            "change_over_window": _round(self.change_over_window),
            "change_last_24h": _round(self.change_last_24h),
            "deviation_from_mean": _round(self.deviation_from_mean),
            "recent_vs_baseline": _round(self.recent_vs_baseline, 3),
            "diurnal_amplitude": _round(self.diurnal_amplitude),
            "first_at": self.first_at.isoformat() if self.first_at else None,
            "last_at": self.last_at.isoformat() if self.last_at else None,
        }


@dataclass(slots=True)
class FeatureSet:
    """Everything the assessments are allowed to look at.

    Built once per analysis and passed to every stage, so health, disease,
    swarming and yield all reason about the same numbers — a score can never
    disagree with the factor list shown next to it.
    """

    window_start: datetime | None = None
    window_end: datetime | None = None
    sample_count: int = 0
    covered_hours: float = 0.0
    sensors: dict[str, SensorStats] = field(default_factory=dict)

    #: Derived relationships between sensors (kept explicit so the engine never
    #: recomputes them with slightly different arithmetic in two places).
    weight_gain_per_day: float | None = None
    humidity_temperature_ratio: float | None = None
    activity_index: float | None = None  # combined vibration + acoustic level
    activity_trend: AiTrend = AiTrend.UNKNOWN
    weight_trend: AiTrend = AiTrend.UNKNOWN
    temperature_trend: AiTrend = AiTrend.UNKNOWN
    humidity_trend: AiTrend = AiTrend.UNKNOWN

    def stats(self, key: str) -> SensorStats | None:
        return self.sensors.get(key)

    def value(self, key: str) -> float | None:
        stats = self.sensors.get(key)
        return stats.current if stats else None

    @property
    def sensors_with_data(self) -> list[str]:
        return [key for key, stats in self.sensors.items() if stats.has_data]

    def as_dict(self) -> dict[str, Any]:
        """Compact, JSON-safe summary persisted with the analysis.

        The full series is not stored — it is already in ``sensor_readings`` —
        but these numbers are what a factor or an anomaly quoted, and keeping
        them makes an old assessment readable without replaying the window.
        """
        return {
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "sample_count": self.sample_count,
            "covered_hours": round(self.covered_hours, 2),
            "sensors": {key: stats.as_dict() for key, stats in self.sensors.items()},
            "derived": {
                "weight_gain_per_day": _round(self.weight_gain_per_day),
                "humidity_temperature_ratio": _round(self.humidity_temperature_ratio, 3),
                "activity_index": _round(self.activity_index, 3),
                "activity_trend": str(self.activity_trend),
                "weight_trend": str(self.weight_trend),
                "temperature_trend": str(self.temperature_trend),
                "humidity_trend": str(self.humidity_trend),
            },
        }


@dataclass(slots=True)
class QualityReport:
    """What the telemetry can and cannot support.

    ``factor`` (0–1) is the multiplier applied to every confidence the engine
    reports, so a thin or stale window produces a low-confidence answer rather
    than a confident wrong one.
    """

    level: AiDataQuality = AiDataQuality.INSUFFICIENT
    factor: float = 0.0
    source: AiAnalysisSource = AiAnalysisSource.NO_DATA
    sample_count: int = 0
    covered_hours: float = 0.0
    expected_samples: int | None = None
    coverage: float | None = None
    newest_reading_at: datetime | None = None
    newest_age_minutes: float | None = None
    is_stale: bool = False
    device_online: bool | None = None
    device_status: str | None = None
    missing_sensors: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    suspect_jumps: int = 0
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": str(self.level),
            "source": str(self.source),
            "sample_count": self.sample_count,
            "covered_hours": round(self.covered_hours, 2),
            "expected_samples": self.expected_samples,
            "coverage": _round(self.coverage, 3),
            "newest_reading_at": self.newest_reading_at.isoformat()
            if self.newest_reading_at
            else None,
            "newest_age_minutes": _round(self.newest_age_minutes, 1),
            "is_stale": self.is_stale,
            "device_online": self.device_online,
            "device_status": self.device_status,
            "missing_sensors": self.missing_sensors,
            "suspect_jumps": self.suspect_jumps,
            "issues": self.issues,
            "confidence_factor": _round(self.factor, 3),
            "summary": self.summary,
        }


@dataclass(slots=True)
class Contribution:
    """One piece of evidence behind a score, with the deltas it caused.

    ``delta`` is the points this factor added to (or removed from) the score, so
    the UI can show *why* a number came out where it did instead of presenting a
    black box.
    """

    code: str
    label: str
    detail: str
    direction: str  # POSITIVE | NEGATIVE | NEUTRAL
    delta: float
    sensors: list[str] = field(default_factory=list)
    value: float | None = None
    reference: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "detail": self.detail,
            "direction": self.direction,
            "delta": _round(self.delta, 1),
            "sensors": list(self.sensors),
            "value": _round(self.value),
            "reference": self.reference,
        }


@dataclass(slots=True)
class Anomaly:
    """A pattern outside the reference band — never a diagnosis."""

    code: str
    label: str
    detail: str
    severity: AiAlertSeverity
    sensors: list[str] = field(default_factory=list)
    value: float | None = None
    reference: str | None = None
    weight: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "detail": self.detail,
            "severity": str(self.severity),
            "sensors": list(self.sensors),
            "value": _round(self.value),
            "reference": self.reference,
            "weight": _round(self.weight, 1),
        }


@dataclass(slots=True)
class Recommendation:
    """An action, tied to the evidence that produced it."""

    code: str
    title: str
    detail: str
    priority: str = "ROUTINE"  # ROUTINE | SOON | PRIORITY
    reason: str = ""
    sensors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "priority": self.priority,
            "reason": self.reason,
            "sensors": list(self.sensors),
        }


@dataclass(slots=True)
class HealthAssessment:
    """Colony health indicator (0–100) with its evidence."""

    score: int | None
    status: AiHealthStatus
    confidence: int
    trend: AiTrend = AiTrend.UNKNOWN
    factors: list[Contribution] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    summary: str = ""
    basis: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "status": str(self.status),
            "status_label": self.status.label,
            "confidence": self.confidence,
            "trend": str(self.trend),
            "summary": self.summary,
            "basis": self.basis,
            "factors": [factor.as_dict() for factor in self.factors],
            "anomalies": [anomaly.as_dict() for anomaly in self.anomalies],
        }


@dataclass(slots=True)
class RiskAssessment:
    """Disease or swarming risk — a risk band, never a confirmation."""

    score: int | None
    level: AiRiskLevel
    confidence: int
    indicators: list[Contribution] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    recommendation: Recommendation | None = None
    summary: str = ""
    disclaimer: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": str(self.level),
            "level_label": self.level.label,
            "confidence": self.confidence,
            "summary": self.summary,
            "disclaimer": self.disclaimer,
            "indicators": [indicator.as_dict() for indicator in self.indicators],
            "anomalies": [anomaly.as_dict() for anomaly in self.anomalies],
            "recommendation": self.recommendation.as_dict() if self.recommendation else None,
        }


@dataclass(slots=True)
class YieldPrediction:
    """Projected stored-honey mass from the measured weight trend.

    ``unit`` and ``period_days`` travel with the number because "12.8" is
    meaningless without them, and the UI must render both.
    """

    predicted_kg: float | None
    unit: str = "kg"
    confidence: int = 0
    trend: AiTrend = AiTrend.UNKNOWN
    period_days: int | None = None
    basis: str = ""
    factors: list[Contribution] = field(default_factory=list)
    summary: str = ""
    available: bool = False
    #: Slope the projection is built on (kg/day) and how well the line fits (r²).
    gain_per_day: float | None = None
    fit: float | None = None
    #: Why there is no projection, in words, or the caveats that qualify one.
    reason: str | None = None
    notes: list[str] = field(default_factory=list)
    #: How much of the trailing period the fit actually covers (0–1).
    completeness: float | None = None
    observed_days: float | None = None
    samples: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "predicted_yield": _round(self.predicted_kg, 2),
            "unit": self.unit,
            "confidence": self.confidence,
            "trend": str(self.trend),
            "trend_label": self.trend.label,
            "period_days": self.period_days,
            "gain_per_day": _round(self.gain_per_day, 3),
            "fit": _round(self.fit, 3),
            "completeness": _round(self.completeness, 3),
            "observed_days": _round(self.observed_days, 1),
            "samples": self.samples,
            "reason": self.reason,
            "notes": list(self.notes),
            "summary": self.summary,
            "basis": self.basis,
            "factors": [factor.as_dict() for factor in self.factors],
        }


@dataclass(slots=True)
class AlertSpec:
    """A signal worth a beekeeper's attention, produced by the engine.

    The engine decides *what* is worth raising; ``AlertService`` decides whether
    it is new, a repeat, or already handled.
    """

    alert_type: AiAlertType
    severity: AiAlertSeverity
    title: str
    message: str
    metric: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnalysisResult:
    """The complete output of one analysis run, before it is persisted."""

    health: HealthAssessment
    disease: RiskAssessment
    swarming: RiskAssessment
    yield_prediction: YieldPrediction
    recommendations: list[Recommendation]
    features: FeatureSet
    quality: QualityReport
    alerts: list[AlertSpec] = field(default_factory=list)
    model_type: str = ""
    model_version: str = ""
    analyzed_at: datetime | None = None
    overall_confidence: int = 0
    #: Hive the analysis was computed for, and the one-line summary a dashboard
    #: can print without reinterpreting the numbers.
    hive_id: int | None = None
    hive_code: str | None = None
    summary: str = ""

    @property
    def has_prediction(self) -> bool:
        return self.quality.level is not AiDataQuality.INSUFFICIENT

    def as_detail(self) -> dict[str, Any]:
        """The explanation payload stored on the analysis row."""
        return {
            "summary": self.summary or self.health.summary,
            "health": self.health.as_dict(),
            "disease_risk": self.disease.as_dict(),
            "swarming_risk": self.swarming.as_dict(),
            "yield_prediction": self.yield_prediction.as_dict(),
            "recommendations": [item.as_dict() for item in self.recommendations],
            "features": self.features.as_dict(),
            "quality": self.quality.as_dict(),
            "alerts_raised": [
                {
                    "type": str(spec.alert_type),
                    "severity": str(spec.severity),
                    "title": spec.title,
                }
                for spec in self.alerts
            ],
            "model": {"type": self.model_type, "version": self.model_version},
        }


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


__all__ = [
    "COLONY_SENSORS",
    "SENSOR_LABELS",
    "AlertSpec",
    "AnalysisResult",
    "Anomaly",
    "Contribution",
    "FeatureSet",
    "HealthAssessment",
    "QualityReport",
    "Recommendation",
    "RiskAssessment",
    "SensorStats",
    "YieldPrediction",
]

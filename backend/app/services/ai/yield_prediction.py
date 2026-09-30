"""Yield projection.

The projection is an extrapolation, and it is presented as one
at every layer of the platform:

* it needs real *duration* — ``AI_YIELD_MIN_DAYS`` of history and
  ``AI_YIELD_MIN_SAMPLES`` readings — before it will produce a number at all;
* it is a straight line fitted to the recorded weight series over the last
  ``AI_YIELD_PERIOD_DAYS`` days, projected forward and clamped to a plausible
  range, never a harvest promise;
* it says how well the line fits (``r²``) and how much of the window had weight
  data (``completeness``), so a beekeeper can judge it;
* it is reported per period, not per hive-season, and the API labels the field
  "projected" alongside the assumption list.

If a hive has no weight sensor, or the weight series is too short, the answer is
``None`` plus a plain-language reason — not zero, and not a national average.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.models.enums import AiDataQuality, AiTrend
from app.models.sensor_reading import SensorReading
from app.services.ai import thresholds as T
from app.services.ai.quality import cap_confidence
from app.services.ai.types import FeatureSet, QualityReport, YieldPrediction


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _weight_series(
    readings: Sequence[SensorReading], *, since: datetime
) -> tuple[list[datetime], list[float]]:
    moments: list[datetime] = []
    values: list[float] = []
    for reading in readings:
        value = reading.weight
        moment = _as_utc(reading.timestamp)
        if value is None or moment is None or moment < since:
            continue
        moments.append(moment)
        values.append(float(value))
    return moments, values


def _slope(moments: Sequence[datetime], values: Sequence[float]) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    origin = moments[0]
    hours = [(moment - origin).total_seconds() / 3600.0 for moment in moments]
    if max(hours) - min(hours) <= 0:
        return None, None

    count = len(hours)
    mean_x = sum(hours) / count
    mean_y = sum(values) / count
    denominator = sum((x - mean_x) ** 2 for x in hours)
    if denominator == 0:
        return None, None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(hours, values, strict=True)) / denominator
    intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for y in values)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(hours, values, strict=True))
    r_squared = 1.0 - (residual / total) if total > 0 else None
    return slope, r_squared


def _trend(gain_per_day: float | None) -> AiTrend:
    if gain_per_day is None:
        return AiTrend.UNKNOWN
    if gain_per_day > 0.02:
        return AiTrend.RISING
    if gain_per_day < -0.02:
        return AiTrend.FALLING
    return AiTrend.STABLE


def project_yield(
    readings: Sequence[SensorReading],
    features: FeatureSet,
    quality: QualityReport,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> YieldPrediction:
    """Fit the weight series and project it forward, or explain why not."""
    now = _as_utc(now) or datetime.now(timezone.utc)
    period_days = settings.AI_YIELD_PERIOD_DAYS
    prediction = YieldPrediction(
        predicted_kg=None,
        confidence=0,
        trend=AiTrend.UNKNOWN,
        period_days=period_days,
        basis=(
            "Straight-line fit to the recorded hive weight over the trailing period, projected "
            "forward. An extrapolation of stored weight change — not a harvest guarantee."
        ),
    )

    weight_stats = features.stats("weight")
    if weight_stats is None or not weight_stats.has_data:
        prediction.reason = "This hive has no weight readings in the window, so no projection is possible."
        return prediction

    if quality.level is AiDataQuality.INSUFFICIENT:
        prediction.reason = "Not enough telemetry yet to project a yield."
        return prediction

    if features.covered_hours < settings.AI_YIELD_MIN_DAYS * 24:
        prediction.reason = (
            f"Weight history covers {features.covered_hours / 24:.1f} days; at least "
            f"{settings.AI_YIELD_MIN_DAYS} days are needed before a projection is meaningful."
        )
        return prediction

    since = now - timedelta(days=period_days)
    moments, values = _weight_series(readings, since=since)
    if len(values) < settings.AI_YIELD_MIN_SAMPLES:
        prediction.reason = (
            f"Only {len(values)} weight reading(s) fall inside the last {period_days} days; at "
            f"least {settings.AI_YIELD_MIN_SAMPLES} are needed."
        )
        return prediction

    slope_per_hour, r_squared = _slope(moments, values)
    if slope_per_hour is None:
        prediction.reason = "The weight readings share a single timestamp, so no trend can be fitted."
        return prediction

    observed_days = (moments[-1] - moments[0]).total_seconds() / 86400.0
    if observed_days <= 0:
        prediction.reason = "The weight readings share a single timestamp, so no trend can be fitted."
        return prediction

    gain_per_day = slope_per_hour * 24.0
    if abs(gain_per_day) > T.YIELD_MAX_DAILY_GAIN:
        # A scale reading a multi-kilogram change per day is a refit, a super
        # being added or a disturbed sensor — not nectar. Refuse rather than
        # project an artefact forward for a month.
        prediction.reason = (
            f"The fitted weight trend ({gain_per_day:+.2f} kg/day) is outside the plausible range "
            "for honey accumulation, which usually means the scale was disturbed or a box was "
            "added or removed inside the window."
        )
        return prediction

    fit = None if r_squared is None else round(max(0.0, min(1.0, r_squared)), 2)
    if fit is None or fit < T.YIELD_MIN_FIT:
        prediction.reason = (
            "The weight series does not follow a steady enough trend to project: the fitted line "
            f"explains {(fit or 0.0) * 100:.0f} % of the variation, below the "
            f"{T.YIELD_MIN_FIT * 100:.0f} % needed."
        )
        return prediction

    completeness = min(1.0, observed_days / period_days)
    prediction.trend = _trend(gain_per_day)
    prediction.gain_per_day = round(gain_per_day, 3)
    prediction.fit = fit
    prediction.observed_days = round(observed_days, 1)
    prediction.samples = len(values)
    prediction.completeness = round(completeness, 2)

    raw = (
        30.0
        + 30.0 * fit
        + 25.0 * completeness
        + 15.0 * min(1.0, len(values) / (settings.AI_YIELD_MIN_SAMPLES * 3))
    )
    prediction.confidence = cap_confidence(raw, quality)
    if prediction.confidence < T.CONFIDENCE_FLOOR_FOR_PREDICTION:
        prediction.reason = (
            "The history and fit are too weak to publish a projection for this hive yet."
        )
        return prediction

    prediction.predicted_kg = round(max(0.0, gain_per_day * period_days), 2)
    if prediction.confidence < 40:
        prediction.notes.append(
            "The fit and history are weak, so treat this as a rough indication only."
        )
    if prediction.predicted_kg == 0.0:
        prediction.notes.append(
            "The fitted trend is flat or negative, so no accumulation is projected for the period."
        )

    prediction.available = True
    if gain_per_day < 0:
        prediction.summary = (
            f"Weight is trending down at about {abs(gain_per_day):.2f} kg/day, so no accumulation "
            f"is projected over the next {prediction.period_days} days."
        )
    else:
        prediction.summary = (
            f"Projected weight change of about {prediction.predicted_kg:.2f} kg over "
            f"{prediction.period_days} days, from a fit over {prediction.observed_days:.1f} days of "
            "weight readings."
        )
    return prediction


__all__ = ["project_yield"]

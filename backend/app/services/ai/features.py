"""Feature extraction — turns stored readings into the numbers the AI reasons about.

This module is the only place that touches raw ``SensorReading`` objects. It is a
pure function of the series and a clock: no session, no settings lookups inside
the maths, no hidden state.

What it produces (per sensor)
-----------------------------
``current`` · ``mean`` · ``minimum`` · ``maximum`` · ``spread`` (standard
deviation) · ``trend_per_hour`` (least-squares slope) · ``change_over_window`` ·
``change_last_24h`` · ``deviation_from_mean`` · ``baseline`` / ``recent_mean`` and
their ratio · ``diurnal_amplitude``

…plus cross-sensor features: weight gain per day, a humidity/temperature
relationship, a combined activity index and the trend of each of those.

Three rules the code holds to:

1. **Nothing is invented.** A sensor with no readings yields a ``SensorStats``
   with ``samples == 0``; no value is interpolated, carried forward or defaulted
   to a "typical" hive number. A missing sensor lowers confidence instead.
2. **Missing values inside a packet are skipped, not treated as zero.** A device
   that reports temperature but not weight produces a temperature series only.
3. **Time is respected.** Gaps matter: a slope over six samples spread across two
   hours is not the same evidence as six samples across six days, which is why
   ``covered_hours`` travels with the features.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone

from app.models.sensor_reading import SensorReading
from app.models.enums import AiTrend
from app.services.ai.thresholds import RECENT_WINDOW_HOURS, SENSOR_UNITS
from app.services.ai.types import COLONY_SENSORS, FeatureSet, SensorStats

#: A slope smaller than this (in the sensor's own units per hour) is noise, not a
#: trend — reported as STABLE rather than as a meaningless rise or fall.
_TREND_EPSILON = {
    "temperature": 0.05,
    "humidity": 0.15,
    "weight": 0.005,
    "vibration": 0.01,
    "acoustic_level": 0.05,
}


def _to_float(value: object) -> float | None:
    """Decimal → float, ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _stddev(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _slope_per_hour(
    moments: Sequence[datetime], values: Sequence[float]
) -> tuple[float | None, float | None]:
    """Least-squares slope, and the R² of that fit.

    Returns ``(slope_per_hour, r_squared)``. Both ``None`` when there are fewer
    than two distinct instants — a trend cannot be estimated from one point, and
    pretending otherwise is exactly the failure mode this engine must avoid.
    """
    if len(values) < 2 or len(moments) != len(values):
        return None, None

    origin = moments[0]
    hours = [(moment - origin).total_seconds() / 3600.0 for moment in moments]
    if max(hours) - min(hours) <= 0:
        return None, None

    count = len(hours)
    mean_x = sum(hours) / count
    mean_y = sum(values) / count
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(hours, values, strict=True))
    denominator = sum((x - mean_x) ** 2 for x in hours)
    if denominator == 0:
        return None, None

    slope = numerator / denominator
    intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for y in values)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(hours, values, strict=True))
    r_squared = 1.0 - (residual / total) if total > 0 else None
    return slope, r_squared


def _diurnal_amplitude(
    pairs: Iterable[tuple[datetime, float]], window_hours: float
) -> float | None:
    """Largest day-over-day swing in the series.

    Buckets by UTC day and returns the widest ``max - min`` inside any single
    bucket. Needs at least two days of history to say anything at all.
    """
    buckets: dict[object, list[float]] = {}
    for moment, value in pairs:
        buckets.setdefault(moment.date(), []).append(value)
    if len(buckets) < 2:
        return None
    return max(max(values) - min(values) for values in buckets.values() if len(values) >= 2)


def _series(
    readings: Sequence[SensorReading], key: str
) -> tuple[list[datetime], list[float]]:
    """Ordered ``(timestamps, values)`` for one sensor, skipping nulls."""
    moments: list[datetime] = []
    values: list[float] = []
    for reading in readings:
        value = _to_float(getattr(reading, key, None))
        moment = _as_utc(reading.timestamp)
        if value is None or moment is None:
            continue
        moments.append(moment)
        values.append(value)
    return moments, values


def _stats_for(key: str, readings: Sequence[SensorReading], *, now: datetime) -> SensorStats:
    moments, values = _series(readings, key)
    stats = SensorStats(key=key, unit=SENSOR_UNITS.get(key, ""))
    stats.samples = len(values)
    if not values:
        return stats

    stats.current = values[-1]
    stats.mean = _mean(values)
    stats.minimum = min(values)
    stats.maximum = max(values)
    stats.spread = _stddev(values)
    stats.trend_per_hour, _ = _slope_per_hour(moments, values)
    stats.change_over_window = values[-1] - values[0]
    stats.deviation_from_mean = (
        values[-1] - stats.mean if stats.mean is not None else None
    )
    stats.first_at = moments[0]
    stats.last_at = moments[-1]

    # Last 24 hours, when the window reaches back that far.
    cutoff = now - timedelta(hours=24)
    recent_day = [value for moment, value in zip(moments, values, strict=True) if moment >= cutoff]
    if len(recent_day) >= 2:
        stats.change_last_24h = recent_day[-1] - recent_day[0]

    # "Recent behaviour vs the rest of the window" — the shape both the activity
    # and the temperature checks care about.
    recent_cutoff = now - timedelta(hours=RECENT_WINDOW_HOURS)
    recent = [value for moment, value in zip(moments, values, strict=True) if moment >= recent_cutoff]
    earlier = [value for moment, value in zip(moments, values, strict=True) if moment < recent_cutoff]
    stats.recent_mean = _mean(recent)
    stats.baseline = _mean(earlier)
    if stats.recent_mean is not None and stats.baseline not in (None, 0):
        stats.recent_vs_baseline = stats.recent_mean / stats.baseline

    stats.diurnal_amplitude = _diurnal_amplitude(zip(moments, values, strict=True), 0)
    return stats


def _trend_of(stats: SensorStats | None) -> AiTrend:
    if stats is None or stats.trend_per_hour is None or stats.samples < 3:
        return AiTrend.UNKNOWN
    epsilon = _TREND_EPSILON.get(stats.key, 0.01)
    if stats.trend_per_hour > epsilon:
        return AiTrend.RISING
    if stats.trend_per_hour < -epsilon:
        return AiTrend.FALLING
    return AiTrend.STABLE


def extract_features(
    readings: Sequence[SensorReading],
    *,
    now: datetime,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> FeatureSet:
    """Build the ``FeatureSet`` for one hive's window.

    ``readings`` must already be ordered oldest → newest and already restricted
    to the window; the caller (``AiService``) owns that query because it also
    needs the row count for the data-quality report.
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    ordered = sorted(readings, key=lambda reading: _as_utc(reading.timestamp) or now)

    features = FeatureSet(
        window_start=_as_utc(window_start) or (_as_utc(ordered[0].timestamp) if ordered else None),
        window_end=_as_utc(window_end) or (_as_utc(ordered[-1].timestamp) if ordered else None),
        sample_count=len(ordered),
    )

    moments = [_as_utc(reading.timestamp) for reading in ordered]
    stamps = [moment for moment in moments if moment is not None]
    if len(stamps) >= 2:
        features.covered_hours = (stamps[-1] - stamps[0]).total_seconds() / 3600.0

    features.sensors = {key: _stats_for(key, ordered, now=now) for key in COLONY_SENSORS}

    temperature = features.sensors["temperature"]
    humidity = features.sensors["humidity"]
    weight = features.sensors["weight"]
    vibration = features.sensors["vibration"]
    acoustic = features.sensors["acoustic_level"]

    # -- Derived cross-sensor features --------------------------------------
    weight_moments, weight_values = _series(ordered, "weight")
    if len(weight_values) >= 3:
        slope_per_hour, _ = _slope_per_hour(weight_moments, weight_values)
        if slope_per_hour is not None:
            features.weight_gain_per_day = slope_per_hour * 24.0

    if temperature and humidity and temperature.current and humidity.current:
        # A ratio, not a dew point: it says "damp for this temperature", which is
        # the pattern a mould/brood-chill discussion starts from.
        features.humidity_temperature_ratio = humidity.current / temperature.current

    # Activity: vibration and acoustic are different units, so each is scaled by
    # the level that count as "busy" for its own sensor before being combined.
    activity_parts: list[float] = []
    if vibration and vibration.current is not None:
        activity_parts.append(vibration.current / 1.5)
    if acoustic and acoustic.current is not None:
        activity_parts.append(acoustic.current / 45.0)
    if activity_parts:
        features.activity_index = sum(activity_parts) / len(activity_parts)

    activity_trends = [
        _trend_of(sensor)
        for sensor in (vibration, acoustic)
        if sensor is not None and sensor.has_data
    ]
    features.activity_trend = activity_trends[0] if activity_trends else AiTrend.UNKNOWN
    if len(set(activity_trends)) == 1 and activity_trends:
        features.activity_trend = activity_trends[0]

    features.weight_trend = _trend_of(weight)
    features.temperature_trend = _trend_of(temperature)
    features.humidity_trend = _trend_of(humidity)
    return features


__all__ = ["extract_features"]

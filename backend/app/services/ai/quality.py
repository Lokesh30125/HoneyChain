"""Data quality — deciding what the telemetry can and cannot support.

The engine's whole value rests on this module. A confident-sounding health score
derived from four packets, or a yield projection from a device that stopped
reporting three days ago, would be worse than no answer at all — so every
analysis starts by asking:

* **Is there any telemetry?** No readings → ``INSUFFICIENT``, and the API says
  "AI analysis unavailable — no telemetry data."
* **Is there *history*, not just samples?** Ten packets inside one minute is not
  a trend. The window must span ``AI_MIN_HISTORY_HOURS`` as well as contain
  ``AI_MIN_SAMPLES`` readings.
* **Is it current?** A window whose newest reading is older than
  ``AI_STALE_AFTER_HOURS`` is reported stale, and the UI prints that instead of
  quietly showing yesterday's numbers.
* **Which sensors actually reported?** A device without a weight sensor can be
  assessed for temperature and humidity but cannot produce a yield projection.
* **Where did it come from?** ``REAL_DEVICE`` / ``SIMULATOR`` / ``MIXED`` /
  ``MANUAL`` is computed from the readings' own ``source`` column. Manual entry
  is not a device measurement, so it caps confidence hard; the engine never asks
  a beekeeper to type numbers in order to get a prediction.
* **Are there impossible jumps?** A step faster than the rate limit between
  consecutive readings is a suspect sample (probe glitch, refit, power event).
  It is counted, excluded from nothing silently — it lowers the quality factor
  so the conclusion is stated less confidently.

The output is a :class:`~app.services.ai.types.QualityReport` whose ``factor``
multiplies every confidence the engine reports.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.models.enums import AiAnalysisSource, AiDataQuality, TelemetrySource
from app.models.sensor_reading import SensorReading
from app.services.ai.thresholds import (
    CONFIDENCE_CEILING,
    MANUAL_SOURCE_CONFIDENCE_CAP,
    MAX_PLAUSIBLE_CHANGE_PER_MINUTE,
)
from app.services.ai.types import COLONY_SENSORS, FeatureSet, QualityReport

#: Coverage below this is reported as LIMITED even when the raw counts pass.
_COVERAGE_LIMITED = 0.6
#: Missing sensors: one is a limitation, this many is a hole in the picture.
_MISSING_SENSOR_LIMIT = 2

_SENSOR_PHRASES = {
    "temperature": "temperature",
    "humidity": "humidity",
    "weight": "weight",
    "vibration": "vibration",
    "acoustic_level": "acoustic activity",
}


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def detect_suspect_jumps(readings: Sequence[SensorReading]) -> int:
    """Count consecutive-sample changes faster than physically plausible.

    Compared per *minute* rather than per sample, so an irregular reporting
    cadence cannot turn a normal change into a false jump.
    """
    ordered = sorted(
        readings, key=lambda reading: _as_utc(reading.timestamp) or datetime.min.replace(tzinfo=timezone.utc)
    )
    jumps = 0
    for previous, current in zip(ordered, ordered[1:]):
        previous_at = _as_utc(previous.timestamp)
        current_at = _as_utc(current.timestamp)
        if previous_at is None or current_at is None:
            continue
        minutes = abs((current_at - previous_at).total_seconds()) / 60.0
        if minutes <= 0:
            continue
        for key, limit in MAX_PLAUSIBLE_CHANGE_PER_MINUTE.items():
            before = _number(getattr(previous, key, None))
            after = _number(getattr(current, key, None))
            if before is None or after is None:
                continue
            if abs(after - before) / minutes > limit:
                jumps += 1
                break
    return jumps


def resolve_source(readings: Sequence[SensorReading]) -> AiAnalysisSource:
    """Which telemetry sources the window actually contains."""
    if not readings:
        return AiAnalysisSource.NO_DATA

    seen = {str(getattr(reading.source, "value", reading.source)) for reading in readings}
    hardware = TelemetrySource.REAL_DEVICE.value in seen
    simulator = TelemetrySource.SIMULATOR.value in seen
    manual = TelemetrySource.MANUAL.value in seen

    if len(seen) > 1:
        return AiAnalysisSource.MIXED
    if hardware:
        return AiAnalysisSource.REAL_DEVICE
    if simulator:
        return AiAnalysisSource.SIMULATOR
    if manual:
        return AiAnalysisSource.MANUAL
    return AiAnalysisSource.NO_DATA  # pragma: no cover - unknown enum value


def _expected_samples(
    readings: Sequence[SensorReading], *, covered_hours: float, sampling_seconds: int | None
) -> int | None:
    """How many readings the cadence suggests for this window."""
    if sampling_seconds is None or sampling_seconds <= 0:
        return None
    if covered_hours <= 0:
        return None
    return max(1, int(covered_hours * 3600 / sampling_seconds))


def assess_quality(
    readings: Sequence[SensorReading],
    features: FeatureSet,
    *,
    settings: Settings,
    now: datetime,
    newest_reading_at: datetime | None = None,
    device_status: str | None = None,
    sampling_seconds: int | None = None,
    has_device: bool = True,
) -> QualityReport:
    """Grade the evidence and explain every limitation in words."""
    now = _as_utc(now) or datetime.now(timezone.utc)
    report = QualityReport(
        sample_count=len(readings),
        covered_hours=features.covered_hours,
    )
    report.source = resolve_source(readings)
    report.device_status = device_status
    report.device_online = None if device_status is None else device_status == "ONLINE"

    newest = _as_utc(newest_reading_at) or max(
        (_as_utc(reading.timestamp) for reading in readings if reading.timestamp is not None),
        default=None,
    )
    report.newest_reading_at = newest
    if newest is not None:
        report.newest_age_minutes = (now - newest).total_seconds() / 60.0
        report.is_stale = (now - newest) > timedelta(hours=settings.AI_STALE_AFTER_HOURS)

    report.missing_sensors = [
        key for key in COLONY_SENSORS if not (features.stats(key) and features.stats(key).has_data)
    ]
    report.expected_samples = _expected_samples(
        readings, covered_hours=features.covered_hours, sampling_seconds=sampling_seconds
    )
    if report.expected_samples:
        report.coverage = min(1.0, len(readings) / report.expected_samples)
    report.suspect_jumps = detect_suspect_jumps(readings)

    issues: list[str] = []

    # -- Hard stops ----------------------------------------------------------
    if not readings:
        issues.append("No telemetry has been recorded for this hive.")
        if not has_device:
            issues.append("No IoT device is paired with this hive.")
        report.level = AiDataQuality.INSUFFICIENT
        report.factor = 0.0
        report.summary = (
            "AI analysis unavailable — no telemetry data."
            if has_device
            else "AI analysis unavailable — no device is paired with this hive."
        )
        report.issues = issues
        return report

    if len(readings) < settings.AI_MIN_SAMPLES:
        issues.append(
            f"Only {len(readings)} reading(s) are available; "
            f"{settings.AI_MIN_SAMPLES} are needed to describe a pattern."
        )

    if features.covered_hours < settings.AI_MIN_HISTORY_HOURS:
        issues.append(
            f"The window covers {features.covered_hours:.1f} h of history; "
            f"at least {settings.AI_MIN_HISTORY_HOURS} h are needed for a trend."
        )

    if len(readings) < settings.AI_MIN_SAMPLES or features.covered_hours < settings.AI_MIN_HISTORY_HOURS:
        report.level = AiDataQuality.INSUFFICIENT
        report.factor = 0.0
        report.summary = "AI analysis limited — more historical telemetry is required."
        report.issues = issues
        return report

    # -- Soft limitations ----------------------------------------------------
    if report.is_stale:
        age = report.newest_age_minutes or 0
        issues.append(
            f"The newest reading is {age / 60:.1f} h old, so the picture may have moved on."
        )
    if report.device_online is False:
        issues.append(
            f"The device is reported {report.device_status}, so the latest values may be stale."
        )
    if report.coverage is not None and report.coverage < _COVERAGE_LIMITED:
        issues.append(
            f"The window holds {len(readings)} readings of an expected {report.expected_samples} "
            f"({report.coverage * 100:.0f} % of the configured cadence)."
        )
    if len(report.missing_sensors) >= _MISSING_SENSOR_LIMIT:
        phrases = ", ".join(_SENSOR_PHRASES.get(key, key) for key in report.missing_sensors)
        issues.append(f"No readings for: {phrases}. Those checks are skipped, not estimated.")
    if report.suspect_jumps:
        issues.append(
            f"{report.suspect_jumps} change(s) between consecutive readings exceed the physically "
            "plausible rate and were treated as suspect samples."
        )

    limited = bool(
        report.is_stale
        or report.device_online is False
        or (report.coverage is not None and report.coverage < _COVERAGE_LIMITED)
        or report.suspect_jumps > 0
        or len(report.missing_sensors) >= _MISSING_SENSOR_LIMIT
    )
    report.level = AiDataQuality.LIMITED if limited else AiDataQuality.GOOD

    # -- Confidence factor ---------------------------------------------------
    # Composed from the raw counts rather than from a single flag, so a window
    # that is merely thin lands near 0.6 and one that is thin, stale and missing
    # sensors lands near 0.2.
    sample_factor = min(1.0, len(readings) / max(1, settings.AI_MIN_SAMPLES * 3))
    history_factor = min(1.0, features.covered_hours / max(1.0, settings.AI_MIN_HISTORY_HOURS * 8))
    coverage_factor = report.coverage if report.coverage is not None else 0.8
    sensor_factor = max(0.4, 1.0 - 0.15 * len(report.missing_sensors))
    freshness_factor = 0.4 if report.is_stale else (0.75 if report.device_online is False else 1.0)
    jump_factor = max(0.5, 1.0 - 0.1 * report.suspect_jumps)

    factor = (
        0.35 * sample_factor
        + 0.25 * history_factor
        + 0.2 * coverage_factor
        + 0.2 * freshness_factor
    ) * sensor_factor * jump_factor
    report.factor = max(0.05, min(1.0, factor))

    if report.source is AiAnalysisSource.MANUAL:
        issues.append(
            "Every reading in this window was entered by hand, not measured by a device."
        )
    elif report.source is AiAnalysisSource.MIXED:
        issues.append("The window mixes hardware, simulator and/or manual readings.")

    report.summary = (
        "Telemetry is sufficient for an assessment."
        if report.level is AiDataQuality.GOOD
        else "Assessment is based on incomplete telemetry — treat it as indicative."
    )
    report.issues = issues
    return report


def cap_confidence(confidence: float, report: QualityReport) -> int:
    """Apply the quality factor and the source rules to a raw confidence.

    Manual readings cannot support a device-grade conclusion however many there
    are, so they are capped explicitly rather than only through the factor.
    """
    value = min(confidence * report.factor, CONFIDENCE_CEILING)
    if report.source is AiAnalysisSource.NO_DATA:
        value = 0.0
    elif report.source is AiAnalysisSource.MANUAL:
        value = min(value, MANUAL_SOURCE_CONFIDENCE_CAP)
    return int(max(0, min(CONFIDENCE_CEILING, round(value))))


__all__ = ["assess_quality", "cap_confidence", "detect_suspect_jumps", "resolve_source"]

"""Recommendations — turning findings into things a beekeeper can actually do.

Three rules hold this module together:

1. **Every recommendation traces to a finding.** Each one carries ``reason``, and
   most carry the ``sensors`` or the indicator they came from. Nothing is emitted
   for a hive whose patterns are all in band.
2. **Advice is about the hive, not about the app.** "Inspect the brood nest",
   "check ventilation", "confirm the scale is level" — never "upgrade your plan"
   and never a chemical or medical instruction.
3. **Priority is honest.** ``ROUTINE`` (keep doing what you do), ``SOON`` (look
   within a few days), ``PRIORITY`` (look at the first opportunity). The engine
   never says "urgent" about a sensor reading.

Module-level helpers keep the individual bundles readable, and the engine decides
which ones apply.
"""

from __future__ import annotations

from app.core.config import Settings
from app.models.enums import (
    AiAlertSeverity,
    AiAlertType,
    AiAnalysisSource,
    AiDataQuality,
    AiRiskLevel,
)
from app.services.ai import thresholds as T
from app.services.ai.types import (
    AlertSpec,
    Anomaly,
    FeatureSet,
    HealthAssessment,
    QualityReport,
    Recommendation,
    RiskAssessment,
    YieldPrediction,
)

#: Order used to sort the final list. PRIORITY first, then SOON, then ROUTINE.
_PRIORITY_ORDER = {"PRIORITY": 0, "SOON": 1, "ROUTINE": 2}


def _quality_recommendations(quality: QualityReport, settings: Settings) -> list[Recommendation]:
    found: list[Recommendation] = []
    if quality.level is AiDataQuality.INSUFFICIENT:
        if quality.source is AiAnalysisSource.NO_DATA:
            found.append(
                Recommendation(
                    code="pair_device",
                    title="Pair an IoT device with this hive",
                    detail=(
                        "No device is reporting for this hive yet. Pair one from the IoT Monitoring "
                        "screen and telemetry will start flowing into these screens."
                    ),
                    priority="ROUTINE",
                    reason="No telemetry has ever been recorded for the hive.",
                )
            )
        else:
            found.append(
                Recommendation(
                    code="collect_more_telemetry",
                    title="Let telemetry accumulate before trusting an assessment",
                    detail=(
                        f"At least {settings.AI_MIN_SAMPLES} readings spanning "
                        f"{settings.AI_MIN_HISTORY_HOURS} hours are needed. Keep the device reporting "
                        "and check back."
                    ),
                    priority="ROUTINE",
                    reason="The current window is too small to describe a pattern.",
                )
            )
        return found

    if quality.is_stale:
        found.append(
            Recommendation(
                code="check_device_reporting",
                title="Check why the device stopped reporting",
                detail=(
                    "The newest reading is older than the staleness threshold. Check the device's "
                    "power and connectivity — the values shown here describe the past, not now."
                ),
                priority="SOON",
                reason=f"Newest reading is {(quality.newest_age_minutes or 0) / 60:.1f} h old.",
            )
        )
    elif quality.device_online is False:
        found.append(
            Recommendation(
                code="device_offline",
                title="Wake the device or confirm it is expected to be offline",
                detail=(
                    "The paired device is currently reported offline, so the latest values may be "
                    "out of date."
                ),
                priority="SOON",
                reason=f"Device status is {quality.device_status}.",
            )
        )

    if quality.suspect_jumps:
        found.append(
            Recommendation(
                code="verify_sensor_mount",
                title="Verify the sensor readings against the hive",
                detail=(
                    "Some consecutive readings changed faster than is physically plausible for a "
                    "hive — often a loose mount, a re-seated probe or a scale that was disturbed. "
                    "A quick visual check settles it."
                ),
                priority="ROUTINE",
                reason=f"{quality.suspect_jumps} implausible change(s) between consecutive readings.",
            )
        )
    return found


def _temperature_recommendations(features: FeatureSet, anomalies: list[Anomaly]) -> list[Recommendation]:
    codes = {anomaly.code for anomaly in anomalies}
    if "TEMPERATURE_OUT_OF_BAND" not in codes:
        return []
    stats = features.stats("temperature")
    mean = stats.mean if stats and stats.mean is not None else None
    hot = mean is not None and mean > T.TEMPERATURE_COMFORT[1]
    return [
        Recommendation(
            code="temperature_hot" if hot else "temperature_cold",
            title="Check shade and ventilation" if hot else "Check the hive's shelter and windbreak",
            detail=(
                "Look at how much direct sun and airflow the hive gets during the hottest part of "
                "the day, and whether the entrance is blocked."
                if hot
                else "Look at draughts, exposure and entrance size — a chill in the nest shows up "
                "first in the temperature trace."
            ),
            priority="SOON",
            reason=f"Mean nest temperature was {mean:.1f} °C, outside the reference band."
            if mean is not None
            else "Nest temperature sat outside the reference band.",
            sensors=["temperature"],
        )
    ]


def _humidity_recommendations(features: FeatureSet, anomalies: list[Anomaly]) -> list[Recommendation]:
    codes = {anomaly.code for anomaly in anomalies}
    if "HUMIDITY_OUT_OF_BAND" not in codes:
        return []
    stats = features.stats("humidity")
    mean = stats.mean if stats and stats.mean is not None else None
    damp = mean is not None and mean > T.HUMIDITY_COMFORT[1]
    return [
        Recommendation(
            code="humidity_high" if damp else "humidity_low",
            title="Check ventilation and moisture inside the hive" if damp else "Check the nectar flow and ventilation",
            detail=(
                "Persistently damp air is worth a look: check that the roof is sound, that the "
                "hive has airflow, and how the colony looks at the next inspection."
                if damp
                else "Air this dry is uncommon in a working colony — confirm the sensor is not "
                "sitting in a draught before reading much into it."
            ),
            priority="SOON" if damp else "ROUTINE",
            reason=f"Mean interior humidity was {mean:.1f} %, outside the reference band."
            if mean is not None
            else "Interior humidity sat outside the reference band.",
            sensors=["humidity"],
        )
    ]


def _weight_recommendations(features: FeatureSet, anomalies: list[Anomaly]) -> list[Recommendation]:
    codes = {anomaly.code for anomaly in anomalies}
    found: list[Recommendation] = []

    if "WEIGHT_DROP" in codes:
        found.append(
            Recommendation(
                code="weight_drop",
                title="Inspect the hive and the scale",
                detail=(
                    "Weight loss over a day can follow consumption, honey taken off, robbing or a "
                    "colony leaving. Check the scale is level and undisturbed, then look inside — "
                    "the reading alone cannot say which it was."
                ),
                priority="SOON",
                reason="The recorded weight fell sharply within the window.",
                sensors=["weight"],
            )
        )
    if "WEIGHT_STAGNATION" in codes:
        found.append(
            Recommendation(
                code="weight_stagnation",
                title="Review whether the colony has room and forage",
                detail=(
                    "Weight held flat across the window. If a nectar flow is on, that is worth a "
                    "look — check stores and space in the hive at the next inspection."
                ),
                priority="ROUTINE",
                reason="No measurable weight change across the window.",
                sensors=["weight"],
            )
        )
    gain = features.weight_gain_per_day
    # The upper bound matters as much as the lower one: a fitted gain of
    # hundreds of kilograms per day is a disturbed scale, and advising a super on
    # the back of it would be advice built on an artefact.
    if gain is not None and T.WEIGHT_DAILY_GAIN_GOOD * 2 <= gain <= T.YIELD_MAX_DAILY_GAIN:
        found.append(
            Recommendation(
                code="weight_gain",
                title="Consider adding a super",
                detail=(
                    "Weight is accumulating steadily. If the supers are close to full, the colony "
                    "may need room — check before it feels crowded."
                ),
                priority="ROUTINE",
                reason=f"Weight is rising about {gain:.2f} kg/day.",
                sensors=["weight"],
            )
        )
    return found


def _activity_recommendations(features: FeatureSet, anomalies: list[Anomaly]) -> list[Recommendation]:
    codes = {anomaly.code for anomaly in anomalies}
    found: list[Recommendation] = []
    if "ACTIVITY_SPIKE" in codes or "ACOUSTIC_ANOMALY" in codes:
        found.append(
            Recommendation(
                code="activity_spike",
                title="Observe the colony entrance",
                detail=(
                    "Watch entrance traffic at a busy time of day and look at the front of the hive. "
                    "Elevated activity can mean several things at once — the trace says it changed, "
                    "not why."
                ),
                priority="SOON",
                reason="Activity and/or acoustic level rose well above this hive's own baseline.",
                sensors=[sensor for sensor in ("vibration", "acoustic_level") if features.stats(sensor) and features.stats(sensor).has_data],
            )
        )
    if "ACTIVITY_SUPPRESSED" in codes:
        found.append(
            Recommendation(
                code="activity_suppressed",
                title="Compare with the neighbouring hives",
                detail=(
                    "This hive is quieter than its own baseline. A side-by-side glance at another "
                    "hive in the same apiary is the quickest way to judge whether that is the "
                    "weather or the colony."
                ),
                priority="SOON",
                reason="Activity fell below this hive's own baseline.",
                sensors=["vibration"],
            )
        )
    return found


def _health_recommendations(health: HealthAssessment) -> list[Recommendation]:
    found: list[Recommendation] = []
    if health.status.value in ("HEALTHY", "INSUFFICIENT_DATA") or health.score is None:
        return found

    status = health.status.value
    priority = "PRIORITY" if status == "CRITICAL" else ("SOON" if status == "AT_RISK" else "ROUTINE")
    top = [factor for factor in health.factors if factor.direction == "NEGATIVE"][:3]
    found.append(
        Recommendation(
            code="health_follow_up",
            title="Review the factors behind the health indicator",
            detail=(
                "The indicator is derived from the factors listed above it. Read them alongside "
                "the sensor charts and decide whether an inspection is warranted."
            ),
            priority=priority,
            reason=(
                "Factors that pulled the score down: "
                + "; ".join(factor.label.lower() for factor in top)
                + "."
                if top
                else "The health indicator is below the reference bands."
            ),
            sensors=sorted({sensor for factor in top for sensor in factor.sensors}),
        )
    )
    return found


def build_recommendations(
    features: FeatureSet,
    anomalies: list[Anomaly],
    quality: QualityReport,
    health: HealthAssessment,
    disease: RiskAssessment,
    swarming: RiskAssessment,
    yield_prediction: YieldPrediction,
    *,
    settings: Settings,
) -> list[Recommendation]:
    """Assemble, de-duplicate and order the recommendation list."""
    found: list[Recommendation] = []

    if quality.level is AiDataQuality.INSUFFICIENT:
        # A window this thin cannot describe a colony, so the only honest advice
        # is about the data itself. Suggesting "add a super" because a two-minute
        # weight series happened to slope upwards is exactly the fake insight this
        # phase exists to avoid.
        return _order(_quality_recommendations(quality, settings))

    found.extend(_quality_recommendations(quality, settings))
    found.extend(_temperature_recommendations(features, anomalies))
    found.extend(_humidity_recommendations(features, anomalies))
    found.extend(_weight_recommendations(features, anomalies))
    found.extend(_activity_recommendations(features, anomalies))
    found.extend(_health_recommendations(health))

    if disease.recommendation is not None:
        found.append(disease.recommendation)
    if swarming.recommendation is not None:
        found.append(swarming.recommendation)

    if yield_prediction.predicted_kg is not None and yield_prediction.trend.value == "RISING":
        found.append(
            Recommendation(
                code="yield_on_track",
                title="Plan for the projected harvest",
                detail=(
                    f"Weight patterns project about {yield_prediction.predicted_kg:.2f} kg over "
                    f"{yield_prediction.period_days} days. Treat it as an indication and arrange "
                    "extraction capacity accordingly."
                ),
                priority="ROUTINE",
                reason="A rising weight trend supports a yield projection.",
                sensors=["weight"],
            )
        )

    return _order(found)


def _order(found: list[Recommendation]) -> list[Recommendation]:
    """One entry per code, priority first — the order a reader should act in."""
    # One recommendation per code: a hive whose temperature is off-band should
    # see "check shade and ventilation" once, not once per contributing factor.
    unique: dict[str, Recommendation] = {}
    for recommendation in found:
        unique.setdefault(recommendation.code, recommendation)

    return sorted(
        unique.values(),
        key=lambda item: (_PRIORITY_ORDER.get(item.priority, 3), item.code),
    )


def alert_candidates(
    anomalies: list[Anomaly],
    health: HealthAssessment,
    disease: RiskAssessment,
    swarming: RiskAssessment,
    *,
    quality: QualityReport,
) -> list[AlertSpec]:
    """The small subset of findings worth an entry in the alerts list.

    Alerts are deliberately scarce: they are for things a beekeeper wants to know
    without opening the app. Everything else stays in the analysis payload as a
    factor, an indicator or a recommendation. De-duplication, cooldown and
    acknowledgement are the alert service's job, not the engine's.
    """
    candidates: list[AlertSpec] = []

    if health.status.value == "CRITICAL":
        candidates.append(
            AlertSpec(
                alert_type=AiAlertType.HEALTH_CRITICAL,
                severity=AiAlertSeverity.CRITICAL,
                title="Colony health indicator is critical",
                message=(
                    "Multiple strong deviations were recorded for this hive. Review the factors "
                    "listed with the analysis and inspect when you can."
                ),
                metric=f"health_score={health.score}",
                context={"health_status": health.status.value, "confidence": health.confidence},
            )
        )
    elif health.status.value == "AT_RISK":
        candidates.append(
            AlertSpec(
                alert_type=AiAlertType.HEALTH_AT_RISK,
                severity=AiAlertSeverity.WARNING,
                title="Colony health indicator is at risk",
                message="Several recorded patterns are outside the reference bands for this hive.",
                metric=f"health_score={health.score}",
                context={"health_status": health.status.value, "confidence": health.confidence},
            )
        )

    if disease.level is AiRiskLevel.HIGH and disease.score is not None:
        candidates.append(
            AlertSpec(
                alert_type=AiAlertType.DISEASE_RISK_HIGH,
                severity=AiAlertSeverity.WARNING,
                title="Disease risk indicators are elevated",
                message=(
                    "Several patterns associated with colony stress were recorded together. This "
                    "is a prompt to inspect, not a diagnosis."
                ),
                metric=f"disease_risk={disease.score}",
                context={"level": disease.level.value, "confidence": disease.confidence},
            )
        )

    if swarming.level is AiRiskLevel.HIGH and swarming.score is not None:
        candidates.append(
            AlertSpec(
                alert_type=AiAlertType.SWARMING_RISK_HIGH,
                severity=AiAlertSeverity.WARNING,
                title="Swarming risk indicators are elevated",
                message=(
                    "Patterns commonly seen around swarming were recorded together. Check colony "
                    "space and queen cells at the next opportunity."
                ),
                metric=f"swarming_risk={swarming.score}",
                context={"level": swarming.level.value, "confidence": swarming.confidence},
            )
        )

    for anomaly in anomalies:
        if anomaly.code == "TEMPERATURE_OUT_OF_BAND" and anomaly.severity is AiAlertSeverity.CRITICAL:
            candidates.append(
                AlertSpec(
                    alert_type=AiAlertType.TEMPERATURE_ANOMALY,
                    severity=AiAlertSeverity.WARNING,
                    title="Temperature outside the reference band",
                    message=anomaly.detail,
                    metric=f"temperature={anomaly.value}",
                    context={"reference": anomaly.reference},
                )
            )
        elif anomaly.code == "HUMIDITY_OUT_OF_BAND" and anomaly.severity is AiAlertSeverity.CRITICAL:
            candidates.append(
                AlertSpec(
                    alert_type=AiAlertType.HUMIDITY_ANOMALY,
                    severity=AiAlertSeverity.WARNING,
                    title="Humidity outside the reference band",
                    message=anomaly.detail,
                    metric=f"humidity={anomaly.value}",
                    context={"reference": anomaly.reference},
                )
            )
        elif anomaly.code == "WEIGHT_DROP" and anomaly.severity is AiAlertSeverity.WARNING:
            candidates.append(
                AlertSpec(
                    alert_type=AiAlertType.WEIGHT_TREND_ANOMALY,
                    severity=AiAlertSeverity.WARNING,
                    title="Hive weight fell",
                    message=anomaly.detail,
                    metric=f"weight_change={anomaly.value}",
                    context={"reference": anomaly.reference},
                )
            )
        elif anomaly.code == "ACTIVITY_SUPPRESSED":
            candidates.append(
                AlertSpec(
                    alert_type=AiAlertType.ACTIVITY_ANOMALY,
                    severity=AiAlertSeverity.INFO,
                    title="Activity fell below this hive's baseline",
                    message=anomaly.detail,
                    metric=f"activity_ratio={anomaly.value}",
                    context={"reference": anomaly.reference},
                )
            )
        elif anomaly.code == "ACTIVITY_SPIKE":
            candidates.append(
                AlertSpec(
                    alert_type=AiAlertType.ACTIVITY_ANOMALY,
                    severity=AiAlertSeverity.INFO,
                    title="Activity rose above this hive's baseline",
                    message=anomaly.detail,
                    metric=f"activity_ratio={anomaly.value}",
                    context={"reference": anomaly.reference},
                )
            )

    # Stale telemetry is a monitoring problem, not a colony finding, but it is
    # precisely the thing a beekeeper needs to know without opening the app.
    if quality.is_stale:
        candidates.append(
            AlertSpec(
                alert_type=AiAlertType.DATA_STALE,
                severity=AiAlertSeverity.INFO,
                title="Telemetry has stopped arriving",
                message=(
                    f"The newest reading for this hive is {(quality.newest_age_minutes or 0) / 60:.1f} h "
                    "old. Check the device's power and connectivity."
                ),
                metric=f"age_hours={(quality.newest_age_minutes or 0) / 60:.1f}",
                context={"device_status": quality.device_status},
            )
        )
    return candidates


__all__ = ["alert_candidates", "build_recommendations"]

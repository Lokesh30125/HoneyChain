"""Swarming risk assessment.

Swarming is the one event in beekeeping that shows up in telemetry as a
*combination*: activity climbs, the acoustic pattern changes, and — if the colony
actually leaves — the hive suddenly weighs less. This module scores that
combination.

It does not, and cannot, predict that a swarm will happen. A colony that looks
restless may be preparing to swarm, may be dealing with a new nectar flow, may
have a ventilation problem, or may simply have a loose sensor mount. Everything
this module returns is therefore worded as **risk**, with the indicators named and
the recommended action being an inspection — never a statement that swarming is
going to occur, and never advice to intervene blindly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import Settings
from app.models.enums import AiDataQuality, AiRiskLevel, ColonyStrength, QueenStatus
from app.services.ai import thresholds as T
from app.services.ai.quality import cap_confidence
from app.services.ai.types import (
    Anomaly,
    Contribution,
    FeatureSet,
    QualityReport,
    Recommendation,
    RiskAssessment,
)

DISCLAIMER = (
    "Swarming risk is an indicator derived from sensor patterns. It does not predict that a "
    "swarm will occur — colonies with similar patterns often do not swarm, and colonies with low "
    "scores sometimes do."
)

_SUMMARY = {
    AiRiskLevel.LOW: "No cluster of swarming-associated patterns was recorded in this window.",
    AiRiskLevel.MODERATE: (
        "Some patterns associated with pre-swarming behaviour were recorded; they do not by "
        "themselves indicate an imminent swarm."
    ),
    AiRiskLevel.HIGH: (
        "Several patterns commonly seen around swarming were recorded together. An inspection is "
        "worthwhile."
    ),
    AiRiskLevel.UNKNOWN: "Not enough telemetry to assess swarming risk.",
}

_BASIS = (
    "Baseline rule-based risk score: activity rise against the hive's own baseline, acoustic "
    "change, weight behaviour and season. Not trained on, or validated against, observed "
    "swarming events."
)


def _band(score: float) -> AiRiskLevel:
    if score < T.SWARMING_BANDS["low_until"]:
        return AiRiskLevel.LOW
    if score < T.SWARMING_BANDS["moderate_until"]:
        return AiRiskLevel.MODERATE
    return AiRiskLevel.HIGH


def assess_swarming_risk(
    features: FeatureSet,
    anomalies: list[Anomaly],
    quality: QualityReport,
    *,
    settings: Settings,
    queen_status: QueenStatus = QueenStatus.UNKNOWN,
    colony_strength: ColonyStrength = ColonyStrength.UNKNOWN,
    moment: datetime | None = None,
) -> RiskAssessment:
    """Score swarming risk from recorded patterns, or return ``UNKNOWN``."""
    if quality.level is AiDataQuality.INSUFFICIENT:
        return RiskAssessment(
            score=None,
            level=AiRiskLevel.UNKNOWN,
            confidence=0,
            indicators=[],
            anomalies=[],
            recommendation=None,
            summary=_SUMMARY[AiRiskLevel.UNKNOWN],
            disclaimer=DISCLAIMER,
        )

    now = moment or datetime.now(timezone.utc)
    indicators: list[Contribution] = []
    codes = {anomaly.code for anomaly in anomalies}

    vibration = features.stats("vibration")
    acoustic = features.stats("acoustic_level")
    weight = features.stats("weight")

    # -- Activity rising -----------------------------------------------------
    if "ACTIVITY_SPIKE" in codes:
        indicator = next(anomaly for anomaly in anomalies if anomaly.code == "ACTIVITY_SPIKE")
        indicators.append(
            Contribution(
                code="activity_spike",
                label="Activity rose sharply above this hive's baseline",
                detail=indicator.detail,
                direction="NEGATIVE",
                delta=T.SWARMING_WEIGHTS["activity_spike"],
                sensors=["vibration"],
                value=indicator.value,
                reference=indicator.reference,
            )
        )
    if features.activity_trend.value == "RISING":
        indicators.append(
            Contribution(
                code="activity_rising",
                label="Activity trending upward",
                detail="Vibration and/or acoustic level rose steadily across the window.",
                direction="NEGATIVE",
                delta=T.SWARMING_WEIGHTS["activity_rising"],
                sensors=[sensor for sensor in ("vibration", "acoustic_level") if features.stats(sensor) and features.stats(sensor).has_data],
            )
        )

    # -- Acoustic change -----------------------------------------------------
    if "ACOUSTIC_ANOMALY" in codes:
        indicator = next(anomaly for anomaly in anomalies if anomaly.code == "ACOUSTIC_ANOMALY")
        indicators.append(
            Contribution(
                code="acoustic_anomaly",
                label="Acoustic pattern changed",
                detail=indicator.detail,
                direction="NEGATIVE",
                delta=T.SWARMING_WEIGHTS["acoustic_anomaly"],
                sensors=["acoustic_level"],
                value=indicator.value,
                reference=indicator.reference,
            )
        )

    # -- Weight behaviour ----------------------------------------------------
    gain_per_day = features.weight_gain_per_day
    gained_earlier = gain_per_day is not None and features.covered_hours > 0
    if "WEIGHT_DROP" in codes and gained_earlier:
        indicator = next(anomaly for anomaly in anomalies if anomaly.code == "WEIGHT_DROP")
        indicators.append(
            Contribution(
                code="weight_drop_after_gain",
                label="Hive weight dropped",
                detail=(
                    indicator.detail
                    + " A colony leaving with its stores is one of several possible explanations."
                ),
                direction="NEGATIVE",
                delta=T.SWARMING_WEIGHTS["weight_drop_after_gain"],
                sensors=["weight"],
                value=indicator.value,
            )
        )
    elif (
        "WEIGHT_STAGNATION" in codes
        and features.activity_index is not None
        and features.activity_index > 1.0
    ):
        indicators.append(
            Contribution(
                code="weight_stagnation_with_activity",
                label="Weight flat while activity is high",
                detail=(
                    "The hive is not accumulating weight even though activity is elevated — a "
                    "pattern worth an inspection."
                ),
                direction="NEGATIVE",
                delta=T.SWARMING_WEIGHTS["weight_stagnation_with_activity"],
                sensors=["weight", "vibration"],
                value=gain_per_day,
            )
        )

    # -- Nest temperature ----------------------------------------------------
    temperature = features.stats("temperature")
    if temperature is not None and temperature.has_data and temperature.mean is not None:
        if temperature.mean > T.TEMPERATURE_COMFORT[1]:
            indicators.append(
                Contribution(
                    code="temperature_above_band",
                    label="Nest warmer than the reference band",
                    detail=(
                        f"Mean {temperature.mean:.1f} °C against a band of "
                        f"{T.TEMPERATURE_COMFORT[0]:.0f}–{T.TEMPERATURE_COMFORT[1]:.0f} °C. Crowding "
                        "is one of several possible reasons."
                    ),
                    direction="NEGATIVE",
                    delta=T.SWARMING_WEIGHTS["temperature_above_band"],
                    sensors=["temperature"],
                    value=temperature.mean,
                )
            )

    # -- Season --------------------------------------------------------------
    if now.month in T.SWARMING_SEASON_MONTHS:
        indicators.append(
            Contribution(
                code="seasonal_peak",
                label="Within a commonly reported swarming season",
                detail=(
                    f"Month {now.month} falls in the spring build-up or post-monsoon period in "
                    "which swarming is most often reported in this region."
                ),
                direction="NEGATIVE",
                delta=T.SWARMING_WEIGHTS["seasonal_peak"],
                reference="seasonal modifier, not a prediction",
            )
        )

    # -- Recorded colony observations ---------------------------------------
    if colony_strength is ColonyStrength.STRONG:
        indicators.append(
            Contribution(
                code="colony_strong",
                label="Colony recorded as strong",
                detail="Strong colonies are the ones that usually build up to swarming.",
                direction="NEGATIVE",
                delta=T.SWARMING_WEIGHTS["colony_strong"],
            )
        )
    if queen_status is QueenStatus.PRESENT:
        indicators.append(
            Contribution(
                code="queen_observed_present",
                label="Queen recorded as present",
                detail="A laying queen is part of the normal build-up to swarming.",
                direction="NEGATIVE",
                delta=T.SWARMING_WEIGHTS["queen_observed_present"],
            )
        )

    # -- Reassuring evidence -------------------------------------------------
    if features.activity_trend.value == "FALLING" or "ACTIVITY_SUPPRESSED" in codes:
        indicators.append(
            Contribution(
                code="activity_suppressed",
                label="Activity is low or falling",
                detail="Activity is below this hive's own baseline, which is not a swarming pattern.",
                direction="POSITIVE",
                delta=T.SWARMING_WEIGHTS["activity_suppressed"],
                sensors=["vibration"],
            )
        )
    if (
        temperature is not None
        and temperature.mean is not None
        and T.TEMPERATURE_COMFORT[0] <= temperature.mean <= T.TEMPERATURE_COMFORT[1]
        and features.activity_trend.value != "RISING"
    ):
        indicators.append(
            Contribution(
                code="environment_stable",
                label="Nest environment settled",
                detail="Temperature sat inside the reference band and activity was not rising.",
                direction="POSITIVE",
                delta=T.SWARMING_WEIGHTS["environment_stable"],
                sensors=["temperature"],
            )
        )

    negative_count = sum(1 for indicator in indicators if indicator.direction == "NEGATIVE")
    score = max(0.0, min(100.0, sum(indicator.delta for indicator in indicators)))
    if negative_count >= 3:
        score = min(100.0, score + T.SWARMING_WEIGHTS["crowding_indicators_multiple"])
    level = _band(score)

    raw = 40.0 + 35.0 * min(1.0, features.sample_count / 48.0) - 4.0 * negative_count
    confidence = cap_confidence(max(28.0, raw), quality)

    return RiskAssessment(
        score=int(round(score)),
        level=level,
        confidence=confidence,
        indicators=indicators,
        anomalies=anomalies,
        recommendation=_recommendation(level, indicators),
        summary=_SUMMARY[level],
        disclaimer=DISCLAIMER,
    )


def _recommendation(level: AiRiskLevel, indicators: list[Contribution]) -> Recommendation | None:
    negative = [indicator for indicator in indicators if indicator.direction == "NEGATIVE"]
    if level is AiRiskLevel.LOW:
        return None

    sensors = sorted({sensor for indicator in negative for sensor in indicator.sensors})
    if level is AiRiskLevel.HIGH:
        return Recommendation(
            code="swarming_risk_high",
            title="Inspect the colony for signs associated with swarming",
            detail=(
                "Check for queen cells, brood nest congestion and space in the supers, and follow "
                "the management practice appropriate to your apiary — this is a prompt to look, "
                "not a statement that a swarm will happen."
            ),
            priority="PRIORITY",
            reason="Several patterns commonly seen around swarming were recorded together.",
            sensors=sensors,
        )
    return Recommendation(
        code="swarming_risk_moderate",
        title="Plan a check of colony space",
        detail=(
            "Watch the indicators over the next few days and inspect when convenient: room in the "
            "hive and queen-cell development are the things to look for."
        ),
        priority="SOON",
        reason="Some patterns associated with build-up were recorded.",
        sensors=sensors,
    )


__all__ = ["DISCLAIMER", "assess_swarming_risk"]

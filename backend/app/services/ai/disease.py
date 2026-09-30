"""Disease risk assessment.

What this produces, and what it refuses to produce
--------------------------------------------------
A **risk band** — ``LOW`` / ``MODERATE`` / ``HIGH`` with a 0–100 score — from the
sensor patterns that beekeeping practice associates with a colony that is
struggling. It never says a hive *has* a disease. Nothing in the platform can
know that: no pathogen is measured here, no sample is cultured, and a sensor
cannot see a brood pattern.

So the language is fixed by construction:

* the assessment is titled **disease risk**;
* indicators are introduced as *possible contributing* patterns;
* the recommendation is always to inspect — and to involve an experienced
  beekeeper or the KVIC extension service for a real determination;
* the disclaimer travels with the payload, so a screen cannot show the band
  without the sentence that qualifies it.

The indicators themselves are additive and visible, which is what makes the band
checkable: damp-and-cool windows, unusual acoustic patterns, a falling weight
trend, a recorded absence of the queen, several sensors deviating at once.
"""

from __future__ import annotations

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
    "This is an AI-assisted risk indicator based on sensor patterns, not a diagnosis. "
    "Only an inspection and, where appropriate, laboratory testing can determine whether a "
    "colony has a disease."
)

_SUMMARY = {
    AiRiskLevel.LOW: "No sensor pattern in this window suggests elevated disease risk.",
    AiRiskLevel.MODERATE: (
        "Some sensor patterns are associated with conditions worth checking; none of them "
        "confirms anything on its own."
    ),
    AiRiskLevel.HIGH: (
        "Several sensor patterns associated with colony stress were recorded together. "
        "An inspection is advisable."
    ),
    AiRiskLevel.UNKNOWN: "Not enough telemetry to assess disease risk.",
}

_BASIS = (
    "Baseline rule-based risk score: additive weights over damp/cool nest patterns, acoustic "
    "activity, weight trend and recorded colony observations. Not trained on, or validated "
    "against, confirmed disease outcomes."
)


def _band(score: float) -> AiRiskLevel:
    if score < T.DISEASE_BANDS["low_until"]:
        return AiRiskLevel.LOW
    if score < T.DISEASE_BANDS["moderate_until"]:
        return AiRiskLevel.MODERATE
    return AiRiskLevel.HIGH


def assess_disease_risk(
    features: FeatureSet,
    anomalies: list[Anomaly],
    quality: QualityReport,
    *,
    settings: Settings,
    queen_status: QueenStatus = QueenStatus.UNKNOWN,
    colony_strength: ColonyStrength = ColonyStrength.UNKNOWN,
) -> RiskAssessment:
    """Score disease risk from recorded patterns, or return ``UNKNOWN``."""
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

    indicators: list[Contribution] = []
    codes = {anomaly.code for anomaly in anomalies}

    # -- Damp nest -----------------------------------------------------------
    humidity = features.stats("humidity")
    if humidity is not None and humidity.has_data and humidity.mean is not None:
        mean = humidity.mean
        if mean >= T.HUMIDITY_HIGH:
            indicators.append(
                Contribution(
                    code="humidity_extremely_high",
                    label="Interior humidity stayed very high",
                    detail=(
                        f"Mean {mean:.1f} % across the window (reference above {T.HUMIDITY_HIGH:.0f} % "
                        "is the damp range used by the baseline)."
                    ),
                    direction="NEGATIVE",
                    delta=T.DISEASE_WEIGHTS["humidity_extremely_high"],
                    sensors=["humidity"],
                    value=mean,
                    reference=f"< {T.HUMIDITY_HIGH:.0f} %",
                )
            )
        elif mean > T.HUMIDITY_COMFORT[1]:
            indicators.append(
                Contribution(
                    code="humidity_persistently_high",
                    label="Interior humidity above the comfort band",
                    detail=f"Mean {mean:.1f} % against a band of {T.HUMIDITY_COMFORT[0]:.0f}–{T.HUMIDITY_COMFORT[1]:.0f} %.",
                    direction="NEGATIVE",
                    delta=T.DISEASE_WEIGHTS["humidity_persistently_high"],
                    sensors=["humidity"],
                    value=mean,
                    reference=f"≤ {T.HUMIDITY_COMFORT[1]:.0f} %",
                )
            )
        elif mean < T.HUMIDITY_LOW:
            indicators.append(
                Contribution(
                    code="humidity_low",
                    label="Interior humidity below the comfort band",
                    detail=f"Mean {mean:.1f} % against a band of {T.HUMIDITY_COMFORT[0]:.0f}–{T.HUMIDITY_COMFORT[1]:.0f} %.",
                    direction="NEGATIVE",
                    delta=T.DISEASE_WEIGHTS["humidity_low"],
                    sensors=["humidity"],
                    value=mean,
                    reference=f"≥ {T.HUMIDITY_COMFORT[0]:.0f} %",
                )
            )

    # -- Nest temperature ----------------------------------------------------
    temperature = features.stats("temperature")
    if temperature is not None and temperature.has_data and temperature.mean is not None:
        mean = temperature.mean
        low, high = T.TEMPERATURE_COMFORT
        if mean < low:
            indicators.append(
                Contribution(
                    code="temperature_below_band",
                    label="Nest temperature below the reference band",
                    detail=f"Mean {mean:.1f} °C against a band of {low:.0f}–{high:.0f} °C.",
                    direction="NEGATIVE",
                    delta=T.DISEASE_WEIGHTS["temperature_below_band"],
                    sensors=["temperature"],
                    value=mean,
                    reference=f"{low:.0f}–{high:.0f} °C",
                )
            )
        elif mean > high:
            indicators.append(
                Contribution(
                    code="temperature_above_band",
                    label="Nest temperature above the reference band",
                    detail=f"Mean {mean:.1f} °C against a band of {low:.0f}–{high:.0f} °C.",
                    direction="NEGATIVE",
                    delta=T.DISEASE_WEIGHTS["temperature_above_band"],
                    sensors=["temperature"],
                    value=mean,
                    reference=f"{low:.0f}–{high:.0f} °C",
                )
            )
        if temperature.spread is not None and temperature.spread > T.TEMPERATURE_SPREAD_HIGH:
            indicators.append(
                Contribution(
                    code="temperature_volatile",
                    label="Nest temperature fluctuated",
                    detail=f"Standard deviation {temperature.spread:.2f} °C across the window.",
                    direction="NEGATIVE",
                    delta=T.DISEASE_WEIGHTS["temperature_volatile"],
                    sensors=["temperature"],
                    value=temperature.spread,
                    reference=f"< {T.TEMPERATURE_SPREAD_HIGH:.1f} °C",
                )
            )

    # -- Acoustic pattern ----------------------------------------------------
    acoustic = features.stats("acoustic_level")
    if acoustic is not None and acoustic.has_data:
        if "ACOUSTIC_ANOMALY" in codes:
            indicator = next(anomaly for anomaly in anomalies if anomaly.code == "ACOUSTIC_ANOMALY")
            indicators.append(
                Contribution(
                    code="acoustic_anomaly",
                    label="Unusual acoustic pattern",
                    detail=indicator.detail,
                    direction="NEGATIVE",
                    delta=T.DISEASE_WEIGHTS["acoustic_anomaly"],
                    sensors=["acoustic_level"],
                    value=indicator.value,
                    reference=indicator.reference,
                )
            )
        elif acoustic.spread is not None and acoustic.mean and acoustic.spread / acoustic.mean > 0.35:
            indicators.append(
                Contribution(
                    code="acoustic_high_variability",
                    label="Acoustic activity varied widely",
                    detail=(
                        f"Variation was {acoustic.spread / acoustic.mean * 100:.0f} % of the mean "
                        "acoustic level."
                    ),
                    direction="NEGATIVE",
                    delta=T.DISEASE_WEIGHTS["acoustic_high_variability"],
                    sensors=["acoustic_level"],
                    value=acoustic.spread / acoustic.mean,
                    reference="< 35 % of mean",
                )
            )

    # -- Activity and weight -------------------------------------------------
    if "ACTIVITY_SUPPRESSED" in codes:
        indicator = next(anomaly for anomaly in anomalies if anomaly.code == "ACTIVITY_SUPPRESSED")
        indicators.append(
            Contribution(
                code="activity_suppressed",
                label="Unusually low activity",
                detail=indicator.detail,
                direction="NEGATIVE",
                delta=T.DISEASE_WEIGHTS["activity_suppressed"],
                sensors=["vibration"],
                value=indicator.value,
            )
        )
    if "WEIGHT_DROP" in codes:
        indicator = next(anomaly for anomaly in anomalies if anomaly.code == "WEIGHT_DROP")
        indicators.append(
            Contribution(
                code="weight_declining",
                label="Hive weight is falling",
                detail=indicator.detail,
                direction="NEGATIVE",
                delta=T.DISEASE_WEIGHTS["weight_declining"],
                sensors=["weight"],
                value=indicator.value,
            )
        )
    if "MULTI_SENSOR_ANOMALY" in codes:
        indicator = next(anomaly for anomaly in anomalies if anomaly.code == "MULTI_SENSOR_ANOMALY")
        indicators.append(
            Contribution(
                code="multi_sensor_anomaly",
                label="Several sensors deviated together",
                detail=indicator.detail,
                direction="NEGATIVE",
                delta=T.DISEASE_WEIGHTS["multi_sensor_anomaly"],
                sensors=indicator.sensors,
            )
        )

    # -- Recorded observations ----------------------------------------------
    if queen_status is QueenStatus.ABSENT:
        indicators.append(
            Contribution(
                code="queen_observed_absent",
                label="Queen recorded as absent",
                detail="Recorded on the hive by the beekeeper — a queenless colony is more vulnerable.",
                direction="NEGATIVE",
                delta=T.DISEASE_WEIGHTS["queen_observed_absent"],
            )
        )

    # -- Reassuring evidence reduces the score ------------------------------
    # A stable, warm, dry nest with steady weight is positive evidence, and
    # leaving it out would make every hive look risky by default.
    if (
        temperature is not None
        and temperature.has_data
        and temperature.mean is not None
        and T.TEMPERATURE_COMFORT[0] <= temperature.mean <= T.TEMPERATURE_COMFORT[1]
        and humidity is not None
        and humidity.mean is not None
        and T.HUMIDITY_COMFORT[0] <= humidity.mean <= T.HUMIDITY_COMFORT[1]
    ):
        indicators.append(
            Contribution(
                code="environment_stable",
                label="Nest environment stable",
                detail="Temperature and humidity both sat inside the reference bands for the window.",
                direction="POSITIVE",
                delta=T.DISEASE_WEIGHTS["environment_stable"],
                sensors=["temperature", "humidity"],
            )
        )
    if colony_strength is ColonyStrength.STRONG:
        indicators.append(
            Contribution(
                code="colony_strong",
                label="Colony recorded as strong",
                detail="The beekeeper's own assessment on the hive record.",
                direction="POSITIVE",
                delta=T.DISEASE_WEIGHTS["colony_strong"],
            )
        )

    score = max(0.0, min(100.0, sum(indicator.delta for indicator in indicators)))
    level = _band(score)

    raw = (40.0 + 35.0 * min(1.0, features.sample_count / 48.0)) - 6.0 * len(indicators)
    raw = max(30.0, raw)  # never claim near-zero confidence about a risk band
    confidence = cap_confidence(raw, quality)

    recommendation = _recommendation(level, indicators)

    return RiskAssessment(
        score=int(round(score)),
        level=level,
        confidence=confidence,
        indicators=indicators,
        anomalies=anomalies,
        recommendation=recommendation,
        summary=_SUMMARY[level],
        disclaimer=DISCLAIMER,
    )


def _recommendation(level: AiRiskLevel, indicators: list[Contribution]) -> Recommendation | None:
    """Advice tied to what actually fired, or nothing when nothing did."""
    negative = [indicator for indicator in indicators if indicator.direction == "NEGATIVE"]
    if level is AiRiskLevel.LOW and not negative:
        return None

    sensors = sorted({sensor for indicator in negative for sensor in indicator.sensors})
    if level is AiRiskLevel.HIGH:
        return Recommendation(
            code="disease_risk_high",
            title="Inspect the hive and consider an experienced assessment",
            detail=(
                "Open the hive and check the brood pattern, stores and colony behaviour. If "
                "something looks wrong, involve an experienced beekeeper or the KVIC extension "
                "service rather than treating it from sensor readings alone."
            ),
            priority="PRIORITY",
            reason="Several patterns associated with colony stress were recorded together.",
            sensors=sensors,
        )
    if level is AiRiskLevel.MODERATE:
        return Recommendation(
            code="disease_risk_moderate",
            title="Schedule an inspection and watch the trend",
            detail=(
                "Check the nest conditions in person at the next convenient visit, and keep an eye "
                "on the indicators listed here over the next few days."
            ),
            priority="SOON",
            reason="Some recorded patterns are worth confirming by eye.",
            sensors=sensors,
        )
    return Recommendation(
        code="disease_risk_low",
        title="Keep monitoring",
        detail=(
            "No action is indicated. Continue normal inspections; the risk score will keep "
            "updating as new telemetry arrives."
        ),
        priority="ROUTINE",
        reason="The risk band is low, but at least one indicator moved off the reference band.",
        sensors=sensors,
    )


__all__ = ["DISCLAIMER", "assess_disease_risk"]

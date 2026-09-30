"""Colony health assessment.

How the score is produced
-------------------------
``score = 70 + min(Σ positive deltas, 20) + Σ negative deltas``, clamped to 0–100.

That is the whole model, and it is intentionally that simple: a beekeeper (or a
future maintainer) can read the factor list next to the score and check the
arithmetic. The two constants matter and are explained where they are defined:
the score tops out at 90 (a heuristic should not report a perfect 100) and the
positive side is capped so that good readings can never drown out a negative
finding such as a recorded queenless colony. Each factor is a statement about a measured pattern, with
the value it saw and the reference it compared against, and each carries the
points it contributed — positive or negative. There is no hidden weighting, no
black-box feature vector and no per-hive constant: two hives with different
telemetry cannot produce the same factor list.

What the score is *not*
-----------------------
It is not a diagnosis, not a veterinary assessment and not a scientific
measurement of colony vigour. ``HEALTHY`` means "the recorded patterns sit inside
the reference bands", nothing more, and the API says so wherever the number is
shown. When the telemetry cannot support a statement the status is
``INSUFFICIENT_DATA`` and the score is ``None`` — never a middling default that
would be mistaken for a finding.
"""

from __future__ import annotations

from app.core.config import Settings
from app.models.enums import AiDataQuality, AiHealthStatus, ColonyStrength, QueenStatus
from app.services.ai import thresholds as T
from app.services.ai.quality import cap_confidence
from app.services.ai.types import (
    Anomaly,
    Contribution,
    FeatureSet,
    HealthAssessment,
    QualityReport,
)

#: Status text. Deliberately about *patterns*, not about the colony's condition.
_STATUS_SUMMARY = {
    AiHealthStatus.HEALTHY: "Recorded patterns sit inside the reference bands.",
    AiHealthStatus.ATTENTION: "Some recorded patterns have moved away from the reference bands.",
    AiHealthStatus.AT_RISK: "Several recorded patterns are outside the reference bands.",
    AiHealthStatus.CRITICAL: "Multiple strong deviations were recorded in this window.",
    AiHealthStatus.INSUFFICIENT_DATA: "Not enough telemetry to produce a health indicator.",
}

_BASIS = (
    "HoneyChain baseline health indicator (rule-based, not a trained or clinically "
    "validated model). It adds and subtracts published weights for measured sensor patterns "
    "against reference bands; positive evidence counts up to a fixed budget, so the indicator "
    f"tops out at {int(T.HEALTH_BASE_SCORE + T.HEALTH_POSITIVE_BUDGET)} rather than 100."
)


def _band_status(score: float) -> AiHealthStatus:
    for threshold, name in T.HEALTH_THRESHOLDS:
        if score >= threshold:
            return AiHealthStatus(name)
    return AiHealthStatus.CRITICAL  # pragma: no cover - the last band is 0


def _temperature_factors(features: FeatureSet) -> list[Contribution]:
    stats = features.stats("temperature")
    if stats is None or not stats.has_data:
        return []

    low, high = T.TEMPERATURE_COMFORT
    mean = stats.mean if stats.mean is not None else stats.current
    factors: list[Contribution] = []
    if mean is None:
        return factors

    if low <= mean <= high:
        factors.append(
            Contribution(
                code="temperature_stable",
                label="Nest temperature within the reference band",
                detail=f"Mean {mean:.1f} °C against a reference band of {low:.0f}–{high:.0f} °C.",
                direction="POSITIVE",
                delta=T.HEALTH_WEIGHTS["temperature_stable"],
                sensors=["temperature"],
                value=mean,
                reference=f"{low:.0f}–{high:.0f} °C",
            )
        )
    else:
        delta = mean - high if mean > high else mean - low
        extreme = not (T.TEMPERATURE_WIDE[0] <= mean <= T.TEMPERATURE_WIDE[1])
        weight_key = "temperature_extreme" if extreme else "temperature_drift"
        factors.append(
            Contribution(
                code=weight_key,
                label="Nest temperature outside the reference band",
                detail=(
                    f"Mean {mean:.1f} °C is {abs(delta):.1f} °C "
                    f"{'above' if delta > 0 else 'below'} the band of {low:.0f}–{high:.0f} °C."
                ),
                direction="NEGATIVE",
                delta=T.HEALTH_WEIGHTS[weight_key],
                sensors=["temperature"],
                value=mean,
                reference=f"{low:.0f}–{high:.0f} °C",
            )
        )

    if stats.spread is not None and stats.spread > T.TEMPERATURE_SPREAD_HIGH:
        factors.append(
            Contribution(
                code="temperature_volatile",
                label="Nest temperature fluctuates",
                detail=(
                    f"Standard deviation {stats.spread:.2f} °C over the window "
                    f"(reference < {T.TEMPERATURE_SPREAD_HIGH:.1f} °C)."
                ),
                direction="NEGATIVE",
                delta=T.HEALTH_WEIGHTS["temperature_volatile"],
                sensors=["temperature"],
                value=stats.spread,
                reference=f"< {T.TEMPERATURE_SPREAD_HIGH:.1f} °C",
            )
        )
    return factors


def _humidity_factors(features: FeatureSet) -> list[Contribution]:
    stats = features.stats("humidity")
    if stats is None or not stats.has_data:
        return []
    low, high = T.HUMIDITY_COMFORT
    mean = stats.mean if stats.mean is not None else stats.current
    if mean is None:
        return []

    if low <= mean <= high:
        return [
            Contribution(
                code="humidity_in_band",
                label="Interior humidity within the reference band",
                detail=f"Mean {mean:.1f} % against a reference band of {low:.0f}–{high:.0f} %.",
                direction="POSITIVE",
                delta=T.HEALTH_WEIGHTS["humidity_in_band"],
                sensors=["humidity"],
                value=mean,
                reference=f"{low:.0f}–{high:.0f} %",
            )
        ]

    extreme = mean >= T.HUMIDITY_HIGH or mean <= T.HUMIDITY_LOW
    key = "humidity_extreme" if extreme else "humidity_drift"
    return [
        Contribution(
            code=key,
            label="Interior humidity outside the reference band",
            detail=(
                f"Mean {mean:.1f} % is {'above' if mean > high else 'below'} the band of "
                f"{low:.0f}–{high:.0f} %."
            ),
            direction="NEGATIVE",
            delta=T.HEALTH_WEIGHTS[key],
            sensors=["humidity"],
            value=mean,
            reference=f"{low:.0f}–{high:.0f} %",
        )
    ]


def _activity_factors(features: FeatureSet, anomalies: list[Anomaly]) -> list[Contribution]:
    factors: list[Contribution] = []
    vibration = features.stats("vibration")
    acoustic = features.stats("acoustic_level")
    codes = {anomaly.code for anomaly in anomalies}

    if vibration is not None and vibration.has_data:
        ratio = vibration.recent_vs_baseline
        if "ACTIVITY_SPIKE" in codes:
            factors.append(
                Contribution(
                    code="activity_spike",
                    label="Activity above this hive's own baseline",
                    detail=f"Recent vibration is {ratio:.2f}× the earlier baseline."
                    if ratio is not None
                    else "Recent vibration is above this hive's baseline.",
                    direction="NEGATIVE",
                    delta=T.HEALTH_WEIGHTS["activity_spike"],
                    sensors=["vibration"],
                    value=ratio,
                    reference=f"< {T.ACTIVITY_SPIKE_RATIO:.1f}× baseline",
                )
            )
        elif "ACTIVITY_SUPPRESSED" in codes:
            factors.append(
                Contribution(
                    code="activity_suppressed",
                    label="Activity below this hive's own baseline",
                    detail=f"Recent vibration is {ratio:.2f}× the earlier baseline."
                    if ratio is not None
                    else "Recent vibration is below this hive's baseline.",
                    direction="NEGATIVE",
                    delta=T.HEALTH_WEIGHTS["activity_suppressed"],
                    sensors=["vibration"],
                    value=ratio,
                    reference=f"> {T.ACTIVITY_SUPPRESSED_RATIO:.2f}× baseline",
                )
            )
        else:
            factors.append(
                Contribution(
                    code="activity_normal",
                    label="Activity pattern steady",
                    detail="Vibration stayed within the range of this hive's own recent behaviour.",
                    direction="POSITIVE",
                    delta=T.HEALTH_WEIGHTS["activity_normal"],
                    sensors=["vibration"],
                    value=ratio,
                )
            )

    if acoustic is not None and acoustic.has_data:
        if "ACOUSTIC_ANOMALY" in codes or "ACOUSTIC_VARIABILITY" in codes:
            factors.append(
                Contribution(
                    code="acoustic_anomaly",
                    label="Acoustic pattern outside the reference",
                    detail=(
                        f"Mean acoustic level {acoustic.mean:.1f} dB with "
                        f"{'elevated' if acoustic.recent_vs_baseline and acoustic.recent_vs_baseline > 1 else 'unstable'} "
                        "recent activity."
                    ),
                    direction="NEGATIVE",
                    delta=T.HEALTH_WEIGHTS["acoustic_anomaly"],
                    sensors=["acoustic_level"],
                    value=acoustic.mean,
                    reference=f"< {T.ACOUSTIC_ELEVATED_DB:.0f} dB",
                )
            )
        elif "ACOUSTIC_QUIET" in codes:
            # Quiet is ambiguous: it can be a settled colony or a microphone that
            # is not picking the hive up, so it moves the score neither way.
            factors.append(
                Contribution(
                    code="acoustic_quiet",
                    label="Acoustic level below the reference band",
                    detail=(
                        f"Mean acoustic level {acoustic.mean:.1f} dB. Confirm the sensor is mounted "
                        "where it can hear the colony."
                    ),
                    direction="NEUTRAL",
                    delta=0.0,
                    sensors=["acoustic_level"],
                    value=acoustic.mean,
                    reference=f"> {T.ACOUSTIC_QUIET_DB:.0f} dB",
                )
            )
        else:
            factors.append(
                Contribution(
                    code="acoustic_normal",
                    label="Acoustic pattern steady",
                    detail="Acoustic activity stayed inside the reference band for the window.",
                    direction="POSITIVE",
                    delta=T.HEALTH_WEIGHTS["acoustic_normal"],
                    sensors=["acoustic_level"],
                    value=acoustic.mean,
                )
            )
    return factors


def _weight_factors(features: FeatureSet, anomalies: list[Anomaly]) -> list[Contribution]:
    stats = features.stats("weight")
    if stats is None or not stats.has_data or features.covered_hours <= 0:
        return []
    codes = {anomaly.code for anomaly in anomalies}
    gain_per_day = features.weight_gain_per_day

    if "WEIGHT_DROP" in codes:
        severe = gain_per_day is not None and gain_per_day <= -T.WEIGHT_DAILY_DROP_HIGH
        key = "weight_collapse" if severe else "weight_declining"
        return [
            Contribution(
                code=key,
                label="Hive weight is falling",
                detail=(
                    f"Trend {gain_per_day:+.2f} kg/day over {features.covered_hours / 24:.1f} days."
                    if gain_per_day is not None
                    else "The weight series is falling across the window."
                ),
                direction="NEGATIVE",
                delta=T.HEALTH_WEIGHTS[key],
                sensors=["weight"],
                value=gain_per_day,
                reference="no sustained loss",
            )
        ]

    if gain_per_day is not None and gain_per_day >= T.WEIGHT_DAILY_GAIN_GOOD:
        return [
            Contribution(
                code="weight_accumulating",
                label="Weight accumulating",
                detail=(
                    f"Trend {gain_per_day:+.2f} kg/day over {features.covered_hours / 24:.1f} days, "
                    "consistent with nectar being stored."
                ),
                direction="POSITIVE",
                delta=T.HEALTH_WEIGHTS["weight_accumulating"],
                sensors=["weight"],
                value=gain_per_day,
                reference=f"≥ {T.WEIGHT_DAILY_GAIN_GOOD:.2f} kg/day",
            )
        ]

    return [
        Contribution(
            code="weight_stable",
            label="Weight holding steady",
            detail=(
                f"Trend {gain_per_day:+.2f} kg/day."
                if gain_per_day is not None
                else "Weight held steady across the window."
            ),
            direction="NEUTRAL" if gain_per_day is None else "POSITIVE",
            delta=T.HEALTH_WEIGHTS["weight_stable"],
            sensors=["weight"],
            value=gain_per_day,
        )
    ]


def _observation_factors(queen_status: QueenStatus, colony_strength: ColonyStrength) -> list[Contribution]:
    """The beekeeper's own recorded observations, where they exist.

    Only ``PRESENT``/``ABSENT`` and ``STRONG``/``WEAK`` are used: those are stated
    observations. ``UNKNOWN`` and ``UNDER_OBSERVATION`` add nothing, because the
    engine must not read meaning into a field nobody filled in.
    """
    factors: list[Contribution] = []
    if queen_status is QueenStatus.PRESENT:
        factors.append(
            Contribution(
                code="queen_observed_present",
                label="Queen recorded as present",
                detail="Recorded on the hive by the beekeeper, not inferred by the engine.",
                direction="POSITIVE",
                delta=T.HEALTH_WEIGHTS["queen_observed_present"],
            )
        )
    elif queen_status is QueenStatus.ABSENT:
        factors.append(
            Contribution(
                code="queen_observed_absent",
                label="Queen recorded as absent",
                detail="Recorded on the hive by the beekeeper, not inferred by the engine.",
                direction="NEGATIVE",
                delta=T.HEALTH_WEIGHTS["queen_observed_absent"],
            )
        )

    if colony_strength is ColonyStrength.STRONG:
        factors.append(
            Contribution(
                code="colony_strong",
                label="Colony recorded as strong",
                detail="The beekeeper's own assessment on the hive record.",
                direction="POSITIVE",
                delta=T.HEALTH_WEIGHTS["colony_strong"],
            )
        )
    elif colony_strength is ColonyStrength.WEAK:
        factors.append(
            Contribution(
                code="colony_weak",
                label="Colony recorded as weak",
                detail="The beekeeper's own assessment on the hive record.",
                direction="NEGATIVE",
                delta=T.HEALTH_WEIGHTS["colony_weak"],
            )
        )
    return factors


def assess_health(
    features: FeatureSet,
    anomalies: list[Anomaly],
    quality: QualityReport,
    *,
    settings: Settings,
    queen_status: QueenStatus = QueenStatus.UNKNOWN,
    colony_strength: ColonyStrength = ColonyStrength.UNKNOWN,
) -> HealthAssessment:
    """Score colony health from measured patterns, or say the data is insufficient."""
    if quality.level is AiDataQuality.INSUFFICIENT:
        return HealthAssessment(
            score=None,
            status=AiHealthStatus.INSUFFICIENT_DATA,
            confidence=0,
            trend=features.weight_trend,
            factors=[],
            anomalies=[],
            summary=_STATUS_SUMMARY[AiHealthStatus.INSUFFICIENT_DATA],
            basis=_BASIS,
        )

    factors: list[Contribution] = []
    factors.extend(_temperature_factors(features))
    factors.extend(_humidity_factors(features))
    factors.extend(_activity_factors(features, anomalies))
    factors.extend(_weight_factors(features, anomalies))
    factors.extend(_observation_factors(queen_status, colony_strength))

    if "MULTI_SENSOR_ANOMALY" in {anomaly.code for anomaly in anomalies}:
        factors.append(
            Contribution(
                code="multi_sensor_anomaly",
                label="Several sensors deviated together",
                detail="Three or more sensors moved away from their reference bands in this window.",
                direction="NEGATIVE",
                delta=T.HEALTH_WEIGHTS["multi_sensor_anomaly"],
                sensors=sorted({sensor for anomaly in anomalies for sensor in anomaly.sensors}),
            )
        )

    # Positive evidence is capped (see thresholds.HEALTH_POSITIVE_BUDGET): a run
    # of good readings must not be able to cancel out a negative finding, so the
    # arithmetic is split rather than summed blindly.
    positive = sum(factor.delta for factor in factors if factor.direction == "POSITIVE")
    negative = sum(factor.delta for factor in factors if factor.direction == "NEGATIVE")
    contributing = min(positive, T.HEALTH_POSITIVE_BUDGET) + negative
    score = max(0.0, min(100.0, T.HEALTH_BASE_SCORE + contributing))
    status = _band_status(score)

    # Confidence: how much evidence there is, plus how well the sensors agree.
    # Agreement matters because a window where one sensor is good and another is
    # missing cannot support the same conclusion as a complete one.
    agreement = 1.0 - min(0.4, 0.05 * max(0, len(anomalies) - 1))
    raw = (45.0 + 40.0 * min(1.0, features.sample_count / 48.0)) * agreement
    confidence = cap_confidence(raw, quality)

    return HealthAssessment(
        score=int(round(score)),
        status=status,
        confidence=confidence,
        trend=features.weight_trend if features.weight_trend.value != "UNKNOWN" else features.temperature_trend,
        factors=factors,
        anomalies=anomalies,
        summary=_STATUS_SUMMARY[status],
        basis=_BASIS,
    )


__all__ = ["assess_health"]

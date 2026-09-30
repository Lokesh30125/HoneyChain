"""Anomaly detection — patterns outside the reference band.

An anomaly here is a *measured pattern that moved away from the band the baseline
expected*. It is deliberately worded that way everywhere it surfaces: the engine
has no way to know whether an elevated acoustic level is a swarm, a fanning
colony, a nearby tractor or a loose sensor mount, and inventing a cause would be
the single most damaging thing this module could do.

Each detector states the value it saw, the reference it compared against, which
sensors were involved and how much weight the finding carries into the health and
risk scores. Detectors that cannot run (no data for that sensor) return nothing at
all rather than a neutral-looking zero.
"""

from __future__ import annotations

from app.models.enums import AiAlertSeverity
from app.services.ai import thresholds as T
from app.services.ai.types import Anomaly, FeatureSet


def _severity(code: str, *, extreme: bool = False) -> AiAlertSeverity:
    """Baseline severity for an anomaly code, optionally escalated.

    ``extreme=True`` means the reading sits outside the *wide* band, not merely
    outside the comfortable one. Only escalated anomalies are worth an alert on
    their own; a mild drift stays in the factors and recommendations.
    """
    base = AiAlertSeverity(T.ALERT_WORTHY_ANOMALIES.get(code, "INFO"))
    if extreme and base is AiAlertSeverity.WARNING:
        return AiAlertSeverity.CRITICAL
    return base


def temperature_anomalies(features: FeatureSet) -> list[Anomaly]:
    stats = features.stats("temperature")
    if stats is None or not stats.has_data:
        return []

    found: list[Anomaly] = []
    comfortable_low, comfortable_high = T.TEMPERATURE_COMFORT
    wide_low, wide_high = T.TEMPERATURE_WIDE
    mean = stats.mean if stats.mean is not None else stats.current

    if mean is not None and mean > comfortable_high:
        extreme = mean > wide_high
        found.append(
            Anomaly(
                code="TEMPERATURE_OUT_OF_BAND",
                label="Temperature above the reference band",
                detail=(
                    f"Mean nest temperature was {mean:.1f} °C over the window, above the "
                    f"{comfortable_high:.1f} °C reference."
                    + (" The reading is outside the wide band as well." if extreme else "")
                ),
                severity=_severity("TEMPERATURE_OUT_OF_BAND", extreme=extreme),
                sensors=["temperature"],
                value=mean,
                reference=f"{comfortable_low:.1f}–{comfortable_high:.1f} °C",
                weight=18.0 if extreme else 10.0,
            )
        )
    elif mean is not None and mean < comfortable_low:
        extreme = mean < wide_low
        found.append(
            Anomaly(
                code="TEMPERATURE_OUT_OF_BAND",
                label="Temperature below the reference band",
                detail=(
                    f"Mean nest temperature was {mean:.1f} °C over the window, below the "
                    f"{comfortable_low:.1f} °C reference."
                    + (" The reading is outside the wide band as well." if extreme else "")
                ),
                severity=_severity("TEMPERATURE_OUT_OF_BAND", extreme=extreme),
                sensors=["temperature"],
                value=mean,
                reference=f"{comfortable_low:.1f}–{comfortable_high:.1f} °C",
                weight=18.0 if extreme else 11.0,
            )
        )

    if stats.diurnal_amplitude is not None and stats.diurnal_amplitude > T.TEMPERATURE_DAILY_SWING_HIGH:
        found.append(
            Anomaly(
                code="TEMPERATURE_SWING",
                label="Temperature swings widely across a day",
                detail=(
                    f"Temperature moved {stats.diurnal_amplitude:.1f} °C within a single day; a "
                    f"settled colony usually holds a narrower range."
                ),
                severity=_severity("TEMPERATURE_SWING"),
                sensors=["temperature"],
                value=stats.diurnal_amplitude,
                reference=f"< {T.TEMPERATURE_DAILY_SWING_HIGH:.1f} °C per day",
                weight=7.0,
            )
        )
    elif stats.spread is not None and stats.spread > T.TEMPERATURE_SPREAD_HIGH:
        found.append(
            Anomaly(
                code="TEMPERATURE_SWING",
                label="Temperature varies more than usual",
                detail=(
                    f"Temperature varied with a standard deviation of {stats.spread:.2f} °C over "
                    "the window."
                ),
                severity=_severity("TEMPERATURE_SWING"),
                sensors=["temperature"],
                value=stats.spread,
                reference=f"< {T.TEMPERATURE_SPREAD_HIGH:.1f} °C",
                weight=5.0,
            )
        )
    return found


def humidity_anomalies(features: FeatureSet) -> list[Anomaly]:
    stats = features.stats("humidity")
    if stats is None or not stats.has_data:
        return []

    found: list[Anomaly] = []
    low, high = T.HUMIDITY_COMFORT
    mean = stats.mean if stats.mean is not None else stats.current

    if mean is not None and mean > high:
        extreme = mean >= T.HUMIDITY_HIGH
        found.append(
            Anomaly(
                code="HUMIDITY_OUT_OF_BAND",
                label="Humidity above the reference band",
                detail=(
                    f"Mean interior humidity was {mean:.1f} %, above the {high:.0f} % reference"
                    + (" and in the very damp range." if extreme else ".")
                ),
                severity=_severity("HUMIDITY_OUT_OF_BAND", extreme=extreme),
                sensors=["humidity"],
                value=mean,
                reference=f"{low:.0f}–{high:.0f} %",
                weight=16.0 if extreme else 9.0,
            )
        )
    elif mean is not None and mean < low:
        found.append(
            Anomaly(
                code="HUMIDITY_OUT_OF_BAND",
                label="Humidity below the reference band",
                detail=(
                    f"Mean interior humidity was {mean:.1f} %, below the {low:.0f} % reference."
                ),
                severity=_severity("HUMIDITY_OUT_OF_BAND", extreme=mean <= T.HUMIDITY_LOW),
                sensors=["humidity"],
                value=mean,
                reference=f"{low:.0f}–{high:.0f} %",
                weight=8.0,
            )
        )

    if stats.spread is not None and stats.spread > T.HUMIDITY_SPREAD_HIGH:
        found.append(
            Anomaly(
                code="HUMIDITY_SWING",
                label="Humidity varies more than usual",
                detail=(
                    f"Humidity varied with a standard deviation of {stats.spread:.1f} % over the "
                    "window."
                ),
                severity=AiAlertSeverity.INFO,
                sensors=["humidity"],
                value=stats.spread,
                reference=f"< {T.HUMIDITY_SPREAD_HIGH:.0f} %",
                weight=5.0,
            )
        )
    return found


def weight_anomalies(features: FeatureSet) -> list[Anomaly]:
    stats = features.stats("weight")
    if stats is None or not stats.has_data or features.covered_hours <= 0:
        return []

    found: list[Anomaly] = []
    gain_per_day = features.weight_gain_per_day
    change_24h = stats.change_last_24h

    if change_24h is not None and change_24h <= -T.WEIGHT_DAILY_DROP_HIGH:
        found.append(
            Anomaly(
                code="WEIGHT_DROP",
                label="Hive weight fell",
                detail=(
                    f"The hive lost {abs(change_24h):.2f} kg over the last 24 h. Weight loss can "
                    "follow consumption, a swarm, robbing or honey being taken off — the reading "
                    "alone does not distinguish between them."
                ),
                severity=_severity("WEIGHT_DROP"),
                sensors=["weight"],
                value=change_24h,
                reference=f"warn below −{T.WEIGHT_DAILY_DROP_HIGH:.1f} kg/day",
                weight=16.0,
            )
        )
    elif gain_per_day is not None and gain_per_day <= -T.WEIGHT_DAILY_DROP_HIGH / 2:
        found.append(
            Anomaly(
                code="WEIGHT_DROP",
                label="Hive weight trending down",
                detail=(
                    f"Weight is trending down at about {abs(gain_per_day):.2f} kg/day across the "
                    "window."
                ),
                severity=_severity("WEIGHT_DROP"),
                sensors=["weight"],
                value=gain_per_day,
                reference="no sustained loss",
                weight=12.0,
            )
        )
    elif (
        features.covered_hours >= T.WEIGHT_STAGNATION_DAYS * 24
        and gain_per_day is not None
        and abs(gain_per_day) <= T.WEIGHT_STAGNATION_TOLERANCE / T.WEIGHT_STAGNATION_DAYS
    ):
        found.append(
            Anomaly(
                code="WEIGHT_STAGNATION",
                label="No measurable weight change",
                detail=(
                    f"Weight barely moved across {features.covered_hours / 24:.0f} days "
                    f"({gain_per_day:+.3f} kg/day). A colony in a nectar flow normally gains."
                ),
                severity=AiAlertSeverity.INFO,
                sensors=["weight"],
                value=gain_per_day,
                reference="some accumulation expected in a flow",
                weight=6.0,
            )
        )
    return found


def activity_anomalies(features: FeatureSet) -> list[Anomaly]:
    """Vibration and acoustic patterns, judged against the hive's own baseline."""
    found: list[Anomaly] = []

    vibration = features.stats("vibration")
    acoustic = features.stats("acoustic_level")

    if vibration is not None and vibration.has_data:
        ratio = vibration.recent_vs_baseline
        if ratio is not None and ratio >= T.ACTIVITY_SPIKE_RATIO:
            found.append(
                Anomaly(
                    code="ACTIVITY_SPIKE",
                    label="Vibration activity rose sharply",
                    detail=(
                        f"Vibration over the last {T.RECENT_WINDOW_HOURS} h is {ratio:.2f}× this "
                        "hive's own earlier baseline."
                    ),
                    severity=_severity("ACTIVITY_SPIKE"),
                    sensors=["vibration"],
                    value=ratio,
                    reference=f"> {T.ACTIVITY_SPIKE_RATIO:.1f}× baseline",
                    weight=14.0,
                )
            )
        elif ratio is not None and ratio <= T.ACTIVITY_SUPPRESSED_RATIO:
            found.append(
                Anomaly(
                    code="ACTIVITY_SUPPRESSED",
                    label="Vibration activity fell",
                    detail=(
                        f"Vibration over the last {T.RECENT_WINDOW_HOURS} h is {ratio:.2f}× this "
                        "hive's own earlier baseline."
                    ),
                    severity=_severity("ACTIVITY_SUPPRESSED"),
                    sensors=["vibration"],
                    value=ratio,
                    reference=f"< {T.ACTIVITY_SUPPRESSED_RATIO:.2f}× baseline",
                    weight=11.0,
                )
            )

    if (
        vibration is not None
        and vibration.has_data
        and vibration.mean is not None
        and vibration.mean >= T.VIBRATION_ELEVATED
        and "ACTIVITY_SPIKE" not in {anomaly.code for anomaly in found}
    ):
        found.append(
            Anomaly(
                code="ACTIVITY_SPIKE",
                label="Vibration level is high",
                detail=(
                    f"Mean vibration was {vibration.mean:.2f} g over the window, above the "
                    f"{T.VIBRATION_ELEVATED:.1f} g reference used by the baseline."
                ),
                severity=_severity("ACTIVITY_SPIKE"),
                sensors=["vibration"],
                value=vibration.mean,
                reference=f"< {T.VIBRATION_ELEVATED:.1f} g",
                weight=12.0,
            )
        )

    if (
        acoustic is not None
        and acoustic.has_data
        and acoustic.mean is not None
        and acoustic.mean <= T.ACOUSTIC_QUIET_DB
        and acoustic.samples >= 3
    ):
        found.append(
            Anomaly(
                code="ACOUSTIC_QUIET",
                label="Acoustic level is unusually low",
                detail=(
                    f"Mean acoustic level was {acoustic.mean:.1f} dB, below the "
                    f"{T.ACOUSTIC_QUIET_DB:.0f} dB quiet reference. A low reading can also mean the "
                    "microphone is not picking up the hive."
                ),
                severity=AiAlertSeverity.INFO,
                sensors=["acoustic_level"],
                value=acoustic.mean,
                reference=f"> {T.ACOUSTIC_QUIET_DB:.0f} dB",
                weight=6.0,
            )
        )

    if acoustic is not None and acoustic.has_data:
        ratio = acoustic.recent_vs_baseline
        mean = acoustic.mean
        if ratio is not None and ratio >= T.ACTIVITY_SPIKE_RATIO:
            found.append(
                Anomaly(
                    code="ACOUSTIC_ANOMALY",
                    label="Acoustic activity is elevated",
                    detail=(
                        f"Acoustic level over the last {T.RECENT_WINDOW_HOURS} h is {ratio:.2f}× "
                        "this hive's own earlier baseline."
                    ),
                    severity=_severity("ACOUSTIC_ANOMALY"),
                    sensors=["acoustic_level"],
                    value=ratio,
                    reference=f"> {T.ACTIVITY_SPIKE_RATIO:.1f}× baseline",
                    weight=13.0,
                )
            )
        elif mean is not None and mean >= T.ACOUSTIC_ELEVATED_DB:
            found.append(
                Anomaly(
                    code="ACOUSTIC_ANOMALY",
                    label="Acoustic level is high",
                    detail=(
                        f"Mean acoustic level was {mean:.1f} dB over the window, above the "
                        f"{T.ACOUSTIC_ELEVATED_DB:.0f} dB reference used by the baseline."
                    ),
                    severity=_severity("ACOUSTIC_ANOMALY"),
                    sensors=["acoustic_level"],
                    value=mean,
                    reference=f"< {T.ACOUSTIC_ELEVATED_DB:.0f} dB",
                    weight=10.0,
                )
            )
        elif acoustic.spread is not None and acoustic.mean is not None and acoustic.mean > 0:
            relative_variation = acoustic.spread / acoustic.mean
            if relative_variation > 0.35:
                found.append(
                    Anomaly(
                        code="ACOUSTIC_VARIABILITY",
                        label="Acoustic pattern is uneven",
                        detail=(
                            f"Acoustic readings varied by {relative_variation * 100:.0f} % of their "
                            "mean across the window."
                        ),
                        severity=AiAlertSeverity.INFO,
                        sensors=["acoustic_level"],
                        value=relative_variation,
                        reference="< 35 % of mean",
                        weight=7.0,
                    )
                )
    return found


def multi_sensor_anomaly(anomalies: list[Anomaly]) -> Anomaly | None:
    """Flag a window in which several independent sensors moved together.

    One sensor off-band is usually that sensor. Three at once is the pattern that
    justifies asking the beekeeper to look.
    """
    distinct_sensors = {sensor for anomaly in anomalies for sensor in anomaly.sensors}
    if len(distinct_sensors) < 3:
        return None
    return Anomaly(
        code="MULTI_SENSOR_ANOMALY",
        label="Several sensors moved away from their bands",
        detail=(
            "Deviations were detected in "
            + ", ".join(sorted(distinct_sensors))
            + " within the same window, which is harder to explain by one sensor drifting."
        ),
        severity=_severity("MULTI_SENSOR_ANOMALY"),
        sensors=sorted(distinct_sensors),
        weight=12.0,
    )


def detect_anomalies(features: FeatureSet) -> list[Anomaly]:
    """Run every detector, then add the cross-sensor finding if it applies."""
    found: list[Anomaly] = []
    found.extend(temperature_anomalies(features))
    found.extend(humidity_anomalies(features))
    found.extend(weight_anomalies(features))
    found.extend(activity_anomalies(features))

    combined = multi_sensor_anomaly(found)
    if combined is not None:
        found.append(combined)

    # Strongest first, so both the UI and the alert rules read the same order.
    return sorted(found, key=lambda anomaly: anomaly.weight, reverse=True)


__all__ = [
    "activity_anomalies",
    "detect_anomalies",
    "humidity_anomalies",
    "multi_sensor_anomaly",
    "temperature_anomalies",
    "weight_anomalies",
]

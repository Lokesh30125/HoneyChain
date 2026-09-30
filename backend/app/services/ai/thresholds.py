"""Reference bands and weights used by the baseline AI engine.

Read this before trusting a number that came out of the engine
-------------------------------------------------------------
Every constant here is a **heuristic reference band**, chosen from general
honeybee husbandry literature and the behaviour of the development simulator. It
is *not* a trained model, *not* a validated classifier, and *not* a diagnostic
threshold. Nothing in this file has been fitted to real hive outcomes, because
the project does not yet have a labelled history of real hives to fit anything
to — and inventing accuracy numbers for a model that was never trained would be
worse than shipping an honest baseline.

What that means in practice:

* Sensor bands describe the *interior conditions* a colony is usually found in
  (a brood nest sits near 34–35 °C, for example). A reading outside the band is a
  prompt to look, not a finding.
* Risk weights are additive and visible. The score is a sum of the indicator
  weights that fired, clamped to 0–100, which is why the API can explain it.
* Changing any of these values changes the model, so ``MODEL_VERSION`` in
  ``app/core/config.py`` must be bumped with it. Old analyses keep the version
  they were produced with.

A future phase can replace the scorers in this package with a trained model
behind the same interface; until then, this file is the whole "model".
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Reference bands
# --------------------------------------------------------------------------- #
#: Brood-nest temperature band (°C). A healthy colony regulates its nest around
#: 34–35 °C; the accepted band below is deliberately wider so ordinary weather
#: variation does not fire an anomaly.
TEMPERATURE_COMFORT: tuple[float, float] = (32.0, 36.5)
#: Outside this, the reading is far enough from a nest temperature to matter.
TEMPERATURE_WIDE: tuple[float, float] = (26.0, 39.0)
#: A daily swing wider than this suggests poor thermal regulation or a disturbed
#: colony (a healthy nest is remarkably stable).
TEMPERATURE_DAILY_SWING_HIGH = 8.0
TEMPERATURE_SPREAD_HIGH = 2.5  # standard deviation over the window

#: Interior humidity band (%). Below ~45 % brood can desiccate; above ~85 % the
#: nest is damp. Both are prompts to inspect, not verdicts.
HUMIDITY_COMFORT: tuple[float, float] = (45.0, 80.0)
HUMIDITY_HIGH = 85.0
HUMIDITY_LOW = 40.0
HUMIDITY_SPREAD_HIGH = 12.0

#: Weight. A colony gaining steadily is foraging and storing; a drop can be
#: consumption, a swarm, robbing, or a beekeeper taking honey off — the engine
#: says which pattern it saw, never which cause it was.
WEIGHT_DAILY_DROP_HIGH = 0.8  # kg/day of sustained loss
WEIGHT_DAILY_GAIN_GOOD = 0.25  # kg/day that counts as healthy accumulation
WEIGHT_STAGNATION_DAYS = 5  # no measurable change over this long
WEIGHT_STAGNATION_TOLERANCE = 0.25  # kg of "no measurable change"

#: Activity (vibration in g, acoustic in dB — both relative to the sensor's own
#: recent baseline, because absolute values differ between nodes and hives).
ACTIVITY_SPIKE_RATIO = 1.6  # recent vs baseline
ACTIVITY_SUPPRESSED_RATIO = 0.55
ACOUSTIC_ELEVATED_DB = 55.0
ACOUSTIC_QUIET_DB = 20.0
VIBRATION_ELEVATED = 2.5  # g

#: Recent slice used for "is something changing now?" features.
RECENT_WINDOW_HOURS = 6

# --------------------------------------------------------------------------- #
# Weights — health
# --------------------------------------------------------------------------- #
#: A window whose patterns all sit inside their bands starts here, and positive
#: evidence adds to it up to HEALTH_POSITIVE_BUDGET. Two consequences are
#: deliberate: the indicator tops out at 90 rather than a suspiciously perfect
#: 100, and a negative factor is never swallowed by the clamp — a run of good
#: readings cannot hide a recorded queenless, weak or drifting hive.
HEALTH_BASE_SCORE = 70.0
#: How much positive evidence can add, in total. Anything beyond this is
#: recorded in the factor list but does not move the number.
HEALTH_POSITIVE_BUDGET = 20.0

HEALTH_WEIGHTS = {
    "temperature_stable": +8.0,
    "temperature_drift": -14.0,
    "temperature_extreme": -22.0,
    "temperature_volatile": -8.0,
    "humidity_in_band": +6.0,
    "humidity_drift": -10.0,
    "humidity_extreme": -16.0,
    "activity_normal": +6.0,
    "activity_spike": -10.0,
    "activity_suppressed": -12.0,
    "acoustic_normal": +4.0,
    "acoustic_anomaly": -12.0,
    "weight_accumulating": +10.0,
    "weight_stable": +2.0,
    "weight_declining": -14.0,
    "weight_collapse": -20.0,
    "multi_sensor_anomaly": -10.0,
    "queen_observed_present": +4.0,
    "queen_observed_absent": -12.0,
    "colony_strong": +5.0,
    "colony_weak": -8.0,
}

HEALTH_THRESHOLDS = ((80, "HEALTHY"), (60, "ATTENTION"), (40, "AT_RISK"), (0, "CRITICAL"))

# --------------------------------------------------------------------------- #
# Weights — disease risk
# --------------------------------------------------------------------------- #
DISEASE_WEIGHTS = {
    "humidity_persistently_high": 20.0,
    "humidity_extremely_high": 30.0,
    "humidity_low": 14.0,
    "temperature_below_band": 16.0,
    "temperature_above_band": 12.0,
    "temperature_volatile": 12.0,
    "acoustic_anomaly": 18.0,
    "acoustic_high_variability": 10.0,
    "activity_suppressed": 12.0,
    "weight_declining": 12.0,
    "multi_sensor_anomaly": 15.0,
    "queen_observed_absent": 15.0,
    "environment_stable": -12.0,
    "colony_strong": -6.0,
}

#: Risk bands: score below LOW_UNTIL is LOW, below MODERATE_UNTIL is MODERATE.
DISEASE_BANDS = {"low_until": 30, "moderate_until": 60}

# --------------------------------------------------------------------------- #
# Weights — swarming risk
# --------------------------------------------------------------------------- #
SWARMING_WEIGHTS = {
    "activity_spike": 25.0,
    "activity_rising": 15.0,
    "acoustic_anomaly": 18.0,
    "weight_drop_after_gain": 20.0,
    "weight_stagnation_with_activity": 10.0,
    "temperature_above_band": 10.0,
    "seasonal_peak": 8.0,
    "colony_strong": 10.0,
    "queen_observed_present": 6.0,
    "crowding_indicators_multiple": 12.0,
    "environment_stable": -10.0,
    "activity_suppressed": -8.0,
}

SWARMING_BANDS = {"low_until": 30, "moderate_until": 60}

#: Months (UTC) in which swarming is commonly reported in peninsular India —
#: the spring build-up and the post-monsoon dearth. Used only as a small
#: seasonal modifier, and named as such wherever it is shown.
SWARMING_SEASON_MONTHS = frozenset({2, 3, 4, 9, 10})

# --------------------------------------------------------------------------- #
# Yield model
# --------------------------------------------------------------------------- #
#: A weight series is only projected when it spans at least this long and the
#: line through it explains at least this much of the variance. Below either
#: bound the honest answer is "not enough history", not a number.
YIELD_MIN_FIT = 0.35
#: A daily gain above this is treated as an artefact (a super being added, a
#: sensor being refitted) rather than as honey accumulation.
YIELD_MAX_DAILY_GAIN = 6.0

# --------------------------------------------------------------------------- #
# Confidence shaping
# --------------------------------------------------------------------------- #
#: Confidence starts here even for a perfect window: the model is a baseline, and
#: claiming 100 % from a heuristic would be dishonest.
CONFIDENCE_CEILING = 85
CONFIDENCE_FLOOR_FOR_PREDICTION = 25
#: Manual entries are not device measurements, so they cap confidence hard.
MANUAL_SOURCE_CONFIDENCE_CAP = 40

# --------------------------------------------------------------------------- #
# Anomaly / alert severity
# --------------------------------------------------------------------------- #
#: Anomaly codes that are worth an alert on their own, with their severity.
ALERT_WORTHY_ANOMALIES = {
    "TEMPERATURE_OUT_OF_BAND": "WARNING",
    "TEMPERATURE_SWING": "INFO",
    "HUMIDITY_OUT_OF_BAND": "WARNING",
    "WEIGHT_DROP": "WARNING",
    "ACTIVITY_SPIKE": "WARNING",
    "ACTIVITY_SUPPRESSED": "WARNING",
    "ACOUSTIC_ANOMALY": "INFO",
    "MULTI_SENSOR_ANOMALY": "WARNING",
}

#: Data-validity jump limits per minute between consecutive readings. A change
#: faster than this is physically implausible for a hive and is treated as a
#: suspect sample (probe glitch, refit, power event) rather than as colony news.
MAX_PLAUSIBLE_CHANGE_PER_MINUTE = {
    "temperature": 0.6,  # °C/min
    "humidity": 6.0,  # %/min
    "weight": 4.0,  # kg/min
    "vibration": 6.0,  # g/min
    "acoustic_level": 8.0,  # dB/min
}

#: Units quoted in factor text and stored with the feature summary.
SENSOR_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "weight": "kg",
    "vibration": "g",
    "acoustic_level": "dB",
}

__all__ = [
    "ACOUSTIC_ELEVATED_DB",
    "ACOUSTIC_QUIET_DB",
    "ACTIVITY_SPIKE_RATIO",
    "ACTIVITY_SUPPRESSED_RATIO",
    "ALERT_WORTHY_ANOMALIES",
    "CONFIDENCE_CEILING",
    "CONFIDENCE_FLOOR_FOR_PREDICTION",
    "DISEASE_BANDS",
    "DISEASE_WEIGHTS",
    "HEALTH_BASE_SCORE",
    "HEALTH_THRESHOLDS",
    "HEALTH_WEIGHTS",
    "HUMIDITY_COMFORT",
    "HUMIDITY_HIGH",
    "HUMIDITY_LOW",
    "HUMIDITY_SPREAD_HIGH",
    "MANUAL_SOURCE_CONFIDENCE_CAP",
    "MAX_PLAUSIBLE_CHANGE_PER_MINUTE",
    "RECENT_WINDOW_HOURS",
    "SENSOR_UNITS",
    "SWARMING_BANDS",
    "SWARMING_SEASON_MONTHS",
    "SWARMING_WEIGHTS",
    "TEMPERATURE_COMFORT",
    "TEMPERATURE_DAILY_SWING_HIGH",
    "TEMPERATURE_SPREAD_HIGH",
    "TEMPERATURE_WIDE",
    "VIBRATION_ELEVATED",
    "WEIGHT_DAILY_DROP_HIGH",
    "WEIGHT_DAILY_GAIN_GOOD",
    "WEIGHT_STAGNATION_DAYS",
    "WEIGHT_STAGNATION_TOLERANCE",
    "YIELD_MAX_DAILY_GAIN",
    "YIELD_MIN_FIT",
]

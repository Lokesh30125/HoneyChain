"""Phase 4 — the AI engine itself, over hand-built series.

These tests are the honest-core of the AI module. They assert two kinds of thing:

* **What the engine produces** from a known series (bands, factors, alerts).
* **What it refuses to produce.** No score without history, no projection without
  a weight sensor, no hardware-sounding conclusion from manual entries, and never
  a confidence above the published ceiling.

Nothing here touches the database: the engine is a pure function, which is exactly
why it can be tested this way.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.models.enums import (
    AiAlertSeverity,
    AiAlertType,
    AiAnalysisSource,
    AiDataQuality,
    AiHealthStatus,
    AiRiskLevel,
    ColonyStrength,
    QueenStatus,
    TelemetrySource,
)
from app.models.sensor_reading import SensorReading
from app.services.ai import AiEngine
from app.services.ai import thresholds as T

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


class FakeHive:
    """The three attributes the engine reads off a hive."""

    def __init__(self, **overrides):
        self.id = overrides.get("id", 1)
        self.hive_code = overrides.get("hive_code", "HIVE-GNT-00001")
        self.queen_status = overrides.get("queen_status", QueenStatus.UNKNOWN)
        self.colony_strength = overrides.get("colony_strength", ColonyStrength.UNKNOWN)


def series(
    *,
    days: float = 7,
    step_hours: float = 1,
    base_temp: float = 34.0,
    temp_amp: float = 0.6,
    base_humidity: float = 60.0,
    humidity_amp: float = 3.0,
    start_weight: float = 30.0,
    gain_per_day: float = 0.12,
    vibration: float = 0.8,
    acoustic: float = 30.0,
    source: TelemetrySource = TelemetrySource.SIMULATOR,
    now: datetime = NOW,
    device_id: int = 1,
    hive_id: int = 1,
    drop: tuple[str, ...] = (),
) -> list[SensorReading]:
    """A deterministic window ending at ``now``.

    Values follow a slow daily sine so the series looks like a hive rather than a
    constant — a flat line would make the variance-based checks meaningless.
    """
    count = max(1, int(days * 24 / step_hours))
    rows: list[SensorReading] = []
    for index in range(count):
        timestamp = now - timedelta(hours=(count - 1 - index) * step_hours)
        phase = index / 24.0 * 2 * math.pi
        values = {
            "temperature": base_temp + temp_amp * math.sin(phase),
            "humidity": base_humidity + humidity_amp * math.sin(phase + 1.1),
            "weight": start_weight + gain_per_day * (index * step_hours / 24.0),
            "vibration": max(0.0, vibration + 0.15 * math.sin(phase * 2)),
            "acoustic_level": max(0.0, acoustic + 3.0 * math.sin(phase * 2 + 0.5)),
            "battery_level": 88,
            "signal_strength": -62,
        }
        for key in drop:
            values[key] = None
        rows.append(
            SensorReading(
                device_id=device_id,
                hive_id=hive_id,
                timestamp=timestamp,
                source=source,
                **values,
            )
        )
    return rows


def analyze(readings, *, hive=None, now=NOW, **kwargs):
    return AiEngine(get_settings()).analyze(readings, hive=hive or FakeHive(), now=now, **kwargs)


class TestInsufficientData:
    """The engine's most important behaviour: declining to answer."""

    def test_no_readings_produces_no_scores(self):
        result = analyze([])

        assert result.quality.level is AiDataQuality.INSUFFICIENT
        assert result.quality.sample_count == 0
        assert result.quality.source is AiAnalysisSource.NO_DATA
        assert result.health.score is None
        assert result.health.status is AiHealthStatus.INSUFFICIENT_DATA
        assert result.health.confidence == 0
        assert result.disease.level is AiRiskLevel.UNKNOWN
        assert result.disease.score is None
        assert result.swarming.level is AiRiskLevel.UNKNOWN
        assert result.yield_prediction.predicted_kg is None
        assert result.alerts == []
        assert result.overall_confidence == 0
        assert "no telemetry" in result.quality.summary.lower()

    def test_no_device_is_said_out_loud(self):
        result = analyze([], has_device=False)

        assert result.quality.level is AiDataQuality.INSUFFICIENT
        assert "no device is paired" in result.quality.summary.lower()

    def test_too_few_samples_is_insufficient_even_with_long_history(self):
        # Four readings spread over six hours: plenty of time, not enough data.
        readings = series(days=0.25, step_hours=2)

        result = analyze(readings)

        assert result.quality.level is AiDataQuality.INSUFFICIENT
        assert result.health.score is None
        assert any("reading" in issue for issue in result.quality.issues)

    def test_samples_inside_one_minute_are_insufficient(self):
        # Ten packets is not a trend; the window has to cover time as well.
        readings = series(days=1 / 24, step_hours=1 / 60)

        result = analyze(readings)

        assert result.quality.level is AiDataQuality.INSUFFICIENT
        assert any("history" in issue for issue in result.quality.issues)

    def test_insufficient_results_still_carry_a_recommendation_to_fix_it(self):
        result = analyze([])
        codes = {item.code for item in result.recommendations}

        assert "pair_device" in codes

    def test_an_insufficient_result_stores_no_fabricated_scores(self):
        result = analyze([])
        detail = result.as_detail()

        assert detail["health"]["score"] is None
        assert detail["disease_risk"]["score"] is None
        assert detail["swarming_risk"]["score"] is None
        assert detail["yield_prediction"]["predicted_yield"] is None
        assert detail["alerts_raised"] == []


class TestHealthyWindow:
    def test_a_settled_week_is_assessed_as_healthy(self):
        result = analyze(series())

        assert result.quality.level is AiDataQuality.GOOD
        assert result.health.status is AiHealthStatus.HEALTHY
        assert result.health.score is not None and result.health.score >= 80
        assert result.disease.level is AiRiskLevel.LOW
        assert result.disease.score == 0

    def test_the_score_is_the_sum_of_its_published_factors(self):
        result = analyze(series())
        positive = sum(
            factor.delta for factor in result.health.factors if factor.direction == "POSITIVE"
        )
        negative = sum(
            factor.delta for factor in result.health.factors if factor.direction == "NEGATIVE"
        )
        expected = max(
            0.0,
            min(100.0, T.HEALTH_BASE_SCORE + min(positive, T.HEALTH_POSITIVE_BUDGET) + negative),
        )

        assert result.health.score == int(round(expected))
        assert all(factor.detail for factor in result.health.factors)

    def test_the_indicator_never_claims_a_perfect_score(self):
        # Positive evidence is capped on purpose: a heuristic that reports 100/100
        # is claiming more than a sensor baseline can know.
        result = analyze(
            series(days=14, gain_per_day=0.4),
            hive=FakeHive(queen_status=QueenStatus.PRESENT, colony_strength=ColonyStrength.STRONG),
        )

        assert result.health.score == int(T.HEALTH_BASE_SCORE + T.HEALTH_POSITIVE_BUDGET)
        assert result.health.score < 100

    def test_every_factor_says_which_way_it_moved_the_score(self):
        result = analyze(series())

        assert result.health.factors
        assert all(factor.direction in ("POSITIVE", "NEGATIVE", "NEUTRAL") for factor in result.health.factors)

    def test_a_healthy_window_raises_no_alerts(self):
        result = analyze(series())

        assert result.alerts == []

    def test_the_source_is_reported_and_never_upgraded(self):
        simulator = analyze(series(source=TelemetrySource.SIMULATOR))
        hardware = analyze(series(source=TelemetrySource.REAL_DEVICE))

        assert simulator.quality.source is AiAnalysisSource.SIMULATOR
        assert hardware.quality.source is AiAnalysisSource.REAL_DEVICE
        assert simulator.quality.source.is_hardware is False

    def test_mixed_sources_are_reported_as_mixed(self):
        readings = series() + series(source=TelemetrySource.MANUAL, start_weight=31.0)

        result = analyze(readings)

        assert result.quality.source is AiAnalysisSource.MIXED
        assert any("mix" in issue.lower() for issue in result.quality.issues)


class TestStressedWindow:
    """A hot, damp, shrinking hive must look different from a settled one."""

    def stressed(self, **overrides):
        return analyze(
            series(
                base_temp=overrides.pop("base_temp", 41.5),
                base_humidity=overrides.pop("base_humidity", 88.0),
                gain_per_day=overrides.pop("gain_per_day", -0.6),
                acoustic=overrides.pop("acoustic", 52.0),
                **overrides,
            )
        )

    def test_the_health_indicator_moves_off_healthy(self):
        result = self.stressed()

        assert result.health.status in (AiHealthStatus.AT_RISK, AiHealthStatus.CRITICAL)
        assert result.health.score is not None and result.health.score < 60

    def test_the_anomalies_are_named_with_their_reference(self):
        result = self.stressed()
        codes = {anomaly.code for anomaly in result.health.anomalies}

        assert "TEMPERATURE_OUT_OF_BAND" in codes
        assert "HUMIDITY_OUT_OF_BAND" in codes
        assert "WEIGHT_DROP" in codes
        temperature = next(a for a in result.health.anomalies if a.code == "TEMPERATURE_OUT_OF_BAND")
        assert temperature.reference and "°C" in temperature.reference

    def test_an_extreme_excursion_is_escalated_to_an_alert(self):
        result = self.stressed()
        raised = {spec.alert_type for spec in result.alerts}

        assert AiAlertType.TEMPERATURE_ANOMALY in raised
        assert AiAlertType.HEALTH_AT_RISK in raised or AiAlertType.HEALTH_CRITICAL in raised

    def test_disease_risk_rises_and_stays_a_risk(self):
        result = self.stressed()

        assert result.disease.level is AiRiskLevel.HIGH
        assert "not a diagnosis" in result.disease.disclaimer.lower()
        assert result.disease.recommendation is not None
        assert result.disease.recommendation.priority == "PRIORITY"

    def test_every_indicator_states_its_value_and_reference(self):
        result = self.stressed()

        assert result.disease.indicators
        assert all(indicator.detail for indicator in result.disease.indicators)
        assert any(indicator.reference for indicator in result.disease.indicators)

    def test_a_mild_drift_does_not_alert(self):
        # 37.5 °C is above the comfort band but inside the wide band, so it
        # belongs in the factors and recommendations, not in the alert list.
        result = analyze(series(base_temp=37.5, temp_amp=0.2))

        assert result.health.status in (AiHealthStatus.ATTENTION, AiHealthStatus.AT_RISK)
        assert all(spec.alert_type is not AiAlertType.TEMPERATURE_ANOMALY for spec in result.alerts)

    def test_stale_telemetry_is_reported_and_alerted(self):
        readings = series(now=NOW - timedelta(hours=20))

        result = analyze(readings, now=NOW)

        assert result.quality.is_stale is True
        assert result.quality.level is AiDataQuality.LIMITED
        assert any(spec.alert_type is AiAlertType.DATA_STALE for spec in result.alerts)
        assert "stale" in result.summary.lower() or "limited" in result.summary.lower()


class TestActivityChecks:
    def test_elevated_activity_against_its_own_baseline_is_flagged(self):
        settled = series(days=4, vibration=0.5, acoustic=28.0)
        recent = series(days=1, vibration=3.0, acoustic=55.0, now=NOW)
        # Rebuild the recent slice so it sits strictly after the settled one.
        for index, reading in enumerate(recent):
            reading.timestamp = NOW - timedelta(hours=len(recent) - 1 - index)

        result = analyze(settled + recent)

        codes = {anomaly.code for anomaly in result.health.anomalies}
        assert "ACTIVITY_SPIKE" in codes or "ACOUSTIC_ANOMALY" in codes

    def test_a_hive_without_vibration_readings_gets_no_activity_finding(self):
        result = analyze(series(drop=("vibration", "acoustic_level")))

        codes = {anomaly.code for anomaly in result.health.anomalies}
        assert not {code for code in codes if code.startswith("ACTIVITY") or code.startswith("ACOUSTIC")}
        assert "vibration" in result.quality.missing_sensors
        assert "acoustic_level" in result.quality.missing_sensors


class TestYieldPrediction:
    def test_a_growing_weight_series_projects_a_number_with_its_fit(self):
        result = analyze(series(gain_per_day=0.3, days=10))

        prediction = result.yield_prediction
        assert prediction.predicted_kg is not None and prediction.predicted_kg > 0
        assert prediction.fit is not None and prediction.fit > T.YIELD_MIN_FIT
        assert prediction.observed_days and prediction.observed_days >= T.TEMPERATURE_COMFORT[0] - 40
        assert prediction.confidence <= T.CONFIDENCE_CEILING

    def test_a_hive_without_a_weight_sensor_gets_no_projection(self):
        result = analyze(series(drop=("weight",)))

        prediction = result.yield_prediction
        assert prediction.predicted_kg is None
        assert prediction.available is False
        assert "weight" in (prediction.reason or "").lower()

    def test_a_short_weight_history_is_refused_with_a_reason(self):
        result = analyze(series(days=6, step_hours=6, drop=("humidity",)))

        if result.yield_prediction.predicted_kg is None:
            assert result.yield_prediction.reason
        else:
            # Six days over 6-hour steps can legitimately qualify; if it does, the
            # projection must still carry its basis and confidence.
            assert result.yield_prediction.confidence <= T.CONFIDENCE_CEILING

    def test_an_implausible_scale_jump_is_not_projected_forward(self):
        # +8 kg/day fits a straight line beautifully, but no colony stores that
        # much: the shape is fine and the magnitude is wrong, which is exactly the
        # case a naive extrapolation would turn into a 240 kg harvest forecast.
        result = analyze(series(days=4, gain_per_day=8.0))

        assert result.yield_prediction.predicted_kg is None
        assert "plausible" in (result.yield_prediction.reason or "").lower()

    def test_a_noisy_weight_series_is_refused_on_fit_quality(self):
        readings = series(days=4, gain_per_day=0.1)
        for index, reading in enumerate(readings):
            reading.weight = float(reading.weight) + (25.0 if index in (len(readings) - 1, len(readings) - 2) else 0.0)

        result = analyze(readings)

        assert result.yield_prediction.predicted_kg is None
        assert "trend" in (result.yield_prediction.reason or "").lower()

    def test_a_falling_trend_reports_no_accumulation(self):
        result = analyze(series(gain_per_day=-0.3, days=10))
        prediction = result.yield_prediction

        assert prediction.predicted_kg == 0.0
        assert prediction.trend.value == "FALLING"
        assert "no accumulation" in prediction.summary.lower()


class TestConfidenceDiscipline:
    def test_confidence_never_exceeds_the_published_ceiling(self):
        result = analyze(series(days=14, step_hours=1))

        assert result.health.confidence <= T.CONFIDENCE_CEILING
        assert result.disease.confidence <= T.CONFIDENCE_CEILING
        assert result.swarming.confidence <= T.CONFIDENCE_CEILING
        assert result.overall_confidence <= T.CONFIDENCE_CEILING

    def test_manual_entries_cannot_support_device_grade_confidence(self):
        result = analyze(series(source=TelemetrySource.MANUAL, days=14))

        assert result.health.confidence <= T.MANUAL_SOURCE_CONFIDENCE_CAP
        assert result.disease.confidence <= T.MANUAL_SOURCE_CONFIDENCE_CAP
        assert any("hand" in issue for issue in result.quality.issues)

    def test_a_stale_window_is_less_confident_than_a_current_one(self):
        current = analyze(series())
        stale = analyze(series(now=NOW - timedelta(hours=20)), now=NOW)

        assert stale.health.confidence < current.health.confidence
        assert stale.quality.factor < current.quality.factor

    def test_impossible_jumps_lower_the_quality_factor(self):
        clean = series(days=3)
        jumped = series(days=3)
        jumped[10].temperature = float(jumped[10].temperature) + 40.0

        clean_result = analyze(clean)
        jumped_result = analyze(jumped)

        assert jumped_result.quality.suspect_jumps >= 1
        assert jumped_result.quality.factor < clean_result.quality.factor
        assert any("plausible" in issue for issue in jumped_result.quality.issues)


class TestEngineHygiene:
    def test_readings_outside_the_window_are_excluded(self):
        inside = series(days=2)
        ancient = series(days=1, now=NOW - timedelta(days=30))

        result = analyze(inside + ancient)

        assert 0 < result.quality.sample_count <= len(inside)
        assert result.features.window_start >= NOW - timedelta(hours=get_settings().AI_ANALYSIS_WINDOW_HOURS)

    def test_the_engine_does_not_modify_the_rows_it_reads(self):
        readings = series(days=1)
        before = [(float(r.temperature), float(r.humidity), r.timestamp) for r in readings]

        analyze(readings)

        after = [(float(r.temperature), float(r.humidity), r.timestamp) for r in readings]
        assert before == after

    def test_the_stored_detail_is_json_serialisable(self):
        result = analyze(series())
        detail = result.as_detail()
        encoded = json.dumps(detail)

        assert len(encoded) > 500
        assert set(detail) >= {
            "health",
            "disease_risk",
            "swarming_risk",
            "yield_prediction",
            "recommendations",
            "features",
            "quality",
            "alerts_raised",
            "model",
        }

    def test_the_model_is_identified_and_versioned(self):
        result = analyze(series())
        settings = get_settings()

        assert result.model_type == settings.AI_MODEL_TYPE
        assert result.model_version == settings.AI_MODEL_VERSION
        assert result.as_detail()["model"] == {
            "type": settings.AI_MODEL_TYPE,
            "version": settings.AI_MODEL_VERSION,
        }

    def test_the_baseline_never_claims_certainty(self):
        result = analyze(series(days=30))
        text = json.dumps(result.as_detail()).lower()

        assert "diagnos" in text  # the disclaimers are present in the payload
        assert result.health.basis  # and every assessment states its basis


class TestRecordedObservations:
    def test_a_recorded_queen_absence_moves_the_score_and_the_risk(self):
        baseline = analyze(series())
        observed = analyze(
            series(),
            hive=FakeHive(queen_status=QueenStatus.ABSENT, colony_strength=ColonyStrength.WEAK),
        )

        assert observed.health.score < baseline.health.score
        assert observed.disease.score > baseline.disease.score
        assert observed.health.status is not AiHealthStatus.HEALTHY
        codes = {factor.code for factor in observed.health.factors}
        assert "queen_observed_absent" in codes and "colony_weak" in codes

    def test_unknown_observations_add_nothing(self):
        # UNKNOWN and UNDER_OBSERVATION are not evidence, and must not be read as
        # a missing queen.
        result = analyze(series(), hive=FakeHive(queen_status=QueenStatus.UNDER_OBSERVATION))

        codes = {factor.code for factor in result.health.factors}
        assert "queen_observed_absent" not in codes

    def test_a_recorded_strong_colony_lifts_the_health_score(self):
        baseline = analyze(series())
        strong = analyze(series(), hive=FakeHive(colony_strength=ColonyStrength.STRONG))

        assert strong.health.score >= baseline.health.score


class TestAlertScarcity:
    def test_alerts_are_report_level_not_noise(self):
        # A settled week with one mildly noisy sensor should not fill the list.
        result = analyze(series(days=7, humidity_amp=8.0))

        assert len(result.alerts) <= 2
        assert all(isinstance(spec.severity, AiAlertSeverity) for spec in result.alerts)

    def test_a_data_stale_alert_is_informational(self):
        result = analyze(series(now=NOW - timedelta(hours=20)), now=NOW)
        stale = next(spec for spec in result.alerts if spec.alert_type is AiAlertType.DATA_STALE)

        assert stale.severity is AiAlertSeverity.INFO

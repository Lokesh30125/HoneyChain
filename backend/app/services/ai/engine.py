"""The AI engine — one entry point that turns readings into an :class:`AnalysisResult`.

``AiEngine.analyze`` is a pure function of ``(readings, hive, now)``. It touches no
database, no HTTP context and no clock of its own (the caller passes ``now``),
which is what makes it directly testable: build a list of ``SensorReading`` rows,
call ``analyze``, assert on the result.

Order of operations
-------------------
1. **Features** — extract the numbers (``features.extract_features``).
2. **Quality** — grade the evidence *first*, because everything downstream reads
   the grade. If the window cannot support a conclusion, the engine still returns
   a complete result, but every score is ``None``, every band is ``UNKNOWN`` and
   the summary states the reason. Nothing is estimated to fill the gap.
3. **Anomalies** — compare patterns against the reference bands.
4. **Assessments** — health, disease risk, swarming risk, yield projection. Each
   is independent; a sensor with no data simply removes the checks that needed it.
5. **Recommendations** — the actionable list, ordered by priority.
6. **Alerts** — the small subset worth interrupting a beekeeper for.

The result carries the sample count, quality level, source and newest-reading
timestamp that produced it (inside ``quality`` and ``features``), so a stored row
can always be read back with its own context.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from app.core.config import Settings, get_settings
from app.models.enums import AiDataQuality, ColonyStrength, QueenStatus
from app.models.hive import Hive
from app.models.sensor_reading import SensorReading
from app.services.ai.anomalies import detect_anomalies
from app.services.ai.disease import assess_disease_risk
from app.services.ai.features import extract_features
from app.services.ai.health import assess_health
from app.services.ai.quality import assess_quality
from app.services.ai.recommendations import alert_candidates, build_recommendations
from app.services.ai.swarming import assess_swarming_risk
from app.services.ai.types import AnalysisResult, QualityReport
from app.services.ai.yield_prediction import project_yield

logger = logging.getLogger(__name__)


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class AiEngine:
    """Rule-based analysis over one hive's telemetry window.

    Pass explicit ``Settings`` in tests; the default reads the application
    settings once through ``get_settings``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # -- public API ---------------------------------------------------------
    def analyze(
        self,
        readings: Sequence[SensorReading],
        *,
        hive: Hive | None = None,
        now: datetime | None = None,
        device_status: str | None = None,
        device_online: bool | None = None,
        sampling_seconds: int | None = None,
        has_device: bool = True,
    ) -> AnalysisResult:
        """Produce the full analysis for one hive.

        ``readings`` should be every row the caller fetched for the hive; rows
        outside the analysis window are filtered out here so a caller cannot widen
        the window by accident. Anything older than the window is ignored rather
        than summarised, because "the last week" is part of the contract.
        """
        moment = _as_utc(now) or datetime.now(timezone.utc)
        window_start = moment - timedelta(hours=self.settings.AI_ANALYSIS_WINDOW_HOURS)
        windowed = [
            reading
            for reading in readings
            if reading.timestamp is not None
            and window_start <= (_as_utc(reading.timestamp) or moment) <= moment
        ]
        stamps = [
            _as_utc(reading.timestamp)
            for reading in windowed
            if reading.timestamp is not None
        ]
        stamps = [stamp for stamp in stamps if stamp is not None]
        newest = max(stamps, default=None)

        queen_status = getattr(hive, "queen_status", None) or QueenStatus.UNKNOWN
        colony_strength = getattr(hive, "colony_strength", None) or ColonyStrength.UNKNOWN

        features = extract_features(
            windowed,
            now=moment,
            window_start=min(stamps, default=None) or window_start,
            window_end=newest,
        )

        quality: QualityReport = assess_quality(
            windowed,
            features,
            settings=self.settings,
            now=moment,
            newest_reading_at=newest,
            device_status=device_status,
            sampling_seconds=sampling_seconds,
            has_device=has_device,
        )
        if device_online is not None:
            quality.device_online = device_online

        has_history = quality.level is not AiDataQuality.INSUFFICIENT
        anomalies = detect_anomalies(features) if has_history else []

        health = assess_health(
            features,
            anomalies,
            quality,
            settings=self.settings,
            queen_status=queen_status,
            colony_strength=colony_strength,
        )
        disease = assess_disease_risk(
            features,
            anomalies,
            quality,
            settings=self.settings,
            queen_status=queen_status,
            colony_strength=colony_strength,
        )
        swarming = assess_swarming_risk(
            features,
            anomalies,
            quality,
            settings=self.settings,
            queen_status=queen_status,
            colony_strength=colony_strength,
            moment=moment,
        )
        prediction = project_yield(
            windowed, features, quality, settings=self.settings, now=moment
        )

        result = AnalysisResult(
            health=health,
            disease=disease,
            swarming=swarming,
            yield_prediction=prediction,
            recommendations=build_recommendations(
                features,
                anomalies,
                quality,
                health,
                disease,
                swarming,
                prediction,
                settings=self.settings,
            ),
            features=features,
            quality=quality,
            alerts=alert_candidates(anomalies, health, disease, swarming, quality=quality),
            model_type=self.settings.AI_MODEL_TYPE,
            model_version=self.settings.AI_MODEL_VERSION,
            analyzed_at=moment,
            hive_id=getattr(hive, "id", None),
            hive_code=getattr(hive, "hive_code", None),
        )
        result.overall_confidence = self._overall_confidence(result)
        result.summary = self._summary(result)

        logger.info(
            "ai.analysis_complete hive=%s samples=%s quality=%s health=%s alerts=%s",
            result.hive_code or result.hive_id,
            features.sample_count,
            quality.level.value,
            health.status.value,
            len(result.alerts),
        )
        return result

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _overall_confidence(result: AnalysisResult) -> int:
        if not result.has_prediction:
            return 0
        confidences = [
            result.health.confidence,
            result.disease.confidence,
            result.swarming.confidence,
        ]
        if result.yield_prediction.predicted_kg is not None:
            confidences.append(result.yield_prediction.confidence)
        return int(round(sum(confidences) / len(confidences))) if confidences else 0

    @staticmethod
    def _summary(result: AnalysisResult) -> str:
        """One sentence a dashboard can print without reinterpreting the numbers."""
        if not result.has_prediction:
            return result.quality.summary
        parts = [
            "Health indicator "
            f"{result.health.score}/100 ({result.health.status.value.replace('_', ' ').lower()})"
        ]
        if result.disease.level.value != "UNKNOWN":
            parts.append(f"disease risk {result.disease.level.value.lower()}")
        if result.swarming.level.value != "UNKNOWN":
            parts.append(f"swarming risk {result.swarming.level.value.lower()}")
        prediction = result.yield_prediction
        if prediction.predicted_kg is not None and prediction.trend.value == "FALLING":
            parts.append("weight trending down")
        elif prediction.predicted_kg is not None:
            parts.append(
                f"projected weight change about {prediction.predicted_kg:.2f} kg "
                f"per {prediction.period_days} days"
            )
        text = ", ".join(parts) + "."
        if result.quality.level is AiDataQuality.LIMITED:
            text += " Telemetry was limited, so treat this as indicative."
        return text


__all__ = ["AiEngine"]

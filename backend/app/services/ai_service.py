"""AiService — the application layer around the AI engine.

It owns everything the engine deliberately does not: which hive a caller may
touch, which telemetry window to load, when a stored analysis is still good
enough, what to persist, what to audit, and how to describe freshness to the UI.

Three policies live here
------------------------
**Read-through analysis.** ``insight`` returns the newest stored analysis. If
there is none, or the stored one is stale (older than ``AI_ANALYSIS_TTL_HOURS``)
or enough new readings have arrived (``AI_RECOMPUTE_AFTER_SAMPLES``), it computes
and stores a fresh one — but only when ``AI_AUTO_ANALYSIS_ENABLED`` is true, and
only for a caller with the analyse permission. Passing ``refresh=False`` reads
only, and ``refresh=True`` forces a recomputation. This is what keeps the
dashboard populated without a scheduler, and it is documented on the endpoint
because a GET that may write deserves to be explicit.

**Insufficient data is a stored outcome.** A hive with no readings produces an
analysis row with ``data_quality=INSUFFICIENT``, ``sample_count=0`` and null
scores. That row is a true statement about the hive ("nothing has been recorded
yet") and it stops the platform from re-running the engine on every page view.
The API layer turns it into an empty state, never into zeros that look like
measurements.

**Scope is enforced in the service.** A beekeeper can only analyse or read their
own hives; staff with ``AI_READ_ALL``/``AI_ANALYZE_ALL`` are unscoped. Cross-owner
access raises 404, matching the hive and device endpoints, so an outsider cannot
probe for the existence of a hive.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Permission, has_permission
from app.models.ai_analysis import HiveAiAnalysis
from app.models.enums import (
    AuditAction,
    AiDataQuality,
    AiHealthStatus,
    AiRiskLevel,
    DeviceStatus,
)
from app.models.hive import Hive
from app.models.user import User
from app.repositories.ai_repository import AiAnalysisRepository
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.iot_device_repository import IotDeviceRepository, SensorConfigRepository
from app.repositories.sensor_reading_repository import SensorReadingRepository
from app.services.ai import AiEngine
from app.services.ai_alert_service import AiAlertService
from app.services.audit_service import AuditService
from app.services.device_service import DeviceService

logger = get_logger(__name__)

#: How many readings to load for one analysis. The window is seven days by
#: default; this guards against a device reporting every second filling memory.
_MAX_WINDOW_READINGS = 5000


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _float(value) -> float | None:
    return None if value is None else float(value)


class AiService:
    """Analyse hives, store the results and read them back for screens."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.engine = AiEngine(self.settings)
        self.analyses = AiAnalysisRepository(session)
        self.hives = HiveRepository(session)
        self.devices = IotDeviceRepository(session)
        self.sensors = SensorConfigRepository(session)
        self.readings = SensorReadingRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.device_service = DeviceService(session, self.settings)
        self.alert_service = AiAlertService(session, self.settings)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ #
    # Scope
    # ------------------------------------------------------------------ #
    def _owner_id(self, user: User | None) -> uuid.UUID | None:
        if user is None:
            return None
        beekeeper = self.beekeepers.get_by_user_id(user.id)
        return beekeeper.id if beekeeper is not None else None

    def _is_staff(self, user: User | None) -> bool:
        return user is None or has_permission(user.role, Permission.AI_READ_ALL)

    def scoped_hives(self, user: User | None) -> list[Hive]:
        """Every hive the caller may analyse, in one query.

        A beekeeper with no apiary gets an empty list — an empty dashboard, not
        everybody's hives.
        """
        if self._is_staff(user):
            rows, _total = self.hives.search(page=1, page_size=1000)
            return rows
        owner_id = self._owner_id(user)
        if owner_id is None:
            return []
        return self.hives.list_for_beekeeper(owner_id)

    def scoped_hive_ids(self, user: User | None) -> list[uuid.UUID]:
        return [hive.id for hive in self.scoped_hives(user)]

    def _intersect_with_scope(
        self, user: User | None, hive_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]:
        """Keep only the requested hives the caller may already see."""
        visible = set(self.scoped_hive_ids(user))
        if not visible:
            return []
        return [hive_id for hive_id in hive_ids if hive_id in visible]

    def summary_for_hive_ids(self, hive_ids: list[uuid.UUID]) -> dict:
        """The same aggregation for a set of hives, with no user in the picture.

        Used by the cluster view, where visibility was already settled by the
        caller's ``CLUSTER_ANALYTICS_READ`` grant and the cluster relationship.
        """
        if not hive_ids:
            return {
                "total_hives": 0,
                "analysed_hives": 0,
                "hives_without_analysis": 0,
                "hives_with_telemetry": 0,
                "health": {status.value: 0 for status in AiHealthStatus},
                "disease_risk": {level.value: 0 for level in AiRiskLevel},
                "swarming_risk": {level.value: 0 for level in AiRiskLevel},
                "yield": {
                    "hives_with_projection": 0,
                    "total_predicted_kg": 0.0,
                    "average_predicted_kg": 0.0,
                },
                "open_alerts": 0,
                "alerts_by_severity": {},
                "model": self._model_identity(),
            }

        analysed = self.analyses.analyzed_hive_ids(hive_ids)
        latest = self.analyses.latest_per_hive(hive_ids)
        with_telemetry = [
            hive_id
            for hive_id in hive_ids
            if self.readings.latest_timestamp(hive_id=hive_id) is not None
        ]
        return {
            "total_hives": len(hive_ids),
            "analysed_hives": len(analysed),
            "hives_without_analysis": len(hive_ids) - len(analysed),
            "hives_with_telemetry": len(with_telemetry),
            "health": self.analyses.count_by_health_status(hive_ids=hive_ids),
            "disease_risk": self.analyses.count_by_risk_level(kind="disease", hive_ids=hive_ids),
            "swarming_risk": self.analyses.count_by_risk_level(kind="swarming", hive_ids=hive_ids),
            "yield": self.analyses.yield_projection(hive_ids=hive_ids),
            "open_alerts": self.alert_service.alerts.count(hive_ids=hive_ids),
            "alerts_by_severity": self.alert_service.alerts.count_by_severity(hive_ids=hive_ids),
            "latest_analyses": {str(key): row for key, row in latest.items()},
            "model": self._model_identity(),
        }

    def get_hive_for_user(self, user: User | None, hive_id: uuid.UUID) -> Hive:
        """Load a hive, refusing one outside the caller's scope."""
        hive = self.hives.get(hive_id)
        if hive is None:
            raise NotFoundError("Hive not found")
        if not self._is_staff(user):
            owner_id = self._owner_id(user)
            if owner_id is None or hive.beekeeper_id != owner_id:
                raise NotFoundError("Hive not found")
        return hive

    # ------------------------------------------------------------------ #
    # Freshness
    # ------------------------------------------------------------------ #
    def is_stale(self, analysis: HiveAiAnalysis | None, *, now: datetime | None = None) -> bool:
        """A stored analysis is stale when it is old, or its input is.

        Both halves matter: an analysis run a minute ago over six-day-old
        telemetry is not fresh, and neither is one run a week ago over telemetry
        that stopped then.
        """
        if analysis is None:
            return True
        moment = _as_utc(now) or datetime.now(timezone.utc)
        analyzed_at = _as_utc(analysis.analyzed_at)
        if analyzed_at is None or (moment - analyzed_at) > timedelta(
            hours=self.settings.AI_ANALYSIS_TTL_HOURS
        ):
            return True
        newest = _as_utc(analysis.newest_reading_at)
        if newest is None:
            # No telemetry was available when it ran; only new readings make it
            # worth re-running, which `should_analyze` decides.
            return False
        return (moment - newest) > timedelta(hours=self.settings.AI_STALE_AFTER_HOURS)

    def needs_analysis(
        self, hive_id: uuid.UUID, analysis: HiveAiAnalysis | None, *, now: datetime | None = None
    ) -> tuple[bool, str]:
        """``(should_run, reason)`` for the read-through policy."""
        if analysis is None:
            return True, "no_analysis"
        if self.is_stale(analysis, now=now):
            return True, "stale"
        newest = self.readings.latest_timestamp(hive_id=hive_id)
        if newest is not None:
            stored = _as_utc(analysis.newest_reading_at)
            if stored is None or _as_utc(newest) > stored:
                added = self.readings.count_in_window(hive_id=hive_id, since=stored)
                if added >= self.settings.AI_RECOMPUTE_AFTER_SAMPLES:
                    return True, "new_telemetry"
        return False, "fresh"

    # ------------------------------------------------------------------ #
    # Analysis
    # ------------------------------------------------------------------ #
    def analyze_hive(
        self,
        hive: Hive,
        *,
        user: User | None = None,
        force: bool = False,
        commit: bool = True,
        note: str | None = None,
        now: datetime | None = None,
    ) -> tuple[HiveAiAnalysis, dict]:
        """Run the engine over one hive's window and store the result.

        ``force`` bypasses the "is it worth running" question; it does not bypass
        data quality, which is computed from the readings themselves.
        """
        moment = _as_utc(now) or datetime.now(timezone.utc)
        window_start = moment - timedelta(hours=self.settings.AI_ANALYSIS_WINDOW_HOURS)

        device = self._primary_device(hive.id)
        readings = self.readings.history(
            hive_id=hive.id, start=window_start, end=moment, limit=_MAX_WINDOW_READINGS
        )
        device_status = (
            self.device_service.derive_status(device) if device is not None else None
        )

        result = self.engine.analyze(
            readings,
            hive=hive,
            now=moment,
            device_status=str(device_status) if device_status is not None else None,
            device_online=None if device is None else device_status == DeviceStatus.ONLINE,
            sampling_seconds=self._sampling_seconds(device),
            has_device=device is not None,
        )

        analysis = self._persist(hive, result, moment)
        counters = self.alert_service.sync_for_analysis(result, analysis, hive, now=moment)

        self.audit.record(
            AuditAction.AI_ANALYSIS_RUN,
            actor=user,
            entity_type="hive",
            entity_id=hive.id,
            metadata={
                "hive_code": hive.hive_code,
                "data_quality": result.quality.level.value,
                "sample_count": result.features.sample_count,
                "analysis_source": result.quality.source.value,
                "health_status": result.health.status.value,
                "health_score": result.health.score,
                "disease_risk_level": result.disease.level.value,
                "swarming_risk_level": result.swarming.level.value,
                "alerts_created": counters["created"],
                "alerts_bumped": counters["bumped"],
                "alerts_resolved": counters["resolved"],
                "model": f"{result.model_type}@{result.model_version}",
                "note": note,
            },
            description=(
                f"AI analysis run for hive {hive.hive_code} "
                f"({result.quality.level.value}, {result.features.sample_count} readings)"
            ),
        )

        if counters["created"]:
            self.audit.record(
                AuditAction.AI_ALERT_CREATED,
                actor=user,
                entity_type="hive",
                entity_id=hive.id,
                metadata={"count": counters["created"], "hive_code": hive.hive_code},
                description=(
                    f"{counters['created']} AI alert(s) raised for hive {hive.hive_code}"
                ),
            )

        if commit:
            self.session.commit()
            self.session.refresh(analysis)

        logger.info(
            "ai.service_analyzed hive=%s samples=%s quality=%s alerts_created=%s alerts_resolved=%s",
            hive.hive_code,
            result.features.sample_count,
            result.quality.level.value,
            counters["created"],
            counters["resolved"],
        )
        return analysis, counters

    def _persist(self, hive: Hive, result, moment: datetime) -> HiveAiAnalysis:
        """Write one analysis row: scalar columns for SQL, JSONB for the reasoning."""
        prediction = result.yield_prediction
        return self.analyses.record(
            hive_id=hive.id,
            beekeeper_id=hive.beekeeper_id,
            analyzed_at=moment,
            window_start=result.features.window_start,
            window_end=result.features.window_end,
            sample_count=result.features.sample_count,
            newest_reading_at=result.quality.newest_reading_at,
            data_quality=result.quality.level,
            analysis_source=result.quality.source,
            model_type=result.model_type,
            model_version=result.model_version,
            health_score=result.health.score,
            health_status=result.health.status,
            health_confidence=result.health.confidence,
            health_trend=result.health.trend,
            disease_risk_score=result.disease.score,
            disease_risk_level=result.disease.level,
            disease_confidence=result.disease.confidence,
            swarming_risk_score=result.swarming.score,
            swarming_risk_level=result.swarming.level,
            swarming_confidence=result.swarming.confidence,
            predicted_yield_kg=prediction.predicted_kg,
            yield_confidence=prediction.confidence,
            yield_trend=prediction.trend,
            yield_period_days=prediction.period_days,
            overall_confidence=result.overall_confidence,
            detail=result.as_detail(),
        )

    def _primary_device(self, hive_id: uuid.UUID):
        """The device whose state the analysis should reflect.

        A hive can have more than one node; the one seen most recently is the one
        reporting for the hive now, which is what the quality report describes.
        """
        devices = self.devices.list_for_hive(hive_id)
        if not devices:
            return None
        return max(
            devices,
            key=lambda device: (
                _as_utc(device.last_seen) or datetime.min.replace(tzinfo=timezone.utc)
            ),
        )

    def _sampling_seconds(self, device) -> int | None:
        """Configured cadence, used to judge whether a window is complete."""
        if device is None:
            return None
        temperature = self.sensors.get_for_device_type(device.id, "TEMPERATURE")
        if temperature is not None and temperature.sampling_interval:
            return int(temperature.sampling_interval)
        return None

    # ------------------------------------------------------------------ #
    # Reads used by the screens
    # ------------------------------------------------------------------ #
    def latest_for_hive(self, hive_id: uuid.UUID) -> HiveAiAnalysis | None:
        return self.analyses.latest_for_hive(hive_id)

    def history_for_hive(
        self, hive_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[HiveAiAnalysis], int]:
        return (
            self.analyses.history(hive_id, limit=limit, offset=offset),
            self.analyses.count_for_hive(hive_id),
        )

    def latest_for_hives(self, hive_ids: list[uuid.UUID]) -> dict[uuid.UUID, HiveAiAnalysis]:
        return self.analyses.latest_per_hive(hive_ids)

    def summary(self, user: User | None, *, hive_ids: list[uuid.UUID] | None = None) -> dict:
        """Aggregate AI state for the caller's scope, computed in SQL.

        ``hive_ids`` narrows the scope further — it is how the cluster view asks
        for "the AI state of these hives" without reimplementing the aggregation.
        It only ever *reduces* what the caller could already see; the API resolves
        it from the cluster relationship, never from a request parameter.
        """
        if hive_ids is None:
            hive_ids = self.scoped_hive_ids(user)
        else:
            hive_ids = self._intersect_with_scope(user, hive_ids)
        if not hive_ids:
            return {
                "total_hives": 0,
                "analysed_hives": 0,
                "hives_without_analysis": 0,
                "hives_with_telemetry": 0,
                "health": {},
                "disease_risk": {},
                "swarming_risk": {},
                "yield": {"hives_with_projection": 0, "total_predicted_kg": 0.0,
                          "average_predicted_kg": 0.0},
                "open_alerts": 0,
                "alerts_by_severity": {},
                "model": self._model_identity(),
            }

        health = self.analyses.count_by_health_status(hive_ids=hive_ids)
        disease = self.analyses.count_by_risk_level(kind="disease", hive_ids=hive_ids)
        swarming = self.analyses.count_by_risk_level(kind="swarming", hive_ids=hive_ids)
        analysed = self.analyses.analyzed_hive_ids(hive_ids)
        alerts = self.alert_service.summary(user) if user is not None else {
            "open_total": self.alert_service.alerts.count(hive_ids=hive_ids),
            "by_severity": self.alert_service.alerts.count_by_severity(hive_ids=hive_ids),
        }

        return {
            "total_hives": len(hive_ids),
            "analysed_hives": len(analysed),
            "hives_without_analysis": len(hive_ids) - len(analysed),
            "hives_with_telemetry": sum(
                1
                for hive_id in hive_ids
                if self.readings.latest_timestamp(hive_id=hive_id) is not None
            ),
            "health": health,
            "disease_risk": disease,
            "swarming_risk": swarming,
            "yield": self.analyses.yield_projection(hive_ids=hive_ids),
            "open_alerts": alerts.get("open_total", 0),
            "alerts_by_severity": alerts.get("by_severity", {}),
            "model": self._model_identity(),
        }

    def _model_identity(self) -> dict:
        """What produced the numbers, printed on every AI screen."""
        return {
            "type": self.settings.AI_MODEL_TYPE,
            "version": self.settings.AI_MODEL_VERSION,
            "baseline": True,
            "note": (
                "Rule-based baseline model. Scores describe recorded sensor patterns against "
                "reference bands; they are monitoring indicators, not diagnoses."
            ),
        }

    def freshness(self, analysis: HiveAiAnalysis | None, *, now: datetime | None = None) -> dict:
        """Everything a screen needs to caption a stored assessment honestly."""
        moment = _as_utc(now) or datetime.now(timezone.utc)
        if analysis is None:
            return {
                "has_analysis": False,
                "analyzed_at": None,
                "age_minutes": None,
                "is_stale": True,
                "ttl_hours": self.settings.AI_ANALYSIS_TTL_HOURS,
                "stale_after_hours": self.settings.AI_STALE_AFTER_HOURS,
            }
        analyzed_at = _as_utc(analysis.analyzed_at)
        newest = _as_utc(analysis.newest_reading_at)
        return {
            "has_analysis": True,
            "analyzed_at": analyzed_at,
            "age_minutes": (moment - analyzed_at).total_seconds() / 60.0 if analyzed_at else None,
            "newest_reading_at": newest,
            "reading_age_minutes": (moment - newest).total_seconds() / 60.0 if newest else None,
            "is_stale": self.is_stale(analysis, now=moment),
            "ttl_hours": self.settings.AI_ANALYSIS_TTL_HOURS,
            "stale_after_hours": self.settings.AI_STALE_AFTER_HOURS,
        }

    def snapshot_for_hive(
        self,
        hive: Hive,
        *,
        user: User | None = None,
        refresh: bool | None = None,
        commit: bool = True,
    ) -> tuple[HiveAiAnalysis | None, dict]:
        """The read-through entry point used by ``GET /ai/hives/{id}``.

        Returns ``(analysis, meta)`` where ``meta`` records whether an analysis
        was computed during this call and why, so the endpoint can be honest in
        its response about when the numbers were produced.
        """
        now = datetime.now(timezone.utc)
        analysis = self.analyses.latest_for_hive(hive.id)
        auto_enabled = self.settings.AI_AUTO_ANALYSIS_ENABLED

        if refresh is False:
            return analysis, {"computed": False, "reason": "read_only", "auto": False}

        should_run, reason = self.needs_analysis(hive.id, analysis, now=now)
        if refresh is True:
            should_run, reason = True, "forced"
        elif not auto_enabled:
            # Keep the reason the policy produced (no_analysis / stale /
            # new_telemetry) but record that auto-analysis is what stopped it.
            reason = "auto_disabled" if should_run else reason
            should_run = False

        if not should_run:
            return analysis, {"computed": False, "reason": reason, "auto": auto_enabled}

        if user is not None and not has_permission(user.role, Permission.AI_ANALYZE_SELF):
            # Read-only staff roles can see assessments but not generate them.
            return analysis, {"computed": False, "reason": "not_permitted", "auto": auto_enabled}

        analysis, _counters = self.analyze_hive(hive, user=user, commit=commit)
        return analysis, {"computed": True, "reason": reason, "auto": auto_enabled}

    def analyse_all(
        self, user: User | None, *, commit: bool = True, note: str | None = None
    ) -> dict:
        """Analyse every hive in scope — the bulk action and the test hook.

        Sequential and synchronous: this is a manual "refresh everything" action
        for a beekeeper's own hives, not a background job over the whole platform.
        """
        hives = self.scoped_hives(user)
        analysed = 0
        insufficient = 0
        alerts_created = 0
        for hive in hives:
            analysis, counters = self.analyze_hive(hive, user=user, commit=False, note=note)
            analysed += 1
            alerts_created += counters["created"]
            if analysis.data_quality is AiDataQuality.INSUFFICIENT:
                insufficient += 1
        if commit:
            self.session.commit()
        return {
            "hives_analyzed": analysed,
            "hives_with_insufficient_data": insufficient,
            "alerts_created": alerts_created,
            "model": self._model_identity(),
        }


__all__ = ["AiService"]

"""Alert lifecycle for the AI engine.

The engine decides *what* is worth raising. This service decides what happens to
it, and the rules are the whole point of the module:

**One open alert per signal per hive.** The database does not enforce this with a
unique constraint — a partial index on ``status`` would not work on the SQLite
fallback the test suite uses — so the rule lives here: for a given
``dedupe_key`` (hive + alert type), if an alert is already OPEN or ACKNOWLEDGED
and was last seen inside the cooldown window, the new occurrence *bumps* that
alert (``occurrences += 1``, ``last_seen_at`` refreshed) instead of creating a
second row. A signal that comes back after the cooldown expires is recorded as a
new alert, because a hive that was fine for a week and is now not is news.

**Alerts close themselves.** After every sync, any non-resolved alert for the hive
whose signal did not reappear in the latest analysis is marked RESOLVED. Without
that the list grows forever and stops meaning anything.

**Acknowledgement is a human act.** ``acknowledge`` records who and when and
keeps the alert in the list (still not resolved); ``resolve`` closes it; ``reopen``
puts it back. Nothing here sends a notification — there is no notification system
in this phase, and the API says so.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.permissions import Permission, has_permission
from app.models.ai_alert import AiAlert
from app.models.enums import AuditAction, AiAlertSeverity, AiAlertStatus
from app.models.user import User
from app.repositories.ai_repository import AiAlertRepository, AiAnalysisRepository
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.hive_repository import HiveRepository
from app.services.audit_service import AuditService


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def dedupe_key_for(hive_id: uuid.UUID, alert_type) -> str:
    """Stable identity of a signal: one hive, one alert type.

    Exposed as a function because the engine's specs and the stored rows must
    agree on the format — a mismatch would silently create duplicate alerts.
    """
    return f"{hive_id}:{str(alert_type)}"


class AiAlertService:
    """Create, de-duplicate, list and close AI alerts."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.alerts = AiAlertRepository(session)
        self.analyses = AiAnalysisRepository(session)
        self.hives = HiveRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ #
    # Scope helpers
    # ------------------------------------------------------------------ #
    def _owner_id(self, user: User) -> uuid.UUID | None:
        beekeeper = self.beekeepers.get_by_user_id(user.id)
        return beekeeper.id if beekeeper is not None else None

    def _scope(self, user: User) -> tuple[uuid.UUID | None, list[uuid.UUID] | None]:
        """``(beekeeper_id, hive_ids)`` — never both, and never neither for a
        beekeeper. A beekeeper's alerts are their own; staff see everything."""
        if has_permission(user.role, Permission.AI_READ_ALL):
            return None, None
        owner_id = self._owner_id(user)
        if owner_id is None:
            # No apiary to scope to: an empty result, not an error and never
            # every alert on the platform.
            return None, []
        return owner_id, None

    # ------------------------------------------------------------------ #
    # Sync (called by AiService after every analysis)
    # ------------------------------------------------------------------ #
    def sync_for_analysis(self, result, analysis, hive, *, now: datetime | None = None) -> dict:
        """Reconcile the alert table with the alerts the latest analysis raised.

        Takes the engine's ``AnalysisResult`` (which holds the full ``AlertSpec``
        objects) as well as the persisted analysis row, so the alert text is
        stored exactly as the engine produced it rather than re-derived from the
        trimmed JSON summary.

        Returns counters for logging and tests: ``created``, ``bumped``,
        ``resolved``.
        """
        moment = (
            _as_utc(now)
            or _as_utc(analysis.analyzed_at)
            or _as_utc(result.analyzed_at)
            or datetime.now(timezone.utc)
        )
        cooldown_start = moment - timedelta(hours=self.settings.AI_ALERT_COOLDOWN_HOURS)

        created = 0
        bumped = 0
        keep_keys: list[str] = []

        for spec in result.alerts:
            key = dedupe_key_for(hive.id, spec.alert_type)
            keep_keys.append(key)
            existing = self.alerts.active_for_key(dedupe_key=key, since=cooldown_start)
            context = self._context_for(result, spec)

            if existing is not None:
                self.alerts.touch(
                    existing,
                    seen_at=moment,
                    severity=spec.severity,
                    title=spec.title,
                    message=spec.message,
                    context=context,
                    analysis_id=analysis.id,
                )
                bumped += 1
                continue

            self.alerts.record(
                hive_id=hive.id,
                beekeeper_id=hive.beekeeper_id,
                analysis_id=analysis.id,
                alert_type=spec.alert_type,
                severity=spec.severity,
                title=spec.title,
                message=spec.message,
                metric=spec.metric,
                dedupe_key=key,
                occurrences=1,
                first_seen_at=moment,
                last_seen_at=moment,
                status=AiAlertStatus.OPEN,
                context=context,
            )
            created += 1

        resolved = self.alerts.resolve_missing(hive.id, keep_keys=keep_keys)
        self.session.flush()
        return {
            "created": created,
            "bumped": bumped,
            "resolved": resolved,
            "active": len(keep_keys),
        }

    @staticmethod
    def _context_for(result, spec) -> dict:
        """The alert's own context, plus the assessment it came from.

        The full analysis payload already lives on the analysis row; duplicating
        it here would make the alert table heavy and let two copies drift apart.
        """
        context = dict(spec.context or {})
        context.update(
            {
                "health_status": result.health.status.value,
                "health_score": result.health.score,
                "disease_level": result.disease.level.value,
                "swarming_level": result.swarming.level.value,
                "data_quality": result.quality.level.value,
                "analysis_source": result.quality.source.value,
                "model": {"type": result.model_type, "version": result.model_version},
            }
        )
        return context

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def list_items(
        self,
        user: User,
        *,
        hive_id: uuid.UUID | None = None,
        status: AiAlertStatus | None = None,
        severity: AiAlertSeverity | None = None,
        alert_type: str | None = None,
        include_resolved: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AiAlert], int]:
        beekeeper_id, hive_ids = self._scope(user)
        if hive_id is not None:
            hive_ids = [hive_id]
        if hive_ids is not None and not hive_ids:
            return [], 0

        if status is None and not include_resolved:
            # "Everything that still needs attention" is the default view.
            rows_open = self.alerts.search(
                hive_ids=hive_ids,
                beekeeper_id=beekeeper_id,
                status=AiAlertStatus.OPEN,
                severity=severity,
                alert_type=alert_type,
                limit=limit,
                offset=offset,
            )
            rows_acked = self.alerts.search(
                hive_ids=hive_ids,
                beekeeper_id=beekeeper_id,
                status=AiAlertStatus.ACKNOWLEDGED,
                severity=severity,
                alert_type=alert_type,
                limit=limit,
                offset=offset,
            )
            merged = {row.id: row for row in rows_open + rows_acked}
            ordered = sorted(merged.values(), key=lambda row: row.last_seen_at, reverse=True)[:limit]
            total = self.alerts.count(
                hive_ids=hive_ids, beekeeper_id=beekeeper_id, status=AiAlertStatus.OPEN,
                severity=severity, alert_type=alert_type,
            ) + self.alerts.count(
                hive_ids=hive_ids, beekeeper_id=beekeeper_id, status=AiAlertStatus.ACKNOWLEDGED,
                severity=severity, alert_type=alert_type,
            )
            return ordered, total

        rows = self.alerts.search(
            hive_ids=hive_ids,
            beekeeper_id=beekeeper_id,
            status=status,
            severity=severity,
            alert_type=alert_type,
            limit=limit,
            offset=offset,
        )
        total = self.alerts.count(
            hive_ids=hive_ids, beekeeper_id=beekeeper_id, status=status,
            severity=severity, alert_type=alert_type,
        )
        return rows, total

    def get_for_user(self, user: User, alert_id: uuid.UUID) -> AiAlert:
        """Fetch one alert, refusing anything outside the caller's scope.

        Out-of-scope alerts raise 404 rather than 403: a beekeeper should not be
        able to probe for the existence of other people's alerts.
        """
        alert = self.alerts.get(alert_id)
        if alert is None:
            raise NotFoundError("Alert not found")
        if not has_permission(user.role, Permission.AI_READ_ALL):
            owner_id = self._owner_id(user)
            if owner_id is None or alert.beekeeper_id != owner_id:
                raise NotFoundError("Alert not found")
        return alert

    def list_for_hive(self, hive_id: uuid.UUID, *, include_resolved: bool = False, limit: int = 50):
        return self.alerts.list_for_hive(hive_id, limit=limit, include_resolved=include_resolved)

    def summary_for_hive_ids(self, hive_ids: list[uuid.UUID]) -> dict:
        """Alert counters for a set of hives (the cluster view's scope)."""
        by_severity = self.alerts.count_by_severity(hive_ids=hive_ids)
        return {
            "open_total": self.alerts.count(hive_ids=hive_ids),
            "by_severity": by_severity,
            "acknowledged": self.alerts.count(hive_ids=hive_ids, status=AiAlertStatus.ACKNOWLEDGED),
            "resolved": self.alerts.count(hive_ids=hive_ids, status=AiAlertStatus.RESOLVED),
        }

    def summary(self, user: User) -> dict:
        """Counts for the alert tiles: open by severity, plus the total."""
        beekeeper_id, hive_ids = self._scope(user)
        if hive_ids is not None and not hive_ids:
            return {
                "open_total": 0,
                "by_severity": {severity.value: 0 for severity in AiAlertSeverity},
                "acknowledged": 0,
                "resolved": 0,
            }
        by_severity = self.alerts.count_by_severity(
            hive_ids=hive_ids, beekeeper_id=beekeeper_id, open_only=True
        )
        return {
            "open_total": sum(by_severity.values()),
            "by_severity": {
                severity.value: int(by_severity.get(severity.value, 0))
                for severity in AiAlertSeverity
            },
            "acknowledged": self.alerts.count(
                hive_ids=hive_ids, beekeeper_id=beekeeper_id, status=AiAlertStatus.ACKNOWLEDGED
            ),
            "resolved": self.alerts.count(
                hive_ids=hive_ids, beekeeper_id=beekeeper_id, status=AiAlertStatus.RESOLVED
            ),
        }

    # ------------------------------------------------------------------ #
    # Transitions
    # ------------------------------------------------------------------ #
    def acknowledge(self, user: User, alert_id: uuid.UUID, *, note: str | None = None) -> AiAlert:
        alert = self.get_for_user(user, alert_id)
        if alert.status is AiAlertStatus.RESOLVED:
            raise ValidationError("A resolved alert cannot be acknowledged; reopen it first")
        if alert.status is AiAlertStatus.ACKNOWLEDGED:
            return alert

        moment = datetime.now(timezone.utc)
        self.alerts.set_status(
            alert, status=AiAlertStatus.ACKNOWLEDGED, actor_id=user.id, acknowledged_at=moment
        )
        if note:
            context = dict(alert.context or {})
            context["acknowledged_note"] = note[:500]
            alert.context = context
        self.audit.record(
            AuditAction.AI_ALERT_ACKNOWLEDGED,
            actor=user,
            entity_type="ai_alert",
            entity_id=alert.id,
            metadata={"alert_type": str(alert.alert_type), "severity": str(alert.severity)},
            description=f"AI alert {alert.alert_type} acknowledged for hive {alert.hive_id}",
        )
        self.session.commit()
        self.session.refresh(alert)
        return alert

    def resolve(self, user: User, alert_id: uuid.UUID, *, note: str | None = None) -> AiAlert:
        alert = self.get_for_user(user, alert_id)
        if alert.status is AiAlertStatus.RESOLVED:
            return alert
        self.alerts.set_status(
            alert, status=AiAlertStatus.RESOLVED, actor_id=user.id,
            acknowledged_at=alert.acknowledged_at or datetime.now(timezone.utc),
        )
        if note:
            context = dict(alert.context or {})
            context["resolved_note"] = note[:500]
            alert.context = context
        self.audit.record(
            AuditAction.AI_ALERT_ACKNOWLEDGED,
            actor=user,
            entity_type="ai_alert",
            entity_id=alert.id,
            metadata={"status": "RESOLVED", "alert_type": str(alert.alert_type)},
            description=f"AI alert {alert.alert_type} resolved for hive {alert.hive_id}",
        )
        self.session.commit()
        self.session.refresh(alert)
        return alert

    def reopen(self, user: User, alert_id: uuid.UUID) -> AiAlert:
        alert = self.get_for_user(user, alert_id)
        if alert.status is AiAlertStatus.OPEN:
            return alert
        self.alerts.set_status(alert, status=AiAlertStatus.OPEN)
        self.session.commit()
        self.session.refresh(alert)
        return alert

    def resolve_all_for_hive(self, hive_id: uuid.UUID) -> int:
        """Close every open alert on a hive (used when a hive is removed)."""
        resolved = self.alerts.resolve_missing(hive_id, keep_keys=[])
        self.session.flush()
        return resolved


__all__ = ["AiAlertService", "dedupe_key_for"]

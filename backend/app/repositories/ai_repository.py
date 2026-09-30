"""Data access for the AI engine: stored analyses and the alerts they raised.

The AI module reads the telemetry time series through
:class:`~app.repositories.sensor_reading_repository.SensorReadingRepository` — it
does not own that data and never writes to it. What it owns is here:

* ``AiAnalysisRepository`` — the analysis records themselves, including the two
  batched reads the dashboards need (latest analysis per hive, and the aggregate
  counters that will feed cluster analytics);
* ``AiAlertRepository`` — active alerts, their de-duplication lookup and their
  read-state transitions.

Both are thin: the scoring itself lives in ``app.services.ai`` and never touches
SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.models.ai_alert import AiAlert
from app.models.ai_analysis import HiveAiAnalysis
from app.models.enums import AiAlertStatus, AiHealthStatus, AiRiskLevel
from app.repositories.base import BaseRepository


class AiAnalysisRepository(BaseRepository[HiveAiAnalysis]):
    model = HiveAiAnalysis

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def record(
        self,
        *,
        hive_id: uuid.UUID,
        beekeeper_id: uuid.UUID,
        analyzed_at: datetime,
        **values,
    ) -> HiveAiAnalysis:
        return self.create(
            hive_id=hive_id, beekeeper_id=beekeeper_id, analyzed_at=analyzed_at, **values
        )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def latest_for_hive(self, hive_id: uuid.UUID) -> HiveAiAnalysis | None:
        statement = (
            select(HiveAiAnalysis)
            .where(HiveAiAnalysis.hive_id == hive_id)
            .order_by(HiveAiAnalysis.analyzed_at.desc(), HiveAiAnalysis.created_at.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalars().first()

    def count_for_hive(self, hive_id: uuid.UUID) -> int:
        statement = (
            select(func.count())
            .select_from(HiveAiAnalysis)
            .where(HiveAiAnalysis.hive_id == hive_id)
        )
        return int(self.session.execute(statement).scalar_one())

    def history(
        self,
        hive_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[HiveAiAnalysis]:
        statement = (
            select(HiveAiAnalysis)
            .where(HiveAiAnalysis.hive_id == hive_id)
            .order_by(HiveAiAnalysis.analyzed_at.desc(), HiveAiAnalysis.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.execute(statement).scalars().all())

    def latest_per_hive(self, hive_ids: list[uuid.UUID]) -> dict[uuid.UUID, HiveAiAnalysis]:
        """Newest analysis for each hive, in one query (list screens).

        ``DISTINCT ON`` on PostgreSQL; the SQLite fallback used by the test suite
        without a database server does one small query per hive, which is fine
        for a page of hives.
        """
        if not hive_ids:
            return {}

        dialect = self.session.bind.dialect.name if self.session.bind is not None else "postgresql"
        if dialect == "postgresql":
            statement = (
                select(HiveAiAnalysis)
                .where(HiveAiAnalysis.hive_id.in_(hive_ids))
                .distinct(HiveAiAnalysis.hive_id)
                .order_by(
                    HiveAiAnalysis.hive_id,
                    HiveAiAnalysis.analyzed_at.desc(),
                    HiveAiAnalysis.created_at.desc(),
                )
            )
            return {
                row.hive_id: row for row in self.session.execute(statement).scalars().all()
            }

        return {
            hive_id: analysis
            for hive_id in hive_ids
            if (analysis := self.latest_for_hive(hive_id)) is not None
        }

    def latest_for_beekeeper(self, beekeeper_id: uuid.UUID) -> HiveAiAnalysis | None:
        statement = (
            select(HiveAiAnalysis)
            .where(HiveAiAnalysis.beekeeper_id == beekeeper_id)
            .order_by(HiveAiAnalysis.analyzed_at.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalars().first()

    # ------------------------------------------------------------------ #
    # Aggregates
    #
    # These are the numbers a cluster dashboard will read: counting bands is a
    # SQL job, not a per-hive Python loop.
    # ------------------------------------------------------------------ #
    def _scope(
        self, *, beekeeper_id: uuid.UUID | None = None, hive_ids: list[uuid.UUID] | None = None
    ):
        filters = []
        if beekeeper_id is not None:
            filters.append(HiveAiAnalysis.beekeeper_id == beekeeper_id)
        if hive_ids is not None:
            filters.append(HiveAiAnalysis.hive_id.in_(hive_ids))
        return and_(*filters) if filters else None

    def count_by_health_status(
        self,
        *,
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
        latest_only: bool = True,
    ) -> dict[str, int]:
        """Health bands over the **latest** analysis per hive.

        Aggregating every historical row would count the same hive many times, so
        the default restricts to each hive's newest assessment.
        """
        rows = self._latest_rows(
            hive_ids=hive_ids, beekeeper_id=beekeeper_id, latest_only=latest_only
        )
        counts = {status.value: 0 for status in AiHealthStatus}
        for row in rows:
            counts[str(row.health_status)] = counts.get(str(row.health_status), 0) + 1
        return counts

    def count_by_risk_level(
        self,
        *,
        kind: str = "disease",
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
        latest_only: bool = True,
    ) -> dict[str, int]:
        column = (
            HiveAiAnalysis.disease_risk_level
            if kind == "disease"
            else HiveAiAnalysis.swarming_risk_level
        )
        rows = self._latest_rows(
            hive_ids=hive_ids, beekeeper_id=beekeeper_id, latest_only=latest_only
        )
        counts = {level.value: 0 for level in AiRiskLevel}
        for row in rows:
            value = str(getattr(row, column.key))
            counts[value] = counts.get(value, 0) + 1
        return counts

    def yield_projection(
        self,
        *,
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
    ) -> dict:
        """Sum and average of the predicted yield across hives that have one."""
        rows = self._latest_rows(hive_ids=hive_ids, beekeeper_id=beekeeper_id)
        values = [float(row.predicted_yield_kg) for row in rows if row.predicted_yield_kg is not None]
        return {
            "hives_with_projection": len(values),
            "total_predicted_kg": round(sum(values), 2) if values else 0.0,
            "average_predicted_kg": round(sum(values) / len(values), 2) if values else 0.0,
        }

    def _latest_rows(
        self,
        *,
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
        latest_only: bool = True,
    ) -> list[HiveAiAnalysis]:
        condition = self._scope(beekeeper_id=beekeeper_id, hive_ids=hive_ids)
        if not latest_only:
            statement = select(HiveAiAnalysis)
            if condition is not None:
                statement = statement.where(condition)
            return list(self.session.execute(statement).scalars().all())

        newest = (
            select(
                HiveAiAnalysis.hive_id.label("hive_id"),
                func.max(HiveAiAnalysis.analyzed_at).label("analyzed_at"),
            )
            .group_by(HiveAiAnalysis.hive_id)
            .subquery()
        )
        statement = select(HiveAiAnalysis).join(
            newest,
            and_(
                HiveAiAnalysis.hive_id == newest.c.hive_id,
                HiveAiAnalysis.analyzed_at == newest.c.analyzed_at,
            ),
        )
        if condition is not None:
            statement = statement.where(condition)
        return list(self.session.execute(statement).scalars().all())

    def analyzed_hive_ids(self, hive_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        if not hive_ids:
            return set()
        statement = select(HiveAiAnalysis.hive_id).where(
            HiveAiAnalysis.hive_id.in_(hive_ids)
        ).distinct()
        return {row for row in self.session.execute(statement).scalars().all()}

    def delete_for_hive(self, hive_id: uuid.UUID) -> int:
        """Remove the analysis history of a hive (used when a hive is deleted)."""
        rows = self.list(hive_id=hive_id)
        for row in rows:
            self.session.delete(row)
        self.session.flush()
        return len(rows)


class AiAlertRepository(BaseRepository[AiAlert]):
    model = AiAlert

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def record(self, **values) -> AiAlert:
        return self.create(**values)

    def touch(
        self,
        alert: AiAlert,
        *,
        seen_at: datetime,
        severity=None,
        title: str | None = None,
        message: str | None = None,
        context: dict | None = None,
        analysis_id: uuid.UUID | None = None,
    ) -> AiAlert:
        """Register another occurrence of an alert that is still active."""
        values = {
            "occurrences": alert.occurrences + 1,
            "last_seen_at": seen_at,
        }
        if severity is not None:
            values["severity"] = severity
        if title is not None:
            values["title"] = title
        if message is not None:
            values["message"] = message
        if context is not None:
            values["context"] = context
        if analysis_id is not None:
            values["analysis_id"] = analysis_id
        return self.update(alert, **values)

    def set_status(
        self,
        alert: AiAlert,
        *,
        status: AiAlertStatus,
        actor_id: uuid.UUID | None = None,
        acknowledged_at: datetime | None = None,
    ) -> AiAlert:
        return self.update(
            alert,
            status=status,
            acknowledged_at=acknowledged_at,
            acknowledged_by=actor_id if status is not AiAlertStatus.OPEN else None,
        )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def active_for_key(
        self, *, dedupe_key: str, since: datetime | None = None
    ) -> AiAlert | None:
        """The most recent alert still needing attention for this dedupe key.

        ``since`` implements the cooldown: an alert older than the window is no
        longer "active" for de-duplication purposes, so a signal that comes back
        after a long quiet period is reported as a new alert rather than silently
        bumped.
        """
        filters = [
            AiAlert.dedupe_key == dedupe_key,
            AiAlert.status.in_([AiAlertStatus.OPEN, AiAlertStatus.ACKNOWLEDGED]),
        ]
        if since is not None:
            filters.append(AiAlert.last_seen_at >= since)
        statement = (
            select(AiAlert)
            .where(and_(*filters))
            .order_by(AiAlert.last_seen_at.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalars().first()

    def list_for_hive(
        self, hive_id: uuid.UUID, *, limit: int = 50, include_resolved: bool = False
    ) -> list[AiAlert]:
        statement = select(AiAlert).where(AiAlert.hive_id == hive_id)
        if not include_resolved:
            statement = statement.where(AiAlert.status != AiAlertStatus.RESOLVED)
        statement = statement.order_by(AiAlert.last_seen_at.desc()).limit(limit)
        return list(self.session.execute(statement).scalars().all())

    def search(
        self,
        *,
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
        status: AiAlertStatus | None = None,
        severity=None,
        alert_type=None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AiAlert]:
        statement = select(AiAlert)
        condition = self._condition(
            hive_ids=hive_ids,
            beekeeper_id=beekeeper_id,
            status=status,
            severity=severity,
            alert_type=alert_type,
        )
        if condition is not None:
            statement = statement.where(condition)
        statement = (
            statement.order_by(AiAlert.last_seen_at.desc(), AiAlert.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.execute(statement).scalars().all())

    def count(
        self,
        *,
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
        status: AiAlertStatus | None = None,
        severity=None,
        alert_type=None,
    ) -> int:
        statement = select(func.count()).select_from(AiAlert)
        condition = self._condition(
            hive_ids=hive_ids,
            beekeeper_id=beekeeper_id,
            status=status,
            severity=severity,
            alert_type=alert_type,
        )
        if condition is not None:
            statement = statement.where(condition)
        return int(self.session.execute(statement).scalar_one())

    def count_by_severity(
        self,
        *,
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
        open_only: bool = True,
    ) -> dict[str, int]:
        filters = []
        if beekeeper_id is not None:
            filters.append(AiAlert.beekeeper_id == beekeeper_id)
        if hive_ids is not None:
            filters.append(AiAlert.hive_id.in_(hive_ids))
        if open_only:
            filters.append(AiAlert.status != AiAlertStatus.RESOLVED)
        statement = select(AiAlert.severity, func.count()).group_by(AiAlert.severity)
        if filters:
            statement = statement.where(and_(*filters))
        return {
            str(getattr(severity, "value", severity)): int(count)
            for severity, count in self.session.execute(statement).all()
        }

    def resolve_missing(self, hive_id: uuid.UUID, *, keep_keys: list[str]) -> int:
        """Resolve alerts for a hive whose signal is no longer present.

        An alert that stops recurring should close itself: leaving it OPEN would
        make the list grow without bound and stop meaning anything.
        """
        filters = [
            AiAlert.hive_id == hive_id,
            AiAlert.status != AiAlertStatus.RESOLVED,
        ]
        if keep_keys:
            filters.append(AiAlert.dedupe_key.notin_(keep_keys))
        statement = update(AiAlert).where(and_(*filters)).values(status=AiAlertStatus.RESOLVED)
        result = self.session.execute(statement)
        self.session.flush()
        return int(result.rowcount or 0)

    def _condition(
        self,
        *,
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
        status: AiAlertStatus | None = None,
        severity=None,
        alert_type=None,
    ):
        filters = []
        if beekeeper_id is not None:
            filters.append(AiAlert.beekeeper_id == beekeeper_id)
        if hive_ids is not None:
            filters.append(AiAlert.hive_id.in_(hive_ids))
        if status is not None:
            filters.append(AiAlert.status == status)
        if severity is not None:
            filters.append(AiAlert.severity == severity)
        if alert_type is not None:
            filters.append(AiAlert.alert_type == alert_type)
        return and_(*filters) if filters else None


def session_bound_analysis_repository(session: Session) -> AiAnalysisRepository:
    """Helper for jobs and tests that only hold a session."""
    return AiAnalysisRepository(session)


__all__ = [
    "AiAnalysisRepository",
    "AiAlertRepository",
    "session_bound_analysis_repository",
]

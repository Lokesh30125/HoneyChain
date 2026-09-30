"""Data access for ``sensor_readings`` — the telemetry time series.

Two shapes are exposed:

* ``history`` — raw samples in a time window, newest last, capped by ``limit``;
* ``aggregate`` — time-bucketed averages for the longer chart ranges, so a
  30-day chart returns a few hundred points instead of hundreds of thousands.

Both are built on the composite indexes ``(hive_id, timestamp)`` and
``(device_id, timestamp)``, which is what keeps the dashboard responsive as the
series grows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.sensor_reading import SensorReading
from app.repositories.base import BaseRepository

#: Fields a caller may ask to be returned individually.
SENSOR_FIELDS = (
    "temperature",
    "humidity",
    "weight",
    "vibration",
    "acoustic_level",
    "battery_level",
    "signal_strength",
)


class SensorReadingRepository(BaseRepository[SensorReading]):
    model = SensorReading

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def exists_at(self, *, device_pk: uuid.UUID, timestamp: datetime) -> bool:
        """True when this device already has a sample at exactly this instant.

        Backs idempotent ingestion: an MQTT QoS-1 redelivery, or a device that
        retries a POST after a timeout, must not duplicate the sample.
        """
        statement = (
            select(SensorReading.id)
            .where(SensorReading.device_id == device_pk, SensorReading.timestamp == timestamp)
            .limit(1)
        )
        return self.session.execute(statement).first() is not None

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def _window(
        self,
        *,
        hive_id: uuid.UUID | None = None,
        hive_ids: list[uuid.UUID] | None = None,
        device_pk: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        filters = []
        if hive_id is not None:
            filters.append(SensorReading.hive_id == hive_id)
        if hive_ids is not None:
            filters.append(SensorReading.hive_id.in_(hive_ids))
        if device_pk is not None:
            filters.append(SensorReading.device_id == device_pk)
        if beekeeper_id is not None:
            filters.append(SensorReading.beekeeper_id == beekeeper_id)
        if start is not None:
            filters.append(SensorReading.timestamp >= start)
        if end is not None:
            filters.append(SensorReading.timestamp <= end)
        return and_(*filters) if filters else None

    def history(
        self,
        *,
        hive_id: uuid.UUID | None = None,
        device_pk: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
        newest_first: bool = False,
    ) -> list[SensorReading]:
        statement = select(SensorReading)
        condition = self._window(
            hive_id=hive_id, device_pk=device_pk, beekeeper_id=beekeeper_id, start=start, end=end
        )
        if condition is not None:
            statement = statement.where(condition)
        statement = statement.order_by(
            SensorReading.timestamp.desc() if newest_first else SensorReading.timestamp.asc()
        ).limit(limit)
        return list(self.session.execute(statement).scalars().all())

    def latest_for_hive(self, hive_id: uuid.UUID) -> SensorReading | None:
        statement = (
            select(SensorReading)
            .where(SensorReading.hive_id == hive_id)
            .order_by(SensorReading.timestamp.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalars().first()

    def latest_for_device(self, device_pk: uuid.UUID) -> SensorReading | None:
        statement = (
            select(SensorReading)
            .where(SensorReading.device_id == device_pk)
            .order_by(SensorReading.timestamp.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalars().first()

    def latest_per_hive(self, hive_ids: list[uuid.UUID]) -> dict[uuid.UUID, SensorReading]:
        """Newest reading for each of ``hive_ids`` in one query.

        Uses PostgreSQL's ``DISTINCT ON``; other dialects (the SQLite fallback
        used by tests without a database server) fall back to one small query
        per hive, which is fine for the handful of hives on a dashboard page.
        """
        if not hive_ids:
            return {}

        dialect = self.session.bind.dialect.name if self.session.bind is not None else "postgresql"
        if dialect == "postgresql":
            statement = (
                select(SensorReading)
                .where(SensorReading.hive_id.in_(hive_ids))
                .distinct(SensorReading.hive_id)
                .order_by(SensorReading.hive_id, SensorReading.timestamp.desc())
            )
            rows = self.session.execute(statement).scalars().all()
            return {row.hive_id: row for row in rows}

        return {
            hive_id: reading
            for hive_id in hive_ids
            if (reading := self.latest_for_hive(hive_id)) is not None
        }

    def aggregate(
        self,
        *,
        bucket_seconds: int,
        hive_id: uuid.UUID | None = None,
        device_pk: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Average each sensor into fixed-width time buckets.

        Returns plain dictionaries (``timestamp``, per-sensor averages and a
        ``samples`` count) because the caller serialises them straight to the
        chart. Bucketing happens in SQL on PostgreSQL via ``date_bin``; on other
        dialects the caller buckets in Python (see ``TelemetryService``).
        """
        condition = self._window(
            hive_id=hive_id, device_pk=device_pk, beekeeper_id=beekeeper_id, start=start, end=end
        )
        bucket = func.date_bin(
            func.make_interval(0, 0, 0, 0, 0, 0, bucket_seconds),
            SensorReading.timestamp,
            func.cast("1970-01-01T00:00:00+00:00", SensorReading.timestamp.type),
        ).label("bucket")

        statement = (
            select(
                bucket,
                func.avg(SensorReading.temperature).label("temperature"),
                func.avg(SensorReading.humidity).label("humidity"),
                func.avg(SensorReading.weight).label("weight"),
                func.avg(SensorReading.vibration).label("vibration"),
                func.avg(SensorReading.acoustic_level).label("acoustic_level"),
                func.avg(SensorReading.battery_level).label("battery_level"),
                func.count().label("samples"),
            )
            .group_by(bucket)
            .order_by(bucket)
            .limit(limit)
        )
        if condition is not None:
            statement = statement.where(condition)

        rows = self.session.execute(statement).all()
        return [
            {
                "timestamp": row.bucket,
                "temperature": row.temperature,
                "humidity": row.humidity,
                "weight": row.weight,
                "vibration": row.vibration,
                "acoustic_level": row.acoustic_level,
                "battery_level": row.battery_level,
                "samples": int(row.samples),
            }
            for row in rows
        ]

    def count_in_window(
        self,
        *,
        hive_id: uuid.UUID | None = None,
        hive_ids: list[uuid.UUID] | None = None,
        device_pk: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        statement = select(func.count()).select_from(SensorReading)
        condition = self._window(
            hive_id=hive_id,
            hive_ids=hive_ids,
            device_pk=device_pk,
            beekeeper_id=beekeeper_id,
            start=since,
            end=until,
        )
        if condition is not None:
            statement = statement.where(condition)
        return int(self.session.execute(statement).scalar_one())

    def source_mix(
        self,
        *,
        hive_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, int]:
        """How many readings in the window came from each source.

        Surfaced in the API response so a chart can always say whether it is
        showing real device data or simulator data.
        """
        statement = select(SensorReading.source, func.count()).group_by(SensorReading.source)
        condition = self._window(hive_id=hive_id, beekeeper_id=beekeeper_id, start=start, end=end)
        if condition is not None:
            statement = statement.where(condition)
        return {
            str(getattr(source, "value", source)): int(count)
            for source, count in self.session.execute(statement).all()
        }

    def latest_for_devices(self, device_pks: list[uuid.UUID]) -> dict[uuid.UUID, SensorReading]:
        """Newest reading per device, in one round trip.

        List screens show the last known values for every row; asking the
        database once per device would turn one page into N queries.
        """
        if not device_pks:
            return {}

        newest = (
            select(
                SensorReading.device_id.label("device_id"),
                func.max(SensorReading.timestamp).label("timestamp"),
            )
            .where(SensorReading.device_id.in_(device_pks))
            .group_by(SensorReading.device_id)
            .subquery()
        )
        statement = select(SensorReading).join(
            newest,
            and_(
                SensorReading.device_id == newest.c.device_id,
                SensorReading.timestamp == newest.c.timestamp,
            ),
        )
        return {row.device_id: row for row in self.session.execute(statement).scalars().all()}

    def latest_timestamp(
        self,
        *,
        hive_id: uuid.UUID | None = None,
        hive_ids: list[uuid.UUID] | None = None,
        beekeeper_id: uuid.UUID | None = None,
    ) -> datetime | None:
        statement = select(func.max(SensorReading.timestamp))
        condition = self._window(hive_id=hive_id, hive_ids=hive_ids, beekeeper_id=beekeeper_id)
        if condition is not None:
            statement = statement.where(condition)
        return self.session.execute(statement).scalar_one()


def session_bound_repository(session: Session) -> SensorReadingRepository:
    """Small helper for callers that only hold a session (jobs, tests)."""
    return SensorReadingRepository(session)


__all__ = ["SensorReadingRepository", "SENSOR_FIELDS", "session_bound_repository"]

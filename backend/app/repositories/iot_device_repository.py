"""Data access for ``iot_devices`` and their ``sensor_configs`` rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.beekeeper import Beekeeper
from app.models.enums import DeviceStatus
from app.models.hive import Hive
from app.models.iot_device import IotDevice
from app.models.sensor_config import SensorConfig
from app.repositories.base import BaseRepository


class IotDeviceRepository(BaseRepository[IotDevice]):
    model = IotDevice

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_with_relations(self, device_pk: uuid.UUID) -> IotDevice | None:
        statement = (
            select(IotDevice)
            .options(
                joinedload(IotDevice.hive).joinedload(Hive.beekeeper).joinedload(Beekeeper.user),
                joinedload(IotDevice.hive).joinedload(Hive.cluster),
                selectinload(IotDevice.sensors),
            )
            .where(IotDevice.id == device_pk)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_device_id(self, device_id: str) -> IotDevice | None:
        """Look a device up by its hardware identifier (the MQTT/ingest key)."""
        statement = (
            select(IotDevice)
            .options(
                joinedload(IotDevice.hive).joinedload(Hive.beekeeper).joinedload(Beekeeper.user),
                selectinload(IotDevice.sensors),
            )
            .where(func.upper(IotDevice.device_id) == device_id.strip().upper())
        )
        return self.session.execute(statement).scalars().unique().first()

    def device_id_exists(self, device_id: str) -> bool:
        statement = select(IotDevice.id).where(
            func.upper(IotDevice.device_id) == device_id.strip().upper()
        )
        return self.session.execute(statement).first() is not None

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: DeviceStatus | None = None,
        beekeeper_id: uuid.UUID | None = None,
        hive_id: uuid.UUID | None = None,
        hive_ids: list[uuid.UUID] | None = None,
        device_type: str | None = None,
        connection_type: str | None = None,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> tuple[list[IotDevice], int]:
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(IotDevice.device_id).like(term),
                    func.lower(IotDevice.device_name).like(term),
                    func.lower(Hive.hive_code).like(term),
                )
            )
        if status is not None:
            filters.append(IotDevice.status == status)
        if beekeeper_id is not None:
            filters.append(IotDevice.beekeeper_id == beekeeper_id)
        if hive_id is not None:
            filters.append(IotDevice.hive_id == hive_id)
        if hive_ids is not None:
            # A cluster's devices are the devices of that cluster's hives: the
            # relationship is walked, never copied into a second table.
            filters.append(IotDevice.hive_id.in_(hive_ids))
        if device_type:
            filters.append(IotDevice.device_type == device_type)
        if connection_type:
            filters.append(IotDevice.connection_type == connection_type)

        base = (
            select(IotDevice)
            .join(Hive, IotDevice.hive_id == Hive.id)
            .options(
                joinedload(IotDevice.hive),
                joinedload(IotDevice.hive).joinedload(Hive.cluster),
                selectinload(IotDevice.sensors),
            )
        )
        count_statement = (
            select(func.count()).select_from(IotDevice).join(Hive, IotDevice.hive_id == Hive.id)
        )
        if filters:
            condition = and_(*filters)
            base = base.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(IotDevice, order_by, IotDevice.created_at)
        base = base.order_by(column.desc() if descending else column.asc())
        base = base.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(base).scalars().unique().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total

    def list_for_hive(self, hive_id: uuid.UUID) -> list[IotDevice]:
        statement = (
            select(IotDevice)
            .options(selectinload(IotDevice.sensors))
            .where(IotDevice.hive_id == hive_id)
            .order_by(IotDevice.created_at.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def list_for_beekeeper(self, beekeeper_id: uuid.UUID) -> list[IotDevice]:
        statement = (
            select(IotDevice)
            .options(joinedload(IotDevice.hive), selectinload(IotDevice.sensors))
            .where(IotDevice.beekeeper_id == beekeeper_id)
            .order_by(IotDevice.device_id.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def stale(self, *, cutoff: datetime) -> list[IotDevice]:
        """Devices that have reported before but not since ``cutoff``.

        Devices that have *never* reported are excluded: they have no
        ``last_seen`` to compare, and are already OFFLINE by creation default.
        """
        statement = select(IotDevice).where(
            IotDevice.last_seen.is_not(None),
            IotDevice.last_seen < cutoff,
            IotDevice.status != DeviceStatus.MAINTENANCE,
        )
        return list(self.session.execute(statement).scalars().all())

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #
    def count_by_status(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        hive_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, int]:
        statement = select(IotDevice.status, func.count()).group_by(IotDevice.status)
        if hive_ids is not None:
            statement = statement.where(IotDevice.hive_id.in_(hive_ids))
        if beekeeper_id is not None:
            statement = statement.where(IotDevice.beekeeper_id == beekeeper_id)
        counts = {status.value: 0 for status in DeviceStatus}
        for status, count in self.session.execute(statement).all():
            counts[str(getattr(status, "value", status))] = int(count)
        return counts

    def count_all(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        hive_ids: list[uuid.UUID] | None = None,
    ) -> int:
        statement = select(func.count()).select_from(IotDevice)
        if hive_ids is not None:
            statement = statement.where(IotDevice.hive_id.in_(hive_ids))
        if beekeeper_id is not None:
            statement = statement.where(IotDevice.beekeeper_id == beekeeper_id)
        return int(self.session.execute(statement).scalar_one())

    def latest_last_seen(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        hive_ids: list[uuid.UUID] | None = None,
    ) -> datetime | None:
        statement = select(func.max(IotDevice.last_seen))
        if hive_ids is not None:
            statement = statement.where(IotDevice.hive_id.in_(hive_ids))
        if beekeeper_id is not None:
            statement = statement.where(IotDevice.beekeeper_id == beekeeper_id)
        return self.session.execute(statement).scalar_one()

    def list_for_hives(self, hive_ids: list[uuid.UUID]) -> list[IotDevice]:
        """Every device on a set of hives, in hive-code order."""
        if not hive_ids:
            return []
        statement = (
            select(IotDevice)
            .join(Hive, IotDevice.hive_id == Hive.id)
            .options(joinedload(IotDevice.hive))
            .where(IotDevice.hive_id.in_(hive_ids))
            .order_by(Hive.hive_code.asc(), IotDevice.device_id.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())


class SensorConfigRepository(BaseRepository[SensorConfig]):
    model = SensorConfig

    def list_for_device(self, device_pk: uuid.UUID) -> list[SensorConfig]:
        statement = (
            select(SensorConfig)
            .where(SensorConfig.device_id == device_pk)
            .order_by(SensorConfig.sensor_type.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_for_devices(self, device_pks: list[uuid.UUID]) -> dict[uuid.UUID, list[SensorConfig]]:
        """Configured sensors for many devices at once, grouped by device."""
        if not device_pks:
            return {}

        statement = (
            select(SensorConfig)
            .where(SensorConfig.device_id.in_(device_pks))
            .order_by(SensorConfig.sensor_type.asc())
        )
        grouped: dict[uuid.UUID, list[SensorConfig]] = {}
        for config in self.session.execute(statement).scalars().all():
            grouped.setdefault(config.device_id, []).append(config)
        return grouped

    def get_for_device_type(self, device_pk: uuid.UUID, sensor_type: str) -> SensorConfig | None:
        return self.get_by(device_id=device_pk, sensor_type=sensor_type)

    def count_enabled(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        hive_ids: list[uuid.UUID] | None = None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(SensorConfig)
            .join(IotDevice, SensorConfig.device_id == IotDevice.id)
            .where(SensorConfig.enabled.is_(True))
        )
        if hive_ids is not None:
            statement = statement.where(IotDevice.hive_id.in_(hive_ids))
        if beekeeper_id is not None:
            statement = statement.where(IotDevice.beekeeper_id == beekeeper_id)
        return int(self.session.execute(statement).scalar_one())


__all__ = ["IotDeviceRepository", "SensorConfigRepository"]

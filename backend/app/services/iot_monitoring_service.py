"""Monitoring summaries for the beekeeper IoT dashboard.

Every number is counted from the database for the caller's scope. Nothing here
is estimated, extrapolated or filled in from a fixture: an empty account shows
zeros and the screens show their empty states.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.permissions import Permission, has_permission
from app.models.enums import DeviceStatus
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.iot_device_repository import IotDeviceRepository, SensorConfigRepository
from app.repositories.sensor_reading_repository import SensorReadingRepository
from app.services.device_service import DeviceService

#: A device is "connected" when it is reachable — reporting normally, or
#: reporting with a degraded battery (WARNING). MAINTENANCE is deliberately not
#: counted as connected: it is out of service by an operator's decision.
_CONNECTED_STATUSES = (DeviceStatus.ONLINE, DeviceStatus.WARNING)


class IotMonitoringService:
    """Aggregate device and telemetry facts for the monitoring screens."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.hives = HiveRepository(session)
        self.devices = IotDeviceRepository(session)
        self.sensors = SensorConfigRepository(session)
        self.readings = SensorReadingRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.device_service = DeviceService(session, self.settings)

    def _owner_id(self, user: User):
        """``None`` for staff scope, otherwise the caller's beekeeper id."""
        beekeeper = self.beekeepers.get_by_user_id(user.id)
        if beekeeper is not None:
            return beekeeper.id
        # A staff account with no apiary of its own: platform-wide scope.
        return None

    def summary(self, user: User, *, window_hours: int = 24) -> dict:
        """Counts for the ``/beekeeper/iot`` dashboard."""
        beekeeper_id = None
        if not has_permission(user.role, Permission.DEVICE_READ_ALL):
            beekeeper_id = self._owner_id(user)
            if beekeeper_id is None:
                # A role with no apiary and no platform scope sees an empty,
                # honest dashboard rather than an error.
                return _empty_summary(window_hours)

        return self._counts(beekeeper_id=beekeeper_id, window_hours=window_hours)

    def summary_for_hive_ids(self, hive_ids: list, *, window_hours: int = 24) -> dict:
        """The same counters for an explicit set of hives.

        This is how a cluster gets its IoT numbers: the hives come from the
        cluster relationship, and the counting rules are the ones above rather
        than a second implementation that could drift from them.
        """
        if not hive_ids:
            return _empty_summary(window_hours)
        return self._counts(beekeeper_id=None, hive_ids=list(hive_ids), window_hours=window_hours)

    def _counts(
        self,
        *,
        beekeeper_id=None,
        hive_ids: list | None = None,
        window_hours: int = 24,
    ) -> dict:
        """Shared body of :meth:`summary` and :meth:`summary_for_hive_ids`."""
        hive_count = (
            len(hive_ids)
            if hive_ids is not None
            else self.hives.count_all(beekeeper_id=beekeeper_id)
        )
        device_count = self.devices.count_all(beekeeper_id=beekeeper_id, hive_ids=hive_ids)

        # Derived statuses are computed per device, so the counts must be too —
        # reading the stored column would report a device as ONLINE until the
        # next sweep ran.
        statuses = [
            self.device_service.derive_status(device)
            for device in self._devices(beekeeper_id, hive_ids=hive_ids)
        ]
        connected = sum(1 for status in statuses if status in _CONNECTED_STATUSES)
        offline = sum(1 for status in statuses if status == DeviceStatus.OFFLINE)
        maintenance = sum(1 for status in statuses if status == DeviceStatus.MAINTENANCE)
        warning = sum(1 for status in statuses if status == DeviceStatus.WARNING)

        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        last_timestamp = self.readings.latest_timestamp(
            beekeeper_id=beekeeper_id, hive_ids=hive_ids
        )

        return {
            "total_hives": hive_count,
            "total_devices": device_count,
            "connected_devices": connected,
            "offline_devices": offline,
            "warning_devices": warning,
            "maintenance_devices": maintenance,
            "sensors_active": self.sensors.count_enabled(
                beekeeper_id=beekeeper_id, hive_ids=hive_ids
            ),
            "hives_without_device": self._hives_without_device(
                beekeeper_id=beekeeper_id, hive_ids=hive_ids
            ),
            "readings_last_window": self.readings.count_in_window(
                beekeeper_id=beekeeper_id, hive_ids=hive_ids, since=since
            ),
            "window_hours": window_hours,
            "last_telemetry_at": last_timestamp,
            "offline_threshold_seconds": self.settings.DEVICE_OFFLINE_THRESHOLD_SECONDS,
            "generated_at": datetime.now(timezone.utc),
        }

    def _hives_without_device(self, *, beekeeper_id=None, hive_ids: list | None = None) -> int:
        if hive_ids is None:
            return self.hives.device_counts(beekeeper_id=beekeeper_id)["without_device"]
        if not hive_ids:
            return 0
        paired = {
            device.hive_id for device in self.devices.list_for_hives(list(hive_ids))
        }
        return sum(1 for hive_id in hive_ids if hive_id not in paired)

    def _devices(self, beekeeper_id, *, hive_ids: list | None = None) -> list:
        if hive_ids is not None:
            return self.devices.list_for_hives(list(hive_ids))
        if beekeeper_id is None:
            rows, _total = self.devices.search(page=1, page_size=1000)
            return rows
        return self.devices.list_for_beekeeper(beekeeper_id)

    def last_telemetry(self, user: User):
        """The most recent reading in scope, with the device and hive it came from."""
        beekeeper_id = None
        if not has_permission(user.role, Permission.DEVICE_READ_ALL):
            beekeeper_id = self._owner_id(user)
            if beekeeper_id is None:
                return None

        timestamp = self.readings.latest_timestamp(beekeeper_id=beekeeper_id)
        if timestamp is None:
            return None

        rows = self.readings.history(
            beekeeper_id=beekeeper_id, start=timestamp, end=timestamp, limit=1
        )
        if not rows:
            return None
        reading = rows[0]
        device = self.devices.get(reading.device_id)
        hive = self.hives.get(reading.hive_id)
        return {
            "reading": reading,
            "device": device,
            "hive": hive,
            "timestamp": timestamp,
        }


def _empty_summary(window_hours: int) -> dict:
    """A zeroed summary — never a fabricated one."""
    return {
        "total_hives": 0,
        "total_devices": 0,
        "connected_devices": 0,
        "offline_devices": 0,
        "warning_devices": 0,
        "maintenance_devices": 0,
        "sensors_active": 0,
        "hives_without_device": 0,
        "readings_last_window": 0,
        "window_hours": window_hours,
        "last_telemetry_at": None,
        "offline_threshold_seconds": 0,
        "generated_at": datetime.now(timezone.utc),
    }


__all__ = ["IotMonitoringService"]

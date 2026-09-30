"""IoT device management: registration, health, sensors and offline detection.

The device is the bridge between a physical hive and the platform. Three rules
shape this service:

1. **A device belongs to the hive it is attached to**, and therefore to that
   hive's beekeeper. Ownership is copied onto the device row at registration and
   re-checked on every request, so a beekeeper can never register a device
   against another beekeeper's hive.
2. **Status is derived, not asserted.** ``refresh_status`` computes the status
   from ``last_seen`` and battery against the configured thresholds. A device
   that stops reporting becomes OFFLINE by itself; nothing marks every device
   ONLINE permanently. The single exception is MAINTENANCE, which an operator
   sets deliberately and the sweeper leaves alone.
3. **Sensors are configured, not assumed.** Registering a device seeds the
   sensor set an ESP32 hive node carries; each row can then be disabled or
   retuned without touching code.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.permissions import Permission, has_permission
from app.models.enums import DeviceStatus, DeviceType, SensorType, UserRole
from app.models.hive import Hive
from app.models.iot_device import IotDevice
from app.models.sensor_config import DEFAULT_SENSOR_SPECS, SensorConfig
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.iot_device_repository import IotDeviceRepository, SensorConfigRepository
from app.repositories.sensor_reading_repository import SensorReadingRepository
from app.schemas.iot import (
    DeviceCreate,
    DeviceDetail,
    DeviceListItem,
    DeviceUpdate,
    HeartbeatPayload,
    SensorConfigUpdate,
    to_device_detail,
    to_device_list_item,
)
from app.services.audit_service import AuditService

logger = get_logger("service")

#: Fields a client may change on a device.
_EDITABLE_FIELDS = (
    "device_name",
    "device_type",
    "device_type_other",
    "firmware_version",
    "connection_type",
    "installed_at",
    "mqtt_topic",
)


class DeviceService:
    """Business rules for IoT devices and their sensor configuration."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.devices = IotDeviceRepository(session)
        self.sensors = SensorConfigRepository(session)
        self.hives = HiveRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.readings = SensorReadingRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ #
    # Scope helpers
    # ------------------------------------------------------------------ #
    def _owner_record(self, user: User):
        return self.beekeepers.get_by_user_id(user.id)

    def _scope_is_all(self, user: User) -> bool:
        return has_permission(user.role, Permission.DEVICE_READ_ALL)

    def _assert_can_write(self, user: User, device: IotDevice) -> None:
        """404 rather than 403 for another beekeeper's device — see HiveService."""
        if has_permission(user.role, Permission.DEVICE_WRITE_ALL):
            return
        owner = self._owner_record(user)
        if owner is None or device.beekeeper_id != owner.id:
            logger.warning(
                "Device write denied",
                extra={"user_id": str(user.id), "role": str(user.role), "device_id": device.device_id},
            )
            raise NotFoundError("Device not found")

    def _require_visible(self, user: User, device: IotDevice) -> None:
        if self._scope_is_all(user):
            return
        owner = self._owner_record(user)
        if owner is None or device.beekeeper_id != owner.id:
            raise NotFoundError("Device not found")

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #
    def derive_status(self, device: IotDevice, *, now: datetime | None = None) -> DeviceStatus:
        """The status a device *should* have right now.

        * MAINTENANCE — set by an operator; never overwritten.
        * OFFLINE     — never seen, or last seen longer ago than
          ``DEVICE_OFFLINE_THRESHOLD_SECONDS``.
        * WARNING     — reporting, but the battery is at or below
          ``DEVICE_LOW_BATTERY_PERCENT``.
        * ONLINE      — reporting recently with a healthy battery.

        The threshold is deliberately generous: a single lost packet must not
        make working hardware look dead.
        """
        if device.status == DeviceStatus.MAINTENANCE:
            return DeviceStatus.MAINTENANCE

        now = now or datetime.now(timezone.utc)
        if device.last_seen is None:
            return DeviceStatus.OFFLINE

        last_seen = device.last_seen
        if last_seen.tzinfo is None:  # defensive: treat naive values as UTC
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        if now - last_seen > timedelta(seconds=self.settings.DEVICE_OFFLINE_THRESHOLD_SECONDS):
            return DeviceStatus.OFFLINE

        if (
            device.battery_level is not None
            and device.battery_level <= self.settings.DEVICE_LOW_BATTERY_PERCENT
        ):
            return DeviceStatus.WARNING

        return DeviceStatus.ONLINE

    def effective_status(self, device: IotDevice) -> DeviceStatus:
        """Derived status without mutating the row (used when serialising)."""
        return self.derive_status(device)

    def refresh_status(self, device: IotDevice, *, commit: bool = False) -> DeviceStatus:
        """Persist a status change if the derived value differs from the stored one."""
        derived = self.derive_status(device)
        if device.status != derived:
            previous = device.status
            device.status = derived
            self.audit.device_status_changed(
                device, actor=None, previous=previous, new=derived, automatic=True
            )
            logger.info(
                "Device status recomputed",
                extra={"device_id": device.device_id, "from": str(previous), "to": str(derived)},
            )
            if commit:
                self.devices.commit()
        return device.status

    def sweep_statuses(self, *, commit: bool = True) -> list[str]:
        """Re-evaluate every device that has gone quiet.

        Called by the periodic job (``python -m app.scripts.device_status_sweep``)
        and by the MQTT consumer loop. Only devices that have reported before are
        considered, so a never-used device keeps its initial OFFLINE status.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.settings.DEVICE_OFFLINE_THRESHOLD_SECONDS
        )
        changed: list[str] = []
        for device in self.devices.stale(cutoff=cutoff):
            derived = self.derive_status(device)
            if device.status != derived:
                previous = device.status
                device.status = derived
                self.audit.device_status_changed(
                    device, actor=None, previous=previous, new=derived, automatic=True
                )
                changed.append(device.device_id)
                logger.info(
                    "Device marked %s by offline sweep", str(derived),
                    extra={"device_id": device.device_id},
                )
        if changed and commit:
            self.devices.commit()
        return changed

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def register(self, user: User, payload: DeviceCreate) -> IotDevice:
        """Attach a new device to one of the caller's hives."""
        hive = self.hives.get_with_relations(payload.hive_id)
        if hive is None:
            raise NotFoundError("Hive not found", details={"field": "hive_id"})

        # Ownership: the hive must belong to the caller unless they manage all.
        if not has_permission(user.role, Permission.DEVICE_WRITE_ALL):
            owner = self._owner_record(user)
            if owner is None or hive.beekeeper_id != owner.id:
                logger.warning(
                    "Device registration denied",
                    extra={"user_id": str(user.id), "hive_id": str(hive.id)},
                )
                # Same 404 as a read: registering against an unknown hive and
                # against someone else's hive are indistinguishable to the caller.
                raise NotFoundError("Hive not found", details={"field": "hive_id"})

        if self.devices.device_id_exists(payload.device_id):
            raise ValidationError(
                f"Device '{payload.device_id}' is already registered",
                details={"field": "device_id"},
            )

        device = self.devices.create(
            device_id=payload.device_id,
            device_name=payload.device_name,
            hive_id=hive.id,
            # Copied from the hive: the single source of truth for ownership.
            beekeeper_id=hive.beekeeper_id,
            device_type=payload.device_type,
            device_type_other=payload.device_type_other,
            firmware_version=payload.firmware_version,
            connection_type=payload.connection_type,
            mqtt_topic=payload.mqtt_topic or self.telemetry_topic_for(payload.device_id),
            # Never assume a new device is working.
            status=DeviceStatus.OFFLINE,
            installed_at=payload.installed_at or datetime.now(timezone.utc),
        )
        configured = self._seed_sensor_configs(device)
        self.audit.device_registered(device, actor=user, sensor_count=len(configured))
        self.devices.commit()
        logger.info(
            "IoT device registered",
            extra={
                "device_id": device.device_id,
                "hive_code": hive.hive_code,
                "sensors": len(configured),
            },
        )
        return device

    def _seed_sensor_configs(self, device: IotDevice) -> list[SensorConfig]:
        """Create the default sensor set for a newly registered device."""
        created: list[SensorConfig] = []
        for sensor_type, name, unit, interval in DEFAULT_SENSOR_SPECS:
            created.append(
                self.sensors.create(
                    device_id=device.id,
                    sensor_type=sensor_type,
                    sensor_name=name,
                    unit=unit,
                    enabled=True,
                    sampling_interval=interval,
                )
            )
        return created

    def update(self, user: User, device_pk: uuid.UUID, payload: DeviceUpdate) -> IotDevice:
        device = self.get(device_pk)
        self._assert_can_write(user, device)

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationError("No changes supplied")

        # Re-parenting a device is allowed (a sensor may be moved to another
        # hive) but only onto a hive the caller controls.
        if "hive_id" in changes and changes["hive_id"] is not None:
            target = self.hives.get_with_relations(changes["hive_id"])
            if target is None:
                raise NotFoundError("Hive not found", details={"field": "hive_id"})
            if not has_permission(user.role, Permission.DEVICE_WRITE_ALL):
                owner = self._owner_record(user)
                if owner is None or target.beekeeper_id != owner.id:
                    raise NotFoundError("Hive not found", details={"field": "hive_id"})
            device.hive_id = target.id
            device.beekeeper_id = target.beekeeper_id
            changes.pop("hive_id")

        # The hardware type and its description move together: switching to a listed
        # type drops a description that no longer applies, and choosing Other
        # requires one. Checked on the values the device will hold, so a partial
        # update cannot leave the pair disagreeing.
        if "device_type" in changes or "device_type_other" in changes:
            resulting_type = changes.get("device_type", device.device_type)
            if str(resulting_type) == DeviceType.OTHER.value:
                # Keeping the description already on the device is right: an update
                # that does not mention it has not changed it.
                resulting_other = changes.get("device_type_other", device.device_type_other)
                resulting_other = (resulting_other or "").strip() or None
                if not resulting_other:
                    raise ValidationError(
                        "Describe the hardware: with the type set to Other, the record has "
                        "to say what the other hardware was.",
                        details={"device_id": device.device_id, "field": "device_type_other"},
                    )
            else:
                # A listed type carries no description, and one supplied beside it is
                # refused rather than quietly dropped.
                if (changes.get("device_type_other") or "").strip():
                    raise ValidationError(
                        "A description is only recorded when the hardware type is Other; "
                        "this device names listed hardware.",
                        details={"device_id": device.device_id, "field": "device_type_other"},
                    )
                resulting_other = None
            changes["device_type"] = resulting_type
            changes["device_type_other"] = resulting_other

        for field, value in changes.items():
            if field in _EDITABLE_FIELDS:
                setattr(device, field, value)

        self.audit.device_updated(device, actor=user, changed_fields=sorted(changes))
        self.devices.commit()
        return device

    def change_status(
        self,
        user: User,
        device_pk: uuid.UUID,
        status: DeviceStatus,
        *,
        reason: str | None = None,
    ) -> IotDevice:
        """Set a device status by hand.

        Used to take a device out for maintenance (or to bring it back in). Any
        other value is recomputed from ``last_seen`` on the next sweep, which is
        why only MAINTENANCE really sticks — and the API documents that.
        """
        device = self.get(device_pk)
        self._assert_can_write(user, device)

        if device.status == status:
            return device

        previous = device.status
        device.status = status
        self.audit.device_status_changed(
            device, actor=user, previous=previous, new=status, reason=reason
        )
        self.devices.commit()
        return device

    def remove(self, user: User, device_pk: uuid.UUID, *, confirm: bool = False) -> dict:
        """Delete a device, its sensor configuration **and its readings**.

        Telemetry is the record of what a hive physically experienced, so this is
        not done quietly: when the device has readings, the call is refused with
        409 until the caller passes ``confirm=true`` (the API exposes this as
        ``?confirm=true``). The audit entry states how many readings went with the
        device, so the loss is reconstructable from the log even though the
        readings themselves are gone. To keep the history instead, take the device
        out of service with ``PATCH /status`` (MAINTENANCE) rather than deleting it.
        """
        device = self.get(device_pk)
        self._assert_can_write(user, device)

        readings = self.readings.count_in_window(device_pk=device.id)
        if readings and not confirm:
            raise ConflictError(
                "This device has telemetry history",
                details={
                    "device_id": device.device_id,
                    "reading_count": readings,
                    "hint": (
                        "Retry with ?confirm=true to delete the device and its readings, "
                        "or set the status to MAINTENANCE to keep the history."
                    ),
                },
            )

        code = device.device_id
        self.audit.device_removed(device, actor=user, readings=readings)
        self.devices.delete(device)
        self.devices.commit()
        logger.info("Device removed", extra={"device_id": code, "readings_deleted": readings})
        return {
            "device_id": code,
            "readings_deleted": readings,
            "message": (
                f"Device {code} and its {readings} reading(s) were deleted."
                if readings
                else f"Device {code} deleted."
            ),
        }

    def detail(self, user: User, device_pk: uuid.UUID) -> DeviceDetail:
        """Device payload for the API: sensors with values, latest reading, 24h volume."""
        device = self.get_for(user, device_pk)
        sensors = self.sensors.list_for_device(device.id)
        latest = self.readings.latest_for_device(device.id)
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        return to_device_detail(
            device,
            status=self.derive_status(device),
            reading=latest,
            sensors=sensors,
            hive=getattr(device, "hive", None),
            readings_last_24h=self.readings.count_in_window(device_pk=device.id, since=since),
        )

    # ------------------------------------------------------------------ #
    # Heartbeat
    # ------------------------------------------------------------------ #
    def heartbeat(self, user: User | None, payload: HeartbeatPayload) -> IotDevice:
        """Record that a device is alive, with its energy and radio state.

        Accepts the same battery/signal bounds as telemetry, and applies the
        same ownership rule when the caller is a user (devices publishing over
        MQTT authenticate with the broker instead).
        """
        device = self.devices.get_by_device_id(payload.device_id)
        if device is None:
            raise NotFoundError(
                "Unknown device", details={"device_id": payload.device_id}
            )
        if user is not None:
            self._assert_can_write(user, device)

        if payload.battery_level is not None:
            device.battery_level = payload.battery_level
        if payload.signal_strength is not None:
            device.signal_strength = payload.signal_strength

        seen_at = payload.timestamp or datetime.now(timezone.utc)
        if device.last_seen is None or seen_at > device.last_seen:
            device.last_seen = seen_at

        self.refresh_status(device)
        self.devices.commit()
        return device

    # ------------------------------------------------------------------ #
    # Sensors
    # ------------------------------------------------------------------ #
    def list_sensors(self, user: User, device_pk: uuid.UUID) -> list[SensorConfig]:
        device = self.get(device_pk)
        self._require_visible(user, device)
        return self.sensors.list_for_device(device.id)

    def update_sensor(
        self, user: User, device_pk: uuid.UUID, sensor_type: SensorType, payload: SensorConfigUpdate
    ) -> SensorConfig:
        device = self.get(device_pk)
        self._assert_can_write(user, device)

        config = self.sensors.get_for_device_type(device.id, sensor_type)
        if config is None:
            raise NotFoundError(
                "This device has no such sensor",
                details={"sensor_type": str(sensor_type)},
            )

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationError("No changes supplied")

        for field, value in changes.items():
            setattr(config, field, value)

        # The database enforces min < max; check here too so the caller gets a
        # field-level 422 instead of an integrity error.
        if (
            config.min_valid_value is not None
            and config.max_valid_value is not None
            and float(config.min_valid_value) >= float(config.max_valid_value)
        ):
            raise ValidationError(
                "The minimum valid value must be below the maximum",
                details={"field": "min_valid_value"},
            )

        self.audit.device_updated(
            device, actor=user, changed_fields=[f"sensor:{sensor_type}:{k}" for k in sorted(changes)]
        )
        self.sensors.commit()
        return config

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, device_pk: uuid.UUID) -> IotDevice:
        device = self.devices.get_with_relations(device_pk)
        if device is None:
            raise NotFoundError("Device not found")
        return device

    def get_for(self, user: User, device_pk: uuid.UUID) -> IotDevice:
        device = self.get(device_pk)
        self._require_visible(user, device)
        return device

    def get_by_device_id(self, device_id: str) -> IotDevice:
        device = self.devices.get_by_device_id(device_id)
        if device is None:
            raise NotFoundError("Unknown device", details={"device_id": device_id})
        return device

    def list_devices(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: DeviceStatus | None = None,
        hive_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        device_type: str | None = None,
        connection_type: str | None = None,
    ) -> tuple[list[IotDevice], int]:
        owner_filter = None
        if not self._scope_is_all(user):
            owner = self._owner_record(user)
            if owner is None:
                return [], 0
            owner_filter = owner.id
        elif beekeeper_id is not None:
            owner_filter = beekeeper_id

        rows, total = self.devices.search(
            page=page,
            page_size=page_size,
            search=search,
            # Filtering by status has to happen in Python for derived statuses,
            # so the stored status is filtered here and re-checked below.
            status=status if status != DeviceStatus.WARNING else None,
            hive_id=hive_id,
            device_type=device_type,
            connection_type=connection_type,
            beekeeper_id=owner_filter,
        )

        # Reconcile the stored status with the derived one so a device that went
        # quiet is not reported as ONLINE just because the row still says so.
        rows = [self._with_derived_status(device) for device in rows]
        if status is not None:
            rows = [device for device in rows if device.status == status]
        return rows, total

    def list_items(self, user: User, **filters) -> tuple[list[DeviceListItem], int]:
        """List devices as ready-to-send payloads (list rows, sensors included)."""
        rows, total = self.list_devices(user, **filters)
        return self._decorate(rows), total

    def list_items_for_user(self, user: User) -> list[DeviceListItem]:
        """Every device the signed-in beekeeper owns, as list rows."""
        return self._decorate(self.list_for_user(user))

    def _decorate(self, rows: list[IotDevice]) -> list[DeviceListItem]:
        """Attach the latest reading and the sensor set to each row.

        Two batched queries cover the whole page — sensors and newest readings —
        so the cost of a list does not grow with the number of devices.
        """
        if not rows:
            return []

        device_pks = [device.id for device in rows]
        sensors = self.sensors.list_for_devices(device_pks)
        readings = self.readings.latest_for_devices(device_pks)
        return [
            to_device_list_item(
                device,
                status=device.status,
                reading=readings.get(device.id),
                sensors=sensors.get(device.id, []),
            )
            for device in rows
        ]

    def _with_derived_status(self, device: IotDevice) -> IotDevice:
        """Attach the derived status to the row without writing it.

        The stored value can lag up to one sweep interval; the API always
        answers with the derived value so the dashboard cannot show a device as
        ONLINE when its last packet is older than the threshold.
        """
        derived = self.derive_status(device)
        if device.status != derived:
            device.status = derived
        return device

    def list_for_hive(self, hive: Hive) -> list[IotDevice]:
        return [self._with_derived_status(device) for device in self.devices.list_for_hive(hive.id)]

    def list_for_user(self, user: User) -> list[IotDevice]:
        owner = self._owner_record(user)
        if owner is None:
            return []
        return [
            self._with_derived_status(device) for device in self.devices.list_for_beekeeper(owner.id)
        ]

    # ------------------------------------------------------------------ #
    # MQTT helpers
    # ------------------------------------------------------------------ #
    def telemetry_topic_for(self, device_id: str) -> str:
        return f"{self.settings.MQTT_TOPIC_PREFIX}/devices/{device_id}/telemetry"

    def require_mqtt_configured(self) -> None:
        if not self.settings.mqtt_configured:
            raise ServiceUnavailableError(
                "MQTT ingest is not configured",
                details={"hint": "Set MQTT_BROKER_URL to enable broker ingest."},
            )


def device_owner_role(user: User) -> str | None:
    """Small helper for logging/auditing without importing roles everywhere."""
    return str(user.role) if user.role else None


__all__ = ["DeviceService", "device_owner_role", "UserRole"]

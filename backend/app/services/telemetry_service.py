"""Telemetry ingestion and history.

Ingestion is deliberately strict and deliberately dull: look the device up,
check the caller may write for it, validate every number against the sensor's
configured range (with a global sanity bound behind it), refuse timestamps that
cannot be true, then store exactly what arrived. Nothing is repaired, clamped or
substituted — an impossible reading is rejected, never turned into a plausible
one.

Idempotency: ``(device_id, timestamp)`` is unique in the database, so a
re-delivered MQTT packet (QoS 1) or a device that retries after a timeout is
absorbed rather than duplicated. The response says which happened.

Auditability: storing a reading is not an audited event by itself — the series
*is* the record. Instead one ``TELEMETRY_RECEIVED`` entry is written per device
per ``TELEMETRY_AUDIT_INTERVAL_SECONDS`` window, so the audit log shows that a
device is reporting without gaining a row per packet.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.permissions import Permission, has_permission
from app.models.enums import AuditAction, DeviceStatus, SensorType, TelemetrySource
from app.models.hive import Hive
from app.models.iot_device import IotDevice
from app.models.sensor_reading import VALID_RANGES, SensorReading
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.iot_device_repository import IotDeviceRepository, SensorConfigRepository
from app.repositories.sensor_reading_repository import SENSOR_FIELDS, SensorReadingRepository
from app.schemas.iot import TelemetryIngest
from app.services.audit_service import AuditService
from app.services.device_service import DeviceService

logger = get_logger("service")

#: Reading fields that are integers in the database.
_INTEGER_FIELDS = frozenset({"battery_level", "signal_strength"})

#: Accepted ``interval`` query values and their width in seconds. Buckets keep a
#: 30-day chart to a few hundred points.
INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}

#: Chart ranges offered by the dashboard, mapped to a default bucket width.
RANGE_PRESETS: dict[str, tuple[timedelta, str]] = {
    "1h": (timedelta(hours=1), "1m"),
    "6h": (timedelta(hours=6), "5m"),
    "24h": (timedelta(hours=24), "15m"),
    "7d": (timedelta(days=7), "1h"),
    "30d": (timedelta(days=30), "6h"),
}


class TelemetryService:
    """Validated ingestion and querying of sensor readings."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.readings = SensorReadingRepository(session)
        self.devices = IotDeviceRepository(session)
        self.sensors = SensorConfigRepository(session)
        self.hives = HiveRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.device_service = DeviceService(session, self.settings)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def _configured_range(self, device: IotDevice, field: str) -> tuple[float, float] | None:
        """The narrower valid range configured for this sensor, if any."""
        sensor_type = next(
            (sensor for sensor in SensorType if sensor.reading_field == field), None
        )
        if sensor_type is None:
            return None
        config = self.sensors.get_for_device_type(device.id, sensor_type)
        if config is None or config.min_valid_value is None or config.max_valid_value is None:
            return None
        return float(config.min_valid_value), float(config.max_valid_value)

    def validate_reading(
        self, device: IotDevice, field: str, value: float | int | None
    ) -> float | int | None:
        """Check one sensor value against its bounds.

        Raises ``ValidationError`` with field-level details rather than
        clamping: a value outside the physical range is evidence of a broken
        probe or a malformed packet, and silently repairing it would put a
        fabricated number in the time series.
        """
        if value is None:
            return None

        numeric = float(value)
        if numeric != numeric:  # NaN
            raise ValidationError(f"{field} is not a number", details={"field": field})

        lower, upper = VALID_RANGES.get(field, (float("-inf"), float("inf")))
        configured = self._configured_range(device, field)
        if configured is not None:
            lower, upper = max(lower, configured[0]), min(upper, configured[1])

        if not (lower <= numeric <= upper):
            raise ValidationError(
                f"{field} must be between {lower:g} and {upper:g}",
                details={"field": field, "value": numeric, "min": lower, "max": upper},
            )

        if field in _INTEGER_FIELDS:
            return int(round(numeric))
        # Two/three decimal places, as the columns store.
        return round(numeric, 3)

    def validate_timestamp(self, timestamp: datetime | None) -> datetime:
        """Normalise and sanity-check the measurement time.

        A device with an unsynchronised clock routinely reports a time slightly
        in the future; a modest skew is tolerated. Anything further out is a
        configuration error worth surfacing rather than storing.
        """
        now = datetime.now(timezone.utc)
        value = timestamp or now
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        skew = (value - now).total_seconds()
        if skew > self.settings.TELEMETRY_MAX_CLOCK_SKEW_SECONDS:
            raise ValidationError(
                "The reading timestamp is too far in the future",
                details={
                    "field": "timestamp",
                    "skew_seconds": round(skew),
                    "allowed_seconds": self.settings.TELEMETRY_MAX_CLOCK_SKEW_SECONDS,
                },
            )
        # Older than a year is almost certainly a device with no clock at all.
        if value < now - timedelta(days=365):
            raise ValidationError(
                "The reading timestamp is implausibly old",
                details={"field": "timestamp", "value": value.isoformat()},
            )
        return value

    # ------------------------------------------------------------------ #
    # Ingestion
    # ------------------------------------------------------------------ #
    def ingest(
        self,
        payload: TelemetryIngest,
        *,
        actor: User | None = None,
        source: TelemetrySource | None = None,
        enforce_ownership: bool = True,
    ) -> dict:
        """Validate, store and apply one telemetry packet.

        ``actor`` is the authenticated user for HTTP ingestion, or ``None`` for
        the MQTT consumer (where the broker credentials are the authentication).
        The resolved ``source`` always comes from the server side of the call —
        ``SIMULATOR`` for the development simulator over MQTT, and the payload's
        own value for a user-submitted packet — so simulated data can never be
        filed as real hardware data.
        """
        device = self.devices.get_by_device_id(payload.device_id)
        if device is None:
            raise NotFoundError("Unknown device", details={"device_id": payload.device_id})

        if device.hive_id is None:
            raise ValidationError(
                "The device is not attached to a hive", details={"device_id": device.device_id}
            )

        if enforce_ownership and actor is not None:
            self._assert_ingest_allowed(actor, device)

        resolved_source = self._resolve_source(payload, device, source=source)
        timestamp = self.validate_timestamp(payload.timestamp)

        measurements = {
            field: self.validate_reading(device, field, getattr(payload, field))
            for field in SENSOR_FIELDS
        }
        if all(measurements[field] is None for field in SENSOR_FIELDS):
            raise ValidationError(
                "The payload contains no sensor values",
                details={"expected": list(SENSOR_FIELDS)},
            )

        if self.readings.exists_at(device_pk=device.id, timestamp=timestamp):
            # Same device, same instant: a redelivery. Return the existing
            # sample rather than creating a duplicate.
            logger.info(
                "Duplicate telemetry ignored",
                extra={"device_id": device.device_id, "timestamp": timestamp.isoformat()},
            )
            return {
                "duplicate": True,
                "reading": self.readings.latest_for_device(device.id),
                "device": device,
            }

        try:
            reading = self.readings.create(
                device_id=device.id,
                hive_id=device.hive_id,
                beekeeper_id=device.beekeeper_id,
                timestamp=timestamp,
                source=resolved_source,
                **measurements,
            )
        except IntegrityError:
            # Racing duplicate (MQTT consumer + HTTP post for the same instant).
            self.session.rollback()
            existing = self.readings.latest_for_device(device.id)
            return {"duplicate": True, "reading": existing, "device": device}

        self._apply_device_health(device, payload, timestamp)
        self._audit_telemetry(device, reading, actor=actor)
        self.readings.commit()

        return {
            "duplicate": False,
            "reading": reading,
            "device": device,
            "device_status": device.status,
        }

    def _resolve_source(
        self,
        payload: TelemetryIngest,
        device: IotDevice,
        *,
        source: TelemetrySource | None,
    ) -> TelemetrySource:
        """Decide how the reading is labelled.

        The caller (HTTP route or MQTT consumer) decides what it can vouch for.
        A device publishing over the broker is real hardware unless the message
        itself says it came from the simulator — the simulator sets that flag,
        real firmware does not, so guessing 'REAL_DEVICE' for an unlabelled
        packet is safe and explicit.
        """
        if source is not None:
            return source
        return payload.source or TelemetrySource.REAL_DEVICE

    def _assert_ingest_allowed(self, actor: User, device: IotDevice) -> None:
        if has_permission(actor.role, Permission.TELEMETRY_READ_ALL):
            return
        owner = self.beekeepers.get_by_user_id(actor.id)
        if owner is None or device.beekeeper_id != owner.id:
            logger.warning(
                "Telemetry ingest denied",
                extra={"user_id": str(actor.id), "device_id": device.device_id},
            )
            raise ForbiddenError(
                "You cannot submit telemetry for another beekeeper's device",
                details={"device_id": device.device_id},
            )

    def _apply_device_health(
        self, device: IotDevice, payload: TelemetryIngest, timestamp: datetime
    ) -> None:
        """Update last_seen, battery, signal and the derived status."""
        if device.last_seen is None or timestamp > device.last_seen:
            device.last_seen = timestamp
        if payload.battery_level is not None:
            device.battery_level = int(round(float(payload.battery_level)))
        if payload.signal_strength is not None:
            device.signal_strength = int(round(float(payload.signal_strength)))
        if device.installed_at is None:
            device.installed_at = timestamp

        derived = self.device_service.derive_status(device)
        if device.status != derived:
            previous = device.status
            device.status = derived
            self.audit.device_status_changed(
                device, actor=None, previous=previous, new=derived, automatic=True
            )

    def _audit_telemetry(self, device: IotDevice, reading: SensorReading, *, actor: User | None) -> None:
        """Write at most one TELEMETRY_RECEIVED entry per device per window.

        A 5-minute cadence would otherwise add ~105 000 audit rows per device per
        year, which is exactly the expensive logging this phase is told to avoid.
        """
        window_start = datetime.now(timezone.utc) - timedelta(
            seconds=self.settings.TELEMETRY_AUDIT_INTERVAL_SECONDS
        )
        # ``search`` orders newest-first; ``list`` would return an arbitrary row.
        recent, _total = self.audit.logs.search(
            page=1,
            page_size=1,
            action=str(AuditAction.TELEMETRY_RECEIVED),
            entity_type="iot_device",
            entity_id=str(device.id),
        )
        if recent and recent[0].created_at and recent[0].created_at >= window_start:
            return

        self.audit.telemetry_received(
            device,
            actor=actor,
            source=str(reading.source),
            reading_at=reading.timestamp,
        )

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #
    def resolve_range(
        self, *, start: datetime | None, end: datetime | None, range_key: str | None
    ) -> tuple[datetime, datetime, str | None]:
        """Turn a preset or explicit window into ``(start, end, interval)``."""
        now = datetime.now(timezone.utc)
        end = end or now
        interval = None
        if range_key:
            if range_key not in RANGE_PRESETS:
                raise ValidationError(
                    "Unknown range",
                    details={"field": "range", "allowed": sorted(RANGE_PRESETS)},
                )
            span, default_interval = RANGE_PRESETS[range_key]
            start = start or (end - span)
            interval = default_interval
        start = start or (end - timedelta(hours=24))
        if start >= end:
            raise ValidationError(
                "The start of the window must be before the end",
                details={"field": "from"},
            )
        return start, end, interval

    def _visible_hive(self, user: User, hive_id: uuid.UUID) -> Hive:
        hive = self.hives.get_with_relations(hive_id)
        if hive is None:
            raise NotFoundError("Hive not found")
        if has_permission(user.role, Permission.TELEMETRY_READ_ALL):
            return hive
        owner = self.beekeepers.get_by_user_id(user.id)
        if owner is None or hive.beekeeper_id != owner.id:
            # Same reasoning as hives: do not confirm the existence of another
            # beekeeper's hive.
            raise NotFoundError("Hive not found")
        return hive

    def history(
        self,
        user: User,
        hive_id: uuid.UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        range_key: str | None = None,
        interval: str | None = None,
        sensor_type: SensorType | None = None,
        device_pk: uuid.UUID | None = None,
        limit: int = 500,
    ) -> dict:
        """Readings for one hive over a window, raw or time-bucketed."""
        hive = self._visible_hive(user, hive_id)
        window_start, window_end, preset_interval = self.resolve_range(
            start=start, end=end, range_key=range_key
        )

        bucket = interval or preset_interval
        if bucket is not None and bucket not in INTERVAL_SECONDS:
            raise ValidationError(
                "Unknown interval",
                details={"field": "interval", "allowed": sorted(INTERVAL_SECONDS)},
            )

        if device_pk is not None:
            device = self.devices.get_with_relations(device_pk)
            if device is None or device.hive_id != hive.id:
                raise NotFoundError("Device not found for this hive")

        latest = self.readings.latest_for_hive(hive.id)
        # The device that produced it: serialised to the client as the hardware
        # id string, not the internal UUID.
        latest_device = self.devices.get(latest.device_id) if latest is not None else None
        dialect = self.session.get_bind().dialect.name

        if bucket is not None and dialect == "postgresql":
            rows = self.readings.aggregate(
                bucket_seconds=INTERVAL_SECONDS[bucket],
                hive_id=hive.id,
                device_pk=device_pk,
                start=window_start,
                end=window_end,
                limit=limit,
            )
            points = [self._serialise_point(row, aggregated=True, sensor_type=sensor_type) for row in rows]
        else:
            readings = self.readings.history(
                hive_id=hive.id,
                device_pk=device_pk,
                start=window_start,
                end=window_end,
                limit=limit,
            )
            if bucket is not None:
                readings = self._bucket_in_python(readings, INTERVAL_SECONDS[bucket])
            points = [
                self._serialise_point(reading, aggregated=False, sensor_type=sensor_type)
                for reading in readings
            ]

        return {
            "hive": hive,
            "from": window_start,
            "to": window_end,
            "interval": bucket,
            "sensor_type": sensor_type,
            "points": points,
            "count": len(points),
            "latest": latest,
            "latest_device": latest_device,
            "source_mix": self.readings.source_mix(
                hive_id=hive.id, start=window_start, end=window_end
            ),
        }

    @staticmethod
    def _bucket_in_python(readings: list[SensorReading], bucket_seconds: int) -> list[dict]:
        """Average readings into buckets when the database cannot do it.

        Only reached on the SQLite fallback; PostgreSQL uses ``date_bin``.
        """
        buckets: dict[int, dict] = {}
        for reading in readings:
            epoch = int(reading.timestamp.timestamp())
            key = epoch - (epoch % bucket_seconds)
            entry = buckets.setdefault(
                key,
                {
                    "timestamp": datetime.fromtimestamp(key, tz=timezone.utc),
                    "samples": 0,
                    **{field: None for field in SENSOR_FIELDS},
                },
            )
            entry["samples"] += 1
            for field in SENSOR_FIELDS:
                value = getattr(reading, field)
                if value is None:
                    continue
                current = entry[field]
                entry[field] = float(value) if current is None else current + float(value)
        for entry in buckets.values():
            for field in SENSOR_FIELDS:
                if entry[field] is not None:
                    entry[field] = entry[field] / entry["samples"]
        return [buckets[key] for key in sorted(buckets)]

    @staticmethod
    def _as_float(value) -> float | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    def _serialise_point(
        self, source, *, aggregated: bool, sensor_type: SensorType | None
    ) -> dict:
        """One chart point. ``sensor_type`` narrows the payload to one series."""
        fields = SENSOR_FIELDS
        if sensor_type is not None:
            fields = (sensor_type.reading_field,)

        if aggregated:
            point = {"timestamp": source["timestamp"], "samples": source.get("samples")}
            for field in fields:
                point[field] = self._as_float(source.get(field))
            return point

        reading = source
        point = {"timestamp": reading.timestamp, "samples": 1, "source": str(reading.source)}
        for field in fields:
            point[field] = self._as_float(getattr(reading, field))
        return point

    def latest_readings(self, user: User, hive_id: uuid.UUID) -> dict:
        """The most recent sample per device on a hive (live values panel)."""
        hive = self._visible_hive(user, hive_id)
        devices = self.devices.list_for_hive(hive.id)
        by_device = []
        for device in devices:
            reading = self.readings.latest_for_device(device.id)
            by_device.append(
                {
                    "device": device,
                    "status": self.device_service.derive_status(device),
                    "reading": reading,
                }
            )
        hive_latest = self.readings.latest_for_hive(hive.id)
        return {"hive": hive, "devices": by_device, "latest": hive_latest}


__all__ = ["TelemetryService", "INTERVAL_SECONDS", "RANGE_PRESETS", "DeviceStatus"]

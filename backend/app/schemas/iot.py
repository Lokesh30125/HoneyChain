"""IoT schemas — devices, sensor configuration, heartbeat and telemetry.

The telemetry schema (``TelemetryIngest``) is the single contract shared by the
HTTP endpoint and the MQTT consumer. That is deliberate: when real ESP32
hardware replaces the simulator, only the transport changes, never this shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import check_other_pair, display_choice
from app.models.enums import (
    ConnectionType,
    DeviceStatus,
    DeviceType,
    SensorType,
    TelemetrySource,
)

#: Hardware identifiers are printed on a label and become an MQTT topic
#: segment, so they are restricted to characters that survive both.
DEVICE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{3,39}$"


class DeviceCreate(BaseModel):
    """``POST /api/v1/iot/devices``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_id: str = Field(
        min_length=4,
        max_length=40,
        pattern=DEVICE_ID_PATTERN,
        examples=["ESP32-HIVE-0001"],
        description="Unique hardware id. Stored upper-cased for comparison.",
    )
    device_name: str = Field(min_length=2, max_length=120, examples=["North field node"])
    hive_id: uuid.UUID = Field(description="The hive this device reports on.")
    device_type: DeviceType = Field(default=DeviceType.ESP32)
    device_type_other: str | None = Field(
        default=None,
        max_length=120,
        description=(
            "The hardware in the operator's own words. Required when `device_type` is "
            "OTHER, and refused otherwise."
        ),
    )
    connection_type: ConnectionType = Field(default=ConnectionType.MQTT)
    firmware_version: str | None = Field(default=None, max_length=40, examples=["1.0.3"])
    mqtt_topic: str | None = Field(
        default=None,
        max_length=180,
        description="Optional override; the platform default is derived from the device id.",
    )
    installed_at: datetime | None = Field(default=None)

    @model_validator(mode="after")
    def _other_matches_the_type(self):
        """The hardware type and its description agree — the platform-wide rule."""
        check_other_pair(
            kind="hardware",
            value=self.device_type,
            other=self.device_type_other,
            other_option=DeviceType.OTHER.value,
        )
        return self

    @field_validator("device_id")
    @classmethod
    def _normalise_device_id(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if " " in cleaned:
            raise ValueError("Device id cannot contain spaces")
        return cleaned


class DeviceUpdate(BaseModel):
    """``PUT /api/v1/iot/devices/{id}`` — partial update."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_name: str | None = Field(default=None, min_length=2, max_length=120)
    hive_id: uuid.UUID | None = Field(
        default=None, description="Move the device to another hive (own hives only)."
    )
    device_type: DeviceType | None = None
    device_type_other: str | None = Field(default=None, max_length=120)
    connection_type: ConnectionType | None = None
    firmware_version: str | None = Field(default=None, max_length=40)
    mqtt_topic: str | None = Field(default=None, max_length=180)
    installed_at: datetime | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "DeviceUpdate":
        if not self.model_fields_set:
            raise ValueError("Supply at least one field to update")
        return self


class DeviceStatusUpdate(BaseModel):
    """``PATCH /api/v1/iot/devices/{id}/status``.

    Only MAINTENANCE really sticks — the derived status is recomputed from
    ``last_seen``, so a device cannot be declared healthy by hand.
    """

    model_config = ConfigDict(extra="forbid")

    status: DeviceStatus = Field(examples=[DeviceStatus.MAINTENANCE.value])
    reason: str | None = Field(default=None, max_length=300)


class SensorConfigUpdate(BaseModel):
    """``PATCH /api/v1/iot/devices/{id}/sensors/{sensor_type}``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sensor_name: str | None = Field(default=None, min_length=2, max_length=80)
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    enabled: bool | None = None
    sampling_interval: int | None = Field(
        default=None, ge=1, le=86400, description="Seconds between expected readings."
    )
    min_valid_value: float | None = Field(default=None, ge=-10000, le=100000)
    max_valid_value: float | None = Field(default=None, ge=-10000, le=100000)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "SensorConfigUpdate":
        if not self.model_fields_set:
            raise ValueError("Supply at least one field to update")
        if (
            self.min_valid_value is not None
            and self.max_valid_value is not None
            and self.min_valid_value >= self.max_valid_value
        ):
            raise ValueError("The minimum valid value must be below the maximum")
        return self


class TelemetryIngest(BaseModel):
    """One sensor packet — from an ESP32, the simulator, or a manual entry.

    Every measurement is optional (a device may not carry every sensor) but at
    least one must be present, and each value is range-checked by the service
    against the sensor's configured range.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_id: str = Field(min_length=4, max_length=40, examples=["ESP32-HIVE-0001"])
    timestamp: datetime | None = Field(
        default=None,
        description="Measurement time (UTC). Defaults to receipt time when omitted.",
    )
    temperature: float | None = Field(default=None, examples=[34.2])
    humidity: float | None = Field(default=None, examples=[58.4])
    weight: float | None = Field(default=None, examples=[42.6])
    vibration: float | None = Field(default=None, examples=[0.31])
    acoustic_level: float | None = Field(default=None, examples=[41.5])
    battery_level: int | None = Field(default=None, examples=[91])
    signal_strength: int | None = Field(default=None, examples=[-67])
    source: TelemetrySource | None = Field(
        default=None,
        description=(
            "How the reading was produced. The server decides the effective value: "
            "the MQTT consumer treats an unlabelled packet as REAL_DEVICE, and HTTP "
            "submissions default to MANUAL unless the caller says SIMULATOR."
        ),
    )

    @field_validator("device_id")
    @classmethod
    def _normalise_device_id(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def _requires_a_measurement(self) -> "TelemetryIngest":
        measurements = (
            self.temperature,
            self.humidity,
            self.weight,
            self.vibration,
            self.acoustic_level,
            self.battery_level,
            self.signal_strength,
        )
        if all(value is None for value in measurements):
            raise ValueError("Supply at least one sensor value")
        return self


class HeartbeatPayload(BaseModel):
    """``POST /api/v1/iot/devices/heartbeat`` — reachability without a full packet."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_id: str = Field(min_length=4, max_length=40)
    timestamp: datetime | None = None
    battery_level: int | None = Field(default=None, ge=0, le=100)
    signal_strength: int | None = Field(default=None, ge=-140, le=0)

    @field_validator("device_id")
    @classmethod
    def _normalise_device_id(cls, value: str) -> str:
        return value.strip().upper()


class ReadingResult(BaseModel):
    """What the ingestion endpoint reports back."""

    device_id: str
    hive_id: uuid.UUID
    hive_code: str | None = None
    stored: bool
    duplicate: bool
    timestamp: datetime
    source: TelemetrySource
    device_status: DeviceStatus
    battery_level: int | None = None
    signal_strength: int | None = None
    message: str


class SensorConfigPublic(BaseModel):
    """One configured sensor on a device."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sensor_type: SensorType
    sensor_name: str
    unit: str
    enabled: bool
    sampling_interval: int
    min_valid_value: float | None = None
    max_valid_value: float | None = None
    created_at: datetime
    updated_at: datetime


class SensorSnapshot(BaseModel):
    """A sensor's configured state plus its most recent value."""

    sensor_type: SensorType
    sensor_name: str
    unit: str
    enabled: bool
    sampling_interval: int
    value: float | None = None
    recorded_at: datetime | None = None


class DevicePublic(BaseModel):
    """Base device representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: str
    device_name: str
    hive_id: uuid.UUID
    beekeeper_id: uuid.UUID
    device_type: DeviceType
    device_type_other: str | None = None
    device_type_display: str = ""
    connection_type: ConnectionType
    firmware_version: str | None = None
    mqtt_topic: str | None = None
    status: DeviceStatus
    status_label: str = ""
    status_is_derived: bool = True
    battery_level: int | None = None
    signal_strength: int | None = None
    last_seen: datetime | None = None
    installed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DeviceListItem(DevicePublic):
    """A device row in the device list."""

    hive_code: str | None = None
    hive_status: str | None = None
    cluster_code: str | None = None
    sensors_enabled: int = 0
    sensors_total: int = 0
    latest_reading_at: datetime | None = None
    seconds_since_last_seen: int | None = None


class DeviceDetail(DeviceListItem):
    """``GET /api/v1/iot/devices/{id}`` — the device details screen."""

    sensors: list[SensorSnapshot] = Field(default_factory=list)
    latest_reading: "ReadingSnapshot | None" = None
    readings_last_24h: int = 0


class ReadingSnapshot(BaseModel):
    """A stored reading, serialised for the UI."""

    timestamp: datetime
    source: TelemetrySource
    source_label: str
    temperature: float | None = None
    humidity: float | None = None
    weight: float | None = None
    vibration: float | None = None
    acoustic_level: float | None = None
    battery_level: int | None = None
    signal_strength: int | None = None


class TelemetryPoint(BaseModel):
    """One chart point: a raw sample, or an averaged bucket."""

    timestamp: datetime
    samples: int | None = None
    source: str | None = None
    temperature: float | None = None
    humidity: float | None = None
    weight: float | None = None
    vibration: float | None = None
    acoustic_level: float | None = None
    battery_level: float | None = None
    signal_strength: float | None = None


class TelemetryHistoryResponse(BaseModel):
    """``GET /api/v1/iot/telemetry/{hive_id}``."""

    hive_id: uuid.UUID
    hive_code: str
    device_id: str | None = None
    from_timestamp: datetime = Field(alias="from")
    to_timestamp: datetime = Field(alias="to")
    interval: str | None = None
    sensor_type: str | None = None
    count: int = 0
    points: list[TelemetryPoint] = Field(default_factory=list)
    latest: ReadingSnapshot | None = None
    source_mix: dict[str, int] = Field(default_factory=dict)
    message: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class IotSummary(BaseModel):
    """The ``/beekeeper/iot`` dashboard counters — all from the database."""

    total_hives: int = 0
    total_devices: int = 0
    connected_devices: int = 0
    offline_devices: int = 0
    warning_devices: int = 0
    maintenance_devices: int = 0
    sensors_active: int = 0
    hives_without_device: int = 0
    readings_last_window: int = 0
    window_hours: int = 24
    last_telemetry_at: datetime | None = None
    offline_threshold_seconds: int = 0
    generated_at: datetime


class LastTelemetry(BaseModel):
    """Where the newest reading in scope came from.

    ``has_data`` is always present so the monitoring header can distinguish
    "nothing has been received yet" from "the field is missing" without
    inferring it from nulls.
    """

    has_data: bool
    checked_at: datetime
    message: str | None = None
    timestamp: datetime | None = None
    device_id: str | None = None
    device_name: str | None = None
    hive_code: str | None = None
    source: str | None = None
    temperature: float | None = None
    humidity: float | None = None
    weight: float | None = None
    vibration: float | None = None
    acoustic_level: float | None = None


class MqttHealth(BaseModel):
    """``GET /api/v1/health/mqtt``."""

    status: str
    enabled: bool
    broker: str | None = None
    topic: str | None = None
    connected_at: str | None = None
    last_message_at: str | None = None
    last_error: str | None = None
    stats: dict[str, int] = Field(default_factory=dict)
    detail: str | None = None


DeviceDetail.model_rebuild()

__all__ = [
    "DeviceCreate",
    "DeviceUpdate",
    "DeviceStatusUpdate",
    "SensorConfigUpdate",
    "SensorConfigPublic",
    "SensorSnapshot",
    "TelemetryIngest",
    "HeartbeatPayload",
    "ReadingResult",
    "ReadingSnapshot",
    "TelemetryPoint",
    "TelemetryHistoryResponse",
    "DevicePublic",
    "DeviceListItem",
    "DeviceDetail",
    "IotSummary",
    "LastTelemetry",
    "MqttHealth",
]


# --------------------------------------------------------------------------- #
# Serialisers
# --------------------------------------------------------------------------- #
def _number(value):
    """``Numeric``/``Decimal`` → plain JSON number (``None`` stays ``None``)."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return float(value)


def to_reading_snapshot(reading) -> ReadingSnapshot | None:
    if reading is None:
        return None
    return ReadingSnapshot(
        timestamp=reading.timestamp,
        source=reading.source,
        source_label=reading.source.label if reading.source else "",
        temperature=_number(reading.temperature),
        humidity=_number(reading.humidity),
        weight=_number(reading.weight),
        vibration=_number(reading.vibration),
        acoustic_level=_number(reading.acoustic_level),
        battery_level=reading.battery_level,
        signal_strength=reading.signal_strength,
    )


def to_sensor_snapshot(config, reading=None) -> SensorSnapshot:
    """A configured sensor plus whatever value the latest packet carried."""
    value = None
    if reading is not None:
        value = _number(getattr(reading, config.sensor_type.reading_field, None))
    return SensorSnapshot(
        sensor_type=config.sensor_type,
        sensor_name=config.sensor_name,
        unit=config.unit,
        enabled=config.enabled,
        sampling_interval=config.sampling_interval,
        value=value,
        recorded_at=reading.timestamp if (reading is not None and value is not None) else None,
    )


def to_sensor_config_public(config) -> SensorConfigPublic:
    return SensorConfigPublic.model_validate(config)


def to_sensor_status(config, reading=None):
    """One configured sensor for the compact device summary.

    ``SensorStatus`` lives in the hive module (it is part of a hive's device
    block), so it is imported here rather than at module scope to keep the two
    schema modules from importing each other circularly.
    """
    from app.schemas.hive import SensorStatus

    value = None
    if reading is not None:
        value = _number(getattr(reading, config.sensor_type.reading_field, None))
    return SensorStatus(
        sensor_type=str(config.sensor_type),
        sensor_name=config.sensor_name,
        unit=config.unit,
        enabled=config.enabled,
        sampling_interval=config.sampling_interval,
        value=value,
        recorded_at=reading.timestamp if (reading is not None and value is not None) else None,
    )


def to_device_summary(
    device,
    *,
    reading=None,
    status: DeviceStatus | None = None,
    sensors: list | None = None,
) -> DeviceSummary:
    """Compact device block embedded in hive payloads.

    The status passed in should be the *derived* one (see ``DeviceService``);
    the model's stored value is only a fallback.
    """
    from app.schemas.hive import DeviceSummary

    effective = status or device.status
    sensors = sensors if sensors is not None else list(getattr(device, "sensors", []) or [])
    return DeviceSummary(
        id=device.id,
        device_id=device.device_id,
        device_name=device.device_name,
        device_type=str(device.device_type),
        device_type_other=getattr(device, "device_type_other", None),
        device_type_display=display_device_type(device),
        connection_type=str(device.connection_type),
        status=str(effective),
        status_label=effective.label if effective else "",
        battery_level=device.battery_level,
        signal_strength=device.signal_strength,
        last_seen=device.last_seen,
        firmware_version=device.firmware_version,
        installed_at=device.installed_at,
        mqtt_topic=device.mqtt_topic or f"honeychain/devices/{device.device_id}/telemetry",
        sensors=[to_sensor_status(config, reading) for config in sensors],
    )


def display_device_type(device) -> str:
    """What to print for a device's hardware: its listed name, or the operator's own.

    A device registered as *Other* carries the description that was entered with it;
    a bare "Other" would tell a reader nothing about the board in the apiary.
    """
    return display_choice(device.device_type, getattr(device, "device_type_other", None))


def to_device_public(device, *, status: DeviceStatus | None = None) -> DevicePublic:
    """Device fields plus the *derived* status and its human label.

    ``status_is_derived`` tells the UI that the stored column is not necessarily
    what the API just returned, so the badge can explain a corrected state.
    """
    effective = status or device.status
    return DevicePublic(
        id=device.id,
        device_id=device.device_id,
        device_name=device.device_name,
        hive_id=device.hive_id,
        beekeeper_id=device.beekeeper_id,
        device_type=device.device_type,
        device_type_other=device.device_type_other,
        device_type_display=display_device_type(device),
        connection_type=device.connection_type,
        firmware_version=device.firmware_version,
        mqtt_topic=device.mqtt_topic or f"honeychain/devices/{device.device_id}/telemetry",
        status=effective,
        status_label=effective.label if effective else "",
        # Always true: ``status`` above is recomputed from last_seen/battery, so
        # the value a client sees may differ from the stored column until the
        # next sweep persists it. The flag lets the UI say so.
        status_is_derived=True,
        battery_level=device.battery_level,
        signal_strength=device.signal_strength,
        last_seen=device.last_seen,
        installed_at=device.installed_at,
        created_at=device.created_at,
        updated_at=device.updated_at,
    )


def seconds_since(value, *, now=None) -> int | None:
    if value is None:
        return None
    from datetime import datetime, timezone

    reference = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(int((reference - value).total_seconds()), 0)


def to_device_list_item(
    device,
    *,
    status: DeviceStatus | None = None,
    reading=None,
    sensors: list | None = None,
    hive=None,
) -> DeviceListItem:
    """A device row: its hive, its sensor counts and its freshness."""
    hive = hive if hive is not None else getattr(device, "hive", None)
    cluster = getattr(hive, "cluster", None) if hive is not None else None
    enabled = sum(1 for sensor in (sensors or []) if sensor.enabled)
    return DeviceListItem(
        **to_device_public(device, status=status).model_dump(),
        hive_code=getattr(hive, "hive_code", None),
        hive_status=str(hive.status) if hive is not None and hive.status else None,
        cluster_code=getattr(cluster, "cluster_code", None),
        sensors_enabled=enabled,
        sensors_total=len(sensors or []),
        latest_reading_at=reading.timestamp if reading is not None else None,
        seconds_since_last_seen=seconds_since(device.last_seen),
    )


def to_device_detail(
    device,
    *,
    status: DeviceStatus | None = None,
    reading=None,
    sensors: list | None = None,
    hive=None,
    readings_last_24h: int = 0,
) -> DeviceDetail:
    sensors = sensors if sensors is not None else list(getattr(device, "sensors", []) or [])
    return DeviceDetail(
        **to_device_list_item(device, status=status, reading=reading, sensors=sensors, hive=hive).model_dump(),
        sensors=[to_sensor_snapshot(sensor, reading) for sensor in sensors],
        latest_reading=to_reading_snapshot(reading),
        readings_last_24h=readings_last_24h,
    )


def to_telemetry_points(points: list[dict]) -> list[TelemetryPoint]:
    """Chart points from the service's serialised rows.

    ``TelemetryService.history`` already narrows each row to plain JSON
    scalars — a raw sample (all seven sensors, one source) or an averaged bucket
    (per-sensor means plus a sample count). This maps either shape onto the
    response model without re-reading the ORM, which is what keeps the chart
    endpoint free of N+1 queries.
    """
    return [
        TelemetryPoint(
            timestamp=point["timestamp"],
            samples=point.get("samples"),
            source=point.get("source"),
            temperature=_number(point.get("temperature")),
            humidity=_number(point.get("humidity")),
            weight=_number(point.get("weight")),
            vibration=_number(point.get("vibration")),
            acoustic_level=_number(point.get("acoustic_level")),
            battery_level=_number(point.get("battery_level")),
            signal_strength=_number(point.get("signal_strength")),
        )
        for point in points
    ]


__all__.extend(
    [
        "to_device_summary",
        "to_sensor_status",
        "to_device_public",
        "to_device_list_item",
        "to_device_detail",
        "to_reading_snapshot",
        "to_sensor_snapshot",
        "to_sensor_config_public",
        "to_telemetry_points",
        "seconds_since",
    ]
)

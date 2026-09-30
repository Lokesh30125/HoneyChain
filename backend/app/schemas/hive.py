"""Hive schemas — create/update payloads and the shapes the UI renders."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import ColonyStrength, HiveStatus, QueenStatus


class HiveBase(BaseModel):
    """Fields a beekeeper actually knows. Everything else is derived."""

    model_config = ConfigDict(extra="forbid")

    bee_species: str | None = Field(default=None, max_length=80, examples=["Apis cerana indica"])
    queen_status: QueenStatus = Field(default=QueenStatus.UNKNOWN)
    colony_strength: ColonyStrength = Field(default=ColonyStrength.UNKNOWN)
    installation_date: date | None = Field(default=None)

    village: str | None = Field(default=None, max_length=120)
    mandal: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    pincode: str | None = Field(default=None, max_length=10)

    latitude: float | None = Field(default=None, ge=-90, le=90, examples=[16.3067])
    longitude: float | None = Field(default=None, ge=-180, le=180, examples=[80.4365])

    notes: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "bee_species", "village", "mandal", "district", "state", "pincode", "notes", mode="before"
    )
    @classmethod
    def _clean_text(cls, value: object) -> object:
        """Collapse whitespace and turn blank strings into ``None``.

        A field left empty in the form must end up NULL, not an empty string —
        otherwise "not supplied" and "supplied as blank" become indistinguishable
        in reports.
        """
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = " ".join(value.split())
            return cleaned or None
        return value

    @field_validator("pincode")
    @classmethod
    def _check_pincode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not (value.isdigit() and len(value) == 6 and value[0] != "0"):
            raise ValueError("Enter a valid 6-digit PIN code")
        return value

    @model_validator(mode="after")
    def _coordinates_come_in_pairs(self) -> "HiveBase":
        """A lone latitude is not a location.

        Either both coordinates are supplied, or neither is — the hive is then
        registered without a pin rather than with a guessed one.
        """
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude, or neither")
        return self


class HiveCreate(HiveBase):
    """``POST /api/v1/hives``.

    ``hive_code``, ``beekeeper_id``, ``cluster_id`` and the timestamps are
    deliberately absent: with ``extra="forbid"``, sending one is a 422 rather
    than a field that quietly goes nowhere.
    """


class HiveClusterUpdate(BaseModel):
    """``POST /api/v1/hives/{id}/cluster`` — staff-only cluster placement.

    ``cluster_id: null`` clears the placement, which is how a hive whose owner
    was removed from a cluster is left for administrative resolution rather than
    being silently attached to another one.
    """

    model_config = ConfigDict(extra="forbid")

    cluster_id: uuid.UUID | None = Field(
        default=None, description="Target cluster, or null to clear the placement."
    )
    reason: str | None = Field(default=None, max_length=200)


class HiveUpdate(HiveBase):
    """``PUT /api/v1/hives/{id}`` — a partial update of the editable fields."""

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "HiveUpdate":
        if not self.model_fields_set:
            raise ValueError("Supply at least one field to update")
        return self


class HiveStatusUpdate(BaseModel):
    """``PATCH /api/v1/hives/{id}/status``."""

    model_config = ConfigDict(extra="forbid")

    status: HiveStatus = Field(examples=[HiveStatus.MAINTENANCE.value])
    reason: str | None = Field(
        default=None,
        max_length=300,
        description="Optional note recorded in the audit entry.",
    )


class HiveOwnerInfo(BaseModel):
    """The beekeeper behind a hive."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    beekeeper_code: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    district: str | None = None
    state: str | None = None


class HiveClusterInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cluster_code: str
    cluster_name: str
    district: str
    is_active: bool


class SensorValue(BaseModel):
    """One sensor's latest value, as stored."""

    sensor_type: str
    label: str
    unit: str
    value: float | None = None
    recorded_at: datetime | None = None
    source: str | None = None


class DeviceSummary(BaseModel):
    """Compact device view embedded in hive payloads."""

    id: uuid.UUID
    device_id: str
    device_name: str
    device_type: str
    device_type_other: str | None = None
    device_type_display: str = ""
    connection_type: str
    status: str
    status_label: str
    battery_level: int | None = None
    signal_strength: int | None = None
    last_seen: datetime | None = None
    firmware_version: str | None = None
    installed_at: datetime | None = None
    mqtt_topic: str | None = None
    sensors: list["SensorStatus"] = Field(default_factory=list)


class SensorStatus(BaseModel):
    """One configured sensor on a device, with its most recent value."""

    sensor_type: str
    sensor_name: str
    unit: str
    enabled: bool
    sampling_interval: int
    value: float | None = None
    recorded_at: datetime | None = None


class LatestReading(BaseModel):
    """The newest telemetry sample for a hive, for the live values panel."""

    timestamp: datetime
    device_id: str | None = None
    source: str
    source_label: str
    temperature: float | None = None
    humidity: float | None = None
    weight: float | None = None
    vibration: float | None = None
    acoustic_level: float | None = None
    battery_level: int | None = None
    signal_strength: int | None = None


class HivePublic(BaseModel):
    """Base hive representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hive_code: str
    beekeeper_id: uuid.UUID
    cluster_id: uuid.UUID | None = None
    bee_species: str | None = None
    queen_status: QueenStatus
    queen_status_label: str = ""
    colony_strength: ColonyStrength
    colony_strength_label: str = ""
    installation_date: date | None = None
    village: str | None = None
    mandal: str | None = None
    district: str | None = None
    state: str | None = None
    pincode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    has_coordinates: bool = False
    location_label: str | None = None
    status: HiveStatus
    status_label: str = ""
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class HiveListItem(HivePublic):
    """A hive as it appears in the ``My Hives`` list."""

    cluster: HiveClusterInfo | None = None
    device_count: int = 0
    primary_device: DeviceSummary | None = None
    latest_reading: LatestReading | None = None


class HiveDetail(HiveListItem):
    """``GET /api/v1/hives/{id}`` — everything the detail screen shows."""

    owner: HiveOwnerInfo | None = None
    devices: list[DeviceSummary] = Field(default_factory=list)
    sensor_values: list[SensorValue] = Field(default_factory=list)


class HiveSummary(BaseModel):
    """Counts for the hive dashboard header."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    with_device: int = 0
    without_device: int = 0
    #: Hives whose owner has no KVIC cluster yet. Nobody but staff sees this
    #: figure, and it is the worklist that keeps an unassigned apiary from being
    #: invisible: it is counted, listed (``GET /hives?has_cluster=false``) and
    #: never assigned automatically.
    without_cluster: int = 0


class HiveFilterOptions(BaseModel):
    """Filter values actually present in the caller's data."""

    districts: list[str] = Field(default_factory=list)
    bee_species: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)


DeviceSummary.model_rebuild()

__all__ = [
    "HiveCreate",
    "HiveClusterUpdate",
    "HiveUpdate",
    "HiveStatusUpdate",
    "HivePublic",
    "HiveListItem",
    "HiveDetail",
    "HiveOwnerInfo",
    "HiveClusterInfo",
    "HiveSummary",
    "HiveFilterOptions",
    "DeviceSummary",
    "SensorStatus",
    "SensorValue",
    "LatestReading",
]


# --------------------------------------------------------------------------- #
# Serialisers
# --------------------------------------------------------------------------- #
# Response shapes are built by these functions rather than by ``from_attributes``
# alone, because several fields on ``HivePublic`` are *derived*: the status is
# recomputed for devices, coordinates are summarised into a label, and a hive's
# sensor values come from its latest reading rather than from the hive row.
def location_label_for(hive) -> str | None:
    """``"Tenali, Guntur, Andhra Pradesh"`` from whatever parts are known."""
    parts = [part for part in (hive.village, hive.mandal, hive.district, hive.state) if part]
    return ", ".join(parts) if parts else None


def to_hive_public(hive) -> HivePublic:
    return HivePublic(
        id=hive.id,
        hive_code=hive.hive_code,
        beekeeper_id=hive.beekeeper_id,
        cluster_id=hive.cluster_id,
        bee_species=hive.bee_species,
        queen_status=hive.queen_status,
        queen_status_label=hive.queen_status.label if hive.queen_status else "",
        colony_strength=hive.colony_strength,
        colony_strength_label=hive.colony_strength.label if hive.colony_strength else "",
        installation_date=hive.installation_date,
        village=hive.village,
        mandal=hive.mandal,
        district=hive.district,
        state=hive.state,
        pincode=hive.pincode,
        latitude=hive.latitude,
        longitude=hive.longitude,
        has_coordinates=hive.latitude is not None and hive.longitude is not None,
        location_label=location_label_for(hive),
        status=hive.status,
        status_label=hive.status.label if hive.status else "",
        notes=hive.notes,
        created_at=hive.created_at,
        updated_at=hive.updated_at,
    )


def to_cluster_info(cluster) -> HiveClusterInfo | None:
    if cluster is None:
        return None
    return HiveClusterInfo(
        id=cluster.id,
        cluster_code=cluster.cluster_code,
        cluster_name=cluster.cluster_name,
        district=cluster.district,
        is_active=cluster.is_active,
    )


def to_owner_info(hive) -> HiveOwnerInfo | None:
    """The beekeeper behind a hive, as shown on the detail screen."""
    beekeeper = getattr(hive, "beekeeper", None)
    if beekeeper is None:
        return None
    user = getattr(beekeeper, "user", None)
    return HiveOwnerInfo(
        id=beekeeper.id,
        beekeeper_code=beekeeper.beekeeper_code,
        name=getattr(user, "name", None) or getattr(user, "email", None),
        email=getattr(user, "email", None),
        phone=getattr(user, "phone", None),
        district=beekeeper.district,
        state=beekeeper.state,
    )


def to_latest_reading(reading, *, device_label: str | None = None) -> LatestReading | None:
    """The newest sample for a hive, or ``None`` when nothing has arrived yet."""
    if reading is None:
        return None
    return LatestReading(
        timestamp=reading.timestamp,
        device_id=device_label,
        source=str(reading.source),
        source_label=reading.source.label if reading.source else "",
        temperature=_number(reading.temperature),
        humidity=_number(reading.humidity),
        weight=_number(reading.weight),
        vibration=_number(reading.vibration),
        acoustic_level=_number(reading.acoustic_level),
        battery_level=reading.battery_level,
        signal_strength=reading.signal_strength,
    )


def to_sensor_values(reading, *, device_label: str | None = None) -> list[SensorValue]:
    """One entry per sensor that actually reported a value in ``reading``.

    Sensors with ``NULL`` in the packet are omitted rather than shown as ``0``:
    a missing measurement is not a measurement of zero.
    """
    if reading is None:
        return []

    from app.models.enums import SensorType

    values: list[SensorValue] = []
    for sensor_type in SensorType:
        value = getattr(reading, sensor_type.reading_field, None)
        if value is None:
            continue
        values.append(
            SensorValue(
                sensor_type=sensor_type.value,
                label=sensor_type.label,
                unit=sensor_type.unit,
                value=_number(value),
                recorded_at=reading.timestamp,
                source=str(reading.source) if reading.source else None,
            )
        )
    return values


def _number(value) -> float | int | None:
    """Coerce ``Numeric``/``Decimal`` values to plain JSON numbers."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return float(value)


def to_hive_list_item(
    hive,
    *,
    device=None,
    reading=None,
    device_count: int | None = None,
    device_status=None,
    sensors: list | None = None,
) -> HiveListItem:
    """A ``My Hives`` row: the hive, its primary device and its latest reading."""
    from app.schemas.iot import to_device_summary

    return HiveListItem(
        **to_hive_public(hive).model_dump(),
        cluster=to_cluster_info(getattr(hive, "cluster", None)),
        device_count=device_count if device_count is not None else len(getattr(hive, "devices", []) or []),
        primary_device=(
            to_device_summary(device, reading=reading, status=device_status, sensors=sensors)
            if device is not None
            else None
        ),
        latest_reading=to_latest_reading(reading, device_label=device.device_id if device else None),
    )


def to_hive_detail(
    hive,
    *,
    devices: list | None = None,
    readings_by_device: dict | None = None,
    latest=None,
    primary_device=None,
    statuses: dict | None = None,
) -> HiveDetail:
    """The full hive payload: owner, cluster, devices and current sensor values."""
    from app.schemas.iot import to_device_summary

    devices = devices if devices is not None else list(getattr(hive, "devices", []) or [])
    readings_by_device = readings_by_device or {}
    statuses = statuses or {}

    summaries = [
        to_device_summary(
            device,
            reading=readings_by_device.get(device.id),
            status=statuses.get(device.id),
            sensors=getattr(device, "sensors", None),
        )
        for device in devices
    ]
    primary = primary_device or (devices[0] if devices else None)

    return HiveDetail(
        **to_hive_list_item(
            hive,
            device=primary,
            reading=readings_by_device.get(primary.id) if primary else latest,
            device_count=len(devices),
            device_status=statuses.get(primary.id) if primary else None,
            sensors=getattr(primary, "sensors", None) if primary else None,
        ).model_dump(),
        owner=to_owner_info(hive),
        devices=summaries,
        sensor_values=to_sensor_values(latest, device_label=primary.device_id if primary else None),
    )


__all__.extend(
    [
        "to_hive_public",
        "to_hive_list_item",
        "to_hive_detail",
        "to_latest_reading",
        "to_sensor_values",
        "to_owner_info",
        "to_cluster_info",
        "location_label_for",
    ]
)

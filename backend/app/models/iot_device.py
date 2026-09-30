"""``iot_devices`` — ESP32 (and future LoRa) devices attached to hives.

A device belongs to exactly one hive, and therefore to exactly one beekeeper.
That single link is what every ownership check in the IoT module resolves
against, so a beekeeper can never reach another beekeeper's device or readings.

``status`` is stored, but it is *derived* on read by the offline-detection rule
(see ``app/services/device_service.py``): a device that stops reporting becomes
OFFLINE on its own. MAINTENANCE is the one status an operator sets by hand and
the sweeper respects.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Enum as SAEnum,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, UUID_TYPE
from app.models.enums import ConnectionType, DeviceStatus, DeviceType

DEVICE_TYPE_ENUM = SAEnum(
    DeviceType,
    name="device_type",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
CONNECTION_TYPE_ENUM = SAEnum(
    ConnectionType,
    name="connection_type",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)
DEVICE_STATUS_ENUM = SAEnum(
    DeviceStatus,
    name="device_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)


class IotDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A telemetry-capable device registered against a hive."""

    __tablename__ = "iot_devices"

    # -- Identity ------------------------------------------------------------
    device_id: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        unique=True,
        index=True,
        doc="Unique hardware identifier, e.g. ESP32-HIVE-0001. Printed on the "
        "device and used as the MQTT topic segment.",
    )
    device_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # -- Placement -----------------------------------------------------------
    hive_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("hives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    beekeeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("beekeepers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Denormalised owner, copied from the hive at registration so every "
        "authorisation check is a single indexed lookup.",
    )

    # -- Hardware ------------------------------------------------------------
    #: The hardware described in the operator's own words, when ``device_type`` is
    #: ``OTHER``; NULL otherwise.
    device_type_other: Mapped[str | None] = mapped_column(String(120), nullable=True)
    device_type: Mapped[DeviceType] = mapped_column(
        DEVICE_TYPE_ENUM, nullable=False, default=DeviceType.ESP32, server_default=DeviceType.ESP32.value
    )
    firmware_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    connection_type: Mapped[ConnectionType] = mapped_column(
        CONNECTION_TYPE_ENUM,
        nullable=False,
        default=ConnectionType.MQTT,
        server_default=ConnectionType.MQTT.value,
    )
    mqtt_topic: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        doc="Telemetry topic the device publishes to. Derived from the device id "
        "unless an operator supplies a custom one.",
    )

    # -- Health --------------------------------------------------------------
    status: Mapped[DeviceStatus] = mapped_column(
        DEVICE_STATUS_ENUM,
        nullable=False,
        default=DeviceStatus.OFFLINE,
        server_default=DeviceStatus.OFFLINE.value,
        doc="Starts OFFLINE — a device is never assumed to be working before it "
        "has reported at least once.",
    )
    battery_level: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, doc="Percent (0–100), reported by the device."
    )
    signal_strength: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, doc="RSSI in dBm (typically -120…0)."
    )
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Timestamp of the most recent telemetry or heartbeat.",
    )
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The pair travels together or not at all: "Other" without a description
        # would record that something happened and nothing about what it was, and a
        # listed value with a leftover description could contradict it.
        CheckConstraint(
            "(device_type <> 'OTHER' AND device_type_other IS NULL) "
            "OR (device_type = 'OTHER' AND device_type_other IS NOT NULL "
            "AND length(btrim(device_type_other)) > 0)",
            name="ck_device_type_other",
        ),
        CheckConstraint(
            "battery_level IS NULL OR (battery_level >= 0 AND battery_level <= 100)",
            name="device_battery_range",
        ),
        CheckConstraint(
            "signal_strength IS NULL OR (signal_strength >= -140 AND signal_strength <= 0)",
            name="device_signal_range",
        ),
        CheckConstraint("length(device_id) >= 4", name="device_id_min_length"),
        Index("ix_iot_devices_hive_status", "hive_id", "status"),
        Index("ix_iot_devices_beekeeper_status", "beekeeper_id", "status"),
    )

    # -- Relationships -------------------------------------------------------
    hive: Mapped["Hive"] = relationship(back_populates="devices")  # noqa: F821
    beekeeper: Mapped["Beekeeper"] = relationship(back_populates="devices")  # noqa: F821
    sensors: Mapped[list["SensorConfig"]] = relationship(  # noqa: F821
        back_populates="device", cascade="all, delete-orphan"
    )
    readings: Mapped[list["SensorReading"]] = relationship(  # noqa: F821
        back_populates="device", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IotDevice {self.device_id} status={self.status}>"


__all__ = [
    "IotDevice",
    "DEVICE_TYPE_ENUM",
    "CONNECTION_TYPE_ENUM",
    "DEVICE_STATUS_ENUM",
]

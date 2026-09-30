"""``sensor_readings`` — the telemetry time series.

One row per telemetry packet, whatever produced it. ``source`` records whether
the data came from real hardware, the development simulator, or a manual entry,
and it is never rewritten: simulated data must stay distinguishable from real
device data forever, which is what makes the charts trustworthy.

Why a single wide table rather than one table per sensor: the ESP32 sends all of
its sensors in one packet, the dashboard reads them together, and a wide row
keeps a hive's timeline contiguous instead of requiring five-way joins.

Retention: nothing is deleted automatically. The composite indexes below
(``hive_id``+``timestamp``, ``device_id``+``timestamp``) are what any future
down-sampling or partition-by-month job will scan, so the architecture is ready
for a retention policy without one being enabled now.
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
    Numeric,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, UUID_TYPE
from app.models.enums import TelemetrySource

TELEMETRY_SOURCE_ENUM = SAEnum(
    TelemetrySource,
    name="telemetry_source",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)

#: Global data-validity bounds. These are sensor sanity limits — the kind of
#: range a broken probe or a malformed packet falls outside — and deliberately
#: NOT disease, health or yield thresholds. Nothing in this phase interprets a
#: reading; it only stores what was measured and rejects what cannot be true.
VALID_RANGES: dict[str, tuple[float, float]] = {
    "temperature": (-20.0, 80.0),  # °C
    "humidity": (0.0, 100.0),  # %
    "weight": (0.0, 1000.0),  # kg
    "vibration": (0.0, 50.0),  # g
    "acoustic_level": (0.0, 120.0),  # dB (relative activity level)
    "battery_level": (0.0, 100.0),  # %
    "signal_strength": (-140.0, 0.0),  # dBm
}


class SensorReading(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One telemetry packet from one device."""

    __tablename__ = "sensor_readings"

    # -- Provenance ----------------------------------------------------------
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("iot_devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hive_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("hives.id", ondelete="CASCADE"), nullable=False, index=True
    )
    beekeeper_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("beekeepers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner at the time of the reading — the scope every history query "
        "filters on.",
    )

    # -- Time -----------------------------------------------------------------
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="Device-supplied measurement time (UTC). Kept separate from "
        "created_at: a device may buffer and upload later.",
    )

    # -- Measurements (all optional: a device may not carry every sensor) -----
    temperature: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    humidity: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    weight: Mapped[float | None] = mapped_column(Numeric(9, 3), nullable=True)
    vibration: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    acoustic_level: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    battery_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    signal_strength: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # -- Provenance (continued) ----------------------------------------------
    source: Mapped[TelemetrySource] = mapped_column(
        TELEMETRY_SOURCE_ENUM,
        nullable=False,
        default=TelemetrySource.REAL_DEVICE,
        server_default=TelemetrySource.REAL_DEVICE.value,
    )

    __table_args__ = (
        # A device cannot report two different packets for the same instant.
        # This is also what makes re-delivery of an MQTT QoS-1 message (or a
        # retried HTTP post) idempotent instead of duplicating the sample.
        UniqueConstraint("device_id", "timestamp", name="uq_sensor_readings_device_timestamp"),
        CheckConstraint(
            "temperature IS NULL OR (temperature >= -20 AND temperature <= 80)",
            name="reading_temperature_range",
        ),
        CheckConstraint(
            "humidity IS NULL OR (humidity >= 0 AND humidity <= 100)",
            name="reading_humidity_range",
        ),
        CheckConstraint("weight IS NULL OR weight >= 0", name="reading_weight_non_negative"),
        CheckConstraint("vibration IS NULL OR vibration >= 0", name="reading_vibration_non_negative"),
        CheckConstraint(
            "acoustic_level IS NULL OR acoustic_level >= 0", name="reading_acoustic_non_negative"
        ),
        CheckConstraint(
            "battery_level IS NULL OR (battery_level >= 0 AND battery_level <= 100)",
            name="reading_battery_range",
        ),
        CheckConstraint(
            "signal_strength IS NULL OR (signal_strength >= -140 AND signal_strength <= 0)",
            name="reading_signal_range",
        ),
        # The two access shapes the dashboard actually uses, plus the owner
        # scope used by "my hive history".
        Index("ix_sensor_readings_hive_timestamp", "hive_id", "timestamp"),
        Index("ix_sensor_readings_device_timestamp", "device_id", "timestamp"),
        Index("ix_sensor_readings_beekeeper_timestamp", "beekeeper_id", "timestamp"),
    )

    device: Mapped["IotDevice"] = relationship(back_populates="readings")  # noqa: F821
    hive: Mapped["Hive"] = relationship(back_populates="readings")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SensorReading {self.timestamp:%Y-%m-%d %H:%M} source={self.source}>"


__all__ = ["SensorReading", "TELEMETRY_SOURCE_ENUM", "VALID_RANGES", "func"]

"""``sensor_configs`` — which sensors a device carries, and how they behave.

One row per sensor type per device. The rows are created with the device (the
five sensors an ESP32 hive node ships with) and can then be tuned: disabled,
renamed, given a different sampling interval, or constrained to a narrower valid
range than the global default.

The configured range is used when validating incoming telemetry, so a beekeeper
with a different weight sensor can widen the accepted band without a code
change — while the global bounds in ``app/services/telemetry_service.py`` stay
in force as a hard sanity limit.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Enum as SAEnum,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, UUID_TYPE
from app.models.enums import SensorType

SENSOR_TYPE_ENUM = SAEnum(
    SensorType,
    name="sensor_type",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)

#: (type, display name, unit, sampling interval in seconds) for the sensor set
#: an ESP32 hive node carries. Used to seed a new device's configuration.
DEFAULT_SENSOR_SPECS: tuple[tuple[SensorType, str, str, int], ...] = (
    (SensorType.TEMPERATURE, "Hive temperature", "°C", 300),
    (SensorType.HUMIDITY, "Hive humidity", "%", 300),
    (SensorType.WEIGHT, "Hive weight", "kg", 900),
    (SensorType.VIBRATION, "Vibration", "g", 120),
    (SensorType.ACOUSTIC, "Acoustic activity", "dB", 300),
)


class SensorConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configuration for one sensor on one device."""

    __tablename__ = "sensor_configs"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("iot_devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sensor_type: Mapped[SensorType] = mapped_column(SENSOR_TYPE_ENUM, nullable=False)
    sensor_name: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sampling_interval: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=300,
        server_default="300",
        doc="Expected seconds between readings. Informational for the dashboard; "
        "the device ultimately decides its own cadence.",
    )
    min_valid_value: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    max_valid_value: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)

    __table_args__ = (
        UniqueConstraint("device_id", "sensor_type", name="uq_sensor_configs_device_type"),
        CheckConstraint("sampling_interval >= 1", name="sensor_sampling_interval_min"),
        CheckConstraint(
            "min_valid_value IS NULL OR max_valid_value IS NULL OR min_valid_value < max_valid_value",
            name="sensor_valid_range_order",
        ),
    )

    device: Mapped["IotDevice"] = relationship(back_populates="sensors")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SensorConfig {self.sensor_type} enabled={self.enabled}>"


__all__ = ["SensorConfig", "SENSOR_TYPE_ENUM", "DEFAULT_SENSOR_SPECS"]

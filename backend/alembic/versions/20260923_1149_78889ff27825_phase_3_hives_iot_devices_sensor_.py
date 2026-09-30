"""phase 3: hives, iot devices, sensor configs and readings

Revision ID: 78889ff27825
Revises: c71dce65bc61
Create Date: 2026-09-23 11:49:55.599021+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '78889ff27825'
down_revision: Union[str, None] = 'c71dce65bc61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: PostgreSQL enum types introduced by this migration. Each is created once
#: below and referenced by the tables with ``create_type=False``, so a
#: repeated upgrade cannot attempt a second ``CREATE TYPE``.
queen_status_enum = postgresql.ENUM(
    "UNKNOWN",
    "PRESENT",
    "ABSENT",
    "UNDER_OBSERVATION",
    name="queen_status",
    create_type=False,
)
colony_strength_enum = postgresql.ENUM(
    "UNKNOWN",
    "WEAK",
    "MODERATE",
    "STRONG",
    name="colony_strength",
    create_type=False,
)
hive_status_enum = postgresql.ENUM(
    "ACTIVE",
    "INACTIVE",
    "MAINTENANCE",
    "REMOVED",
    name="hive_status",
    create_type=False,
)
device_type_enum = postgresql.ENUM(
    "ESP32",
    "ESP32_GATEWAY",
    "LORA_NODE",
    "OTHER",
    name="device_type",
    create_type=False,
)
connection_type_enum = postgresql.ENUM(
    "WIFI",
    "LORA",
    "MQTT",
    "LORA_MQTT",
    "CELLULAR",
    name="connection_type",
    create_type=False,
)
device_status_enum = postgresql.ENUM(
    "ONLINE",
    "OFFLINE",
    "WARNING",
    "MAINTENANCE",
    name="device_status",
    create_type=False,
)
sensor_type_enum = postgresql.ENUM(
    "TEMPERATURE",
    "HUMIDITY",
    "WEIGHT",
    "VIBRATION",
    "ACOUSTIC",
    "BATTERY",
    name="sensor_type",
    create_type=False,
)
telemetry_source_enum = postgresql.ENUM(
    "REAL_DEVICE",
    "SIMULATOR",
    "MANUAL",
    name="telemetry_source",
    create_type=False,
)

ALL_ENUMS = (
    queen_status_enum,
    colony_strength_enum,
    hive_status_enum,
    device_type_enum,
    connection_type_enum,
    device_status_enum,
    sensor_type_enum,
    telemetry_source_enum,
)

def upgrade() -> None:
    # Enum types first: the tables below reference them.
    for enum_type in ALL_ENUMS:
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table('hives',
    sa.Column('hive_code', sa.String(length=40), nullable=False),
    sa.Column('beekeeper_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
    sa.Column('cluster_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=True),
    sa.Column('bee_species', sa.String(length=80), nullable=True),
    sa.Column('queen_status', queen_status_enum, server_default='UNKNOWN', nullable=False),
    sa.Column('colony_strength', colony_strength_enum, server_default='UNKNOWN', nullable=False),
    sa.Column('installation_date', sa.Date(), nullable=True),
    sa.Column('village', sa.String(length=120), nullable=True),
    sa.Column('mandal', sa.String(length=120), nullable=True),
    sa.Column('district', sa.String(length=80), nullable=True),
    sa.Column('state', sa.String(length=80), nullable=True),
    sa.Column('pincode', sa.String(length=10), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('status', hive_status_enum, server_default='ACTIVE', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$'", name=op.f('ck_hives_hive_pincode_format')),
    sa.CheckConstraint('bee_species IS NULL OR length(bee_species) >= 2', name=op.f('ck_hives_hive_bee_species_min_length')),
    sa.CheckConstraint('latitude IS NULL OR (latitude >= -90 AND latitude <= 90)', name=op.f('ck_hives_hive_latitude_range')),
    sa.CheckConstraint('longitude IS NULL OR (longitude >= -180 AND longitude <= 180)', name=op.f('ck_hives_hive_longitude_range')),
    sa.ForeignKeyConstraint(['beekeeper_id'], ['beekeepers.id'], name=op.f('fk_hives_beekeeper_id_beekeepers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['cluster_id'], ['kvic_clusters.id'], name=op.f('fk_hives_cluster_id_kvic_clusters'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hives'))
    )
    op.create_index(op.f('ix_hives_beekeeper_id'), 'hives', ['beekeeper_id'], unique=False)
    op.create_index('ix_hives_beekeeper_status', 'hives', ['beekeeper_id', 'status'], unique=False)
    op.create_index(op.f('ix_hives_cluster_id'), 'hives', ['cluster_id'], unique=False)
    op.create_index('ix_hives_cluster_status', 'hives', ['cluster_id', 'status'], unique=False)
    op.create_index(op.f('ix_hives_district'), 'hives', ['district'], unique=False)
    op.create_index(op.f('ix_hives_hive_code'), 'hives', ['hive_code'], unique=True)
    op.create_table('iot_devices',
    sa.Column('device_id', sa.String(length=40), nullable=False),
    sa.Column('device_name', sa.String(length=120), nullable=False),
    sa.Column('hive_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
    sa.Column('beekeeper_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
    sa.Column('device_type', device_type_enum, server_default='ESP32', nullable=False),
    sa.Column('firmware_version', sa.String(length=40), nullable=True),
    sa.Column('connection_type', connection_type_enum, server_default='MQTT', nullable=False),
    sa.Column('mqtt_topic', sa.String(length=180), nullable=True),
    sa.Column('status', device_status_enum, server_default='OFFLINE', nullable=False),
    sa.Column('battery_level', sa.SmallInteger(), nullable=True),
    sa.Column('signal_strength', sa.SmallInteger(), nullable=True),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
    sa.Column('installed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('battery_level IS NULL OR (battery_level >= 0 AND battery_level <= 100)', name=op.f('ck_iot_devices_device_battery_range')),
    sa.CheckConstraint('length(device_id) >= 4', name=op.f('ck_iot_devices_device_id_min_length')),
    sa.CheckConstraint('signal_strength IS NULL OR (signal_strength >= -140 AND signal_strength <= 0)', name=op.f('ck_iot_devices_device_signal_range')),
    sa.ForeignKeyConstraint(['beekeeper_id'], ['beekeepers.id'], name=op.f('fk_iot_devices_beekeeper_id_beekeepers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['hive_id'], ['hives.id'], name=op.f('fk_iot_devices_hive_id_hives'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_iot_devices'))
    )
    op.create_index(op.f('ix_iot_devices_beekeeper_id'), 'iot_devices', ['beekeeper_id'], unique=False)
    op.create_index('ix_iot_devices_beekeeper_status', 'iot_devices', ['beekeeper_id', 'status'], unique=False)
    op.create_index(op.f('ix_iot_devices_device_id'), 'iot_devices', ['device_id'], unique=True)
    op.create_index(op.f('ix_iot_devices_hive_id'), 'iot_devices', ['hive_id'], unique=False)
    op.create_index('ix_iot_devices_hive_status', 'iot_devices', ['hive_id', 'status'], unique=False)
    op.create_index(op.f('ix_iot_devices_last_seen'), 'iot_devices', ['last_seen'], unique=False)
    op.create_table('sensor_configs',
    sa.Column('device_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
    sa.Column('sensor_type', sensor_type_enum, nullable=False),
    sa.Column('sensor_name', sa.String(length=80), nullable=False),
    sa.Column('unit', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sampling_interval', sa.Integer(), server_default='300', nullable=False),
    sa.Column('min_valid_value', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('max_valid_value', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('min_valid_value IS NULL OR max_valid_value IS NULL OR min_valid_value < max_valid_value', name=op.f('ck_sensor_configs_sensor_valid_range_order')),
    sa.CheckConstraint('sampling_interval >= 1', name=op.f('ck_sensor_configs_sensor_sampling_interval_min')),
    sa.ForeignKeyConstraint(['device_id'], ['iot_devices.id'], name=op.f('fk_sensor_configs_device_id_iot_devices'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sensor_configs')),
    sa.UniqueConstraint('device_id', 'sensor_type', name='uq_sensor_configs_device_type')
    )
    op.create_index(op.f('ix_sensor_configs_device_id'), 'sensor_configs', ['device_id'], unique=False)
    op.create_table('sensor_readings',
    sa.Column('device_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
    sa.Column('hive_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
    sa.Column('beekeeper_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('temperature', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('humidity', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('weight', sa.Numeric(precision=9, scale=3), nullable=True),
    sa.Column('vibration', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('acoustic_level', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('battery_level', sa.SmallInteger(), nullable=True),
    sa.Column('signal_strength', sa.SmallInteger(), nullable=True),
    sa.Column('source', telemetry_source_enum, server_default='REAL_DEVICE', nullable=False),
    sa.Column('id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('acoustic_level IS NULL OR acoustic_level >= 0', name=op.f('ck_sensor_readings_reading_acoustic_non_negative')),
    sa.CheckConstraint('battery_level IS NULL OR (battery_level >= 0 AND battery_level <= 100)', name=op.f('ck_sensor_readings_reading_battery_range')),
    sa.CheckConstraint('humidity IS NULL OR (humidity >= 0 AND humidity <= 100)', name=op.f('ck_sensor_readings_reading_humidity_range')),
    sa.CheckConstraint('signal_strength IS NULL OR (signal_strength >= -140 AND signal_strength <= 0)', name=op.f('ck_sensor_readings_reading_signal_range')),
    sa.CheckConstraint('temperature IS NULL OR (temperature >= -20 AND temperature <= 80)', name=op.f('ck_sensor_readings_reading_temperature_range')),
    sa.CheckConstraint('vibration IS NULL OR vibration >= 0', name=op.f('ck_sensor_readings_reading_vibration_non_negative')),
    sa.CheckConstraint('weight IS NULL OR weight >= 0', name=op.f('ck_sensor_readings_reading_weight_non_negative')),
    sa.ForeignKeyConstraint(['beekeeper_id'], ['beekeepers.id'], name=op.f('fk_sensor_readings_beekeeper_id_beekeepers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['device_id'], ['iot_devices.id'], name=op.f('fk_sensor_readings_device_id_iot_devices'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['hive_id'], ['hives.id'], name=op.f('fk_sensor_readings_hive_id_hives'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sensor_readings')),
    sa.UniqueConstraint('device_id', 'timestamp', name='uq_sensor_readings_device_timestamp')
    )
    op.create_index(op.f('ix_sensor_readings_beekeeper_id'), 'sensor_readings', ['beekeeper_id'], unique=False)
    op.create_index('ix_sensor_readings_beekeeper_timestamp', 'sensor_readings', ['beekeeper_id', 'timestamp'], unique=False)
    op.create_index(op.f('ix_sensor_readings_device_id'), 'sensor_readings', ['device_id'], unique=False)
    op.create_index('ix_sensor_readings_device_timestamp', 'sensor_readings', ['device_id', 'timestamp'], unique=False)
    op.create_index(op.f('ix_sensor_readings_hive_id'), 'sensor_readings', ['hive_id'], unique=False)
    op.create_index('ix_sensor_readings_hive_timestamp', 'sensor_readings', ['hive_id', 'timestamp'], unique=False)
    op.create_index(op.f('ix_sensor_readings_timestamp'), 'sensor_readings', ['timestamp'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_sensor_readings_timestamp'), table_name='sensor_readings')
    op.drop_index('ix_sensor_readings_hive_timestamp', table_name='sensor_readings')
    op.drop_index(op.f('ix_sensor_readings_hive_id'), table_name='sensor_readings')
    op.drop_index('ix_sensor_readings_device_timestamp', table_name='sensor_readings')
    op.drop_index(op.f('ix_sensor_readings_device_id'), table_name='sensor_readings')
    op.drop_index('ix_sensor_readings_beekeeper_timestamp', table_name='sensor_readings')
    op.drop_index(op.f('ix_sensor_readings_beekeeper_id'), table_name='sensor_readings')
    op.drop_table('sensor_readings')
    op.drop_index(op.f('ix_sensor_configs_device_id'), table_name='sensor_configs')
    op.drop_table('sensor_configs')
    op.drop_index(op.f('ix_iot_devices_last_seen'), table_name='iot_devices')
    op.drop_index('ix_iot_devices_hive_status', table_name='iot_devices')
    op.drop_index(op.f('ix_iot_devices_hive_id'), table_name='iot_devices')
    op.drop_index(op.f('ix_iot_devices_device_id'), table_name='iot_devices')
    op.drop_index('ix_iot_devices_beekeeper_status', table_name='iot_devices')
    op.drop_index(op.f('ix_iot_devices_beekeeper_id'), table_name='iot_devices')
    op.drop_table('iot_devices')
    op.drop_index(op.f('ix_hives_hive_code'), table_name='hives')
    op.drop_index(op.f('ix_hives_district'), table_name='hives')
    op.drop_index('ix_hives_cluster_status', table_name='hives')
    op.drop_index(op.f('ix_hives_cluster_id'), table_name='hives')
    op.drop_index('ix_hives_beekeeper_status', table_name='hives')
    op.drop_index(op.f('ix_hives_beekeeper_id'), table_name='hives')
    op.drop_table('hives')

    # ``drop_table`` never removes a PostgreSQL enum type; without this a later
    # ``upgrade`` would fail with "type ... already exists".
    for enum_type in reversed(ALL_ENUMS):
        enum_type.drop(op.get_bind(), checkfirst=True)

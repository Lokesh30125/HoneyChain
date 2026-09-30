"""phase 4: ai analyses and ai alerts

Revision ID: a77f6c38aaff
Revises: 78889ff27825
Create Date: 2026-09-23 15:29:25.060320+00:00

Creates the two AI-owned tables:

* ``hive_ai_analyses`` — one stored assessment per analysis run, with the
  provenance columns (window, sample count, newest reading, source, model
  version, data quality) that make an old assessment readable months later;
* ``ai_alerts`` — the signals raised by those analyses, de-duplicated in the
  service layer rather than by a unique constraint (a partial index on ``status``
  would not work on the SQLite fallback the test suite uses).

Eight PostgreSQL enum types are created explicitly and dropped on downgrade,
matching the Phase 2/3 pattern: ``drop_table`` does not remove a type, so without
this a later ``upgrade`` would fail with "type ... already exists".
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a77f6c38aaff'
down_revision: Union[str, None] = '78889ff27825'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: PostgreSQL enum types introduced by this migration. Each is created once
#: below and referenced by the tables with ``create_type=False``, so a repeated
#: upgrade cannot attempt a second ``CREATE TYPE``.
health_status_enum = postgresql.ENUM(
    "HEALTHY",
    "ATTENTION",
    "AT_RISK",
    "CRITICAL",
    "INSUFFICIENT_DATA",
    name="ai_health_status",
    create_type=False,
)
risk_level_enum = postgresql.ENUM(
    "LOW",
    "MODERATE",
    "HIGH",
    "UNKNOWN",
    name="ai_risk_level",
    create_type=False,
)
trend_enum = postgresql.ENUM(
    "RISING",
    "STABLE",
    "FALLING",
    "UNKNOWN",
    name="ai_trend",
    create_type=False,
)
data_quality_enum = postgresql.ENUM(
    "GOOD",
    "LIMITED",
    "INSUFFICIENT",
    name="ai_data_quality",
    create_type=False,
)
analysis_source_enum = postgresql.ENUM(
    "REAL_DEVICE",
    "SIMULATOR",
    "MIXED",
    "MANUAL",
    "NO_DATA",
    name="ai_analysis_source",
    create_type=False,
)
alert_type_enum = postgresql.ENUM(
    "HEALTH_CRITICAL",
    "HEALTH_AT_RISK",
    "DISEASE_RISK_HIGH",
    "SWARMING_RISK_HIGH",
    "TEMPERATURE_ANOMALY",
    "HUMIDITY_ANOMALY",
    "WEIGHT_TREND_ANOMALY",
    "ACTIVITY_ANOMALY",
    "DATA_STALE",
    name="ai_alert_type",
    create_type=False,
)
alert_severity_enum = postgresql.ENUM(
    "INFO",
    "WARNING",
    "CRITICAL",
    name="ai_alert_severity",
    create_type=False,
)
alert_status_enum = postgresql.ENUM(
    "OPEN",
    "ACKNOWLEDGED",
    "RESOLVED",
    name="ai_alert_status",
    create_type=False,
)

ALL_ENUMS = (
    health_status_enum,
    risk_level_enum,
    trend_enum,
    data_quality_enum,
    analysis_source_enum,
    alert_type_enum,
    alert_severity_enum,
    alert_status_enum,
)


def upgrade() -> None:
    # Enum types first: the tables below reference them.
    for enum_type in ALL_ENUMS:
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'hive_ai_analyses',
        sa.Column('hive_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
        sa.Column('beekeeper_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sample_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('newest_reading_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_quality', data_quality_enum, server_default='INSUFFICIENT', nullable=False),
        sa.Column('analysis_source', analysis_source_enum, server_default='NO_DATA', nullable=False),
        sa.Column('model_type', sa.String(length=60), nullable=False),
        sa.Column('model_version', sa.String(length=20), nullable=False),
        sa.Column('health_score', sa.SmallInteger(), nullable=True),
        sa.Column('health_status', health_status_enum, server_default='INSUFFICIENT_DATA', nullable=False),
        sa.Column('health_confidence', sa.SmallInteger(), nullable=True),
        sa.Column('health_trend', trend_enum, server_default='UNKNOWN', nullable=False),
        sa.Column('disease_risk_score', sa.SmallInteger(), nullable=True),
        sa.Column('disease_risk_level', risk_level_enum, server_default='UNKNOWN', nullable=False),
        sa.Column('disease_confidence', sa.SmallInteger(), nullable=True),
        sa.Column('swarming_risk_score', sa.SmallInteger(), nullable=True),
        sa.Column('swarming_risk_level', risk_level_enum, server_default='UNKNOWN', nullable=False),
        sa.Column('swarming_confidence', sa.SmallInteger(), nullable=True),
        sa.Column('predicted_yield_kg', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('yield_confidence', sa.SmallInteger(), nullable=True),
        sa.Column('yield_trend', trend_enum, server_default='UNKNOWN', nullable=False),
        sa.Column('yield_period_days', sa.SmallInteger(), nullable=True),
        sa.Column('overall_confidence', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('disease_risk_score IS NULL OR (disease_risk_score >= 0 AND disease_risk_score <= 100)', name=op.f('ck_hive_ai_analyses_ai_analysis_disease_score_range')),
        sa.CheckConstraint('health_score IS NULL OR (health_score >= 0 AND health_score <= 100)', name=op.f('ck_hive_ai_analyses_ai_analysis_health_score_range')),
        sa.CheckConstraint('overall_confidence >= 0 AND overall_confidence <= 100', name=op.f('ck_hive_ai_analyses_ai_analysis_confidence_range')),
        sa.CheckConstraint('sample_count >= 0', name=op.f('ck_hive_ai_analyses_ai_analysis_sample_count_non_negative')),
        sa.CheckConstraint('swarming_risk_score IS NULL OR (swarming_risk_score >= 0 AND swarming_risk_score <= 100)', name=op.f('ck_hive_ai_analyses_ai_analysis_swarming_score_range')),
        sa.ForeignKeyConstraint(['beekeeper_id'], ['beekeepers.id'], name=op.f('fk_hive_ai_analyses_beekeeper_id_beekeepers'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['hive_id'], ['hives.id'], name=op.f('fk_hive_ai_analyses_hive_id_hives'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_hive_ai_analyses')),
    )
    op.create_index('ix_ai_analyses_beekeeper_analyzed', 'hive_ai_analyses', ['beekeeper_id', 'analyzed_at'], unique=False)
    op.create_index('ix_ai_analyses_hive_analyzed', 'hive_ai_analyses', ['hive_id', 'analyzed_at'], unique=False)
    op.create_index('ix_ai_analyses_status_analyzed', 'hive_ai_analyses', ['health_status', 'analyzed_at'], unique=False)
    op.create_index(op.f('ix_hive_ai_analyses_beekeeper_id'), 'hive_ai_analyses', ['beekeeper_id'], unique=False)
    op.create_index(op.f('ix_hive_ai_analyses_hive_id'), 'hive_ai_analyses', ['hive_id'], unique=False)

    op.create_table(
        'ai_alerts',
        sa.Column('hive_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
        sa.Column('beekeeper_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=False),
        sa.Column('analysis_id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=True),
        sa.Column('alert_type', alert_type_enum, nullable=False),
        sa.Column('severity', alert_severity_enum, server_default='WARNING', nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('metric', sa.String(length=60), nullable=True),
        sa.Column('dedupe_key', sa.String(length=140), nullable=False),
        sa.Column('occurrences', sa.Integer(), server_default='1', nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', alert_status_enum, server_default='OPEN', nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), nullable=True),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('id', sa.UUID().with_variant(sa.String(length=36), 'sqlite'), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('occurrences >= 1', name=op.f('ck_ai_alerts_ai_alert_occurrences_min')),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], name=op.f('fk_ai_alerts_acknowledged_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['analysis_id'], ['hive_ai_analyses.id'], name=op.f('fk_ai_alerts_analysis_id_hive_ai_analyses'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['beekeeper_id'], ['beekeepers.id'], name=op.f('fk_ai_alerts_beekeeper_id_beekeepers'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['hive_id'], ['hives.id'], name=op.f('fk_ai_alerts_hive_id_hives'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_alerts')),
    )
    op.create_index(op.f('ix_ai_alerts_analysis_id'), 'ai_alerts', ['analysis_id'], unique=False)
    op.create_index(op.f('ix_ai_alerts_beekeeper_id'), 'ai_alerts', ['beekeeper_id'], unique=False)
    op.create_index('ix_ai_alerts_beekeeper_status', 'ai_alerts', ['beekeeper_id', 'status'], unique=False)
    op.create_index('ix_ai_alerts_created', 'ai_alerts', ['created_at'], unique=False)
    op.create_index('ix_ai_alerts_dedupe', 'ai_alerts', ['dedupe_key', 'status'], unique=False)
    op.create_index(op.f('ix_ai_alerts_dedupe_key'), 'ai_alerts', ['dedupe_key'], unique=False)
    op.create_index(op.f('ix_ai_alerts_hive_id'), 'ai_alerts', ['hive_id'], unique=False)
    op.create_index('ix_ai_alerts_hive_status', 'ai_alerts', ['hive_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ai_alerts_hive_status', table_name='ai_alerts')
    op.drop_index(op.f('ix_ai_alerts_hive_id'), table_name='ai_alerts')
    op.drop_index(op.f('ix_ai_alerts_dedupe_key'), table_name='ai_alerts')
    op.drop_index('ix_ai_alerts_dedupe', table_name='ai_alerts')
    op.drop_index('ix_ai_alerts_created', table_name='ai_alerts')
    op.drop_index('ix_ai_alerts_beekeeper_status', table_name='ai_alerts')
    op.drop_index(op.f('ix_ai_alerts_beekeeper_id'), table_name='ai_alerts')
    op.drop_index(op.f('ix_ai_alerts_analysis_id'), table_name='ai_alerts')
    op.drop_table('ai_alerts')

    op.drop_index(op.f('ix_hive_ai_analyses_hive_id'), table_name='hive_ai_analyses')
    op.drop_index(op.f('ix_hive_ai_analyses_beekeeper_id'), table_name='hive_ai_analyses')
    op.drop_index('ix_ai_analyses_status_analyzed', table_name='hive_ai_analyses')
    op.drop_index('ix_ai_analyses_hive_analyzed', table_name='hive_ai_analyses')
    op.drop_index('ix_ai_analyses_beekeeper_analyzed', table_name='hive_ai_analyses')
    op.drop_table('hive_ai_analyses')

    # ``drop_table`` never removes a PostgreSQL enum type; without this a later
    # ``upgrade`` would fail with "type ... already exists".
    for enum_type in reversed(ALL_ENUMS):
        enum_type.drop(op.get_bind(), checkfirst=True)

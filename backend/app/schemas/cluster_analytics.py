"""Response shapes for the cluster view.

These models describe a *view*, not a table: every field is counted or read from
rows that belong to other entities (beekeepers, hives, devices, readings,
analyses). Nothing here is stored, which is why there is no matching ``INSERT``
anywhere in the codebase.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AiAnalysisSource, AiDataQuality, AiHealthStatus, AiRiskLevel
from app.schemas.iot import ReadingSnapshot


class ClusterIdentity(BaseModel):
    """The cluster itself, as the view names it."""

    id: uuid.UUID
    cluster_code: str
    cluster_name: str
    district: str
    state: str
    is_active: bool
    coordinator_name: str | None = None
    coordinator_phone: str | None = None


class ClusterBeekeeperCounts(BaseModel):
    total: int = 0
    verified: int = 0
    pending: int = 0
    under_review: int = 0
    suspended: int = 0
    rejected: int = 0
    by_verification_status: dict[str, int] = Field(default_factory=dict)


class ClusterHiveCounts(BaseModel):
    total: int = 0
    active: int = 0
    inactive: int = 0
    maintenance: int = 0
    removed: int = 0
    with_device: int = 0
    without_device: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)


class ClusterDeviceCounts(BaseModel):
    total: int = 0
    online: int = 0
    offline: int = 0
    warning: int = 0
    maintenance: int = 0
    sensors_active: int = 0
    last_seen_at: datetime | None = None
    offline_threshold_seconds: int | None = None


class ClusterTelemetryCounts(BaseModel):
    readings_last_24h: int = 0
    latest_reading_at: datetime | None = None
    hives_with_telemetry: int = 0
    hives_without_telemetry: int = 0


class ClusterAiCounts(BaseModel):
    analysed_hives: int = 0
    hives_without_analysis: int = 0
    health: dict[str, int] = Field(default_factory=dict)
    disease_risk: dict[str, int] = Field(default_factory=dict)
    swarming_risk: dict[str, int] = Field(default_factory=dict)
    yield_projection: dict = Field(default_factory=dict)
    open_alerts: int = 0
    alerts_by_severity: dict[str, int] = Field(default_factory=dict)
    model: dict = Field(default_factory=dict)


class ClusterOverview(BaseModel):
    """``GET /api/v1/clusters/{id}/summary`` — the cluster dashboard's numbers."""

    cluster: ClusterIdentity
    beekeepers: ClusterBeekeeperCounts
    hives: ClusterHiveCounts
    devices: ClusterDeviceCounts
    telemetry: ClusterTelemetryCounts
    ai: ClusterAiCounts
    generated_at: datetime


class ClusterAiHiveRow(BaseModel):
    """One hive's AI state inside a cluster."""

    hive_id: uuid.UUID
    hive_code: str
    status: str
    analyzed: bool = False
    analyzed_at: datetime | None = None
    health_score: int | None = None
    health_status: AiHealthStatus | None = None
    health_confidence: int | None = None
    disease_risk_level: AiRiskLevel | None = None
    disease_risk_score: int | None = None
    swarming_risk_level: AiRiskLevel | None = None
    swarming_risk_score: int | None = None
    predicted_yield_kg: float | None = None
    yield_period_days: int | None = None
    data_quality: AiDataQuality | None = None
    analysis_source: AiAnalysisSource | None = None
    sample_count: int = 0


class ClusterAiState(BaseModel):
    """``GET /api/v1/clusters/{id}/ai`` — aggregate AI state plus per-hive rows."""

    summary: dict = Field(default_factory=dict)
    hives: list[ClusterAiHiveRow] = Field(default_factory=list)


class ClusterLatestTelemetry(BaseModel):
    """``GET /api/v1/clusters/{id}/telemetry/latest`` — newest packet in the cluster.

    The chain is printed explicitly (device → hive → beekeeper) because it *is*
    the relationship the cluster view is built on.
    """

    has_data: bool = False
    hive_count: int = 0
    hives_reporting: int = 0
    timestamp: datetime | None = None
    hive_code: str | None = None
    device_id: str | None = None
    device_status: str | None = None
    beekeeper_code: str | None = None
    beekeeper_name: str | None = None
    reading: ReadingSnapshot | None = None


__all__ = [
    "ClusterAiCounts",
    "ClusterAiHiveRow",
    "ClusterAiState",
    "ClusterBeekeeperCounts",
    "ClusterDeviceCounts",
    "ClusterHiveCounts",
    "ClusterIdentity",
    "ClusterLatestTelemetry",
    "ClusterOverview",
    "ClusterTelemetryCounts",
]

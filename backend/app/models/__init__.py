"""Model package — importing this module registers every table on ``Base.metadata``.

Alembic's ``env.py`` and the test fixtures import from here so autogenerate and
``metadata.create_all`` always see the complete schema. Later phases append
their models to the list below; no other file needs to change.
"""

from app.core.database import Base
from app.models.ai_alert import AiAlert
from app.models.ai_analysis import HiveAiAnalysis
from app.models.audit_log import AuditLog
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.beekeeper import Beekeeper
from app.models.blockchain import BlockchainEvent
from app.models.beekeeper_verification_history import BeekeeperVerificationHistory
from app.models.document_sequence import DocumentSequence, district_code
from app.models.enums import (
    BATCH_STATUS_TRANSITIONS,
    ROLE_HOME_ROUTES,
    AccountStatus,
    AiAlertSeverity,
    BatchStage,
    BatchStatus,
    CollectionStatus,
    CollectionUnit,
    DistributionStatus,
    AiAlertStatus,
    AiAlertType,
    AiAnalysisSource,
    AiDataQuality,
    AiHealthStatus,
    AiRiskLevel,
    AiTrend,
    AuditAction,
    ColonyStrength,
    ConnectionType,
    DeviceStatus,
    DeviceType,
    FacilityStatus,
    HiveStatus,
    LabMeasureUnit,
    LabParameterCode,
    LabParameterStatus,
    LabResult,
    LabTestStatus,
    PackageStatus,
    PackagingStatus,
    PackagingType,
    ProcessingStatus,
    ProcessingType,
    QueenStatus,
    SensorType,
    TelemetrySource,
    TokenType,
    UserRole,
    VerificationStatus,
)
from app.models.hive import Hive
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection, HoneyCollectionHive
from app.models.iot_device import IotDevice
from app.models.kvic_cluster import KvicCluster
from app.models.distribution import Distribution
from app.models.laboratory import LabParameter, Laboratory, LabTest, LabTestResult
from app.models.packaging import HoneyPackage, PackagingRun, PackagingUnit
from app.models.processing import HoneyProcessing, ProcessingUnit
from app.models.refresh_token import RefreshToken
from app.models.sensor_config import SensorConfig
from app.models.sensor_reading import SensorReading
from app.models.user import User
from app.models.user_profile import UserProfile

__all__ = [
    # Infrastructure
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    # Identity
    "User",
    "UserProfile",
    "RefreshToken",
    "AuditLog",
    # Beekeeping
    "Beekeeper",
    "BlockchainEvent",
    "BeekeeperVerificationHistory",
    "KvicCluster",
    "DocumentSequence",
    "district_code",
    # Hives & IoT
    "Hive",
    "IotDevice",
    "SensorConfig",
    "SensorReading",
    # AI engine
    "HiveAiAnalysis",
    "AiAlert",
    # Collections & batches (Phase 5)
    "HoneyCollection",
    "HoneyCollectionHive",
    "HoneyBatch",
    # Enumerations
    "UserRole",
    "VerificationStatus",
    "AuditAction",
    "TokenType",
    "AccountStatus",
    "ROLE_HOME_ROUTES",
    "HiveStatus",
    "QueenStatus",
    "ColonyStrength",
    "DeviceType",
    "ConnectionType",
    "DeviceStatus",
    "SensorType",
    "TelemetrySource",
    "AiHealthStatus",
    "AiRiskLevel",
    "AiTrend",
    "AiDataQuality",
    "AiAnalysisSource",
    "AiAlertType",
    "AiAlertSeverity",
    "AiAlertStatus",
    "CollectionStatus",
    "CollectionUnit",
    "BatchStatus",
    "BatchStage",
    "BATCH_STATUS_TRANSITIONS",
    "ProcessingStatus",
    "ProcessingType",
    "FacilityStatus",
    "LabTestStatus",
    "LabResult",
    "LabParameterStatus",
    "LabParameterCode",
    "LabMeasureUnit",
    "PackagingStatus",
    "PackagingType",
    "PackageStatus",
    "DistributionStatus",
    # Processing and laboratory quality (Phase 6)
    "ProcessingUnit",
    "HoneyProcessing",
    "Laboratory",
    "LabParameter",
    "LabTest",
    "LabTestResult",
    # Packaging, packages and distribution (Phase 7)
    "PackagingUnit",
    "PackagingRun",
    "HoneyPackage",
    "Distribution",
]

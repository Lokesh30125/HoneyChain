"""Pydantic request/response contracts — the API validation boundary.

Re-exported so routers and tests can import a contract from one place
(``from app.schemas import BeekeeperPublic``) without tracking which module it
lives in as the API grows.
"""

from app.schemas.admin import (
    AdminBeekeeperContext,
    AdminUserDetail,
    AdminUserStatusUpdateResponse,
    PlatformSummary,
    PlatformSummaryBeekeepers,
    PlatformSummaryClusters,
    PlatformSummaryUsers,
)
from app.schemas.audit import AuditActivitySummary, AuditLogEntry
from app.schemas.auth import (
    AuthResult,
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenMetadata,
)
from app.schemas.beekeeper import (
    BeekeeperClusterInfo,
    BeekeeperCreate,
    BeekeeperDetail,
    BeekeeperFilterOptions,
    BeekeeperListItem,
    BeekeeperOwnerInfo,
    BeekeeperPractice,
    BeekeeperPublic,
    BeekeeperRegistrationInfo,
    BeekeeperSelfUpdate,
    BeekeeperSummary,
    BeekeeperUpdate,
    VerificationChangeRequest,
    VerificationHistoryEntry,
)
from app.schemas.cluster import (
    ClusterBase,
    ClusterCreate,
    ClusterDetail,
    ClusterPublic,
    ClusterStatusUpdate,
    ClusterUpdate,
    ClusterWithCounts,
)
from app.schemas.common import (
    ApiErrorResponse,
    ApiResponse,
    ErrorDetail,
    HealthDetailResponse,
    HealthResponse,
    Meta,
    PaginationParams,
)
from app.schemas.profile import (
    BeekeeperSummaryForProfile,
    FullProfileResponse,
    ProfileLocation,
    ProfilePatch,
    ProfilePersonal,
    ProfilePublic,
    ProfileUpdate,
    UserAccountSummary,
)
from app.schemas.roles import PlatformInfoResponse, RoleInfo
from app.schemas.user import (
    AdminUserStatusUpdate,
    UserCreate,
    UserPublic,
    UserUpdate,
)

__all__ = [
    # admin
    "AdminBeekeeperContext",
    "AdminUserDetail",
    "AdminUserStatusUpdateResponse",
    "PlatformSummary",
    "PlatformSummaryBeekeepers",
    "PlatformSummaryClusters",
    "PlatformSummaryUsers",
    # audit
    "AuditActivitySummary",
    "AuditLogEntry",
    # auth
    "AuthResult",
    "LoginRequest",
    "LogoutRequest",
    "LogoutResponse",
    "MessageResponse",
    "RefreshRequest",
    "RegisterRequest",
    "TokenMetadata",
    # beekeeper
    "BeekeeperClusterInfo",
    "BeekeeperCreate",
    "BeekeeperDetail",
    "BeekeeperFilterOptions",
    "BeekeeperListItem",
    "BeekeeperOwnerInfo",
    "BeekeeperPractice",
    "BeekeeperPublic",
    "BeekeeperRegistrationInfo",
    "BeekeeperSelfUpdate",
    "BeekeeperSummary",
    "BeekeeperUpdate",
    "VerificationChangeRequest",
    "VerificationHistoryEntry",
    # cluster
    "ClusterBase",
    "ClusterCreate",
    "ClusterDetail",
    "ClusterPublic",
    "ClusterStatusUpdate",
    "ClusterUpdate",
    "ClusterWithCounts",
    # common
    "ApiErrorResponse",
    "ApiResponse",
    "ErrorDetail",
    "HealthDetailResponse",
    "HealthResponse",
    "Meta",
    "PaginationParams",
    # profile
    "BeekeeperSummaryForProfile",
    "FullProfileResponse",
    "ProfileLocation",
    "ProfilePatch",
    "ProfilePersonal",
    "ProfilePublic",
    "ProfileUpdate",
    "UserAccountSummary",
    # roles
    "PlatformInfoResponse",
    "RoleInfo",
    # user
    "AdminUserStatusUpdate",
    "UserCreate",
    "UserPublic",
    "UserUpdate",
]

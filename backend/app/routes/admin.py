"""Administrator routes — identity directory, account status and audit review.

Authorisation is declarative: the router requires ``USER_READ_ALL`` as a
baseline, and each mutating route additionally requires the narrower capability
it actually needs. Adding a KVIC-facing view later means granting a permission,
not rewriting a role check.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_permission
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserCreateResponse,
    AdminUserDetail,
    AdminUserRoleUpdate,
    AdminUserRoleUpdateResponse,
    AdminUserStatusUpdateResponse,
    PlatformSummary,
)
from app.schemas.audit import AuditActivitySummary, AuditLogEntry
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.user import AdminUserStatusUpdate, UserPublic
from app.services.admin_service import AdminService

router = APIRouter(
    prefix="/admin",
    tags=["Administration"],
    dependencies=[Depends(require_permission(Permission.USER_READ_ALL))],
)


@router.get(
    "/summary",
    response_model=ApiResponse[PlatformSummary],
    summary="Platform summary (admin only)",
    description=(
        "Account, beekeeper and cluster counts plus the implementation status of "
        "each module. Counts are aggregate queries, so an empty platform reports "
        "zeros rather than placeholder figures."
    ),
)
def platform_summary(session: Session = Depends(db_session)) -> dict:
    return ok(AdminService(session).platform_summary())


# --------------------------------------------------------------------------- #
# Identity directory
# --------------------------------------------------------------------------- #
@router.get(
    "/users",
    response_model=ApiResponse[list[UserPublic]],
    summary="List platform users (admin only)",
    description=(
        "Paginated identity directory, newest first. Search matches name, email "
        "or phone; filter by role and by account status."
    ),
)
def list_users(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Name, email or phone."),
    role: UserRole | None = Query(default=None, description="Filter by a single role."),
    is_active: bool | None = Query(default=None, description="Filter by account status."),
    is_verified: bool | None = Query(default=None, description="Filter by contact verification."),
    session: Session = Depends(db_session),
) -> dict:
    items, total = AdminService(session).list_users(
        page=pagination.page,
        page_size=pagination.page_size,
        role=role,
        is_active=is_active,
        is_verified=is_verified,
        search=search,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "/users",
    response_model=ApiResponse[AdminUserCreateResponse],
    status_code=status.HTTP_201_CREATED,
    # Two capabilities, both required: creating the account, and deciding which
    # role it holds. The service re-checks the same pair — these operations are
    # where a missing check would be privilege escalation, not a cosmetic bug.
    dependencies=[
        Depends(require_permission(Permission.ADMIN_USER_MANAGE, Permission.ADMIN_ROLE_ASSIGN))
    ],
    summary="Create an account for an operational role (admin only)",
    description=(
        "Provisions an account for any of the ten platform roles — laboratory "
        "technician, processor, collection centre, packaging unit, distributor, "
        "retailer, KVIC officer, beekeeper, consumer, or a second administrator. "
        "The account uses the platform's single authentication system: the same "
        "users table, the same password hashing, and the same POST /api/v1/auth/login. "
        "The role is stored on the account and enforced by the permission table on "
        "every request. A BEEKEEPER account is created together with its beekeeper "
        "record, which starts PENDING review. The public registration form remains "
        "limited to BEEKEEPER and CONSUMER."
    ),
)
def create_user(
    payload: AdminUserCreate,
    actor: User = Depends(require_permission(Permission.ADMIN_USER_MANAGE)),
    session: Session = Depends(db_session),
) -> dict:
    user, beekeeper_created = AdminService(session).create_user(payload, actor=actor)
    return ok(
        AdminUserCreateResponse(
            user=UserPublic.model_validate(user),
            message=(
                f"Account created as {user.role.label}"
                + ("" if user.is_active else " (inactive)")
            ),
            beekeeper_created=beekeeper_created,
        )
    )


@router.patch(
    "/users/{user_id}/role",
    response_model=ApiResponse[AdminUserRoleUpdateResponse],
    summary="Change an account's role (admin only)",
    description=(
        "Moves an account to another of the ten roles and records the change in the "
        "audit log with both the previous and the new role. Live sessions are "
        "revoked, because the account's permissions change with the role. An "
        "administrator cannot change their own role, and the last active "
        "administrator cannot be moved off ADMIN. A user can never change their own "
        "role: PATCH /api/v1/users/me rejects the field outright."
    ),
)
def update_user_role(
    user_id: uuid.UUID,
    payload: AdminUserRoleUpdate,
    actor: User = Depends(require_permission(Permission.ADMIN_ROLE_ASSIGN)),
    session: Session = Depends(db_session),
) -> dict:
    updated, previous_role, revoked = AdminService(session).set_user_role(
        user_id, role=payload.role, actor=actor, reason=payload.reason
    )
    return ok(
        AdminUserRoleUpdateResponse(
            user=UserPublic.model_validate(updated),
            previous_role=previous_role,
            message=(
                f"Role changed from {previous_role.label} to {updated.role.label}"
                if previous_role is not updated.role
                else f"Account already held the {updated.role.label} role"
            ),
            sessions_revoked=revoked,
        )
    )


@router.get(
    "/users/{user_id}",
    response_model=ApiResponse[AdminUserDetail],
    summary="Read an account (admin only)",
    description=(
        "Account details with the linked beekeeper context (if any) and the most "
        "recent audited actions on that account."
    ),
)
def read_user(
    user_id: uuid.UUID,
    session: Session = Depends(db_session),
) -> dict:
    return ok(AdminUserDetail(**AdminService(session).user_detail(user_id)))


@router.patch(
    "/users/{user_id}/status",
    response_model=ApiResponse[AdminUserStatusUpdateResponse],
    summary="Activate or deactivate an account (admin only)",
    description=(
        "Disables or re-enables sign-in for an account and records the change in "
        "the audit log. An administrator cannot deactivate their own account, "
        "and the last active administrator cannot be deactivated."
    ),
)
def update_user_status(
    user_id: uuid.UUID,
    payload: AdminUserStatusUpdate,
    actor: User = Depends(require_permission(Permission.ADMIN_USER_MANAGE)),
    session: Session = Depends(db_session),
) -> dict:
    updated = AdminService(session).set_user_active(
        user_id, is_active=payload.is_active, actor=actor, reason=payload.reason
    )
    return ok(
        AdminUserStatusUpdateResponse(
            user=UserPublic.model_validate(updated),
            message=f"Account {'activated' if payload.is_active else 'deactivated'}",
        )
    )


# --------------------------------------------------------------------------- #
# Audit review
# --------------------------------------------------------------------------- #
@router.get(
    "/audit-logs",
    response_model=ApiResponse[list[AuditLogEntry]],
    summary="Audit log (admin only)",
    description=(
        "Append-only record of platform events, newest first: registrations, "
        "sign-ins, profile edits, verification decisions, cluster changes and "
        "account status changes. Secrets and password material are never stored."
    ),
)
def list_audit_logs(
    pagination: PaginationParams = Depends(),
    action: str | None = Query(default=None, max_length=60, description="e.g. BEEKEEPER_VERIFIED"),
    entity_type: str | None = Query(default=None, max_length=60),
    entity_id: str | None = Query(default=None, max_length=64),
    user_id: uuid.UUID | None = Query(default=None, description="Actor's account id."),
    _: User = Depends(require_permission(Permission.AUDIT_READ)),
    session: Session = Depends(db_session),
) -> dict:
    items, total = AdminService(session).list_audit_logs(
        page=pagination.page,
        page_size=pagination.page_size,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/activity",
    response_model=ApiResponse[AuditActivitySummary],
    summary="Recent activity counts (admin only)",
    description="Action counts over a recent window, for the dashboard activity panel.",
)
def activity_summary(
    hours: int = Query(default=24, ge=1, le=720),
    _: User = Depends(require_permission(Permission.AUDIT_READ)),
    session: Session = Depends(db_session),
) -> dict:
    return ok(AuditActivitySummary(**AdminService(session).activity_summary(hours=hours)))

"""Public metadata routes.

The frontend needs the authoritative role list *before* a user can authenticate
(registration, dashboards, docs). Serving it from the backend avoids a second
hard-coded copy in the client that could drift out of sync.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.enums import ROLE_HOME_ROUTES, UserRole
from app.schemas.common import ApiResponse, ok
from app.schemas.roles import PlatformInfoResponse, RoleInfo

router = APIRouter(tags=["Metadata"])


@router.get(
    "/roles",
    response_model=ApiResponse[PlatformInfoResponse],
    summary="List platform roles",
    description=(
        "Returns every role, its human-readable label, its landing route and "
        "whether it may be chosen during public self-registration."
    ),
)
def list_roles() -> dict:
    self_registrable = {role.value for role in UserRole.self_registrable()}
    roles = [
        RoleInfo(
            value=role,
            label=role.label,
            home_route=ROLE_HOME_ROUTES.get(role, "/dashboard"),
            self_registrable=role.value in self_registrable,
        )
        # Declared order, not dictionary order: this is the list the
        # administration screen renders its role picker from.
        for role in UserRole.administration_order()
    ]
    config = get_settings()
    return ok(
        {
            "service": config.SERVICE_NAME,
            "version": config.VERSION,
            "environment": config.ENVIRONMENT,
            "roles": roles,
        }
    )

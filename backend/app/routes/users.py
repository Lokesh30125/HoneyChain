"""User profile routes.

Phase 1 exposes only the signed-in user's own profile. Directory, verification
and KVIC-cluster member management arrive with their respective phases.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse, ok
from app.schemas.user import UserPublic, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=ApiResponse[UserPublic],
    summary="Read my profile",
    description="Equivalent to ``GET /auth/me``; provided as a stable resource-oriented path.",
)
def read_my_profile(user: User = Depends(get_current_user)) -> dict:
    return ok(UserPublic.model_validate(user))


@router.patch(
    "/me",
    response_model=ApiResponse[UserPublic],
    summary="Update my profile",
    description=(
        "Updates editable profile fields. Email, role and account status are "
        "administrator-controlled and cannot be changed here."
    ),
)
def update_my_profile(
    payload: UserUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
) -> dict:
    updated = UserService(session).update_profile(user, payload)
    return ok(UserPublic.model_validate(updated))

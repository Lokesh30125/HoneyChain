"""Profile routes — ``GET/PUT/PATCH /api/v1/profile``.

There is deliberately **no** ``/profile/{user_id}``. A user's profile is reached
only through their own session, so no identifier exists that could be tampered
with to read someone else's details. Administrative review of another account
goes through ``/admin/users/{id}``, which is permission-guarded and audited.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, get_current_user
from app.core.permissions import Permission, require_permission
from app.models.user import User
from app.schemas.common import ApiResponse, ok
from app.schemas.profile import FullProfileResponse, ProfilePatch, ProfileUpdate
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/profile", tags=["Profiles"])


@router.get(
    "",
    response_model=ApiResponse[FullProfileResponse],
    summary="Read my profile",
    description=(
        "Returns the account, the profile details and — for beekeepers — the "
        "linked beekeeper summary in a single response, so the profile page "
        "renders from one consistent snapshot."
    ),
)
def read_my_profile(
    user: User = Depends(require_permission(Permission.USER_READ_SELF)),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProfileService(session).get_full_profile(user))


@router.put(
    "",
    response_model=ApiResponse[FullProfileResponse],
    summary="Replace my profile",
    description=(
        "Full update: fields omitted from the body are cleared. Use PATCH to "
        "change only some fields. Email, role and account status are "
        "administrator-controlled and are not part of this payload."
    ),
)
def replace_my_profile(
    payload: ProfileUpdate,
    user: User = Depends(require_permission(Permission.USER_UPDATE_SELF)),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProfileService(session).replace_profile(user, payload))


@router.patch(
    "",
    response_model=ApiResponse[FullProfileResponse],
    summary="Update my profile",
    description="Partial update — only the fields present in the body are changed.",
)
def update_my_profile(
    payload: ProfilePatch,
    user: User = Depends(require_permission(Permission.USER_UPDATE_SELF)),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ProfileService(session).patch_profile(user, payload))

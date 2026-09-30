"""Reusable FastAPI dependencies: settings, DB session, auth, RBAC, cookies.

Route handlers declare what they need; authorisation is expressed declaratively
via ``Depends(requires_roles(...))`` so no route contains policy logic.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import (
    AuthenticationError,
    ForbiddenError,
    InactiveAccountError,
    TokenInvalidError,
)
from app.core.logging import get_logger
from app.core.security import InvalidTokenError, decode_token
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository

logger = get_logger("api")

#: Name of the HttpOnly cookie carrying the refresh token for browser clients.
REFRESH_COOKIE_NAME = "honeychain_refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"

# ``auto_error=False`` so we can raise our own envelope-shaped 401.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def settings_dependency() -> Settings:
    return get_settings()


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
#: Canonical database dependency. This MUST be the same callable object as
#: ``get_db`` (not a wrapper): FastAPI caches a dependency per callable, so a
#: wrapper would create a *second* session for the same request and objects
#: loaded through one session could not be used with the other.
db_session = get_db


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def resolve_user_from_access_token(token: str, session: Session, settings: Settings) -> User:
    """Validate an access token and return the matching active user.

    Shared by the required-auth and optional-auth dependencies so the decoding
    rules live in exactly one place.
    """
    try:
        claims = decode_token(token, settings, expected_type="access")
    except InvalidTokenError as exc:
        raise TokenInvalidError(str(exc)) from exc

    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError) as exc:
        raise TokenInvalidError("Token payload is malformed") from exc

    user = UserRepository(session).get(user_id)
    if user is None:
        # Valid signature but the account no longer exists (deleted/rotated).
        raise TokenInvalidError("The account linked to this session no longer exists")
    if not user.is_active:
        raise InactiveAccountError()
    return user


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
) -> User:
    """Resolve the authenticated user from the ``Authorization: Bearer`` header."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication credentials were not provided")

    user = resolve_user_from_access_token(credentials.credentials, session, settings)
    request.state.user_id = str(user.id)
    request.state.user_role = str(user.role)
    return user


def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    """Explicit alias used by endpoints that require an enabled account."""
    if not user.is_active:
        raise InactiveAccountError()
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
) -> User | None:
    """Return the user when a valid token is present, else ``None``.

    Used by public-but-personalised endpoints such as the Phase 3 traceability
    lookup, which is readable anonymously but richer when signed in.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        return resolve_user_from_access_token(credentials.credentials, session, settings)
    except (TokenInvalidError, InactiveAccountError):
        return None


def requires_roles(*roles: UserRole | str) -> Callable[[User], User]:
    """Dependency factory implementing role-based access control.

    Usage::

        @router.get("/admin/summary", dependencies=[Depends(requires_roles(UserRole.ADMIN))])
        def summary(...): ...
    """
    allowed = {str(role) for role in roles}

    def dependency(user: User = Depends(get_current_user)) -> User:
        if str(user.role) not in allowed:
            logger.warning(
                "Authorisation denied",
                extra={"user_id": str(user.id), "role": str(user.role), "required": sorted(allowed)},
            )
            raise ForbiddenError(
                "Your role does not have access to this resource",
                details={"required_roles": sorted(allowed), "your_role": str(user.role)},
            )
        return user

    return dependency


# --------------------------------------------------------------------------- #
# Refresh-token cookie helpers
# --------------------------------------------------------------------------- #
def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    """Store the refresh token in an HttpOnly cookie (browser clients).

    Path-scoped to the auth namespace, so it is never attached to ordinary API
    calls, which reduces exposure to XSS-driven theft.
    """
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.refresh_token_ttl_seconds,
        expires=datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_ttl_seconds),
        path=REFRESH_COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN,
        secure=settings.is_production,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN,
        secure=settings.is_production,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )


__all__ = [
    "REFRESH_COOKIE_NAME",
    "REFRESH_COOKIE_PATH",
    "settings_dependency",
    "db_session",
    "resolve_user_from_access_token",
    "get_current_user",
    "get_current_active_user",
    "get_optional_user",
    "requires_roles",
    "set_refresh_cookie",
    "clear_refresh_cookie",
]

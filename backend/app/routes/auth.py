"""Authentication routes — thin transport layer over ``AuthService``.

The route layer is responsible only for: reading the request, delegating to the
service, and shaping the HTTP response (including the refresh-token cookie).
All business rules live in ``app.services.auth_service``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    db_session,
    get_current_user,
    set_refresh_cookie,
    settings_dependency,
)
from app.core.config import Settings
from app.core.exceptions import ValidationError
from app.models.user import User
from app.schemas.auth import (
    AuthResult,
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
    RegisterRequest,
)
from app.schemas.common import ApiResponse, ok
from app.schemas.user import UserPublic
from app.services.auth_service import AuthService, build_auth_result, refresh_token_of

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _service(session: Session, settings: Settings) -> AuthService:
    return AuthService(
        session,
        settings,
        expose_refresh_in_body=settings.AUTH_EXPOSE_REFRESH_IN_BODY,
    )


def _client_context(request: Request) -> dict[str, str | None]:
    return {
        "user_agent": request.headers.get("user-agent"),
        "ip_address": request.client.host if request.client else None,
    }


@router.post(
    "/register",
    response_model=ApiResponse[AuthResult],
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    description=(
        "Creates a user and immediately issues a session. Privileged roles "
        "(ADMIN, KVIC_OFFICER, LAB_TECHNICIAN) cannot be self-assigned."
    ),
)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: Session = Depends(db_session),
    settings: Settings = Depends(settings_dependency),
) -> dict:
    service = _service(session, settings)
    issued = service.register(payload, **_client_context(request))

    refresh_token = refresh_token_of(issued)
    if refresh_token:
        set_refresh_cookie(response, refresh_token, settings)

    return ok(build_auth_result(issued))


@router.post(
    "/login",
    response_model=ApiResponse[AuthResult],
    summary="Authenticate and open a session",
    description=(
        "Returns a short-lived access token in the body. The refresh token is set "
        "as an HttpOnly cookie for browser clients."
    ),
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(db_session),
    settings: Settings = Depends(settings_dependency),
) -> dict:
    service = _service(session, settings)
    issued = service.authenticate(payload, **_client_context(request))

    refresh_token = refresh_token_of(issued)
    if refresh_token:
        set_refresh_cookie(response, refresh_token, settings)

    return ok(build_auth_result(issued))


@router.post(
    "/refresh",
    response_model=ApiResponse[AuthResult],
    summary="Rotate the refresh token",
    description=(
        "Exchanges a valid refresh token (cookie or body) for a new access token. "
        "The presented refresh token is revoked and replaced; replaying a revoked "
        "token revokes every session for that user."
    ),
)
def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    session: Session = Depends(db_session),
    settings: Settings = Depends(settings_dependency),
) -> dict:
    token = (payload.refresh_token if payload else None) or request.cookies.get(
        REFRESH_COOKIE_NAME
    )
    if not token:
        raise ValidationError(
            "No refresh token supplied. Provide it in the request body or as a cookie.",
            details={"accepted_sources": ["body.refresh_token", REFRESH_COOKIE_NAME]},
        )

    service = _service(session, settings)
    issued = service.refresh_session(token, **_client_context(request))

    new_refresh = refresh_token_of(issued)
    if new_refresh:
        set_refresh_cookie(response, new_refresh, settings)

    return ok(build_auth_result(issued))


@router.post(
    "/logout",
    response_model=ApiResponse[LogoutResponse],
    summary="End the current session",
    description=(
        "Revokes the presented refresh token server-side and clears the cookie. "
        "Set ``all_devices: true`` to revoke every session for the signed-in user."
    ),
)
def logout(
    request: Request,
    response: Response,
    payload: LogoutRequest | None = None,
    session: Session = Depends(db_session),
    settings: Settings = Depends(settings_dependency),
) -> dict:
    token = (payload.refresh_token if payload else None) or request.cookies.get(
        REFRESH_COOKIE_NAME
    )
    all_devices = bool(payload and payload.all_devices)

    service = _service(session, settings)
    revoked = service.logout(token, all_devices=all_devices)
    clear_refresh_cookie(response, settings)

    message = (
        "All sessions have been signed out"
        if all_devices
        else "You have been signed out"
    )
    return ok(LogoutResponse(message=message, revoked_sessions=revoked))


@router.get(
    "/me",
    response_model=ApiResponse[UserPublic],
    summary="Current authenticated user",
    description="Requires a valid access token. Used to bootstrap the SPA session.",
)
def me(user: User = Depends(get_current_user)) -> dict:
    return ok(UserPublic.model_validate(user))

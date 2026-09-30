"""Authentication business logic.

Responsibilities
----------------
* Registration with role-policy enforcement and duplicate detection.
* Login with constant-response failure behaviour (no user enumeration).
* Refresh-token rotation with reuse detection.
* Logout (single session) and logout-everywhere (all sessions).
* Structured, secret-free audit logging of every authentication event.

The service never touches HTTP concerns and never builds SQL: it composes the
user repository, the token repository and the ``core.security`` primitives.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    DuplicateResourceError,
    ForbiddenError,
    InactiveAccountError,
    InvalidCredentialsError,
    TokenInvalidError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_device_fingerprint,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.models.enums import ROLE_HOME_ROUTES, UserRole
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    AuthResult,
    LoginRequest,
    RegisterRequest,
    TokenMetadata,
)
from app.schemas.beekeeper import BeekeeperCreate, BeekeeperRegistrationInfo
from app.schemas.user import UserPublic
from app.services.audit_service import AuditService

logger = get_logger("auth")

REVOKE_ROTATED = "rotated"
REVOKE_LOGOUT = "logout"
REVOKE_LOGOUT_ALL = "logout_all"
REVOKE_REUSE_DETECTED = "reuse_detected"
#: An administrator changed the account's role. The permissions attached to the
#: session changed with it, so the session ends and the person signs in again.
REVOKE_ROLE_CHANGED = "role_changed"


@dataclass(slots=True)
class IssuedSession:
    """Internal result bundle for a freshly minted session."""

    user: User
    access_token: str
    refresh_token: str | None
    refresh_jti: str
    token_metadata: TokenMetadata
    #: Set when a beekeeper record was created with the account.
    beekeeper: object | None = None


class AuthService:
    """Orchestrates authentication use cases for the API layer."""

    def __init__(self, session: Session, settings: Settings, *, expose_refresh_in_body: bool = False) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditService(session)
        self.expose_refresh_in_body = expose_refresh_in_body

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def register(
        self,
        payload: RegisterRequest,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedSession:
        """Create an account and immediately issue a session.

        New accounts are always active. Self-registration is restricted to the
        non-privileged role list; ACTIVE-status enforcement happens at login.
        """
        self._assert_role_is_self_registrable(payload.role)

        if self.users.email_exists(payload.email):
            logger.info("Registration rejected: duplicate email", extra={"role": payload.role})
            raise DuplicateResourceError(
                "An account with this email already exists. Try signing in instead.",
                details={"field": "email"},
            )
        if payload.phone and self.users.phone_exists(payload.phone):
            logger.info("Registration rejected: duplicate phone", extra={"role": payload.role})
            raise DuplicateResourceError(
                "An account with this phone number already exists.",
                details={"field": "phone"},
            )

        try:
            user = self.users.create_user(
                name=payload.name,
                email=payload.email,
                password_hash=hash_password(payload.password),
                role=payload.role,
                phone=payload.phone,
                state=payload.state,
                district=payload.district,
                organization=payload.organization,
            )

            # A beekeeper account is meaningless without its beekeeper record, so
            # both are created in the same transaction: if the record fails, the
            # account is not created either. The record always starts PENDING —
            # the platform never verifies a beekeeper on its own.
            beekeeper = None
            if user.role == UserRole.BEEKEEPER:
                from app.services.beekeeper_service import BeekeeperService

                beekeeper = BeekeeperService(self.session).create_for_user(
                    user, payload.beekeeper or BeekeeperCreate()
                )
        except IntegrityError as exc:  # race between the check above and the insert
            self.session.rollback()
            raise DuplicateResourceError(
                "An account with these details already exists."
            ) from exc

        self.audit.user_registered(
            user,
            role=str(user.role),
            beekeeper_code=getattr(beekeeper, "beekeeper_code", None),
        )

        logger.info(
            "User registered",
            extra={
                "user_id": str(user.id),
                "role": str(user.role),
                "state": user.state,
                "district": user.district,
                "beekeeper_code": getattr(beekeeper, "beekeeper_code", None),
            },
        )
        return self._open_session(
            user,
            user_agent=user_agent,
            ip_address=ip_address,
            commit=True,
            beekeeper=beekeeper,
        )

    # ------------------------------------------------------------------ #
    # Login
    # ------------------------------------------------------------------ #
    def authenticate(
        self,
        payload: LoginRequest,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedSession:
        """Verify credentials and open a session."""
        user = self.users.get_by_email(payload.email)

        # Identical error for "unknown email" and "wrong password" so the API
        # cannot be used to enumerate registered accounts.
        if user is None or not verify_password(payload.password, user.password_hash):
            logger.warning(
                "Login failed",
                extra={"email_domain": payload.email.split("@")[-1] if payload.email else None},
            )
            # Recorded for security review. The submitted password is never
            # logged — only that an attempt happened and from which address.
            self.audit.user_login_failed(payload.email, ip_address=ip_address)
            raise InvalidCredentialsError()

        if not user.is_active:
            logger.warning("Login blocked: inactive account", extra={"user_id": str(user.id)})
            raise InactiveAccountError()

        # Transparent upgrade when the stored hash uses older parameters.
        if needs_rehash(user.password_hash):
            self.users.set_password(user, hash_password(payload.password))

        self.users.record_login(user)
        self.audit.user_login(user, ip_address=ip_address, user_agent=user_agent)
        logger.info("Login succeeded", extra={"user_id": str(user.id), "role": str(user.role)})
        return self._open_session(user, user_agent=user_agent, ip_address=ip_address, commit=True)

    # ------------------------------------------------------------------ #
    # Refresh (rotation + reuse detection)
    # ------------------------------------------------------------------ #
    def refresh_session(
        self,
        refresh_token: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedSession:
        """Rotate a refresh token into a brand new session.

        Presenting an already-revoked token is treated as an indicator of token
        theft: every session for that user is revoked immediately.
        """
        claims = self._decode(refresh_token, expected_type="refresh")
        record = self.tokens.get_by_hash(hash_token(refresh_token))

        if record is None:
            logger.warning("Refresh rejected: token not recognised")
            raise TokenInvalidError("Refresh token is not recognised")

        if record.revoked:
            # Replay of a rotated/revoked token -> assume compromise.
            self.tokens.revoke_all_for_user(
                record.user_id, reason=REVOKE_REUSE_DETECTED
            )
            self.tokens.commit()
            logger.error(
                "Refresh token reuse detected — all sessions revoked",
                extra={"user_id": str(record.user_id)},
            )
            raise TokenInvalidError("This session was revoked. Please sign in again.")

        if not record.is_usable:
            self.tokens.revoke(record, reason="expired")
            self.tokens.commit()
            raise TokenInvalidError("Refresh token has expired. Please sign in again.")

        user = self.users.get(uuid.UUID(str(claims["sub"])))
        if user is None or not user.is_active:
            raise InactiveAccountError()

        session = self._open_session(
            user,
            user_agent=user_agent,
            ip_address=ip_address,
            commit=False,
        )
        record.replaced_by_jti = session.refresh_jti
        self.tokens.revoke(record, reason=REVOKE_ROTATED)
        self.tokens.commit()

        logger.info("Session refreshed (token rotated)", extra={"user_id": str(user.id)})
        return session

    # ------------------------------------------------------------------ #
    # Logout
    # ------------------------------------------------------------------ #
    def logout(self, refresh_token: str | None, *, all_devices: bool = False) -> int:
        """Revoke the current session (or all sessions). Idempotent."""
        if all_devices:
            if refresh_token is None:
                raise ValidationError("A refresh token is required to end all sessions")
            claims = self._decode(refresh_token, expected_type="refresh")
            user_id = uuid.UUID(str(claims["sub"]))
            revoked = self.tokens.revoke_all_for_user(user_id, reason=REVOKE_LOGOUT_ALL)
            self.tokens.commit()

            actor = self.users.get(user_id)
            if actor is not None:
                self.audit.user_logout(actor, all_devices=True)

            logger.info("All sessions revoked", extra={"user_id": str(user_id), "count": revoked})
            return revoked

        if not refresh_token:
            # Nothing to revoke (e.g. cookie already cleared) — still a success.
            # No audit entry: no session actually ended.
            return 0

        record = self.tokens.get_by_hash(hash_token(refresh_token))
        if record is None:
            # Unknown/already-purged token: nothing to do, but logout is still
            # a success from the client's perspective.
            logger.info("Logout called with an unrecognised refresh token")
            return 0
        if record.revoked:
            return 0

        self.tokens.revoke(record, reason=REVOKE_LOGOUT)
        self.tokens.commit()

        actor = self.users.get(record.user_id)
        if actor is not None:
            self.audit.user_logout(actor)

        logger.info("Session revoked", extra={"user_id": str(record.user_id)})
        return 1

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _open_session(
        self,
        user: User,
        *,
        user_agent: str | None,
        ip_address: str | None,
        commit: bool,
        beekeeper: object | None = None,
    ) -> IssuedSession:
        access_token, access_expires_at = create_access_token(
            subject=str(user.id), role=str(user.role), settings=self.settings
        )
        refresh_token, refresh_expires_at, jti = create_refresh_token(
            subject=str(user.id), role=str(user.role), settings=self.settings
        )

        self.tokens.issue(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            jti=jti,
            expires_at=refresh_expires_at,
            device=generate_device_fingerprint(user_agent, ip_address),
        )
        if commit:
            self.tokens.commit()
            self.users.refresh(user)

        return IssuedSession(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token if self.expose_refresh_in_body else None,
            refresh_jti=jti,
            beekeeper=beekeeper,
            token_metadata=TokenMetadata(
                token_type="Bearer",
                expires_in=self.settings.access_token_ttl_seconds,
                expires_at=access_expires_at,
            ),
        )

    def _decode(self, token: str, *, expected_type: str) -> dict:
        try:
            return decode_token(token, self.settings, expected_type=expected_type)  # type: ignore[arg-type]
        except InvalidTokenError as exc:
            raise TokenInvalidError(str(exc)) from exc

    @staticmethod
    def _assert_role_is_self_registrable(role: UserRole) -> None:
        if role not in UserRole.self_registrable():
            raise ValidationError(
                f"The '{role.label}' role cannot be self-assigned. "
                "An administrator must provision this account.",
                details={"field": "role", "allowed": [r.value for r in UserRole.self_registrable()]},
            )


class CurrentUserService:
    """Read-only operations on the authenticated user."""

    def __init__(self, session: Session) -> None:
        self.users = UserRepository(session)
        self.session = session

    def get_profile(self, user: User) -> UserPublic:
        return UserPublic.model_validate(user)

    def ensure_active(self, user: User) -> User:
        if not user.is_active:
            raise ForbiddenError("This account is inactive")
        return user


def build_auth_result(issued: IssuedSession) -> AuthResult:
    """Serialise an issued session for the response body."""
    beekeeper = issued.beekeeper
    return AuthResult(
        user=UserPublic.model_validate(issued.user),
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        token=issued.token_metadata,
        # Public-safe subset: the code and status only. Nothing an officer has
        # written about the beekeeper is returned at sign-in.
        beekeeper=(
            BeekeeperRegistrationInfo.model_validate(beekeeper) if beekeeper is not None else None
        ),
        home_route=ROLE_HOME_ROUTES.get(issued.user.role, "/"),
    )


def refresh_token_of(issued: IssuedSession) -> str | None:
    return issued.refresh_token


__all__ = [
    "AuthService",
    "CurrentUserService",
    "IssuedSession",
    "build_auth_result",
    "refresh_token_of",
]

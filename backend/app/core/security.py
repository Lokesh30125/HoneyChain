"""HoneyChain API — password hashing and JWT token primitives.

Nothing in this module reads from the database; it is pure, testable security
logic. Orchestration lives in ``app.services.auth_service``.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from app.core.config import Settings

TokenType = Literal["access", "refresh"]

# bcrypt is the industry default for password storage. The 72-byte input limit
# of bcrypt is handled by rejecting over-long passwords at the schema boundary.
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Return a salted bcrypt hash. Plaintext is never persisted anywhere."""
    return password_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time verification that never raises on malformed hashes."""
    try:
        return password_context.verify(plain_password, password_hash)
    except (ValueError, TypeError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses outdated parameters and should be upgraded."""
    return password_context.needs_update(password_hash)


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def generate_token_id() -> str:
    """Opaque, URL-safe unique identifier used as the ``jti`` claim."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """One-way fingerprint used for at-rest comparison of refresh tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_token(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    settings: Settings,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime, str]:
    """Create a signed JWT. Returns ``(encoded_token, expires_at, jti)``."""
    now = datetime.now(timezone.utc)
    expires_at = now + expires_delta
    token_id = generate_token_id()

    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "jti": token_id,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.JWT_ISSUER,
    }
    if extra_claims:
        payload.update(extra_claims)

    encoded = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded, expires_at, token_id


def create_access_token(
    *, subject: str, role: str, settings: Settings, extra_claims: dict[str, Any] | None = None
) -> tuple[str, datetime]:
    """Short-lived token used to authorise API calls."""
    claims = {"role": role}
    if extra_claims:
        claims.update(extra_claims)
    token, expires_at, _ = _create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        settings=settings,
        extra_claims=claims,
    )
    return token, expires_at


def create_refresh_token(
    *, subject: str, role: str, settings: Settings
) -> tuple[str, datetime, str]:
    """Long-lived token used only to mint new access tokens.

    Returns ``(token, expires_at, jti)``. The service layer persists a hash of
    the token so that it can be revoked (logout / rotation / reuse detection).
    """
    token, expires_at, token_id = _create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        settings=settings,
        extra_claims={"role": role},
    )
    return token, expires_at, token_id


class InvalidTokenError(Exception):
    """Raised when a JWT is malformed, expired, or fails signature checks."""


def decode_token(token: str, settings: Settings, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Validate signature/expiry/issuer and return the claim set."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "jti", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("Token is invalid") from exc

    if expected_type and payload.get("type") != expected_type:
        raise InvalidTokenError(f"Expected a {expected_type} token")

    return payload


def generate_device_fingerprint(user_agent: str | None, ip_address: str | None) -> str:
    """Stable, non-reversible label for the issuing client (audit + UX only)."""
    raw = f"{user_agent or 'unknown'}|{ip_address or 'unknown'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()

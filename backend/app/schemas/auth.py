"""Authentication schemas — requests, responses and token metadata."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.enums import ROLE_HOME_ROUTES, UserRole
from app.schemas.beekeeper import BeekeeperCreate, BeekeeperRegistrationInfo
from app.schemas.user import UserPublic


class RegisterRequest(BaseModel):
    """``POST /api/v1/auth/register`` request body."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)
    confirm_password: str | None = Field(
        default=None,
        description="Optional. When supplied it must match ``password``.",
    )
    role: UserRole = Field(default=UserRole.BEEKEEPER)
    state: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    organization: str | None = Field(default=None, max_length=160)
    accepted_terms: bool = True
    #: Apiary details, required in practice for the BEEKEEPER role: the backend
    #: creates the beekeeper record as part of registration. Supplying this block
    #: with any other role is a validation error rather than a silent no-op.
    beekeeper: BeekeeperCreate | None = Field(
        default=None,
        description="Apiary details. Only accepted when ``role`` is BEEKEEPER.",
    )

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("Name must contain at least 2 characters")
        return cleaned

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        """Baseline policy: length + mixed character classes.

        bcrypt silently truncates beyond 72 bytes, so the schema enforces the
        limit rather than letting two different passwords collide.
        """
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes when UTF-8 encoded")
        if not any(char.isalpha() for char in value):
            raise ValueError("Password must contain at least one letter")
        if not any(char.isdigit() for char in value):
            raise ValueError("Password must contain at least one number")
        return value

    @field_validator("phone")
    @classmethod
    def _clean_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # The same separators the registration form strips: spaces, dashes and
        # brackets. Accepting "(987) 654-3210" in the form and refusing it here
        # is what produced a bare "Invalid request" on sign-up.
        cleaned = value.strip()
        for separator in (" ", "-", "(", ")"):
            cleaned = cleaned.replace(separator, "")
        if not cleaned:
            return None
        if not cleaned.startswith("+") and cleaned.isdigit() and len(cleaned) == 10:
            cleaned = f"+91{cleaned}"  # sensible default for Indian deployments
        if not (cleaned.startswith("+") and cleaned[1:].isdigit() and 8 <= len(cleaned) <= 16):
            raise ValueError("Phone must be a valid number, e.g. +919876543210")
        return cleaned

    @model_validator(mode="after")
    def _passwords_match(self) -> "RegisterRequest":
        if self.confirm_password is not None and self.confirm_password != self.password:
            raise ValueError("Passwords do not match")
        return self

    @model_validator(mode="after")
    def _beekeeper_block_matches_role(self) -> "RegisterRequest":
        """Keep the role and the apiary block consistent.

        A non-beekeeper sending apiary details is almost certainly a client bug
        (or an attempt to create a record they are not entitled to), so it is
        rejected loudly. A beekeeper may omit the block — the record is still
        created, just with the fields left blank for later completion.
        """
        if self.beekeeper is not None and self.role != UserRole.BEEKEEPER:
            raise ValueError(
                "Apiary details can only be supplied when registering as a beekeeper"
            )
        return self


class LoginRequest(BaseModel):
    """``POST /api/v1/auth/login`` request body."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=72)
    remember_me: bool = Field(
        default=False,
        description="Hint for the client on how long to retain the refresh token.",
    )


class RefreshRequest(BaseModel):
    """``POST /api/v1/auth/refresh`` request body.

    The refresh token may alternatively be supplied as an HttpOnly cookie, in
    which case the body can be empty.
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = Field(default=None, min_length=10)


class TokenMetadata(BaseModel):
    """Non-secret token information the client needs to schedule refreshes."""

    token_type: str = "Bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    expires_at: datetime = Field(description="Absolute access token expiry (UTC).")


class AuthResult(BaseModel):
    """Full authentication result: identity + tokens.

    Returned by ``/auth/register``, ``/auth/login`` and ``/auth/refresh``.

    The access token travels in the response body so the SPA can hold it in
    memory. The refresh token is issued as an HttpOnly cookie for browsers and
    is additionally present in the body only when
    ``AUTH_EXPOSE_REFRESH_IN_BODY=true`` (mobile clients, integration tests).
    """

    user: UserPublic
    access_token: str = Field(description="Short-lived bearer token for API calls.")
    refresh_token: str | None = Field(
        default=None,
        description=(
            "Null for browser clients (see the HttpOnly refresh cookie instead). "
            "Populated when AUTH_EXPOSE_REFRESH_IN_BODY=true."
        ),
    )
    token: TokenMetadata
    beekeeper: BeekeeperRegistrationInfo | None = Field(
        default=None,
        description="Present when the account registered with the BEEKEEPER role.",
    )
    home_route: str = Field(
        default="/",
        description=(
            "Where this role starts after signing in. Mirrors the backend's "
            "ROLE_HOME_ROUTES so the client never has to guess a landing page."
        ),
    )


class MessageResponse(BaseModel):
    """Simple acknowledgement payload."""

    message: str


class LogoutResponse(MessageResponse):
    """Acknowledgement for logout, including how many sessions were revoked."""

    revoked_sessions: int = 0


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = Field(default=None, min_length=10)
    all_devices: bool = Field(
        default=False,
        description="Revoke every active session for the user, not just this one.",
    )

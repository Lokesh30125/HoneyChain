"""Administrator-facing schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.enums import UserRole
from app.schemas.audit import AuditLogEntry
from app.schemas.beekeeper import BeekeeperCreate
from app.schemas.user import UserPublic


class AdminUserCreate(BaseModel):
    """``POST /api/v1/admin/users`` — provision an operational account.

    This is the administrator's counterpart to public registration: the same
    ``users`` table, the same password hashing, the same login endpoint — the
    only difference is that the *role* is chosen by the administrator instead of
    being limited to the two roles a visitor may self-assign.

    Every role is accepted here, including ``ADMIN``: a platform with one
    administrator can never name a successor otherwise. The role that results is
    stored on the account and enforced by ``ROLE_PERMISSIONS`` on every request;
    it is not a display setting.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120, examples=["Sita Rao"])
    email: EmailStr = Field(examples=["sita.rao@honeychain.example.com"])
    phone: str | None = Field(default=None, max_length=20)
    #: Same policy as registration: at least 8 characters, letters and numbers,
    #: at most 72 bytes because bcrypt truncates past that.
    password: str = Field(min_length=8, max_length=72)
    role: UserRole = Field(
        description="Any of the ten platform roles. Stored on the account and enforced by RBAC.",
    )
    #: An account can be created disabled — for a technician who starts next
    #: week, say — and enabled later from the same directory.
    is_active: bool = Field(default=True, description="Account status at creation.")
    state: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    organization: str | None = Field(
        default=None,
        max_length=160,
        description="The laboratory, plant, centre or firm the account belongs to.",
    )
    reason: str | None = Field(
        default=None,
        max_length=200,
        description="Optional note recorded in the audit log for this creation.",
    )
    #: Apiary details, accepted only for ``BEEKEEPER`` — the account is useless
    #: without its beekeeper record, so the two are created together. This is the
    #: same block the public registration form sends, not a second definition of
    #: it: one beekeeper record shape, whichever door the account came through.
    beekeeper: BeekeeperCreate | None = Field(
        default=None,
        description="Optional apiary details. Rejected for any role other than BEEKEEPER.",
    )
    #: The facility a packaging-unit account works for. Set here because the
    #: account is useless without it: the run it opens has to name the facility
    #: that packed the honey, and the operator does not choose that per run.
    #: Optional at this boundary — an administrator may attach the account from
    #: the packaging-unit screen instead — but the workspace and every run refuse
    #: with a message naming this action until it is set.
    packaging_unit_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The packaging unit a PACKAGING_UNIT account works for. Accepted only for that role."
        ),
    )

    @model_validator(mode="after")
    def _facility_matches_the_role(self):
        """A facility is named for a packaging-unit account and for no other.

        Letting a laboratory technician carry a packaging unit would put a foreign
        key on an account that has nothing to do with it, and somebody would later
        read it as a relationship.
        """
        if self.packaging_unit_id is not None and self.role is not UserRole.PACKAGING_UNIT:
            raise ValueError(
                "A packaging unit may only be set on an account holding the packaging-unit role."
            )
        return self

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("Name must contain at least 2 characters")
        return cleaned

    @field_validator("password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        """Mirror of the registration policy — one rule, one place per surface."""
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
        cleaned = value.strip().replace(" ", "").replace("-", "")
        if not cleaned:
            return None
        if not cleaned.startswith("+") and cleaned.isdigit() and len(cleaned) == 10:
            cleaned = f"+91{cleaned}"
        if not (cleaned.startswith("+") and cleaned[1:].isdigit() and 8 <= len(cleaned) <= 16):
            raise ValueError("Phone must be a valid number, e.g. +919876543210")
        return cleaned

    @model_validator(mode="after")
    def _beekeeper_block_matches_role(self) -> "AdminUserCreate":
        if self.beekeeper is not None and self.role is not UserRole.BEEKEEPER:
            raise ValueError(
                "Apiary details may only be supplied for a BEEKEEPER account"
            )
        return self


class AdminUserRoleUpdate(BaseModel):
    """``PATCH /api/v1/admin/users/{id}/role`` — change an account's role."""

    model_config = ConfigDict(extra="forbid")

    role: UserRole = Field(description="The role the account should hold from now on.")
    reason: str | None = Field(
        default=None,
        max_length=200,
        description="Optional note recorded in the audit log for this change.",
    )


class AdminUserCreateResponse(BaseModel):
    """Result of provisioning an account, with what else was created with it."""

    user: UserPublic
    message: str
    #: True when a beekeeper record was created alongside the account.
    beekeeper_created: bool = False


class AdminUserRoleUpdateResponse(BaseModel):
    user: UserPublic
    previous_role: UserRole
    message: str
    #: Live sessions revoked because the account's permissions changed.
    sessions_revoked: int = 0


class AdminBeekeeperContext(BaseModel):
    """Beekeeper summary shown alongside an account in the admin directory.

    Read-only context for a decision — not the full beekeeper record, which is
    reached through the beekeeper endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    beekeeper_code: str
    verification_status: str
    district: str | None = None
    state: str | None = None
    number_of_hives: int | None = None
    cluster_name: str | None = None


class AdminUserDetail(BaseModel):
    """``GET /api/v1/admin/users/{id}`` response."""

    user: UserPublic
    beekeeper: AdminBeekeeperContext | None = None
    #: Most recent audited actions on this account, newest first.
    recent_activity: list[AuditLogEntry] = Field(default_factory=list)


class AdminUserStatusUpdateResponse(BaseModel):
    user: UserPublic
    message: str


class PlatformSummaryUsers(BaseModel):
    total: int
    active: int
    inactive: int
    by_role: dict[str, int]


class PlatformSummaryBeekeepers(BaseModel):
    total: int
    by_verification_status: dict[str, int]


class PlatformSummaryClusters(BaseModel):
    total: int
    active: int


class PlatformSummary(BaseModel):
    """``GET /api/v1/admin/summary`` — counts plus honest module status."""

    users: PlatformSummaryUsers
    beekeepers: PlatformSummaryBeekeepers
    clusters: PlatformSummaryClusters
    modules: dict[str, str]

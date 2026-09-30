"""User schemas — the API representation of an identity record.

``UserPublic`` is the *only* user shape returned by the API. It is derived from
the ORM object with ``from_attributes=True`` and deliberately has no password
field, so a credential can never leak through a response model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.models.enums import AccountStatus, UserRole


class UserBase(BaseModel):
    name: str = Field(min_length=2, max_length=120, examples=["Ravi Kumar"])
    email: EmailStr = Field(examples=["ravi.kumar@example.com"])
    phone: str | None = Field(
        default=None,
        max_length=20,
        description="Optional contact number in E.164-ish format.",
        examples=["+919876543210"],
    )
    state: str | None = Field(default=None, max_length=80, examples=["Andhra Pradesh"])
    district: str | None = Field(default=None, max_length=80, examples=["Guntur"])
    organization: str | None = Field(
        default=None,
        max_length=160,
        description="Co-operative, KVIC cluster, lab or company the user belongs to.",
        examples=["Guntur Beekeepers Co-operative"],
    )


class UserCreate(UserBase):
    """Payload accepted by ``POST /api/v1/auth/register``."""

    password: str = Field(
        min_length=8,
        max_length=72,
        description="Minimum 8 characters. Must include letters and numbers.",
        examples=["Honey@2026"],
    )
    role: UserRole = Field(
        default=UserRole.BEEKEEPER,
        description=(
            "Role requested at sign-up. Privileged roles (ADMIN, KVIC_OFFICER, "
            "LAB_TECHNICIAN) cannot be self-assigned and are provisioned by an "
            "administrator. Sending one returns 422."
        ),
    )
    accepted_terms: bool = Field(
        default=True,
        description="Consent to the platform's data and traceability policy.",
    )


class UserUpdate(BaseModel):
    """Editable profile fields (``PATCH /api/v1/users/me``).

    ``extra="forbid"`` makes an attempt to change ``role``, ``email`` or
    ``is_active`` a 422 rather than a silently ignored field.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    state: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    organization: str | None = Field(default=None, max_length=160)


class AdminUserStatusUpdate(BaseModel):
    """Administrator action on an account (``PATCH /api/v1/admin/users/{id}/status``)."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool = Field(description="Target account status.")
    reason: str | None = Field(
        default=None,
        max_length=200,
        description="Optional note recorded in the audit log for this change.",
    )


class UserPublic(BaseModel):
    """Safe, read-only projection of a user."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    phone: str | None = None
    role: UserRole
    is_active: bool
    #: Contact verification. Distinct from a beekeeper's verification status.
    is_verified: bool = False
    state: str | None = None
    district: str | None = None
    organization: str | None = None
    #: The packaging facility this account works for. Carried for the directory —
    #: an administrator looking at a packaging-unit account has to be able to see
    #: which facility it works for, because attaching it is the administrator's
    #: job. Null for every other role.
    packaging_unit_id: uuid.UUID | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    #: The related row itself, read only so the name below comes from the same
    #: record the id points at — never a second copy of it. Excluded from the
    #: response: the directory shows the facility's identity, not the whole row.
    packaging_unit: Any = Field(default=None, exclude=True, repr=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def role_label(self) -> str:
        return self.role.label

    @computed_field  # type: ignore[prop-decorator]
    @property
    def packaging_unit_name(self) -> str | None:
        """The facility's name, or ``None`` when the account works for none."""
        return getattr(self.packaging_unit, "name", None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def account_status(self) -> AccountStatus:
        return AccountStatus.ACTIVE if self.is_active else AccountStatus.INACTIVE

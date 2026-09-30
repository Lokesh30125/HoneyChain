"""Profile schemas — ``GET/PUT /api/v1/profile``."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import UserRole

#: Days a person must have lived to be plausible; guards obvious input errors.
MIN_AGE_YEARS = 10


class ProfileLocation(BaseModel):
    """Indian administrative location, shared by profiles and beekeepers."""

    model_config = ConfigDict(extra="forbid")

    village: str | None = Field(default=None, max_length=120, examples=["Tenali"])
    mandal: str | None = Field(default=None, max_length=120, examples=["Tenali"])
    district: str | None = Field(default=None, max_length=80, examples=["Guntur"])
    state: str | None = Field(default=None, max_length=80, examples=["Andhra Pradesh"])
    pincode: str | None = Field(default=None, max_length=6, examples=["522201"])

    @field_validator("pincode")
    @classmethod
    def _validate_pincode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not (cleaned.isdigit() and len(cleaned) == 6 and cleaned[0] != "0"):
            raise ValueError("Enter a valid 6-digit Indian PIN code")
        return cleaned

    @field_validator("village", "mandal", "district", "state")
    @classmethod
    def _clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class ProfilePersonal(BaseModel):
    """Personal details. All optional — never required at registration."""

    model_config = ConfigDict(extra="forbid")

    profile_photo: str | None = Field(
        default=None,
        max_length=512,
        description="URL or stored path of the profile photo.",
    )
    date_of_birth: date | None = None
    gender: str | None = Field(
        default=None, description="One of: male, female, other, prefer_not_to_say"
    )
    address: str | None = Field(default=None, max_length=500)

    @field_validator("date_of_birth")
    @classmethod
    def _validate_dob(cls, value: date | None) -> date | None:
        if value is None:
            return None
        today = date.today()
        if value > today:
            raise ValueError("Date of birth cannot be in the future")
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age > 120:
            raise ValueError("Enter a valid date of birth")
        return value

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"male", "female", "other", "prefer_not_to_say"}
        cleaned = value.strip().lower()
        if cleaned and cleaned not in allowed:
            raise ValueError(f"Gender must be one of: {', '.join(sorted(allowed))}")
        return cleaned or None


class ProfileUpdate(ProfilePersonal, ProfileLocation):
    """``PUT /api/v1/profile`` — full replace of the editable surface."""


class ProfilePatch(ProfilePersonal, ProfileLocation):
    """``PATCH /api/v1/profile`` — partial update; only sent fields change."""

    model_config = ConfigDict(extra="forbid")


class UserAccountSummary(BaseModel):
    """Read-only account information shown in the profile's Account section."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRole
    role_label: str = ""
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None


class ProfilePublic(ProfilePersonal, ProfileLocation):
    """The profile as returned to its owner."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID | None = None
    user_id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BeekeeperSummaryForProfile(BaseModel):
    """Compact beekeeper block embedded in the profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    beekeeper_code: str
    verification_status: str
    verification_label: str = ""
    experience_years: int | None = None
    bee_species: str | None = None
    number_of_hives: int | None = None
    village: str | None = None
    mandal: str | None = None
    district: str | None = None
    state: str | None = None
    pincode: str | None = None
    registration_date: date | None = None
    cluster_id: uuid.UUID | None = None
    cluster_code: str | None = None
    cluster_name: str | None = None


class FullProfileResponse(BaseModel):
    """Everything the profile page needs, in one response.

    Returning the account, profile and beekeeper summary together avoids three
    round trips on page load and guarantees the sections cannot disagree.
    """

    account: UserAccountSummary
    profile: ProfilePublic
    beekeeper: BeekeeperSummaryForProfile | None = None

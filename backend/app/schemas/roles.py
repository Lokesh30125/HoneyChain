"""Schemas describing the platform role catalogue."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import UserRole


class RoleInfo(BaseModel):
    value: UserRole = Field(description="Stable role key used by the API and RBAC.")
    label: str = Field(description="Human-readable label for display.")
    home_route: str = Field(description="Frontend route this role lands on after sign-in.")
    self_registrable: bool = Field(
        description="Whether a visitor may select this role on the public registration form."
    )


class PlatformInfoResponse(BaseModel):
    service: str
    version: str
    environment: str
    roles: list[RoleInfo]

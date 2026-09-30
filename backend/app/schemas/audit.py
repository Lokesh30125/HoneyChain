"""Audit log schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AuditLogEntry(BaseModel):
    """One audit record as returned by the admin audit view."""

    # ``populate_by_name`` lets the model be built either from the ORM attribute
    # name (``event_metadata``) or the API field name (``metadata``).
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    action: str
    actor_email: str | None = None
    actor_role: str | None = None
    user_id: uuid.UUID | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    #: Exposed under the API name ``metadata``; the ORM attribute is
    #: ``event_metadata`` because ``metadata`` is reserved by SQLAlchemy.
    #: Both names are accepted on input, with the ORM attribute name first:
    #: on a SQLAlchemy model, ``metadata`` resolves to ``MetaData`` (the whole
    #: schema), so the alias order is not cosmetic.
    event_metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("event_metadata", "metadata"),
        serialization_alias="metadata",
    )
    description: str | None = None
    ip_address: str | None = None
    created_at: datetime


class AuditActivitySummary(BaseModel):
    """Recent activity counts for the admin dashboard."""

    window_hours: int
    total: int
    by_action: dict[str, int]
    generated_at: datetime

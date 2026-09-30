"""Canonical response envelope and shared schema primitives.

Every endpoint returns one of::

    {"success": true,  "data": {...}}                       # single resource
    {"success": true,  "data": {...}, "meta": {...}}        # paginated list
    {"success": false, "error": {"code": "...", "message": "..."}}

``ApiResponse`` documents these shapes in OpenAPI; the runtime construction
happens in the route layer through the ``ok()`` / ``paginated()`` helpers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_serializer

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human readable, user-safe message.")
    details: list[dict[str, Any]] | dict[str, Any] | None = Field(
        default=None, description="Optional field-level validation details."
    )


class Meta(BaseModel):
    """Pagination and request metadata."""

    page: int | None = None
    page_size: int | None = None
    total_items: int | None = None
    total_pages: int | None = None
    request_id: str | None = None

    model_config = ConfigDict(extra="allow")


class ApiResponse(BaseModel, Generic[T]):
    """Standard success envelope.

    ``meta`` is omitted entirely when there is nothing to report, so a simple
    response is exactly ``{"success": true, "data": {...}}`` while a paginated
    one adds ``meta``.
    """

    success: bool = True
    data: T | None = None
    meta: Meta | None = None

    @model_serializer(mode="wrap")
    def _omit_empty(self, handler):
        serialised = handler(self)
        return {key: value for key, value in serialised.items() if value is not None or key == "success"}


class ApiErrorResponse(BaseModel):
    """Standard error envelope."""

    success: bool = False
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str = Field(examples=["HoneyChain API"])


class HealthDetailResponse(BaseModel):
    """Extended readiness payload (``/api/v1/health/db``)."""

    status: str
    service: str
    version: str
    environment: str
    timestamp: datetime
    components: dict[str, Any]


class PaginationParams(BaseModel):
    """Reusable query parameters for list endpoints added in later phases."""

    page: int = Field(default=1, ge=1, description="1-based page number.")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page (max 100).")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def ok(data: T | None = None, *, meta: Meta | None = None) -> dict[str, Any]:
    """Build a success envelope dict for the response serialiser."""
    payload: dict[str, Any] = {"success": True, "data": data}
    if meta is not None:
        payload["meta"] = meta.model_dump(exclude_none=True)
    return payload


def paginated(
    items: list[Any], *, total_items: int, page: int, page_size: int, request_id: str | None = None
) -> dict[str, Any]:
    """Build a success envelope for a paginated collection."""
    total_pages = (total_items + page_size - 1) // page_size if page_size else 0
    return ok(
        items,
        meta=Meta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            request_id=request_id,
        ),
    )

def check_other_pair(
    *, kind: str, value, other: str | None, other_option: str = "OTHER", field: str = "other"
) -> None:
    """An "Other" choice and the description that goes with it must agree.

    Shared by every field in the platform that offers an "Other" option — what a
    processing run did, what a batch was packed into, what hardware a device is.
    One rule, so no two of them can drift: the description is required when the
    choice is "Other", and refused when it is one of the listed values.

    Raising `ValueError` inside a Pydantic model validator turns into a 422 with the
    message intact; the services call it for the same reason when an update changes
    only half of the pair.
    """
    is_other = str(value) == other_option
    text = (other or "").strip()
    if is_other and not text:
        raise ValueError(
            f"Describe the {kind}: with the type set to Other, the record has to say what "
            f"the {kind} was."
        )
    if not is_other and text:
        raise ValueError(
            f"A description is only recorded when the type is Other; this record names a "
            f"listed {kind}."
        )

def display_choice(value, other: str | None, *, other_option: str = "OTHER") -> str:
    """What to print for a choice that offered *Other*.

    A record set to "Other" carries the description the operator typed, and that
    is what a reader needs — the bare word "Other" says something happened without
    saying what. Everywhere else the enum's own label is used, so callers do not
    each invent their own wording.
    """
    if str(getattr(value, "value", value)) == other_option and other:
        return other
    label = getattr(value, "label", None)
    return label or str(getattr(value, "value", value))

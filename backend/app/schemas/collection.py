"""Request and response models for collections.

Two shapes are deliberately absent from the request models: ``beekeeper_id`` and
``cluster_id``. A beekeeper cannot say who they are or which cluster their harvest
belongs to — the service derives both from the authenticated user's own beekeeper
record (the Phase-4.1 relationship). ``extra="forbid"`` means an attempt to send
them is rejected with 422 rather than silently ignored, so a client never believes
it set something it did not.

The AI fields are **read-only everywhere**. They are filled from stored analyses
when the harvest is recorded and reported back; a payload cannot set, adjust or
"improve" an AI estimate, exactly as it cannot claim a harvested weight.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import BatchStage, BatchStatus, CollectionStatus, CollectionUnit

#: A single harvest is bounded on the high side only to catch a mistyped figure
#: (one apiary does not yield twenty tonnes in a day); the low side is a real
#: rule — you cannot record taking nothing.
MAX_COLLECTION_QUANTITY_KG = Decimal("20000")
MAX_SOURCE_HIVES = 50


class CollectionSourceInput(BaseModel):
    """One hive's contribution to a harvest."""

    model_config = ConfigDict(extra="forbid")

    hive_id: uuid.UUID
    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        description=(
            "Quantity taken from this hive, in the collection's unit. Required when more "
            "than one hive contributes; for a single-hive harvest it may be omitted if the "
            "collection total is given instead."
        ),
    )
    notes: str | None = Field(default=None, max_length=200)


class CollectionCreate(BaseModel):
    """``POST /api/v1/collections``."""

    model_config = ConfigDict(extra="forbid")

    hives: list[CollectionSourceInput] = Field(
        min_length=1,
        max_length=MAX_SOURCE_HIVES,
        description="Source hives. The harvest is traceable to each one individually.",
    )
    collection_date: date = Field(description="The day the honey was harvested.")
    total_quantity: Decimal | None = Field(
        default=None,
        gt=0,
        le=MAX_COLLECTION_QUANTITY_KG,
        description=(
            "Actual harvested quantity. Computed as the sum of the per-hive quantities "
            "when those are supplied; if supplied alongside them it must match the sum."
        ),
    )
    unit: CollectionUnit = CollectionUnit.KG
    status: CollectionStatus = Field(
        default=CollectionStatus.PLANNED,
        description="PLANNED (scheduled) or IN_PROGRESS (harvesting now).",
    )
    notes: str | None = Field(default=None, max_length=2000)
    client_reference: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional client key. Repeating a create with the same key returns the "
            "collection already stored instead of recording the harvest twice."
        ),
    )

    @field_validator("status")
    @classmethod
    def _status_must_be_open(cls, value: CollectionStatus) -> CollectionStatus:
        """A create may not declare itself finished — completion is its own step."""
        if not value.is_open:
            raise ValueError(
                "A new collection starts as PLANNED or IN_PROGRESS. "
                "Use POST /collections/{id}/complete to complete it."
            )
        return value

    @field_validator("collection_date")
    @classmethod
    def _date_not_in_the_future(cls, value: date) -> date:
        """Honey cannot be recorded as harvested tomorrow."""
        if value > date.today():
            raise ValueError("Collection date cannot be in the future")
        return value

    @model_validator(mode="after")
    def _quantities_are_unambiguous(self) -> "CollectionCreate":
        hive_count = len(self.hives)

        missing = [str(row.hive_id) for row in self.hives if row.quantity is None]
        if missing and not (hive_count == 1 and self.total_quantity is not None):
            raise ValueError(
                "Each source hive needs its own quantity, unless a single hive is "
                "selected and the collection total is supplied."
            )

        if self.total_quantity is not None:
            per_hive = [row.quantity for row in self.hives if row.quantity is not None]
            if per_hive:
                summed = sum(per_hive, Decimal("0"))
                if summed != self.total_quantity:
                    raise ValueError(
                        f"total_quantity ({self.total_quantity}) does not match the sum of "
                        f"the per-hive quantities ({summed}). Send one or the other, or "
                        f"make them agree."
                    )

        seen: set[uuid.UUID] = set()
        for row in self.hives:
            if row.hive_id in seen:
                raise ValueError("The same hive cannot contribute twice to one collection")
            seen.add(row.hive_id)

        return self

    def per_hive_quantity(self, hive_id: uuid.UUID) -> Decimal | None:
        for row in self.hives:
            if row.hive_id == hive_id:
                return row.quantity
        return None


class CollectionUpdate(BaseModel):
    """``PATCH /api/v1/collections/{id}`` — only while the harvest is open."""

    model_config = ConfigDict(extra="forbid")

    hives: list[CollectionSourceInput] | None = Field(default=None, max_length=MAX_SOURCE_HIVES)
    collection_date: date | None = None
    total_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_COLLECTION_QUANTITY_KG)
    unit: CollectionUnit | None = None
    status: CollectionStatus | None = Field(
        default=None, description="PLANNED ⇄ IN_PROGRESS only."
    )
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("collection_date")
    @classmethod
    def _date_not_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Collection date cannot be in the future")
        return value

    @field_validator("status")
    @classmethod
    def _status_must_be_open(cls, value: CollectionStatus | None) -> CollectionStatus | None:
        if value is not None and not value.is_open:
            raise ValueError(
                "Use POST /collections/{id}/complete or /cancel to finish a collection."
            )
        return value


class CollectionCancel(BaseModel):
    """``POST /api/v1/collections/{id}/cancel``."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=200)


class CollectionComplete(BaseModel):
    """``POST /api/v1/collections/{id}/complete``.

    The body is optional in practice — completion takes no instruction from the
    client. It exists so a caller *may* record why the harvest ended and is
    refused extra fields, keeping the endpoint's contract explicit.
    """

    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- #
# Read models
# --------------------------------------------------------------------------- #
class CollectionAiContext(BaseModel):
    """The AI estimate that existed at harvest time — context, never the harvest."""

    predicted_yield_kg: Decimal | None = None
    prediction_hive_count: int = 0
    captured_at: datetime | None = None
    actual_quantity: Decimal | None = None
    difference_kg: Decimal | None = Field(
        default=None,
        description=(
            "actual − predicted, for this harvest only. It is a comparison, not a "
            "statement about model accuracy."
        ),
    )
    note: str | None = None


class CollectionIotContext(BaseModel):
    """Recent sensor readings around the harvest, labelled as context.

    Deliberately *not* a harvest figure: hive weight includes boxes, frames and
    bees, and this platform has no validated weight-to-honey rule, so none is
    applied.
    """

    has_data: bool = False
    hive_code: str | None = None
    device_id: str | None = None
    recorded_at: datetime | None = None
    source: str | None = None
    source_label: str | None = None
    temperature: float | None = None
    humidity: float | None = None
    weight: float | None = None
    vibration: float | None = None
    acoustic_level: float | None = None
    note: str | None = None


class CollectionSourceHive(BaseModel):
    """One contributing hive, with what it gave."""

    hive_id: uuid.UUID
    hive_code: str
    quantity: Decimal
    unit: str
    unit_label: str
    hive_status: str | None = None
    village: str | None = None
    district: str | None = None
    ai_predicted_yield_kg: Decimal | None = None
    ai_analysis_id: uuid.UUID | None = None
    notes: str | None = None


class CollectionListItem(BaseModel):
    id: uuid.UUID
    collection_code: str
    status: CollectionStatus
    status_label: str
    collection_date: date
    total_quantity: Decimal
    unit: CollectionUnit
    unit_label: str
    source_hive_count: int
    source_hive_codes: list[str] = Field(default_factory=list)
    beekeeper_id: uuid.UUID | None = None
    beekeeper_code: str | None = None
    beekeeper_name: str | None = None
    cluster_id: uuid.UUID | None = None
    cluster_code: str | None = None
    cluster_name: str | None = None
    has_batch: bool = False
    batch_id: uuid.UUID | None = None
    batch_code: str | None = None
    ai_predicted_yield_kg: Decimal | None = None
    notes: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class CollectionDetail(CollectionListItem):
    sources: list[CollectionSourceHive] = Field(default_factory=list)
    ai_context: CollectionAiContext | None = None
    iot_context: CollectionIotContext | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    client_reference: str | None = None
    updated_at: datetime
    can_complete: bool = False
    can_cancel: bool = False
    can_edit: bool = False


class CollectionSummary(BaseModel):
    """Counters for the collection workspace."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    planned: int = 0
    in_progress: int = 0
    completed: int = 0
    cancelled: int = 0
    batches_created: int = 0
    harvested_totals: dict[str, float] = Field(
        default_factory=dict,
        description="Completed quantity per unit — never summed across units.",
    )
    open_quantity: dict[str, float] = Field(
        default_factory=dict,
        description="Quantity recorded on harvests still open, per unit.",
    )


class EligibleHive(BaseModel):
    """A hive the caller may start a harvest on, with the context to plan it."""

    id: uuid.UUID
    hive_code: str
    status: str
    status_label: str
    village: str | None = None
    district: str | None = None
    total_collections: int = 0
    last_collection_date: date | None = None
    last_collection_code: str | None = None
    ai_predicted_yield_kg: Decimal | None = None
    ai_analyzed_at: datetime | None = None
    ai_health_status: str | None = None
    ai_data_quality: str | None = None
    latest_weight_kg: float | None = None
    latest_reading_at: datetime | None = None


class EligibleHiveList(BaseModel):
    hives: list[EligibleHive] = Field(default_factory=list)
    total: int = 0
    eligible_statuses: list[str] = Field(default_factory=list)
    note: str | None = None


__all__ = [
    "CollectionCreate",
    "CollectionUpdate",
    "CollectionCancel",
    "CollectionComplete",
    "CollectionSourceInput",
    "CollectionSourceHive",
    "CollectionListItem",
    "CollectionDetail",
    "CollectionSummary",
    "CollectionAiContext",
    "CollectionIotContext",
    "EligibleHive",
    "EligibleHiveList",
]

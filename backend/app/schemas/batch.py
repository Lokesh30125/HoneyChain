"""Request and response models for honey batches.

There is **no** ``BatchUpdate`` model, and that is the point. Everything a batch
says about a harvest — its code, its collection, the source hives, the date, the
quantity, the unit, the beekeeper and the cluster — is fixed when it is created.
No Prompt 5 endpoint accepts a body that could alter any of it, so the API cannot
be used to rewrite history even by mistake.

Status and stage are reported with the full lifecycle so the UI can render the
timeline honestly: ``COLLECTION`` is reached, everything after it is *not
started*. Those later stages are listed, never claimed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BatchStage, BatchStatus, CollectionUnit


class BatchListItem(BaseModel):
    id: uuid.UUID
    batch_code: str
    status: BatchStatus
    status_label: str
    current_stage: BatchStage
    current_stage_label: str
    collection_id: uuid.UUID
    collection_code: str
    collection_date: date
    quantity: Decimal
    unit: CollectionUnit
    unit_label: str
    source_hive_count: int = 0
    source_hive_codes: list[str] = Field(default_factory=list)
    beekeeper_id: uuid.UUID | None = None
    beekeeper_code: str | None = None
    beekeeper_name: str | None = None
    cluster_id: uuid.UUID | None = None
    cluster_code: str | None = None
    cluster_name: str | None = None
    ai_predicted_yield_kg: Decimal | None = None
    ai_prediction_hive_count: int = Field(
        default=0, description="How many source hives carried an AI yield estimate."
    )
    #: How far the batch has travelled, one field per stage, each derived from the
    #: stage's own records — never from a status somebody typed in. A cluster can
    #: therefore show the whole chain for its honey without opening each batch.
    processing_status: str = "NOT_STARTED"
    processing_status_label: str = "Not started"
    laboratory_status: str = "NOT_STARTED"
    laboratory_status_label: str = "Not started"
    packaging_status: str = "NOT_STARTED"
    packaging_status_label: str = "Not started"
    distribution_status: str = "NOT_STARTED"
    distribution_status_label: str = "Not started"
    packaged_quantity: Decimal = Decimal("0")
    package_count: int = 0
    created_at: datetime


class BatchTraceStage(BaseModel):
    """One stop on the traceability timeline.

    ``state`` answers "how far along is this stage", ``outcome`` answers "how did
    it end" — kept apart so a completed laboratory stage that rejected the batch is
    not reported as an unqualified success.
    """

    stage: BatchStage
    label: str
    state: str = Field(description="'completed', 'current' or 'not_started'.")
    reached: bool = False
    is_current: bool = False
    outcome: str | None = Field(
        default=None,
        description="'APPROVED' or 'REJECTED' for a decided laboratory stage; otherwise None.",
    )
    detail: str | None = Field(
        default=None, description="What actually happened here, when it happened."
    )
    recorded_at: datetime | None = None
    module_available: bool = Field(
        default=False,
        description="False for every stage this phase cannot produce. Rendered as NOT STARTED.",
    )
    note: str | None = None


class BatchAiContext(BaseModel):
    """Predicted yield next to the actual harvest — context, not a score."""

    has_analysis: bool = False
    predicted_yield_kg: Decimal | None = None
    prediction_hive_count: int = 0
    captured_at: datetime | None = None
    actual_quantity: Decimal | None = None
    difference_kg: Decimal | None = Field(
        default=None,
        description=(
            "actual − predicted for this single harvest. It compares one estimate with one "
            "weighed harvest; it says nothing about model accuracy."
        ),
    )
    per_hive: list["BatchAiPerHive"] = Field(default_factory=list)
    note: str | None = None


class BatchAiPerHive(BaseModel):
    hive_id: uuid.UUID
    hive_code: str
    ai_predicted_yield_kg: Decimal | None = None
    quantity: Decimal


class BatchCollectionRef(BaseModel):
    """The collection this batch came from."""

    id: uuid.UUID
    collection_code: str
    status: str
    collection_date: date
    total_quantity: Decimal
    unit: CollectionUnit
    unit_label: str
    completed_at: datetime | None = None
    notes: str | None = None
    source_hive_count: int = 0


class BatchSourceHive(BaseModel):
    """Where this batch's honey actually came from."""

    hive_id: uuid.UUID
    hive_code: str
    hive_status: str | None = None
    quantity: Decimal
    unit: str
    unit_label: str
    contribution_share: float | None = Field(
        default=None, description="This hive's share of the batch, as a fraction."
    )
    village: str | None = None
    district: str | None = None
    beekeeper_code: str | None = None


class BatchHiveRef(BaseModel):
    """A hive a batch traces back to, as the hive registry holds it today."""

    hive_id: uuid.UUID
    hive_code: str
    status: str
    status_label: str
    colony_strength: str | None = None
    village: str | None = None
    district: str | None = None
    beekeeper_code: str | None = None
    note: str | None = Field(
        default=None,
        description="Explains that this is the hive's current registry state, not a harvest-time copy.",
    )


class BatchProcessingRef(BaseModel):
    """The latest processing run on a batch, read from the run itself.

    Present only when a run exists. ``input_quantity`` and ``output_quantity`` are
    ``None`` until someone measured them: the batch's own weight is never copied in
    as a stand-in figure.
    """

    id: uuid.UUID
    processing_code: str
    status: str
    status_label: str
    processing_type: str
    processing_type_label: str
    input_quantity: Decimal | None = None
    output_quantity: Decimal | None = None
    loss_quantity: Decimal | None = Field(
        default=None, description="input − output, stored rather than computed by the reader."
    )
    loss_percent: float | None = None
    unit: str
    unit_label: str
    processing_date: date
    start_time: datetime | None = None
    completion_time: datetime | None = None
    operator_name: str | None = None
    processing_unit_name: str | None = None
    notes: str | None = None


class BatchLabResultRef(BaseModel):
    """One recorded laboratory measurement on a batch's latest test."""

    parameter_code: str
    parameter_name: str
    value: Decimal
    unit: str
    unit_label: str
    status: str
    status_label: str
    evaluated: bool = Field(
        default=False, description="False when no range is configured, so nothing was compared."
    )
    reference_min: Decimal | None = None
    reference_max: Decimal | None = None
    reference_source: str | None = None


class BatchLabTestRef(BaseModel):
    """The latest laboratory test on a batch — results included, values as recorded."""

    id: uuid.UUID
    test_code: str
    sample_code: str
    status: str
    status_label: str
    overall_result: str
    overall_result_label: str
    result_summary: str | None = None
    is_override: bool = False
    round_number: int = 1
    test_date: date
    completed_at: datetime | None = None
    laboratory_name: str | None = None
    technician_name: str | None = None
    sample_quantity: Decimal | None = None
    sample_unit: str | None = None
    sample_unit_label: str | None = None
    parameter_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    unevaluated_count: int = 0
    results: list[BatchLabResultRef] = Field(default_factory=list)

    # -- the quality analysis and what happened to it -----------------------
    ai_status: str | None = Field(
        default=None, description="The analysis verdict: PASS, HOLD, FAIL or INCONCLUSIVE."
    )
    ai_risk_level: str | None = None
    ai_summary: dict | None = Field(
        default=None, description="The stored analysis, with the model, version and source behind it."
    )
    hold_reason: str | None = None
    held_at: datetime | None = None
    held_by: str | None = None
    released_with_risk: bool = False
    risk_override: dict | None = None


class BatchDetail(BatchListItem):
    model_config = ConfigDict(extra="forbid")

    collection: BatchCollectionRef
    sources: list[BatchSourceHive] = Field(default_factory=list)
    ai_context: BatchAiContext
    timeline: list[BatchTraceStage] = Field(default_factory=list)
    prediction_difference_kg: Decimal | None = None
    updated_at: datetime
    #: What was done to the honey and what the laboratory measured. Both are read
    #: from their own records — the batch stores neither, so the three can never
    #: disagree. ``processing`` is None until someone opens a run.
    processing_count: int = 0
    processing: BatchProcessingRef | None = None
    test_count: int = 0
    laboratory: BatchLabTestRef | None = None
    #: Every status this batch may legally move to next, from the platform's
    #: transition table. Empty means the batch is at the end of the journey.
    allowed_next_statuses: list[str] = Field(default_factory=list)
    #: Everything this phase can do to a batch, stated so the client does not guess.
    editable_fields: list[str] = Field(
        default_factory=list, description="Empty: no field of a batch is editable in this phase."
    )
    next_possible_stages: list[str] = Field(
        default_factory=list,
        description=(
            "The stages the batch can actually move to next, from the transition table. "
            "Empty once the batch is finished."
        ),
    )
    #: What packaging and distribution have recorded about this batch, read from
    #: their own rows. ``None`` when nothing has happened yet — no zero-filled
    #: placeholder stands in for work that has not been done.
    packaging: "BatchPackagingRef | None" = None
    distribution: "BatchDistributionRef | None" = None


class BatchPackagingRef(BaseModel):
    """How far this batch has been packed, read from the packaging records.

    Quantities are counted rather than copied: what the laboratory approved is
    the measured output of the completed processing run, what is packed is the
    sum of completed packaging runs, and what remains is the difference.
    """

    run_count: int = 0
    completed_count: int = 0
    open_run_id: uuid.UUID | None = None
    open_run_code: str | None = None
    latest_run_id: uuid.UUID | None = None
    latest_run_code: str | None = None
    latest_status: str | None = None
    latest_status_label: str | None = None
    packaging_type: str | None = None
    packaging_type_label: str | None = None
    packaging_type_other: str | None = None
    #: What to print: the listed container, or the description the run recorded.
    packaging_type_display: str | None = None
    packaging_date: date | None = None
    packaged_quantity: Decimal | None = None
    package_count: int = 0
    approved_quantity: Decimal = Decimal("0")
    packaged_total: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    unit: str | None = None
    unit_label: str | None = None
    packaged_by_name: str | None = None
    packaging_unit_name: str | None = None


class BatchDistributionRef(BaseModel):
    """Where this batch's packages have got to, read from the shipments."""

    shipment_count: int = 0
    delivered_count: int = 0
    open_count: int = 0
    latest_id: uuid.UUID | None = None
    latest_code: str | None = None
    latest_status: str | None = None
    latest_status_label: str | None = None
    destination: str | None = None
    retailer_name: str | None = None
    carrier: str | None = None
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None
    received_by_name: str | None = None
    quantity_dispatched: Decimal = Decimal("0")
    unit: str | None = None
    unit_label: str | None = None


class BatchSummary(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    collected: int = 0
    batched_totals: dict[str, float] = Field(default_factory=dict)
    awaiting_collection_completion: int = Field(
        default=0, description="Open collections that have no batch yet."
    )


__all__ = [
    "BatchListItem",
    "BatchDetail",
    "BatchSummary",
    "BatchAiContext",
    "BatchHiveRef",
    "BatchAiPerHive",
    "BatchCollectionRef",
    "BatchSourceHive",
    "BatchTraceStage",
    "BatchLabResultRef",
    "BatchLabTestRef",
    "BatchProcessingRef",
]

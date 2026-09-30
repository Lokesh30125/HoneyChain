"""Response models for the traceability layer.

The read models say what a screen may render: a transaction as the Admin or KVIC
ledger shows it (with its payload and its chain status), the raw ledger rows as
the chain itself reports them, health, and a batch's traceability. The public
customer page has its own model (:class:`PublicTrace`) because its fields are a
deliberately smaller set — what a buyer may see, and nothing else.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BlockchainEventRead(BaseModel):
    """One traceability event, as HoneyChain recorded it and the chain holds it."""

    id: str
    event_id: str
    tx_type: str
    tx_type_label: str
    tx_id: str | None = None
    status: str = Field(description="PENDING, SUBMITTED, CONFIRMED, FAILED or SKIPPED.")
    status_label: str
    batch_id: str | None = None
    batch_code: str | None = None
    collection_id: str | None = None
    processing_id: str | None = None
    lab_test_id: str | None = None
    packaging_id: str | None = None
    package_id: str | None = None
    distribution_id: str | None = None
    cluster_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    attempt_count: int = 0
    last_error: str | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    confirmed_at: datetime | None = None


class BlockchainTransactionRead(BaseModel):
    """A transaction as the blockchain service reports it — the raw ledger."""

    tx_id: str
    tx_type: str
    batch_id: str | None = None
    timestamp: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    #: Whether this transaction is one HoneyChain recorded, and under which
    #: event. Absent for the transactions written before this platform wrote any
    #: — those are shown, described as unlinked, and never attached to a batch.
    matched_event_id: str | None = None
    matched_batch_code: str | None = None
    honey_chain_recorded: bool = False


class BlockchainHealthRead(BaseModel):
    """What the service says about itself, and what HoneyChain owes it."""

    service: dict[str, Any]
    honeychain: dict[str, Any]


class BatchTraceabilityRead(BaseModel):
    """One batch's records, its traceability events and the timeline they make."""

    batch: dict[str, Any]
    #: Set when the answer is narrowed to one package of the batch.
    package_code: str | None = None
    transactions: list[BlockchainEventRead]
    blockchain: dict[str, Any]
    timeline: list[dict[str, Any]]
    packages: list[dict[str, Any]]
    #: The real record behind every stage — cluster, collection, beekeeper,
    #: source hives, processing, laboratory, packaging, packages, shipments and
    #: retailer receipts — plus a one-line-per-stage summary (``stages``).
    chain: dict[str, Any] = Field(default_factory=dict)


class PackageQrRead(BaseModel):
    """A package's QR identity and the label itself."""

    package_code: str
    #: The stable public id of the label, derived from the package code
    #: (``QR-HC-PKG-2026-000001``). Stable across reprints and refreshes.
    qr_id: str
    batch_code: str | None = None
    qr_payload: str | None = None
    generated_at: datetime | None = None
    scans: int = 0
    svg: str = Field(description="The QR label as an inline SVG, ready to print.")
    event_id: str | None = Field(
        default=None, description="The traceability event that records this QR."
    )
    tx_id: str | None = None


class PublicTraceStage(BaseModel):
    stage: str
    label: str
    reached: bool
    at: str | None = None
    detail: str | None = None
    outcome: str | None = None


class PublicTraceTransaction(BaseModel):
    event_id: str
    tx_type: str
    tx_id: str | None = None
    status: str
    timestamp: str | None = None
    synchronized: bool


class PublicTrace(BaseModel):
    """The customer's view: where this honey came from, and what is on the ledger.

    Field names here are the contract for the public page; nothing outside this
    model is shown to a customer.
    """

    package: dict[str, Any]
    product: dict[str, Any]
    source: dict[str, Any]
    processing: list[dict[str, Any]]
    laboratory: list[dict[str, Any]]
    packaging: dict[str, Any]
    distribution: list[dict[str, Any]]
    timeline: list[PublicTraceStage]
    blockchain: dict[str, Any]
    qr: dict[str, Any]
    #: Whether this package may be published at all, and why not when it may not
    #: (a cancelled package). A page shows the public journey only when it is
    #: available.
    verification: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BatchTraceabilityRead",
    "BlockchainEventRead",
    "BlockchainHealthRead",
    "BlockchainTransactionRead",
    "PackageQrRead",
    "PublicTrace",
    "PublicTraceStage",
    "PublicTraceTransaction",
]

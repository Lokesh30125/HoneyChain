"""``blockchain_events`` — HoneyChain's own record of what it put on the ledger.

The blockchain service keeps the ledger. This table keeps HoneyChain's side of
the conversation with it, and it exists for three reasons that are all about
honesty rather than bookkeeping:

**Nothing is lost when the chain is unreachable.** A harvest is completed, a
batch is created, a shipment is dispatched — those are the facts, and they are
committed to HoneyChain's own tables whether or not the blockchain service
answers. The event row is written in the *same transaction* as the record
change, so the pair can never disagree: there is no window in which the honey
moved and nothing remembers that it did. What is left is a row in ``PENDING``,
which a worker retries until the ledger accepts it.

**Nothing is written twice.** ``event_id`` is unique and derived from the record
the event is about (``BATCH-…-CREATED``, ``DIST-…-DISPATCHED``). A double-click,
a browser retry, a page refresh, an API retry, a worker restart or a second tab
all land on the same row: the second attempt sees the existing event and reuses
its transaction id instead of submitting a duplicate.

**The ledger can be read without the chain being up.** The Admin ledger and a
batch's traceability are answered from these rows, which is what makes them
fast, scopeable by cluster, and available during an outage — the response says
``CONFIRMED`` for what the chain accepted, ``PENDING`` for what is waiting, and
``FAILED`` with the actual error for what it refused. It never says "verified"
about a row that was not.

What is *not* here
------------------
No second copy of the supply chain. There is one collection, one batch, one
processing run, one lab test, one packaging run, one package and one shipment in
this database, and this table points at them by foreign key — it does not
restate them. The payload column keeps the JSON that was actually submitted,
because that is a different fact from the record (it is what the chain holds),
and an auditor comparing the two is the whole point.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUID_TYPE, UUIDPrimaryKeyMixin
from app.models.enums import BlockchainEventType, BlockchainStatus

BLOCKCHAIN_STATUS_ENUM = SAEnum(
    BlockchainStatus,
    name="blockchain_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)

BLOCKCHAIN_EVENT_TYPE_ENUM = SAEnum(
    BlockchainEventType,
    name="blockchain_event_type",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
    native_enum=True,
    validate_strings=True,
)

#: Longest payload we will submit, in characters of serialised JSON. A
#: traceability event is a summary, not a document: if a payload crosses this
#: line something is being put on the chain that should not be (telemetry, a
#: laboratory report), and the event is refused loudly rather than truncated.
MAX_PAYLOAD_CHARACTERS = 8000


class BlockchainEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One traceability event, in HoneyChain's database and (once accepted) on
    the blockchain."""

    __tablename__ = "blockchain_events"
    __table_args__ = (
        # The idempotency key. Two attempts to record the same logical event —
        # however they arrive — collide here and resolve to one row.
        UniqueConstraint("event_id", name="uq_blockchain_events_event_id"),
        Index("ix_blockchain_events_batch", "batch_id"),
        Index("ix_blockchain_events_cluster", "cluster_id"),
        Index("ix_blockchain_events_status", "status"),
        Index("ix_blockchain_events_type", "tx_type"),
        Index("ix_blockchain_events_tx_id", "tx_id"),
        # The worker's query: oldest pending first.
        Index("ix_blockchain_events_status_created", "status", "created_at"),
    )

    # -- Identity ----------------------------------------------------------- #
    event_id: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        doc=(
            "Idempotency key, e.g. ``BATCH-HC-BATCH-2026-000001-CREATED``. Derived "
            "from the record the event describes, never random, so the same logical "
            "event always has the same key."
        ),
    )
    tx_type: Mapped[BlockchainEventType] = mapped_column(
        BLOCKCHAIN_EVENT_TYPE_ENUM,
        nullable=False,
        doc="The event type submitted to the blockchain service.",
    )

    # -- What it is about --------------------------------------------------- #
    # Every link is a real foreign key to the single record the event describes.
    # ON DELETE SET NULL: retiring a record must not erase the traceability of
    # what happened; the codes below keep the event readable afterwards.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("honey_batches.id", ondelete="SET NULL"),
        nullable=True,
        doc="The honey batch this event belongs to.",
    )
    batch_code: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        doc="The batch code, kept beside the id so the event reads correctly even "
        "if the batch row is ever removed.",
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("honey_collections.id", ondelete="SET NULL"), nullable=True
    )
    processing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("honey_processing_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    lab_test_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("lab_tests.id", ondelete="SET NULL"), nullable=True
    )
    packaging_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("packaging_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("packages.id", ondelete="SET NULL"), nullable=True
    )
    distribution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("distributions.id", ondelete="SET NULL"),
        nullable=True,
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("kvic_clusters.id", ondelete="SET NULL"),
        nullable=True,
        doc="The cluster the batch belongs to, denormalised so an officer's "
        "ledger is one indexed filter instead of a join through four tables "
        "that may themselves be missing a link.",
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="The account whose action produced the event. Kept for the audit "
        "ledger; never exposed on the public traceability page.",
    )

    # -- What was submitted ------------------------------------------------- #
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="The exact JSON body submitted for this event, as the chain holds it.",
    )

    # -- Where it stands ---------------------------------------------------- #
    status: Mapped[BlockchainStatus] = mapped_column(
        BLOCKCHAIN_STATUS_ENUM,
        nullable=False,
        default=BlockchainStatus.PENDING,
        doc="PENDING → SUBMITTED → CONFIRMED, or FAILED with the reason kept.",
    )
    tx_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        doc="The transaction id the blockchain service returned. Never invented.",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, doc="Submission attempts so far."
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="The actual failure from the last attempt, shown to an operator so a "
        "retry is a decision rather than a guess.",
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When the last attempt was sent."
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the ledger accepted it. The only timestamp that may be labelled "
        "'recorded on chain'.",
    )

    # -- Relationships (read-only navigation for the ledger) ---------------- #
    batch = relationship("HoneyBatch", lazy="joined", viewonly=True)
    package = relationship("HoneyPackage", lazy="joined", viewonly=True)
    distribution = relationship("Distribution", lazy="joined", viewonly=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<BlockchainEvent {self.event_id} {self.tx_type} {self.status}"
            f" tx_id={self.tx_id}>"
        )

    @property
    def is_confirmed(self) -> bool:
        return self.status is BlockchainStatus.CONFIRMED and bool(self.tx_id)

    @property
    def subject_code(self) -> str | None:
        """The most specific identifier this event is about, for a ledger row."""
        for candidate in (
            self.batch_code,
            self.event_id,
        ):
            if candidate:
                return candidate
        return None


__all__ = [
    "BLOCKCHAIN_EVENT_TYPE_ENUM",
    "BLOCKCHAIN_STATUS_ENUM",
    "MAX_PAYLOAD_CHARACTERS",
    "BlockchainEvent",
]

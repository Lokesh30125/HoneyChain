"""Phase 8 — blockchain traceability: the event outbox and a package's QR identity

The blockchain service keeps the ledger. This migration adds HoneyChain's own
record of the conversation with it, and the identity a package's QR code carries.

``blockchain_events``
    One row per real supply-chain transition: the type, the record it is about
    (foreign keys to the *existing* tables — no second supply chain lives here),
    the payload that was submitted, and where the submission stands. Written in
    the same transaction as the record change that caused it, so an event and the
    fact it describes can never disagree.

    ``event_id`` is unique and derived from the record (``BATCH-<code>-CREATED``),
    which is what makes the whole layer idempotent: a double-click, a retry, a
    worker restart or two browser tabs all resolve to one row. ``tx_id`` is the
    blockchain service's own identifier and is only ever written from its answer,
    so a row shows ``CONFIRMED`` because the chain said so, never because the
    platform hoped so.

``packages.qr_payload`` and friends
    A package's public identity: the link its QR encodes, when the identity was
    issued, and how many times the page has been opened. Stored on the package
    because that is what the code resolves to — there is no separate QR table,
    and the label cannot drift away from the record it names.

Both are additive. Nothing existing is altered, nothing is backfilled: a package
packed before this migration simply has no QR yet, which is the truth about it
and is what the screens say. Existing ledger entries on the blockchain service
are untouched — the integration writes new transactions and reads the old ones,
and never rewrites either.

Revision ID: 9b1f4c2d7e05
Revises: 7c1d90ab5f21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9b1f4c2d7e05"
down_revision: str | None = "7c1d90ab5f21"
branch_labels = None
depends_on = None

BLOCKCHAIN_STATUS = postgresql.ENUM(
    "PENDING", "SUBMITTED", "CONFIRMED", "FAILED", "SKIPPED",
    name="blockchain_status",
    create_type=False,
)

BLOCKCHAIN_EVENT_TYPE = postgresql.ENUM(
    "COLLECTION_COMPLETED",
    "BATCH_CREATED",
    "PROCESSING_STARTED",
    "PROCESSING_COMPLETED",
    "LAB_TEST_STARTED",
    "QUALITY_CHECKED",
    "QUALITY_FAILED",
    "QUALITY_HOLD",
    "PROCEEDED_WITH_RISK",
    "PACKAGING_STARTED",
    "PACKAGE_CREATED",
    "PACKAGED",
    "DISTRIBUTION_CREATED",
    "DISTRIBUTION_DISPATCHED",
    "IN_TRANSIT",
    "DELIVERED",
    "RETAILER_RECEIVED",
    "QR_GENERATED",
    "CUSTOMER_QR_VERIFIED",
    name="blockchain_event_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    BLOCKCHAIN_STATUS.create(bind, checkfirst=True)
    BLOCKCHAIN_EVENT_TYPE.create(bind, checkfirst=True)

    op.create_table(
        "blockchain_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("tx_type", BLOCKCHAIN_EVENT_TYPE, nullable=False),
        sa.Column("batch_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("batch_code", sa.String(length=40), nullable=True),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("processing_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("lab_test_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("packaging_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("package_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("distribution_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("cluster_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("actor_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", BLOCKCHAIN_STATUS, nullable=False),
        sa.Column("tx_id", sa.String(length=200), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        # Every reference is to an existing record. SET NULL, not CASCADE: nothing
        # is ever deleted through this table, and retiring a record must not take
        # the traceability of what happened with it.
        sa.ForeignKeyConstraint(
            ["batch_id"], ["honey_batches.id"], name="fk_blockchain_events_batch_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["honey_collections.id"],
            name="fk_blockchain_events_collection_id", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["processing_id"], ["honey_processing_records.id"],
            name="fk_blockchain_events_processing_id", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lab_test_id"], ["lab_tests.id"], name="fk_blockchain_events_lab_test_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["packaging_id"], ["packaging_records.id"],
            name="fk_blockchain_events_packaging_id", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"], ["packages.id"], name="fk_blockchain_events_package_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["distribution_id"], ["distributions.id"],
            name="fk_blockchain_events_distribution_id", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"], ["kvic_clusters.id"], name="fk_blockchain_events_cluster_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_blockchain_events_actor_id", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("event_id", name="uq_blockchain_events_event_id"),
    )
    op.create_index("ix_blockchain_events_batch", "blockchain_events", ["batch_id"])
    op.create_index("ix_blockchain_events_cluster", "blockchain_events", ["cluster_id"])
    op.create_index("ix_blockchain_events_status", "blockchain_events", ["status"])
    op.create_index("ix_blockchain_events_type", "blockchain_events", ["tx_type"])
    op.create_index("ix_blockchain_events_tx_id", "blockchain_events", ["tx_id"])
    op.create_index(
        "ix_blockchain_events_status_created", "blockchain_events", ["status", "created_at"]
    )

    op.add_column("packages", sa.Column("qr_payload", sa.String(length=300), nullable=True))
    op.add_column("packages", sa.Column("qr_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "packages",
        sa.Column("qr_scan_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("packages", sa.Column("qr_last_scanned_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("packages", "qr_last_scanned_at")
    op.drop_column("packages", "qr_scan_count")
    op.drop_column("packages", "qr_generated_at")
    op.drop_column("packages", "qr_payload")

    op.drop_index("ix_blockchain_events_status_created", table_name="blockchain_events")
    op.drop_index("ix_blockchain_events_tx_id", table_name="blockchain_events")
    op.drop_index("ix_blockchain_events_type", table_name="blockchain_events")
    op.drop_index("ix_blockchain_events_status", table_name="blockchain_events")
    op.drop_index("ix_blockchain_events_cluster", table_name="blockchain_events")
    op.drop_index("ix_blockchain_events_batch", table_name="blockchain_events")
    op.drop_table("blockchain_events")

    bind = op.get_bind()
    BLOCKCHAIN_EVENT_TYPE.drop(bind, checkfirst=True)
    BLOCKCHAIN_STATUS.drop(bind, checkfirst=True)

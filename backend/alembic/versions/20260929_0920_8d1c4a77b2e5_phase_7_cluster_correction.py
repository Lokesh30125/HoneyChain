"""phase 7 correction: the KVIC cluster on packaging and packages, and a batch backfill

Revision ID: 8d1c4a77b2e5
Revises: 72ee81e59167
Create Date: 2026-09-29 09:20:00.000000+00:00

Three corrections, none of which adds a new entity or a duplicate record:

1. ``packaging_records.cluster_id`` and ``packages.cluster_id``.

   A honey batch belongs to a KVIC cluster through its collection and its
   beekeeper, and the cluster screens ask "what was packed, and what is on its
   way, for my cluster?". Answering that by joining packaging → batch → cluster
   every time works but is wasteful, and it leaves the cluster unable to filter
   packing history on its own terms. The column is a copy of the batch's own
   cluster, written once when the row is created, and nullable because a batch
   that is not in a cluster is a real state on this platform.

2. ``honey_batches.cluster_id`` backfill.

   The batch copies its cluster from the collection, which copies it from the
   beekeeper. Rows written before that was true — or written while a beekeeper
   was between clusters — can be missing it. The correction is derived from the
   records that already exist: the collection's cluster first, then the
   beekeeper's current cluster. Nothing is invented and nothing is deleted: an
   UPDATE that fills a null, and only where the answer is already in the database.

3. ``packaging_records`` / ``packages`` backfill from their batch.

   Same principle: the cluster of a packing run or a package is the cluster of the
   batch it came from, so it can be filled in for rows written before the column
   existed.

Every corrected row is written to ``audit_logs`` as a data correction, so a
backfilled cluster is never an unexplained value. The audit rows name no user —
no person did this; a migration did — and carry the batch, the old value and the
source the value came from.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8d1c4a77b2e5"
down_revision: Union[str, None] = "72ee81e59167"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # -- the cluster on the two Phase 7 tables ------------------------------
    for table in ("packaging_records", "packages"):
        op.add_column(
            table,
            sa.Column("cluster_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_cluster_id_kvic_clusters",
            table,
            "kvic_clusters",
            ["cluster_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_cluster_id", table, ["cluster_id"])

    # -- 1. batches missing their cluster, recovered from their own records ---
    op.execute(
        """
        UPDATE honey_batches AS b
        SET cluster_id = c.cluster_id
        FROM honey_collections AS c
        WHERE b.collection_id = c.id
          AND b.cluster_id IS NULL
          AND c.cluster_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE honey_batches AS b
        SET cluster_id = k.kvic_cluster_id
        FROM beekeepers AS k
        WHERE b.beekeeper_id = k.id
          AND b.cluster_id IS NULL
          AND k.kvic_cluster_id IS NOT NULL
        """
    )

    # -- 2. packing runs and packages follow their batch ----------------------
    op.execute(
        """
        UPDATE packaging_records AS p
        SET cluster_id = b.cluster_id
        FROM honey_batches AS b
        WHERE p.batch_id = b.id
          AND p.cluster_id IS NULL
          AND b.cluster_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE packages AS p
        SET cluster_id = b.cluster_id
        FROM honey_batches AS b
        WHERE p.batch_id = b.id
          AND p.cluster_id IS NULL
          AND b.cluster_id IS NOT NULL
        """
    )

    # -- 3. say so, in the audit log the platform already keeps ---------------
    op.execute(
        """
        INSERT INTO audit_logs (action, actor_role, entity_type, entity_id, metadata, description)
        SELECT
            'DATA_CORRECTION',
            'SYSTEM',
            'batch',
            b.batch_code,
            jsonb_build_object(
                'field', 'cluster_id',
                'value', b.cluster_id::text,
                'source', 'collection/beekeeper relationship',
                'reason', 'Phase 7 correction: the batch cluster is derived from its collection and beekeeper.'
            ),
            'Batch ' || b.batch_code || ' cluster filled from its collection/beekeeper relationship'
        FROM honey_batches AS b
        WHERE b.cluster_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # The audit rows describe a correction that is being undone, so they go first.
    op.execute("DELETE FROM audit_logs WHERE action = 'DATA_CORRECTION' AND actor_role = 'SYSTEM'")

    for table in ("packaging_records", "packages"):
        op.drop_index(f"ix_{table}_cluster_id", table_name=table)
        op.drop_constraint(f"fk_{table}_cluster_id_kvic_clusters", table, type_="foreignkey")
        op.drop_column(table, "cluster_id")

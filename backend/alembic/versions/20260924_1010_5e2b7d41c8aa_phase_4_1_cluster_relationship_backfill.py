"""Phase 4.1 — backfill the organisational relationship on existing hives.

What this migration does, and why it is data-only
-------------------------------------------------
Phase 4.1 establishes one source of truth for the chain

``KVIC → Cluster → Beekeeper → Hive → IoT Device → Telemetry → AI Analysis``.

The schema for that chain already exists: ``beekeepers.kvic_cluster_id`` and
``hives.cluster_id`` are real foreign keys, both indexed, with
``ix_hives_cluster_status`` available for the cluster dashboards. Nothing new has
to be created, and — importantly — nothing new *should* be: a second table of
"KVIC hives" or "KVIC telemetry" would be exactly the duplication this phase
exists to prevent.

What was missing is historical: hives registered before a beekeeper was placed in
a cluster keep ``cluster_id = NULL`` (the hive inherits its owner's cluster at
creation time, and at that moment the owner had none). This migration repairs
that one gap by copying the relationship the database already knows — the hive's
owner's cluster — onto the hive.

Two rules it follows:

* **It never invents a cluster.** Hives whose owner still has no cluster stay
  ``NULL``. They are listed for administrative resolution
  (``GET /api/v1/hives?has_cluster=false``) instead of being attached somewhere
  plausible.
* **It never overwrites a placement.** Only rows that are currently ``NULL`` are
  touched, so a hive deliberately placed by staff keeps its cluster.

Downgrade deliberately does nothing: the values this writes are the correct ones
for the relationship, and clearing them would make hives that are visible to a
cluster today invisible tomorrow. Reversing data loss is not something a
downgrade should do silently.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e2b7d41c8aa"
down_revision: Union[str, None] = "a77f6c38aaff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Give every hive the cluster its owner already belongs to.

    Runs as one ``UPDATE ... FROM`` so the whole relationship is resolved in the
    database: no row-by-row loop, no Python in the middle, and the statement is
    idempotent — running it twice changes nothing the second time.
    """
    op.execute(
        """
        UPDATE hives
           SET cluster_id = beekeepers.kvic_cluster_id,
               updated_at = NOW()
          FROM beekeepers
         WHERE hives.beekeeper_id = beekeepers.id
           AND hives.cluster_id IS NULL
           AND beekeepers.kvic_cluster_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """No-op by design — see the module docstring.

    The backfilled values *are* the relationship. Removing them would hide hives
    from the cluster that owns them, which is data loss dressed as a rollback.
    """

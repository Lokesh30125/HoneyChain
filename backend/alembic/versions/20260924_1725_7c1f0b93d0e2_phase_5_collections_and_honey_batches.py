"""phase 5: collections and honey batches

Revision ID: 7c1f0b93d0e2
Revises: 5e2b7d41c8aa
Create Date: 2026-09-24 17:25:06.950836+00:00

Creates the three tables Phase 5 needs and nothing else — no processing, no
laboratory, no packaging, no distribution, no QR and no blockchain table exists
because none of those modules is built:

* ``honey_collections`` — one row per harvest event: the beekeeper who took the
  honey, the cluster that beekeeper belonged to at the time, the date, the
  quantity actually harvested, the unit, the status and the AI estimate that
  existed when it was recorded (kept in its own columns, never merged into the
  harvested figure);
* ``honey_collection_hives`` — one row **per contributing hive**, with the
  quantity measured at that hive, so "22.5 kg from 3 hives" stays queryable down
  to each hive instead of collapsing into a count;
* ``honey_batches`` — the traceable unit a completed collection produces. Its
  ``collection_id`` is UNIQUE, which is what makes one batch per completed
  collection a database guarantee rather than a convention, and it is what makes a
  retried completion idempotent under concurrency.

The quantities are ``NUMERIC(10,3)``: a harvest is weighed to the gram and is
never a float, so a total is exact and adding two contributions is arithmetic
rather than a rounding exercise.

Four PostgreSQL enum types are created explicitly and dropped on downgrade,
matching the Phase 2/3/4 pattern: ``drop_table`` does not remove a type, so
without the explicit drop a later ``upgrade`` would fail with "type ... already
exists".

``honey_collection_hives.hive_id`` is ``ON DELETE RESTRICT``: a hive that
contributed honey to a recorded harvest cannot be hard-deleted out from under the
batch that came from it. Retiring a hive (status ``REMOVED``) remains available in
the registry, so history is never broken by a delete.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7c1f0b93d0e2'
down_revision: Union[str, None] = '5e2b7d41c8aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: PostgreSQL enum types introduced by this migration. Created once below and
#: referenced with ``create_type=False`` so a repeated upgrade cannot attempt a
#: second ``CREATE TYPE``.
collection_status_enum = postgresql.ENUM(
    "PLANNED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    name="collection_status",
    create_type=False,
)
collection_unit_enum = postgresql.ENUM(
    "KG",
    "GRAM",
    name="collection_unit",
    create_type=False,
)
batch_status_enum = postgresql.ENUM(
    "COLLECTED",
    "PROCESSING",
    "LAB_TESTING",
    "PACKAGED",
    "DISTRIBUTION",
    "COMPLETED",
    "REJECTED",
    name="batch_status",
    create_type=False,
)
batch_stage_enum = postgresql.ENUM(
    "COLLECTION",
    "PROCESSING",
    "LABORATORY",
    "PACKAGING",
    "DISTRIBUTION",
    "COMPLETED",
    name="batch_stage",
    create_type=False,
)

ALL_ENUMS = (
    collection_status_enum,
    collection_unit_enum,
    batch_status_enum,
    batch_stage_enum,
)


def upgrade() -> None:
    bind = op.get_bind()

    for enum_type in ALL_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # ------------------------------------------------------------------ #
    # honey_collections — one harvest event
    # ------------------------------------------------------------------ #
    op.create_table(
        "honey_collections",
        sa.Column("collection_code", sa.String(length=40), nullable=False),
        sa.Column("client_reference", sa.String(length=64), nullable=True),
        sa.Column(
            "beekeeper_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "cluster_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column("collection_date", sa.Date(), nullable=False),
        sa.Column("total_quantity", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("unit", collection_unit_enum, server_default="KG", nullable=False),
        sa.Column("status", collection_status_enum, server_default="PLANNED", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ai_predicted_yield_kg", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("ai_prediction_hive_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ai_prediction_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=200), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_quantity > 0",
            name=op.f("ck_honey_collections_collection_total_quantity_positive"),
        ),
        sa.CheckConstraint(
            "ai_predicted_yield_kg IS NULL OR ai_predicted_yield_kg >= 0",
            name=op.f("ck_honey_collections_collection_predicted_yield_non_negative"),
        ),
        sa.CheckConstraint(
            "ai_prediction_hive_count >= 0",
            name=op.f("ck_honey_collections_collection_prediction_hive_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["beekeeper_id"],
            ["beekeepers.id"],
            name=op.f("fk_honey_collections_beekeeper_id_beekeepers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["kvic_clusters.id"],
            name=op.f("fk_honey_collections_cluster_id_kvic_clusters"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_honey_collections")),
        sa.UniqueConstraint(
            "beekeeper_id", "client_reference", name="collection_client_reference_per_beekeeper"
        ),
    )
    op.create_index(
        "ix_collections_beekeeper_date",
        "honey_collections",
        ["beekeeper_id", "collection_date"],
        unique=False,
    )
    op.create_index(
        "ix_collections_cluster_date",
        "honey_collections",
        ["cluster_id", "collection_date"],
        unique=False,
    )
    op.create_index(
        "ix_collections_status_date", "honey_collections", ["status", "collection_date"], unique=False
    )
    op.create_index(
        op.f("ix_honey_collections_beekeeper_id"), "honey_collections", ["beekeeper_id"], unique=False
    )
    op.create_index(
        op.f("ix_honey_collections_cluster_id"), "honey_collections", ["cluster_id"], unique=False
    )
    # Unique at the database level, not only by convention: a duplicate collection
    # code cannot exist even if two requests race for the same sequence value.
    op.create_index(
        op.f("ix_honey_collections_collection_code"),
        "honey_collections",
        ["collection_code"],
        unique=True,
    )
    op.create_index(
        op.f("ix_honey_collections_collection_date"),
        "honey_collections",
        ["collection_date"],
        unique=False,
    )
    op.create_index(op.f("ix_honey_collections_status"), "honey_collections", ["status"], unique=False)

    # ------------------------------------------------------------------ #
    # honey_collection_hives — the source hives, one row each
    # ------------------------------------------------------------------ #
    op.create_table(
        "honey_collection_hives",
        sa.Column(
            "collection_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "hive_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column("hive_code", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("ai_predicted_yield_kg", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column(
            "ai_analysis_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column("notes", sa.String(length=200), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0", name=op.f("ck_honey_collection_hives_collection_hive_quantity_positive")
        ),
        sa.CheckConstraint(
            "ai_predicted_yield_kg IS NULL OR ai_predicted_yield_kg >= 0",
            name=op.f("ck_honey_collection_hives_collection_hive_predicted_yield_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["honey_collections.id"],
            name=op.f("fk_honey_collection_hives_collection_id_honey_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hive_id"],
            ["hives.id"],
            name=op.f("fk_honey_collection_hives_hive_id_hives"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ai_analysis_id"],
            ["hive_ai_analyses.id"],
            name=op.f("fk_honey_collection_hives_ai_analysis_id_hive_ai_analyses"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_honey_collection_hives")),
        # One row per hive per harvest: the same hive cannot contribute twice,
        # which is what makes the collection total a trustworthy sum.
        sa.UniqueConstraint(
            "collection_id", "hive_id", name="collection_hive_unique_per_collection"
        ),
    )
    op.create_index(
        "ix_collection_hives_hive_created",
        "honey_collection_hives",
        ["hive_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_honey_collection_hives_collection_id"),
        "honey_collection_hives",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_honey_collection_hives_hive_id"), "honey_collection_hives", ["hive_id"], unique=False
    )

    # ------------------------------------------------------------------ #
    # honey_batches — the traceable unit
    # ------------------------------------------------------------------ #
    op.create_table(
        "honey_batches",
        sa.Column("batch_code", sa.String(length=40), nullable=False),
        sa.Column(
            "collection_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "beekeeper_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "cluster_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column("collection_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("unit", collection_unit_enum, nullable=False),
        sa.Column("status", batch_status_enum, server_default="COLLECTED", nullable=False),
        sa.Column("current_stage", batch_stage_enum, server_default="COLLECTION", nullable=False),
        sa.Column("source_hive_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ai_predicted_yield_kg", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("ai_prediction_hive_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prediction_difference_kg", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_honey_batches_batch_quantity_positive")),
        sa.CheckConstraint(
            "source_hive_count >= 0", name=op.f("ck_honey_batches_batch_source_hive_count_non_negative")
        ),
        sa.CheckConstraint(
            "ai_predicted_yield_kg IS NULL OR ai_predicted_yield_kg >= 0",
            name=op.f("ck_honey_batches_batch_predicted_yield_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["honey_collections.id"],
            name=op.f("fk_honey_batches_collection_id_honey_collections"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["beekeeper_id"],
            ["beekeepers.id"],
            name=op.f("fk_honey_batches_beekeeper_id_beekeepers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["kvic_clusters.id"],
            name=op.f("fk_honey_batches_cluster_id_kvic_clusters"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_honey_batches")),
    )
    op.create_index(
        "ix_batches_beekeeper_date", "honey_batches", ["beekeeper_id", "collection_date"], unique=False
    )
    op.create_index(
        "ix_batches_cluster_date", "honey_batches", ["cluster_id", "collection_date"], unique=False
    )
    op.create_index(
        "ix_batches_status_date", "honey_batches", ["status", "collection_date"], unique=False
    )
    op.create_index(op.f("ix_honey_batches_batch_code"), "honey_batches", ["batch_code"], unique=True)
    op.create_index(op.f("ix_honey_batches_beekeeper_id"), "honey_batches", ["beekeeper_id"], unique=False)
    op.create_index(op.f("ix_honey_batches_cluster_id"), "honey_batches", ["cluster_id"], unique=False)
    op.create_index(
        op.f("ix_honey_batches_collection_date"), "honey_batches", ["collection_date"], unique=False
    )
    # One batch per collection — the guarantee that a retried completion cannot
    # produce a second batch, enforced by the database rather than by the service.
    op.create_index(
        op.f("ix_honey_batches_collection_id"), "honey_batches", ["collection_id"], unique=True
    )
    op.create_index(op.f("ix_honey_batches_status"), "honey_batches", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_honey_batches_status"), table_name="honey_batches")
    op.drop_index(op.f("ix_honey_batches_collection_id"), table_name="honey_batches")
    op.drop_index(op.f("ix_honey_batches_collection_date"), table_name="honey_batches")
    op.drop_index(op.f("ix_honey_batches_cluster_id"), table_name="honey_batches")
    op.drop_index(op.f("ix_honey_batches_beekeeper_id"), table_name="honey_batches")
    op.drop_index(op.f("ix_honey_batches_batch_code"), table_name="honey_batches")
    op.drop_index("ix_batches_status_date", table_name="honey_batches")
    op.drop_index("ix_batches_cluster_date", table_name="honey_batches")
    op.drop_index("ix_batches_beekeeper_date", table_name="honey_batches")
    op.drop_table("honey_batches")

    op.drop_index(op.f("ix_honey_collection_hives_hive_id"), table_name="honey_collection_hives")
    op.drop_index(op.f("ix_honey_collection_hives_collection_id"), table_name="honey_collection_hives")
    op.drop_index("ix_collection_hives_hive_created", table_name="honey_collection_hives")
    op.drop_table("honey_collection_hives")

    op.drop_index(op.f("ix_honey_collections_status"), table_name="honey_collections")
    op.drop_index(op.f("ix_honey_collections_collection_date"), table_name="honey_collections")
    op.drop_index(op.f("ix_honey_collections_collection_code"), table_name="honey_collections")
    op.drop_index(op.f("ix_honey_collections_cluster_id"), table_name="honey_collections")
    op.drop_index(op.f("ix_honey_collections_beekeeper_id"), table_name="honey_collections")
    op.drop_index("ix_collections_status_date", table_name="honey_collections")
    op.drop_index("ix_collections_cluster_date", table_name="honey_collections")
    op.drop_index("ix_collections_beekeeper_date", table_name="honey_collections")
    op.drop_table("honey_collections")

    # ``drop_table`` never removes a PostgreSQL enum type; without this a later
    # ``upgrade`` would fail with "type ... already exists".
    for enum_type in reversed(ALL_ENUMS):
        enum_type.drop(op.get_bind(), checkfirst=True)

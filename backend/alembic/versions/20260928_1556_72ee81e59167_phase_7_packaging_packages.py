"""phase 7: packaging, packages and distribution

Revision ID: 72ee81e59167
Revises: c4a1e7d29b03
Create Date: 2026-09-28 15:56:42.149601+00:00

Adds the downstream half of the chain: what happens to a batch *after* the
laboratory approves it.

Three tables, split along the lines the supply chain draws:

``packaging_units``
    The place where packing happens — the same shape as ``processing_units`` and
    ``laboratories``, because a facility is a facility whatever stage it serves.
    Deliberately small: a packaging record needs a reference to where the work
    happened, not a facility-management system.

``packaging_records``
    One packing operation on one approved batch: what was drawn from the batch,
    what left as packages, the package size, the count, and who did it. A batch
    may be packed in several runs, which is why this is a table and not columns
    on the batch — and why a partial unique index allows only one *open* run per
    batch at a time.

``packages``
    One row per physical package, created when a packaging run completes, each
    with its own stable ``package_code``. ``packaging_id`` and ``batch_id`` keep
    the package attached to the operation that made it and the honey it came
    from, so the chain ``package → packaging → batch → collection → hive →
    beekeeper → cluster`` is a walk over foreign keys rather than a copy.

``distributions``
    One shipment line: a package, a quantity, a destination, a carrier, a
    retailer account when the destination is one, and the timestamps of the
    journey. Partial distribution needs no extra table — what a package still has
    unshipped is the difference between its quantity and the sum of its
    non-cancelled shipments.

What is deliberately *not* here: no ledger, no hash, no QR payload, no trust
score. Later phases add those; what this one leaves them is stable identifiers,
timestamps and audit rows. No existing table is altered except for four new
PostgreSQL enum types, and no quantity anywhere is rewritten — what was
harvested, what was processed and what was packed are three recorded facts.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "72ee81e59167"
down_revision: Union[str, None] = "c4a1e7d29b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PACKAGING_STATUS = postgresql.ENUM(
    "PENDING",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    name="packaging_status",
    create_type=False,
)
PACKAGING_TYPE = postgresql.ENUM(
    "JAR",
    "BOTTLE",
    "POUCH",
    "TIN",
    "BULK_CONTAINER",
    "OTHER",
    name="packaging_type",
    create_type=False,
)
PACKAGE_STATUS = postgresql.ENUM(
    "CREATED",
    "READY_FOR_DISTRIBUTION",
    "IN_DISTRIBUTION",
    "DELIVERED",
    "CANCELLED",
    name="package_status",
    create_type=False,
)
DISTRIBUTION_STATUS = postgresql.ENUM(
    "READY_FOR_DISPATCH",
    "DISPATCHED",
    "IN_TRANSIT",
    "DELIVERED",
    "CANCELLED",
    name="distribution_status",
    create_type=False,
)
#: Vocabulary that already exists — reused, never re-created.
FACILITY_STATUS = postgresql.ENUM(
    "ACTIVE", "INACTIVE", name="facility_status", create_type=False
)
COLLECTION_UNIT = postgresql.ENUM("KG", "GRAM", name="collection_unit", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    for enum_type in (PACKAGING_STATUS, PACKAGING_TYPE, PACKAGE_STATUS, DISTRIBUTION_STATUS):
        enum_type.create(bind, checkfirst=True)

    # -- packaging_units ----------------------------------------------------
    op.create_table(
        "packaging_units",
        sa.Column("unit_code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("registration_identifier", sa.String(length=80), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column("state", sa.String(length=80), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column(
            "owner_user_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column("status", FACILITY_STATUS, server_default="ACTIVE", nullable=False),
        sa.Column("capacity_kg_per_day", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_packaging_units_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_packaging_units")),
    )
    op.create_index(op.f("ix_packaging_units_district"), "packaging_units", ["district"])
    op.create_index(op.f("ix_packaging_units_owner_user_id"), "packaging_units", ["owner_user_id"])
    op.create_index(op.f("ix_packaging_units_unit_code"), "packaging_units", ["unit_code"], unique=True)

    # -- packaging_records --------------------------------------------------
    op.create_table(
        "packaging_records",
        sa.Column("packaging_code", sa.String(length=40), nullable=False),
        sa.Column("batch_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False),
        sa.Column(
            "packaging_unit_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "packaged_by_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column("status", PACKAGING_STATUS, server_default="PENDING", nullable=False),
        sa.Column("packaging_type", PACKAGING_TYPE, nullable=False),
        sa.Column("packaging_date", sa.Date(), nullable=False),
        sa.Column("input_quantity", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("packaged_quantity", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("package_size", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("number_of_packages", sa.Integer(), nullable=True),
        sa.Column("unit", COLLECTION_UNIT, nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "input_quantity IS NULL OR input_quantity > 0",
            name=op.f("ck_packaging_records_ck_packaging_input_quantity_positive"),
        ),
        sa.CheckConstraint(
            "number_of_packages IS NULL OR number_of_packages > 0",
            name=op.f("ck_packaging_records_ck_packaging_package_count_positive"),
        ),
        sa.CheckConstraint(
            "package_size IS NULL OR package_size > 0",
            name=op.f("ck_packaging_records_ck_packaging_package_size_positive"),
        ),
        sa.CheckConstraint(
            "packaged_quantity IS NULL OR input_quantity IS NULL OR packaged_quantity <= input_quantity",
            name=op.f("ck_packaging_records_ck_packaging_packaged_not_above_input"),
        ),
        sa.CheckConstraint(
            "packaged_quantity IS NULL OR packaged_quantity > 0",
            name=op.f("ck_packaging_records_ck_packaging_packaged_quantity_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["honey_batches.id"],
            name=op.f("fk_packaging_records_batch_id_honey_batches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["packaged_by_id"],
            ["users.id"],
            name=op.f("fk_packaging_records_packaged_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["packaging_unit_id"],
            ["packaging_units.id"],
            name=op.f("fk_packaging_records_packaging_unit_id_packaging_units"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_packaging_records")),
    )
    op.create_index("ix_packaging_batch_created", "packaging_records", ["batch_id", "created_at"])
    op.create_index(op.f("ix_packaging_records_batch_id"), "packaging_records", ["batch_id"])
    op.create_index(op.f("ix_packaging_records_packaged_by_id"), "packaging_records", ["packaged_by_id"])
    op.create_index(
        op.f("ix_packaging_records_packaging_code"), "packaging_records", ["packaging_code"], unique=True
    )
    op.create_index(
        op.f("ix_packaging_records_packaging_unit_id"), "packaging_records", ["packaging_unit_id"]
    )
    op.create_index(op.f("ix_packaging_records_status"), "packaging_records", ["status"])
    # One open packing operation per batch: a double submission cannot create two
    # rival records of the same work.
    op.create_index(
        "uq_packaging_open_per_batch",
        "packaging_records",
        ["batch_id"],
        unique=True,
        postgresql_where="status IN ('PENDING', 'IN_PROGRESS')",
    )

    # -- packages -----------------------------------------------------------
    op.create_table(
        "packages",
        sa.Column("package_code", sa.String(length=40), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "packaging_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column("batch_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False),
        sa.Column("package_size", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("unit", COLLECTION_UNIT, nullable=False),
        sa.Column("packaging_type", PACKAGING_TYPE, nullable=False),
        sa.Column("packaging_date", sa.Date(), nullable=False),
        sa.Column("status", PACKAGE_STATUS, server_default="CREATED", nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("package_size > 0", name=op.f("ck_packages_ck_packages_package_size_positive")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_packages_ck_packages_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["honey_batches.id"],
            name=op.f("fk_packages_batch_id_honey_batches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["packaging_id"],
            ["packaging_records.id"],
            name=op.f("fk_packages_packaging_id_packaging_records"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_packages")),
        # The identifier printed on a package is unique for the life of the
        # platform: it is what a later QR phase will resolve.
        sa.UniqueConstraint("package_code", name="uq_packages_package_code"),
    )
    op.create_index("ix_packages_batch_created", "packages", ["batch_id", "created_at"])
    op.create_index(op.f("ix_packages_batch_id"), "packages", ["batch_id"])
    op.create_index(op.f("ix_packages_package_code"), "packages", ["package_code"])
    op.create_index(op.f("ix_packages_packaging_id"), "packages", ["packaging_id"])
    op.create_index("ix_packages_packaging_sequence", "packages", ["packaging_id", "sequence_number"])
    op.create_index(op.f("ix_packages_status"), "packages", ["status"])

    # -- distributions ------------------------------------------------------
    op.create_table(
        "distributions",
        sa.Column("distribution_code", sa.String(length=40), nullable=False),
        sa.Column(
            "package_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column("batch_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False),
        sa.Column(
            "distributor_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "retailer_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column("destination", sa.String(length=200), nullable=False),
        sa.Column("destination_district", sa.String(length=80), nullable=True),
        sa.Column("status", DISTRIBUTION_STATUS, server_default="READY_FOR_DISPATCH", nullable=False),
        sa.Column("quantity", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("unit", COLLECTION_UNIT, nullable=False),
        sa.Column("carrier", sa.String(length=160), nullable=True),
        sa.Column("tracking_reference", sa.String(length=80), nullable=True),
        sa.Column("dispatch_date", sa.Date(), nullable=True),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_transit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_by_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        # The database itself refuses a delivery that no dispatch preceded, and a
        # delivery dated before its own dispatch. The service refuses them first;
        # this is what makes the impossible state unreachable even from a bug.
        sa.CheckConstraint(
            "status <> 'DELIVERED' OR dispatched_at IS NOT NULL",
            name=op.f("ck_distributions_ck_distributions_delivered_requires_dispatch"),
        ),
        sa.CheckConstraint(
            "delivered_at IS NULL OR dispatched_at IS NULL OR delivered_at >= dispatched_at",
            name=op.f("ck_distributions_ck_distributions_delivered_after_dispatch"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_distributions_ck_distributions_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["honey_batches.id"],
            name=op.f("fk_distributions_batch_id_honey_batches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["distributor_id"],
            ["users.id"],
            name=op.f("fk_distributions_distributor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["packages.id"],
            name=op.f("fk_distributions_package_id_packages"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["received_by_id"],
            ["users.id"],
            name=op.f("fk_distributions_received_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["retailer_id"],
            ["users.id"],
            name=op.f("fk_distributions_retailer_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_distributions")),
    )
    op.create_index("ix_distributions_batch_created", "distributions", ["batch_id", "created_at"])
    op.create_index(op.f("ix_distributions_batch_id"), "distributions", ["batch_id"])
    op.create_index(op.f("ix_distributions_destination_district"), "distributions", ["destination_district"])
    op.create_index(
        op.f("ix_distributions_distribution_code"), "distributions", ["distribution_code"], unique=True
    )
    op.create_index(op.f("ix_distributions_distributor_id"), "distributions", ["distributor_id"])
    op.create_index(op.f("ix_distributions_package_id"), "distributions", ["package_id"])
    op.create_index("ix_distributions_package_status", "distributions", ["package_id", "status"])
    op.create_index(op.f("ix_distributions_retailer_id"), "distributions", ["retailer_id"])
    op.create_index("ix_distributions_retailer_status", "distributions", ["retailer_id", "status"])
    op.create_index(op.f("ix_distributions_status"), "distributions", ["status"])


def downgrade() -> None:
    op.drop_table("distributions")
    op.drop_table("packages")
    op.drop_table("packaging_records")
    op.drop_table("packaging_units")

    bind = op.get_bind()
    for enum_type in (DISTRIBUTION_STATUS, PACKAGE_STATUS, PACKAGING_TYPE, PACKAGING_STATUS):
        enum_type.drop(bind, checkfirst=True)

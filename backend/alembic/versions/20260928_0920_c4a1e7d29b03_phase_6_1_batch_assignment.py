"""phase 6.1: processing and laboratory batch assignment

Revision ID: c4a1e7d29b03
Revises: 9b4d2f81ac07
Create Date: 2026-09-28 09:20:41.117402+00:00

Adds *who is responsible for the work*, which Phase 6 deliberately left out: a run
and a test knew which facility did the job, but not which person had been given it.
The workflow could therefore record what happened, not what was waiting to happen.

The allocation lives on the operational record — ``honey_processing_records`` for
processing, ``lab_tests`` for the laboratory — and **not** on the batch. A batch is
one shared row that the processor, the laboratory, the beekeeper and the KVIC
officer all read; hanging one role's queue off it would make the shared record carry
that role's booking, and a batch would appear "assigned" to people it has nothing to
do with.

Per record, five columns:

* ``processor_id`` / ``assigned_technician_id`` — the person responsible. NULL means
  nobody yet, and the work stays in the shared queue rather than vanishing.
* ``assigned_by_id`` — who allocated it (SET NULL: the allocation outlives the
  allocator's account).
* ``assigned_at`` / ``accepted_at`` — when it was handed over, and when the named
  person took it on.
* ``assignment_status`` — ``UNASSIGNED`` / ``ASSIGNED`` / ``ACCEPTED``.

Existing rows are backfilled to ``ACCEPTED`` with the person who actually did the
work (``operator_id`` / ``technician_id``), because work that is already finished —
or already under way — was plainly somebody's: leaving those rows ``UNASSIGNED``
would say the opposite of what the records show. No new table, no second copy of
the batch, no change to any quantity.

One PostgreSQL enum type is added (``assignment_status``), used by both tables so
the laboratory and the processing side cannot drift into two vocabularies.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4a1e7d29b03"
down_revision: Union[str, None] = "9b4d2f81ac07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ASSIGNMENT_STATUS = postgresql.ENUM(
    "UNASSIGNED",
    "ASSIGNED",
    "ACCEPTED",
    name="assignment_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(
        "UNASSIGNED",
        "ASSIGNED",
        "ACCEPTED",
        name="assignment_status",
    ).create(bind, checkfirst=True)

    # -- processing runs ---------------------------------------------------
    op.add_column(
        "honey_processing_records",
        sa.Column("processor_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "honey_processing_records",
        sa.Column("assigned_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "honey_processing_records",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "honey_processing_records",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "honey_processing_records",
        sa.Column(
            "assignment_status",
            ASSIGNMENT_STATUS,
            nullable=False,
            server_default="UNASSIGNED",
        ),
    )
    op.create_foreign_key(
        op.f("fk_honey_processing_records_processor_id_users"),
        "honey_processing_records",
        "users",
        ["processor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_honey_processing_records_assigned_by_id_users"),
        "honey_processing_records",
        "users",
        ["assigned_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_honey_processing_records_processor_id"),
        "honey_processing_records",
        ["processor_id"],
    )
    op.create_index(
        op.f("ix_honey_processing_records_assignment_status"),
        "honey_processing_records",
        ["assignment_status"],
    )

    # -- laboratory tests --------------------------------------------------
    op.add_column(
        "lab_tests",
        sa.Column("assigned_technician_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "lab_tests",
        sa.Column("assigned_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "lab_tests",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lab_tests",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lab_tests",
        sa.Column(
            "assignment_status",
            ASSIGNMENT_STATUS,
            nullable=False,
            server_default="UNASSIGNED",
        ),
    )
    op.create_foreign_key(
        op.f("fk_lab_tests_assigned_technician_id_users"),
        "lab_tests",
        "users",
        ["assigned_technician_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_lab_tests_assigned_by_id_users"),
        "lab_tests",
        "users",
        ["assigned_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_lab_tests_assigned_technician_id"),
        "lab_tests",
        ["assigned_technician_id"],
    )
    op.create_index(
        op.f("ix_lab_tests_assignment_status"),
        "lab_tests",
        ["assignment_status"],
    )

    # -- backfill: work already done was somebody's ------------------------
    # A finished or in-flight run was performed by its operator, and a recorded test
    # by its technician. Saying so is not an invention: the record already holds the
    # name, and leaving the row unassigned would contradict it.
    op.execute(
        """
        UPDATE honey_processing_records
           SET processor_id = operator_id,
               assigned_by_id = operator_id,
               assigned_at = COALESCE(start_time, created_at),
               accepted_at = COALESCE(start_time, created_at),
               assignment_status = 'ACCEPTED'
         WHERE processor_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE lab_tests
           SET assigned_technician_id = technician_id,
               assigned_by_id = technician_id,
               assigned_at = COALESCE(sample_collected_at, created_at),
               accepted_at = COALESCE(sample_collected_at, created_at),
               assignment_status = 'ACCEPTED'
         WHERE assigned_technician_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_lab_tests_assignment_status"), table_name="lab_tests")
    op.drop_index(op.f("ix_lab_tests_assigned_technician_id"), table_name="lab_tests")
    op.drop_constraint(
        op.f("fk_lab_tests_assigned_by_id_users"), "lab_tests", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_lab_tests_assigned_technician_id_users"), "lab_tests", type_="foreignkey"
    )
    for column in (
        "assignment_status",
        "accepted_at",
        "assigned_at",
        "assigned_by_id",
        "assigned_technician_id",
    ):
        op.drop_column("lab_tests", column)

    op.drop_index(
        op.f("ix_honey_processing_records_assignment_status"),
        table_name="honey_processing_records",
    )
    op.drop_index(
        op.f("ix_honey_processing_records_processor_id"),
        table_name="honey_processing_records",
    )
    op.drop_constraint(
        op.f("fk_honey_processing_records_assigned_by_id_users"),
        "honey_processing_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_honey_processing_records_processor_id_users"),
        "honey_processing_records",
        type_="foreignkey",
    )
    for column in (
        "assignment_status",
        "accepted_at",
        "assigned_at",
        "assigned_by_id",
        "processor_id",
    ):
        op.drop_column("honey_processing_records", column)

    postgresql.ENUM(name="assignment_status").drop(op.get_bind(), checkfirst=True)

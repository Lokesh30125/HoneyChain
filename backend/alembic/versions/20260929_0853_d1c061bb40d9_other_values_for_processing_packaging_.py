"""Other" recorded in the operator's own words

Revision ID: d1c061bb40d9
Revises: 8d1c4a77b2e5
Create Date: 2026-09-29 08:53:35.157034+00:00

Three fields in the platform offer an ``OTHER`` choice — what a processing run
did, what a batch was packed into, and what hardware a device is. Until now,
choosing "Other" recorded the word *Other* and nothing else: the operation
happened, the record said nothing about what it was, and the value could not be
reported on.

This revision gives each of them somewhere to put the description, and a
constraint so the pair cannot be recorded half-way:

* the text is **required** when the type is ``OTHER``;
* the text is **forbidden** when the type is one of the listed values, so a
  category and a free-text description can never disagree.

``iot_devices`` already holds a device name and firmware version; the constraint
applies to the new column only, and existing rows are untouched because none of
the three tables currently holds a row recorded as ``OTHER``. A row that did
would be given the description it never carried before the constraint is added —
stated as unknown rather than invented — and the correction audited, which is
what the guard below does.
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1c061bb40d9"
down_revision: Union[str, None] = "8d1c4a77b2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (table, type column, new description column, human name of the field)
FIELD_GROUPS: list[tuple[str, str, str, str]] = [
    ("honey_processing_records", "processing_type", "processing_type_other", "processing type"),
    ("packaging_records", "packaging_type", "packaging_type_other", "packaging type"),
    ("iot_devices", "device_type", "device_type_other", "device type"),
]

UNDESCRIBED = "Other (not described when it was recorded)"


def upgrade() -> None:
    for table, type_column, other_column, label in FIELD_GROUPS:
        op.add_column(table, sa.Column(other_column, sa.String(length=120), nullable=True))

        # Any row already recorded as OTHER holds no description, because there was
        # nowhere to put one. It is marked as exactly that — a statement about the
        # record, not a guess about the operation — and the correction is written to
        # the audit log so a reader can see when and why it changed.
        connection = op.get_bind()
        rows = connection.execute(
            sa.text(
                f"SELECT id FROM {table} WHERE {type_column} = 'OTHER' AND {other_column} IS NULL"
            )
        ).fetchall()
        for (row_id,) in rows:
            connection.execute(
                sa.text(
                    f"UPDATE {table} SET {other_column} = :value WHERE id = :id"
                ),
                {"value": UNDESCRIBED, "id": row_id},
            )
            # The columns are spelled exactly as the audit table has them: the
            # actor is ``user_id`` (NULL here — the correction is the migration's,
            # not a person's), the roles column is ``actor_role``, and the payload
            # column is ``metadata``. There is no ``updated_at``: an audit row is
            # written once and never amended.
            connection.execute(
                sa.text(
                    "INSERT INTO audit_logs (id, user_id, actor_role, action, entity_type, "
                    "entity_id, metadata, description, created_at) "
                    "VALUES (:id, NULL, 'SYSTEM', 'DATA_CORRECTION', :entity_type, :entity_id, "
                    "CAST(:metadata AS jsonb), :description, now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "entity_type": table,
                    "entity_id": str(row_id),
                    "metadata": (
                        '{"field": "%s", "value": "%s", "source": '
                        '"backfilled by the migration that added %s"}'
                        % (other_column, UNDESCRIBED, other_column)
                    ),
                    "description": (
                        f"{UNDESCRIBED} — recorded as OTHER before {other_column} existed"
                    ),
                },
            )

        # The same raw name the models declare, so the constraint Alembic creates
        # here and the one `Base.metadata.create_all` creates for the tests are
        # named identically — a schema that differs only in constraint names is a
        # schema that hides differences.
        op.create_check_constraint(
            f"ck_{other_column}",
            table,
            f"({type_column} <> 'OTHER' AND {other_column} IS NULL) "
            f"OR ({type_column} = 'OTHER' AND {other_column} IS NOT NULL "
            f"AND length(btrim({other_column})) > 0)",
        )
        print(f"  {label}: {other_column} added with its constraint")


def downgrade() -> None:
    for table, _type_column, other_column, _label in reversed(FIELD_GROUPS):
        op.drop_constraint(f"ck_{other_column}", table, type_="check")
        op.drop_column(table, other_column)

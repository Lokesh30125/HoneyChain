"""Packaging units: a real facility registry an account can belong to

Two columns, one relationship, and they exist because of a dead end the operator
hit: the packaging screen asked which facility the honey was packed in and there
was no way to register one, so the answer was always "No unit registered yet".

* ``packaging_units.address`` — the postal address, which is a different fact from
  the town the facility is in.
* ``users.packaging_unit_id`` — the facility a ``PACKAGING_UNIT`` account works
  for. The relationship is stored here and **only** here: the unit does not keep a
  second copy of its membership, so the two can never disagree about who works
  where. ``ON DELETE SET NULL`` because a retired unit must not take its people's
  accounts with it.

Nothing is backfilled. An account created before this migration simply has no
facility, which is the truth about it — and the screens say so in a way that leads
to the administrator action that fixes it, rather than offering a dropdown of
other organisations' facilities.

Revision ID: 7c1d90ab5f21
Revises: 3f6b21ac9d47
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "7c1d90ab5f21"
down_revision: str | None = "3f6b21ac9d47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("packaging_units", sa.Column("address", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("packaging_unit_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_packaging_unit_id_packaging_units",
        "users",
        "packaging_units",
        ["packaging_unit_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_users_packaging_unit_id", "users", ["packaging_unit_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_users_packaging_unit_id", table_name="users")
    op.drop_constraint(
        "fk_users_packaging_unit_id_packaging_units", "users", type_="foreignkey"
    )
    op.drop_column("users", "packaging_unit_id")
    op.drop_column("packaging_units", "address")

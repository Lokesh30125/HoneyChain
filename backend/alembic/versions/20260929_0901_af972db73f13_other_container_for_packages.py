"""the container a package was packed into, in the operator's own words

Adds ``packages.packaging_type_other`` so a package can carry the description that
belongs to a container typed *Other*, exactly as its packaging run does.

Why the package needs its own copy rather than reading the run's: a package is the
record that travels — it is shipped, received by a shop and eventually shown to a
consumer — and it has to be able to say what it is without the run being loaded.
That is why the packaging type itself is stored on the package too. The description
is copied from the run when the packages are created, and from then on the two are
independent records of the same fact.

The pair rule is enforced here as well as in the API, because the API is not the
only thing that can write:

    (packaging_type <> 'OTHER' AND packaging_type_other IS NULL)
    OR (packaging_type = 'OTHER' AND packaging_type_other IS NOT NULL
        AND length(btrim(packaging_type_other)) > 0)

Packages recorded before this revision are backfilled from their run: a package
whose run was described has inherited that description (the run is the only place
the words were ever written down), and a package typed *Other* with no description
anywhere is given an explicit marker saying so, with an audit entry recording the
correction through the existing audit trail.

Revision ID: af972db73f13
Revises: d1c061bb40d9
Create Date: 2026-09-29 09:01:51.217560+00:00

"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'af972db73f13'
down_revision: Union[str, None] = 'd1c061bb40d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: The same wording the run-level backfill uses. It states plainly that the words
#: were never recorded at the time, which is the honest thing to show a reader.
UNRECORDED = "Other (not described when it was recorded)"


def upgrade() -> None:
    op.add_column(
        'packages',
        sa.Column(
            'packaging_type_other',
            sa.String(length=120),
            nullable=True,
            comment=(
                "The container in the operator's own words, copied from the run when "
                "the packaging type is OTHER; NULL otherwise."
            ),
        ),
    )

    # A package inherits the description its run carries: this is a copy of a fact
    # that already exists, not a new one.
    op.execute(
        sa.text(
            """
            UPDATE packages AS p
               SET packaging_type_other = r.packaging_type_other
              FROM packaging_records AS r
             WHERE p.packaging_id = r.id
               AND p.packaging_type = 'OTHER'
               AND p.packaging_type_other IS NULL
               AND r.packaging_type_other IS NOT NULL
            """
        )
    )

    # Anything still typed OTHER without a description had none recorded anywhere.
    # Saying so explicitly keeps the constraint honest and the record truthful.
    connection = op.get_bind()
    orphans = connection.execute(
        sa.text(
            "SELECT id, package_code FROM packages "
            "WHERE packaging_type = 'OTHER' AND packaging_type_other IS NULL"
        )
    ).fetchall()
    if orphans:
        connection.execute(
            sa.text(
                "UPDATE packages SET packaging_type_other = :text "
                "WHERE packaging_type = 'OTHER' AND packaging_type_other IS NULL"
            ),
            {"text": UNRECORDED},
        )
        # The audit trail already exists; the correction is written into it rather
        # than being a silent rewrite of someone's record. The columns are spelled
        # as the audit table has them, and the actor is NULL with the role marked
        # SYSTEM: nobody typed this, a migration did.
        for package_id, code in orphans:
            connection.execute(
                sa.text(
                    "INSERT INTO audit_logs "
                    "(id, user_id, actor_role, action, entity_type, entity_id, metadata, "
                    "description, created_at) "
                    "VALUES (:id, NULL, 'SYSTEM', 'DATA_CORRECTION', 'package', :entity_id, "
                    "CAST(:metadata AS jsonb), :description, now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "entity_id": str(package_id),
                    "metadata": (
                        '{"field": "packaging_type_other", "value": "%s", "reason": '
                        '"packages typed OTHER had no container description recorded", '
                        '"package_code": "%s"}' % (UNRECORDED, code)
                    ),
                    "description": (
                        f"Package {code} was typed OTHER before the container "
                        "description existed"
                    ),
                },
            )

    op.create_check_constraint(
        "ck_package_type_other",
        "packages",
        "(packaging_type <> 'OTHER' AND packaging_type_other IS NULL) "
        "OR (packaging_type = 'OTHER' AND packaging_type_other IS NOT NULL "
        "AND length(btrim(packaging_type_other)) > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_package_type_other", "packages", type_="check")
    op.drop_column("packages", "packaging_type_other")

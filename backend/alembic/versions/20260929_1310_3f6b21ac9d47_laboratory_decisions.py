"""laboratory decisions: hold, risk override, AI analysis and the packaging handover

Revision ID: 3f6b21ac9d47
Revises: af972db73f13
Create Date: 2026-09-29 13:10:00.000000+00:00

What this revision changes, and why each piece is a *record* rather than a flag:

1. **Two batch states.** ``LAB_HOLD`` and ``PROCEEDED_WITH_RISK`` are statuses a
   batch can genuinely be in, not notices on a screen. A held batch has to be
   distinguishable from one that was never tested, and a batch released under a
   recorded risk has to be distinguishable from one that simply passed — both for
   the packaging floor and for anyone reading the history later. The state a
   batch is in after approval is also split: ``APPROVED`` (the laboratory decided)
   and ``PACKAGING_READY`` (…and it has been released to be packed), because once
   a batch can be released under a recorded risk, "passed" and "available to pack"
   are two different statements.

2. **``lab_tests.status`` gains ``HOLD``.** A held test is closed for work and
   open for a decision. It is not COMPLETED — the laboratory has not decided — and
   it is not IN_PROGRESS, which would keep offering it as bench work it is not.

3. **A measurement's provenance.** ``lab_test_results.measurement_source``
   (``DEMO`` / ``MANUAL`` / ``REAL_DEVICE``) records where a number came from, so a
   value the platform pre-filled can never be read as one an instrument reported.

4. **Configured methods and development defaults** on ``lab_parameters``, so a
   laboratory chooses a method from a list that applies to the parameter it is
   measuring, and so a development installation has somewhere to declare the
   values it pre-fills.

5. **The AI analysis, the hold and the override** on ``lab_tests``: the analysis
   is stored with the model, version and source that produced it; the hold keeps
   its reason and who recorded it; the override keeps the risks the user was
   shown, the analysis behind them, and the user and moment of the decision.

6. **The development profile is installed as configuration**, with its provenance
   written into ``reference_source`` so every screen that shows a range also says
   where it came from. It never overwrites a range a person configured, and a
   production installation (``LAB_DEMO_CONFIGURATION_ENABLED=false``) installs
   nothing, leaving every measurement unjudged until real limits are entered.

Nothing is deleted, no row is replaced, and existing tests keep the status they
already have.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3f6b21ac9d47"
down_revision: Union[str, None] = "af972db73f13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: The two states added to the batch lifecycle.
BATCH_STATUS_VALUES = ("LAB_HOLD", "PROCEEDED_WITH_RISK", "PACKAGING_READY")
#: The measurement provenance enum.
SOURCE_VALUES = ("DEMO", "MANUAL", "REAL_DEVICE")
#: The new audit actions, so an installation can filter on them.
AUDIT_ACTIONS = (
    "LAB_QUALITY_ANALYSED",
    "LAB_HOLD",
    "LAB_HOLD_RELEASED",
    "PROCEEDED_WITH_RISK",
    "BATCH_PACKAGING_READY",
)


def _enum_values(bind, type_name: str) -> set[str]:
    rows = bind.execute(
        sa.text(
            "select enumlabel from pg_enum e join pg_type t on t.oid = e.enumtypid "
            "where t.typname = :name"
        ),
        {"name": type_name},
    ).scalars()
    return set(rows)


def _add_enum_values(bind, type_name: str, values: Sequence[str]) -> None:
    """Add labels to an existing PostgreSQL enum, skipping the ones already there."""
    if bind.dialect.name != "postgresql":
        return
    existing = _enum_values(bind, type_name)
    for value in values:
        if value in existing:
            continue
        # ``IF NOT EXISTS`` keeps this idempotent if a database was migrated twice
        # by hand while the feature was being built.
        op.execute(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'")


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # ------------------------------------------------------------------ #
    # 1. The lifecycle values                                            #
    # ------------------------------------------------------------------ #
    _add_enum_values(bind, "batch_status", BATCH_STATUS_VALUES)
    _add_enum_values(bind, "lab_test_status", ("HOLD",))
    # The measurement provenance is a new type on PostgreSQL; on the SQLite
    # fallback the ORM stores it as a string and ``create_all`` builds it.
    if dialect == "postgresql":
        sa.Enum(*SOURCE_VALUES, name="lab_measurement_source").create(bind, checkfirst=True)
    # ``audit_logs.action`` is a plain string column on this project, not an enum
    # (the action vocabulary lives in ``AuditAction``), so the new actions need no
    # DDL at all. The list is kept here as the record of what this revision
    # introduced, and asserted by the test suite.

    # ------------------------------------------------------------------ #
    # 2. Provenance on every recorded measurement                        #
    # ------------------------------------------------------------------ #
    if dialect == "postgresql":
        # Added with its default already in the target type, so existing rows are
        # filled in the same statement: every measurement recorded before this
        # revision was typed by a person, so MANUAL is what they were — stated by
        # the migration rather than guessed per row.
        op.execute(
            "ALTER TABLE lab_test_results ADD COLUMN measurement_source "
            "lab_measurement_source NOT NULL DEFAULT 'MANUAL'"
        )
    else:
        op.add_column(
            "lab_test_results",
            sa.Column("measurement_source", sa.Text(), nullable=False, server_default="MANUAL"),
        )

    # ------------------------------------------------------------------ #
    # 3. Configured methods and development defaults on the catalogue    #
    # ------------------------------------------------------------------ #
    op.add_column(
        "lab_parameters",
        sa.Column(
            "methods",
            postgresql.JSONB(astext_type=sa.Text()) if dialect == "postgresql" else sa.Text(),
            nullable=True,
            comment="Configured method options for this parameter: [{code, label}].",
        ),
    )
    op.add_column(
        "lab_parameters",
        sa.Column(
            "development_value",
            sa.Numeric(10, 4),
            nullable=True,
            comment="Development/demo starting value. Never a measurement that was taken.",
        ),
    )

    # ------------------------------------------------------------------ #
    # 4. The analysis, the hold and the override on a test               #
    # ------------------------------------------------------------------ #
    json_type = (
        postgresql.JSONB(astext_type=sa.Text()) if dialect == "postgresql" else sa.Text()
    )
    op.add_column("lab_tests", sa.Column("ai_analysis", json_type, nullable=True))
    op.add_column("lab_tests", sa.Column("ai_status", sa.String(20), nullable=True))
    op.add_column("lab_tests", sa.Column("ai_risk_level", sa.String(20), nullable=True))
    op.add_column("lab_tests", sa.Column("ai_model", sa.String(80), nullable=True))
    op.add_column("lab_tests", sa.Column("ai_model_version", sa.String(40), nullable=True))
    op.add_column("lab_tests", sa.Column("ai_source", sa.String(40), nullable=True))
    op.add_column(
        "lab_tests", sa.Column("ai_analysed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("lab_tests", sa.Column("ai_analysed_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_lab_tests_ai_analysed_by",
        "lab_tests",
        "users",
        ["ai_analysed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("lab_tests", sa.Column("hold_reason", sa.String(500), nullable=True))
    op.add_column("lab_tests", sa.Column("held_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("lab_tests", sa.Column("held_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_lab_tests_held_by",
        "lab_tests",
        "users",
        ["held_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("lab_tests", sa.Column("risk_override", json_type, nullable=True))
    op.add_column("lab_tests", sa.Column("overridden_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_lab_tests_overridden_by",
        "lab_tests",
        "users",
        ["overridden_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "lab_tests", sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True)
    )

    # ------------------------------------------------------------------ #
    # 5. The development profile, installed as labelled configuration     #
    # ------------------------------------------------------------------ #
    # The profile itself lives in ``app.services.lab_demo_profile`` and is applied
    # here through the same function the application calls, so a migrated database
    # and a freshly started application cannot disagree about what the development
    # configuration is. It writes nothing when ``LAB_DEMO_CONFIGURATION_ENABLED``
    # is false, and never overwrites a range a person configured.
    from sqlalchemy.orm import Session

    from app.core.config import get_settings
    from app.services.lab_demo_profile import install_demo_configuration

    settings = get_settings()
    if settings.LAB_DEMO_CONFIGURATION_ENABLED:
        # Through a session on the migration's own connection, so the profile is
        # written inside the same transaction as the columns it configures.
        with Session(bind) as session:
            install_demo_configuration(session)


def downgrade() -> None:
    for column in (
        "overridden_at",
        "overridden_by_id",
        "risk_override",
        "held_by_id",
        "held_at",
        "hold_reason",
        "ai_analysed_by_id",
        "ai_analysed_at",
        "ai_source",
        "ai_model_version",
        "ai_model",
        "ai_risk_level",
        "ai_status",
        "ai_analysis",
    ):
        op.drop_column("lab_tests", column)
    op.drop_column("lab_parameters", "development_value")
    op.drop_column("lab_parameters", "methods")
    op.drop_column("lab_test_results", "measurement_source")
    # Enum labels are not removed: a PostgreSQL enum cannot drop one without being
    # rebuilt, and a value that is no longer written is harmless. The data those
    # rows describe is real history either way.

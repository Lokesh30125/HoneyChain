"""phase 6: processing and laboratory quality

Revision ID: 9b4d2f81ac07
Revises: 7c1f0b93d0e2
Create Date: 2026-09-25 10:30:12.418773+00:00

Adds the two stages that follow collection — what was done to the honey, and what
was measured in it — and nothing else. There is no packaging table, no
distribution table, no QR payload table, no trust score and no ledger table,
because none of those modules is built.

Five new tables:

* ``processing_units`` — where processing happened: a name, a location, a
  registration identifier, an operator and whether the unit is operating. A
  reference, not a facility-management system.
* ``honey_processing_records`` — one processing run on one batch: the type of
  operation, the quantities that went in and came out, the loss between them, the
  operator, the facility, the start and completion times and the status. A partial
  unique index allows at most one *open* run per batch, so a double submission
  cannot leave two rival records of the same operation, while cancelled and
  completed runs stay in the table as history.
* ``laboratories`` — the facility that performed a test. Same deliberately small
  shape as a processing unit.
* ``lab_tests`` — one test of one batch: its own test code, its own sample code,
  the facility, the technician, the sample quantity, the status and the derived
  overall result. Plural per batch by design: a retest is a new row that
  references the earlier test, never an edit of it.
* ``lab_test_results`` — one row per measured parameter, with the value, the unit,
  the reference range that was in force, the resulting parameter status and the
  method. A keyed table rather than a wide one, so adding a parameter is a
  catalogue row rather than a migration.

One new table carries configuration rather than measurements:
``lab_parameters``. Its rows are seeded here with **names and units only** — the
fact that a moisture reading is expressed in percent is not a scientific claim.
The reference ranges (``reference_min`` / ``reference_max`` / ``reference_source``)
are intentionally left NULL: this project publishes no threshold it was not given,
so an unevaluated measurement is reported as ``NOT_EVALUATED`` and a test with
nothing to compare against is ``INCONCLUSIVE``. An administrator configures the
applicable ranges through the API, recording where each one came from.

``batch_status`` gains one value, ``APPROVED``, because Phase 6 is the first phase
that can decide a batch's fate. PostgreSQL cannot remove an enum value without
rewriting the type, so the downgrade leaves it in place (documented there); the
value is simply unused once the Phase-6 tables are gone.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9b4d2f81ac07'
down_revision: Union[str, None] = '7c1f0b93d0e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: PostgreSQL enum types introduced by this migration. Created once below and
#: referenced in the tables with ``create_type=False``, as in Phases 2–5.
facility_status_enum = postgresql.ENUM(
    "ACTIVE",
    "INACTIVE",
    name="facility_status",
    create_type=False,
)
processing_status_enum = postgresql.ENUM(
    "PENDING",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    name="processing_status",
    create_type=False,
)
processing_type_enum = postgresql.ENUM(
    "FILTERING",
    "DECRYSTALLIZATION",
    "PASTEURIZATION",
    "BLENDING",
    "MOISTURE_REDUCTION",
    "OTHER",
    name="processing_type",
    create_type=False,
)
lab_measure_unit_enum = postgresql.ENUM(
    "%",
    "mg/kg",
    "mS/cm",
    "DN",
    "mm Pfund",
    "meq/kg",
    "g/100g",
    "pH",
    "unitless",
    name="lab_measure_unit",
    create_type=False,
)
lab_test_status_enum = postgresql.ENUM(
    "PENDING",
    "IN_PROGRESS",
    "COMPLETED",
    name="lab_test_status",
    create_type=False,
)
lab_result_enum = postgresql.ENUM(
    "PENDING",
    "PASS",
    "FAIL",
    "INCONCLUSIVE",
    name="lab_result",
    create_type=False,
)
lab_parameter_status_enum = postgresql.ENUM(
    "PASS",
    "FAIL",
    "NOT_EVALUATED",
    name="lab_parameter_status",
    create_type=False,
)

ALL_ENUMS = (
    facility_status_enum,
    processing_status_enum,
    processing_type_enum,
    lab_measure_unit_enum,
    lab_test_status_enum,
    lab_result_enum,
    lab_parameter_status_enum,
)

#: ``collection_unit`` already exists from Phase 5; a processing run and a sample
#: are both masses and reuse it rather than inventing a parallel unit type.
collection_unit_enum = postgresql.ENUM(
    "KG",
    "GRAM",
    name="collection_unit",
    create_type=False,
)

BATCH_STATUS_APPROVED = "alter type batch_status add value if not exists 'APPROVED' after 'LAB_TESTING'"

#: The measurement slots a honey quality test may record. Names and units only —
#: no thresholds. ``is_required`` is a platform review policy (all False until an
#: administrator decides otherwise), never a scientific statement.
PARAMETER_CATALOGUE: tuple[dict, ...] = (
    {
        "code": "MOISTURE",
        "name": "Moisture content",
        "unit": "%",
        "display_order": 10,
        "description": "Water content of the honey, as measured.",
    },
    {
        "code": "PH",
        "name": "pH",
        "unit": "pH",
        "display_order": 20,
        "description": "Acidity of the honey on the pH scale, as measured.",
    },
    {
        "code": "FREE_ACIDITY",
        "name": "Free acidity",
        "unit": "meq/kg",
        "display_order": 30,
        "description": "Free acidity, as measured.",
    },
    {
        "code": "ELECTRICAL_CONDUCTIVITY",
        "name": "Electrical conductivity",
        "unit": "mS/cm",
        "display_order": 40,
        "description": "Electrical conductivity, as measured.",
    },
    {
        "code": "HMF",
        "name": "Hydroxymethylfurfural (HMF)",
        "unit": "mg/kg",
        "display_order": 50,
        "description": "HMF content, as measured.",
    },
    {
        "code": "DIASTASE_ACTIVITY",
        "name": "Diastase activity",
        "unit": "DN",
        "display_order": 60,
        "description": "Diastase number, as measured.",
    },
    {
        "code": "SUCROSE",
        "name": "Sucrose content",
        "unit": "g/100g",
        "display_order": 70,
        "description": "Sucrose content, as measured.",
    },
    {
        "code": "REDUCING_SUGARS",
        "name": "Reducing sugars",
        "unit": "g/100g",
        "display_order": 80,
        "description": "Reducing sugar content, as measured.",
    },
    {
        "code": "WATER_INSOLUBLE_SOLIDS",
        "name": "Water-insoluble solids",
        "unit": "%",
        "display_order": 90,
        "description": "Water-insoluble solids, as measured.",
    },
    {
        "code": "ASH",
        "name": "Ash content",
        "unit": "%",
        "display_order": 100,
        "description": "Ash content, as measured.",
    },
    {
        "code": "COLOR",
        "name": "Colour",
        "unit": "mm Pfund",
        "display_order": 110,
        "description": "Colour, on the scale the laboratory reports.",
    },
    {
        "code": "PURITY",
        "name": "Purity / adulteration indicator",
        "unit": "%",
        "display_order": 120,
        "description": "Purity indicator as reported by the laboratory's method.",
    },
    {
        "code": "OTHER",
        "name": "Other measurement",
        "unit": "unitless",
        "display_order": 999,
        "description": (
            "Any measurement outside this catalogue. The technician names it and states its unit; "
            "several may be recorded on one test."
        ),
    },
)


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------ #
    # The one status value Phase 6 introduces
    # ------------------------------------------------------------------ #
    # ``ADD VALUE`` cannot run inside a transaction on older PostgreSQL. Alembic
    # opens one, so the statement is committed first where required. The new value
    # is not used by this migration, only by the running application afterwards.
    if bind.dialect.name == "postgresql":
        if bind.in_transaction():
            with op.get_context().autocommit_block():
                op.execute(BATCH_STATUS_APPROVED)
        else:  # pragma: no cover - depends on how the migration is invoked
            op.execute(BATCH_STATUS_APPROVED)

    for enum_type in ALL_ENUMS:
        enum_type.create(bind, checkfirst=True)

    # ------------------------------------------------------------------ #
    # processing_units — where honey is processed
    # ------------------------------------------------------------------ #
    op.create_table(
        "processing_units",
        sa.Column("unit_code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("registration_identifier", sa.String(length=80), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column("state", sa.String(length=80), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column(
            "operator_user_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "status",
            facility_status_enum,
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("capacity_kg_per_day", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["operator_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_units")),
    )
    op.create_index(op.f("ix_processing_units_unit_code"), "processing_units", ["unit_code"], unique=True)
    op.create_index("ix_processing_units_district", "processing_units", ["district"])
    op.create_index("ix_processing_units_operator_user_id", "processing_units", ["operator_user_id"])

    # ------------------------------------------------------------------ #
    # laboratories — where honey is tested
    # ------------------------------------------------------------------ #
    op.create_table(
        "laboratories",
        sa.Column("laboratory_code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("registration_identifier", sa.String(length=80), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column("state", sa.String(length=80), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column("accredited", sa.Boolean(), nullable=True),
        sa.Column(
            "status",
            facility_status_enum,
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_laboratories")),
    )
    op.create_index(op.f("ix_laboratories_laboratory_code"), "laboratories", ["laboratory_code"], unique=True)
    op.create_index("ix_laboratories_district", "laboratories", ["district"])

    # ------------------------------------------------------------------ #
    # honey_processing_records — one run on one batch
    # ------------------------------------------------------------------ #
    op.create_table(
        "honey_processing_records",
        sa.Column("processing_code", sa.String(length=40), nullable=False),
        sa.Column(
            "batch_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False
        ),
        sa.Column(
            "processing_unit_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "operator_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False
        ),
        sa.Column("processing_type", processing_type_enum, nullable=False),
        sa.Column("status", processing_status_enum, nullable=False, server_default="PENDING"),
        sa.Column("input_quantity", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("output_quantity", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("loss_quantity", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("unit", collection_unit_enum, nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
            name="ck_processing_input_quantity_positive",
        ),
        sa.CheckConstraint(
            "output_quantity IS NULL OR output_quantity >= 0",
            name="ck_processing_output_quantity_non_negative",
        ),
        sa.CheckConstraint(
            "output_quantity IS NULL OR input_quantity IS NULL OR output_quantity <= input_quantity",
            name="ck_processing_output_not_above_input",
        ),
        sa.CheckConstraint(
            "output_quantity IS NULL OR loss_quantity = input_quantity - output_quantity",
            name="ck_processing_loss_matches_quantities",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["honey_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["processing_unit_id"], ["processing_units.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_honey_processing_records")),
    )
    op.create_index(
        op.f("ix_honey_processing_records_processing_code"),
        "honey_processing_records",
        ["processing_code"],
        unique=True,
    )
    op.create_index("ix_honey_processing_records_batch_id", "honey_processing_records", ["batch_id"])
    op.create_index(
        "ix_honey_processing_records_processing_unit_id",
        "honey_processing_records",
        ["processing_unit_id"],
    )
    op.create_index("ix_honey_processing_records_operator_id", "honey_processing_records", ["operator_id"])
    op.create_index("ix_honey_processing_records_status", "honey_processing_records", ["status"])
    op.create_index(
        "ix_honey_processing_records_processing_date", "honey_processing_records", ["processing_date"]
    )
    op.create_index("ix_processing_batch_created", "honey_processing_records", ["batch_id", "created_at"])
    # At most one run under way per batch. Cancelled and completed runs are
    # history and are excluded, so a batch can be processed again after a
    # cancelled attempt without deleting the attempt.
    op.create_index(
        "uq_processing_open_per_batch",
        "honey_processing_records",
        ["batch_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'IN_PROGRESS')"),
    )

    # ------------------------------------------------------------------ #
    # lab_parameters — the catalogue and the configured ranges
    # ------------------------------------------------------------------ #
    op.create_table(
        "lab_parameters",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("unit", lab_measure_unit_enum, nullable=False),
        sa.Column("description", sa.String(length=400), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reference_min", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("reference_max", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("reference_source", sa.String(length=300), nullable=True),
        sa.Column(
            "reference_updated_by_id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            nullable=True,
        ),
        sa.Column("reference_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "reference_min IS NULL OR reference_max IS NULL OR reference_min <= reference_max",
            name="ck_lab_parameters_reference_range_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["reference_updated_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_parameters")),
        sa.UniqueConstraint("code", name="uq_lab_parameters_code"),
    )
    op.create_index(op.f("ix_lab_parameters_code"), "lab_parameters", ["code"])
    op.create_index("ix_lab_parameters_order", "lab_parameters", ["display_order"])

    # ------------------------------------------------------------------ #
    # lab_tests — one test of one batch
    # ------------------------------------------------------------------ #
    op.create_table(
        "lab_tests",
        sa.Column("test_code", sa.String(length=40), nullable=False),
        sa.Column("sample_code", sa.String(length=40), nullable=False),
        sa.Column(
            "batch_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False
        ),
        sa.Column(
            "processing_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False
        ),
        sa.Column(
            "laboratory_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False
        ),
        sa.Column(
            "technician_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False
        ),
        sa.Column("sample_quantity", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("sample_unit", collection_unit_enum, nullable=False),
        sa.Column("sample_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample_notes", sa.String(length=500), nullable=True),
        sa.Column("test_date", sa.Date(), nullable=False),
        sa.Column("status", lab_test_status_enum, nullable=False, server_default="PENDING"),
        sa.Column("overall_result", lab_result_enum, nullable=False, server_default="PENDING"),
        sa.Column("result_summary", sa.String(length=500), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column(
            "retest_of_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=True
        ),
        sa.Column("retest_reason", sa.String(length=500), nullable=True),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "decided_by_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=True
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("override_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sample_quantity > 0", name="ck_lab_tests_sample_quantity_positive"),
        sa.ForeignKeyConstraint(["batch_id"], ["honey_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["processing_id"], ["honey_processing_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["laboratory_id"], ["laboratories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["technician_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["retest_of_id"], ["lab_tests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_tests")),
    )
    op.create_index(op.f("ix_lab_tests_test_code"), "lab_tests", ["test_code"], unique=True)
    op.create_index(op.f("ix_lab_tests_sample_code"), "lab_tests", ["sample_code"], unique=True)
    op.create_index("ix_lab_tests_batch_id", "lab_tests", ["batch_id"])
    op.create_index("ix_lab_tests_processing_id", "lab_tests", ["processing_id"])
    op.create_index("ix_lab_tests_laboratory_id", "lab_tests", ["laboratory_id"])
    op.create_index("ix_lab_tests_technician_id", "lab_tests", ["technician_id"])
    op.create_index("ix_lab_tests_retest_of_id", "lab_tests", ["retest_of_id"])
    op.create_index("ix_lab_tests_status", "lab_tests", ["status"])
    op.create_index("ix_lab_tests_overall_result", "lab_tests", ["overall_result"])
    op.create_index("ix_lab_tests_test_date", "lab_tests", ["test_date"])
    op.create_index("ix_lab_tests_batch_created", "lab_tests", ["batch_id", "created_at"])

    # ------------------------------------------------------------------ #
    # lab_test_results — one measured parameter
    # ------------------------------------------------------------------ #
    op.create_table(
        "lab_test_results",
        sa.Column(
            "lab_test_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=False
        ),
        sa.Column("parameter_code", sa.String(length=40), nullable=False),
        sa.Column("parameter_name", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("unit", lab_measure_unit_enum, nullable=False),
        sa.Column("reference_min", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("reference_max", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("reference_source", sa.String(length=300), nullable=True),
        sa.Column(
            "status", lab_parameter_status_enum, nullable=False, server_default="NOT_EVALUATED"
        ),
        sa.Column("method", sa.String(length=120), nullable=True),
        sa.Column("remarks", sa.String(length=500), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recorded_by_id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), nullable=True
        ),
        sa.Column(
            "id",
            sa.UUID().with_variant(sa.String(length=36), "sqlite"),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["lab_test_id"], ["lab_tests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parameter_code"], ["lab_parameters.code"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_test_results")),
    )
    op.create_index("ix_lab_test_results_lab_test_id", "lab_test_results", ["lab_test_id"])
    op.create_index("ix_lab_results_test_created", "lab_test_results", ["lab_test_id", "created_at"])
    # One row per parameter per test — except OTHER, which may describe more than
    # one unlisted measurement.
    op.create_index(
        "uq_lab_results_test_parameter",
        "lab_test_results",
        ["lab_test_id", "parameter_code"],
        unique=True,
        postgresql_where=sa.text("parameter_code <> 'OTHER'"),
    )

    # ------------------------------------------------------------------ #
    # The parameter catalogue — names and units only, no thresholds
    # ------------------------------------------------------------------ #
    parameters = sa.table(
        "lab_parameters",
        sa.column("id", sa.UUID()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("unit", lab_measure_unit_enum),
        sa.column("description", sa.String()),
        sa.column("is_required", sa.Boolean()),
        sa.column("display_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        parameters,
        [
            {
                "id": row_id,
                "code": row["code"],
                "name": row["name"],
                "unit": row["unit"],
                "description": row["description"],
                # No parameter is required until an administrator says so: the
                # platform does not decide which measurements a standard demands.
                "is_required": False,
                "display_order": row["display_order"],
                "is_active": True,
            }
            for row_id, row in zip(
                (row_id for row_id in _uuid_stream(len(PARAMETER_CATALOGUE))),
                PARAMETER_CATALOGUE,
                strict=True,
            )
        ],
    )


def downgrade() -> None:
    op.drop_index("uq_lab_results_test_parameter", table_name="lab_test_results")
    op.drop_index("ix_lab_results_test_created", table_name="lab_test_results")
    op.drop_index("ix_lab_test_results_lab_test_id", table_name="lab_test_results")
    op.drop_table("lab_test_results")

    for index in (
        "ix_lab_tests_batch_created",
        "ix_lab_tests_test_date",
        "ix_lab_tests_overall_result",
        "ix_lab_tests_status",
        "ix_lab_tests_retest_of_id",
        "ix_lab_tests_technician_id",
        "ix_lab_tests_laboratory_id",
        "ix_lab_tests_processing_id",
        "ix_lab_tests_batch_id",
        "ix_lab_tests_sample_code",
        "ix_lab_tests_test_code",
    ):
        op.drop_index(index, table_name="lab_tests")
    op.drop_table("lab_tests")

    op.drop_index("ix_lab_parameters_order", table_name="lab_parameters")
    op.drop_index("ix_lab_parameters_code", table_name="lab_parameters")
    op.drop_table("lab_parameters")

    op.drop_index("uq_processing_open_per_batch", table_name="honey_processing_records")
    for index in (
        "ix_processing_batch_created",
        "ix_honey_processing_records_processing_date",
        "ix_honey_processing_records_status",
        "ix_honey_processing_records_operator_id",
        "ix_honey_processing_records_processing_unit_id",
        "ix_honey_processing_records_batch_id",
        "ix_honey_processing_records_processing_code",
    ):
        op.drop_index(index, table_name="honey_processing_records")
    op.drop_table("honey_processing_records")

    op.drop_index("ix_laboratories_district", table_name="laboratories")
    op.drop_index("ix_laboratories_laboratory_code", table_name="laboratories")
    op.drop_table("laboratories")

    op.drop_index("ix_processing_units_operator_user_id", table_name="processing_units")
    op.drop_index("ix_processing_units_district", table_name="processing_units")
    op.drop_index("ix_processing_units_unit_code", table_name="processing_units")
    op.drop_table("processing_units")

    # ``drop_table`` never removes a PostgreSQL enum type; without this a later
    # ``upgrade`` would fail with "type ... already exists".
    for enum_type in reversed(ALL_ENUMS):
        enum_type.drop(op.get_bind(), checkfirst=True)

    # ``batch_status`` deliberately keeps its APPROVED value: PostgreSQL cannot
    # remove an enum value without rewriting the type and every row that uses it,
    # and once the tables above are gone nothing can set it. Re-running the
    # upgrade is safe because the statement uses ADD VALUE IF NOT EXISTS.


def _uuid_stream(count: int):
    """Deterministic catalogue ids, so re-running a migration is reproducible."""
    import uuid as _uuid

    namespace = _uuid.UUID("6f6c1d2e-9f6b-4a1e-9c3f-6d0f3a5e6b21")
    for index in range(count):
        yield _uuid.uuid5(namespace, f"lab-parameter-{index}")

"""Install the laboratory parameter catalogue, if it is not there already.

Why this exists
---------------
The catalogue — which measurements the platform can record, and in which unit —
is *configuration*, not sample data. The Phase-6 migration creates the 13 rows, so
a migrated database has them from the first request. But a database built from the
models alone (the test suite does exactly that, with ``create_all``) has the table
and none of the rows. This module closes that gap: it installs the same catalogue,
idempotently, and it is safe to run against any database.

What it deliberately does **not** do
------------------------------------
It never writes a reference range, and it never marks a parameter as required.
Both of those are decisions an administrator makes per project, with a stated
source, through the API — and the platform refuses to invent a scientific limit
on anyone's behalf. Every row it installs is a *slot to measure into*, with
``reference_min``/``reference_max`` NULL, which is why a measured value with no
limit configured is reported as ``NOT_EVALUATED`` rather than passed.

The list below is deliberately a second copy of the one in
``alembic/versions/20260925_1030_9b4d2f81ac07_phase_6_processing_and_laboratory.py``.
Migrations must stay readable years later, so they carry their own data rather
than importing application modules that move on; the two lists are pinned together
by the test suite, which asserts the exact codes and units the platform ships.

Usage::

    python -m app.scripts.seed_lab_parameters          # install if missing
    python -m app.scripts.seed_lab_parameters --check  # report only
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import build_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.models.enums import LabMeasureUnit
from app.models.laboratory import LabParameter

#: ``(code, name, unit, description, display_order)`` — the measurement slots the
#: platform ships. Ranges are configured later, by a person, with a source.
LAB_PARAMETER_CATALOGUE: tuple[tuple[str, str, LabMeasureUnit, str, int], ...] = (
    (
        "MOISTURE",
        "Moisture content",
        LabMeasureUnit.PERCENT,
        "Water content of the honey, as measured by the laboratory.",
        10,
    ),
    (
        "PH",
        "pH",
        LabMeasureUnit.PH_SCALE,
        "Acidity of the honey.",
        20,
    ),
    (
        "FREE_ACIDITY",
        "Free acidity",
        LabMeasureUnit.MEQ_PER_KG,
        "Free acidity, reported in milliequivalents per kilogram.",
        30,
    ),
    (
        "ELECTRICAL_CONDUCTIVITY",
        "Electrical conductivity",
        LabMeasureUnit.MS_PER_CM,
        "Electrical conductivity of a honey solution.",
        40,
    ),
    (
        "HMF",
        "Hydroxymethylfurfural (HMF)",
        LabMeasureUnit.MG_PER_KG,
        "HMF content, reported in milligrams per kilogram.",
        50,
    ),
    (
        "DIASTASE_ACTIVITY",
        "Diastase activity",
        LabMeasureUnit.DN,
        "Diastase number, a measure of enzyme activity.",
        60,
    ),
    (
        "SUCROSE",
        "Sucrose content",
        LabMeasureUnit.G_PER_100G,
        "Sucrose content, reported in grams per 100 g.",
        70,
    ),
    (
        "REDUCING_SUGARS",
        "Reducing sugars",
        LabMeasureUnit.G_PER_100G,
        "Reducing sugar content, reported in grams per 100 g.",
        80,
    ),
    (
        "WATER_INSOLUBLE_SOLIDS",
        "Water-insoluble solids",
        LabMeasureUnit.PERCENT,
        "Water-insoluble solids, as a percentage.",
        90,
    ),
    (
        "ASH",
        "Ash content",
        LabMeasureUnit.PERCENT,
        "Ash content, as a percentage.",
        100,
    ),
    (
        "COLOR",
        "Colour",
        LabMeasureUnit.MM_PFUND,
        "Colour, reported in millimetres on the Pfund scale.",
        110,
    ),
    (
        "PURITY",
        "Purity / adulteration screen",
        LabMeasureUnit.PERCENT,
        "A purity determination, as the laboratory reports it.",
        120,
    ),
    (
        "OTHER",
        "Other measurement",
        LabMeasureUnit.UNITLESS,
        (
            "A free slot for a measurement the catalogue does not name. Each recorded "
            "row states what it measured, in words, and nothing is judged unless a "
            "range is configured for it while the row is recorded."
        ),
        130,
    ),
)

#: The same list the Phase-6 migration installs. Asserted by the test suite so the
#: two can never drift apart unnoticed.
CATALOGUE_CODES: tuple[str, ...] = tuple(row[0] for row in LAB_PARAMETER_CATALOGUE)


def seed_lab_parameters(session: Session, *, check_only: bool = False) -> dict[str, object]:
    """Insert any missing catalogue rows. Existing rows are left exactly as they are.

    "Left exactly as they are" is the important part: if an administrator has
    configured a range for moisture, running this again must not clear it. Only
    absent codes are added.
    """
    existing = {
        code for code in session.execute(select(LabParameter.code)).scalars().all()
    }
    missing = [row for row in LAB_PARAMETER_CATALOGUE if row[0] not in existing]

    if check_only or not missing:
        return {
            "installed": 0,
            "missing": [row[0] for row in missing],
            "total": len(existing),
            "check_only": check_only,
        }

    for code, name, unit, description, display_order in missing:
        session.add(
            LabParameter(
                code=code,
                name=name,
                unit=unit,
                description=description,
                # No range and not required: the platform records what it is told
                # and judges nothing until an administrator configures a limit and
                # says where that limit came from.
                is_required=False,
                reference_min=None,
                reference_max=None,
                reference_source=None,
                display_order=display_order,
                is_active=True,
            )
        )
    session.commit()
    return {
        "installed": len(missing),
        "missing": [],
        "total": len(existing) + len(missing),
        "check_only": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the laboratory parameter catalogue (idempotent)."
    )
    parser.add_argument(
        "--check", action="store_true", help="Report what is missing without writing."
    )
    args = parser.parse_args(argv)

    settings = build_settings()
    configure_logging(settings)

    session = SessionLocal()
    try:
        result = seed_lab_parameters(session, check_only=args.check)
    finally:
        session.close()

    if args.check:
        print(
            f"Catalogue: {result['total']} parameter(s) present; "
            f"missing: {result['missing'] or 'none'}"
        )
    else:
        print(
            f"Catalogue: installed {result['installed']} parameter(s); "
            f"{result['total']} present in total."
        )
        print(
            "No reference range was configured and no parameter was marked required: "
            "those are decisions an administrator makes through the API, with a source."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())

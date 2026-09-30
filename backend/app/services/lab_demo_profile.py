"""Development/demo laboratory configuration — declared once, labelled everywhere.

Why this module exists
----------------------
The platform records honey quality measurements against a catalogue of
parameters. In production, each parameter's acceptable range is entered by an
administrator with a stated source, and the platform judges a measurement only
against what it was given.

That leaves a working installation with nothing configured and, correctly, every
test *inconclusive*. That is the right production behaviour and a useless demo:
a person cannot see the workflow run end to end without spending an afternoon
configuring ranges first. This module closes that gap the only honest way —
by **declaring a development profile in one place**, labelling its provenance on
every row it writes, and keeping it strictly separate from anything a person has
configured.

Three rules hold the honesty in place
-------------------------------------
1. **It never overwrites.** A parameter whose range was configured by a person
   (``reference_updated_by_id`` is set) is left exactly as it is. Running the
   development installer again after configuring moisture by hand changes
   nothing about moisture.
2. **It says where it came from.** Every range it installs carries
   ``reference_source = DEMO_SOURCE``, and that text is rendered next to the
   range wherever the platform shows them. Nothing here is claimed to be a
   regulatory standard, a buyer's specification or anyone's official limit. The
   values themselves are round numbers chosen to be plausible for honey so the
   demo produces a sensible verdict; they are the shape of a configuration, not
   a scientific statement.
3. **It is configuration, not measurement.** A starting value is stored with
   ``measurement_source = DEMO`` when a test is opened, and every screen that
   shows a recorded value shows where it came from. A technician replacing one
   makes it ``MANUAL``. Nothing in this module ever claims that a value was
   measured by an instrument.

Replacing it later
------------------
Point 1 is what makes the profile replaceable: an administrator configures real
ranges and their source through ``PATCH /api/v1/lab-parameters/{code}``, and this
module stops touching those parameters for good. Turning
``LAB_DEMO_CONFIGURATION_ENABLED`` and ``LAB_DEMO_MEASUREMENTS_ENABLED`` off
leaves a production installation that records and judges exactly what it was
told, and nothing this file ever wrote is required for the workflow to run.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.laboratory import LabParameter

#: The provenance written onto every range this module installs. It is shown in
#: the UI beside the range, so nobody has to guess who decided it.
DEMO_SOURCE = "DEMO configuration — development profile, not a regulatory standard"

#: One entry per catalogue parameter:
#: ``(code, reference_min, reference_max, development_value, methods)``.
#:
#: * the range is what a measured value is compared against in demo mode;
#: * ``development_value`` is what a test is pre-filled with — deliberately
#:   *inside* the range, so the normal path through the demo is a passing test;
#: * ``methods`` are the bench methods that apply to that measurement. "Other"
#:   is always offered on top of the list, and the words typed for it are stored
#:   exactly as typed.
#:
#: The ranges are round numbers in each parameter's own unit. They describe the
#: shape of a configuration so the workflow can be demonstrated; they are not
#: quoted from any standard and the platform never presents them as one.
DEMO_PROFILE: tuple[tuple[str, Decimal, Decimal, Decimal, tuple[tuple[str, str], ...]], ...] = (
    (
        "MOISTURE",
        Decimal("15"),
        Decimal("20"),
        Decimal("17.2"),
        (
            ("REFRACTOMETRY", "Refractometry (refractive index)"),
            ("KARL_FISCHER", "Karl Fischer titration"),
            ("DISTILLATION", "Distillation"),
        ),
    ),
    (
        "PH",
        Decimal("3.2"),
        Decimal("4.5"),
        Decimal("3.9"),
        (
            ("PH_METER", "pH meter"),
            ("POTENTIOMETRIC", "Potentiometric titration"),
        ),
    ),
    (
        "FREE_ACIDITY",
        Decimal("5"),
        Decimal("40"),
        Decimal("18.0"),
        (
            ("TITRATION", "Acid–base titration"),
            ("POTENTIOMETRIC", "Potentiometric titration"),
        ),
    ),
    (
        "ELECTRICAL_CONDUCTIVITY",
        Decimal("0.1"),
        Decimal("0.8"),
        Decimal("0.35"),
        (
            ("CONDUCTIVITY_METER", "Conductivity meter"),
            ("CELL", "Conductivity cell"),
        ),
    ),
    (
        "HMF",
        Decimal("0"),
        Decimal("40"),
        Decimal("12.0"),
        (
            ("HPLC", "High-performance liquid chromatography"),
            ("SPECTROPHOTOMETRY", "Spectrophotometry (Winkler)"),
        ),
    ),
    (
        "DIASTASE_ACTIVITY",
        Decimal("8"),
        Decimal("30"),
        Decimal("18.5"),
        (
            ("SCHADE", "Schade method (diastase number)"),
            ("SPECTROPHOTOMETRY", "Spectrophotometry"),
        ),
    ),
    (
        "SUCROSE",
        Decimal("0"),
        Decimal("5"),
        Decimal("1.8"),
        (
            ("HPLC", "High-performance liquid chromatography"),
            ("ENZYMATIC", "Enzymatic assay"),
        ),
    ),
    (
        "REDUCING_SUGARS",
        Decimal("60"),
        Decimal("80"),
        Decimal("71.0"),
        (
            ("FEHLING", "Fehling's titration"),
            ("HPLC", "High-performance liquid chromatography"),
        ),
    ),
    (
        "WATER_INSOLUBLE_SOLIDS",
        Decimal("0"),
        Decimal("0.5"),
        Decimal("0.12"),
        (
            ("GRAVIMETRIC", "Gravimetric determination"),
            ("FILTRATION", "Filtration and weighing"),
        ),
    ),
    (
        "ASH",
        Decimal("0"),
        Decimal("0.6"),
        Decimal("0.18"),
        (
            ("GRAVIMETRIC", "Gravimetric determination (muffle furnace)"),
        ),
    ),
    (
        "COLOR",
        Decimal("10"),
        Decimal("85"),
        Decimal("38.0"),
        (
            ("PFUND", "Pfund colour grader"),
            ("SPECTROPHOTOMETRY", "Spectrophotometric colour"),
        ),
    ),
    (
        "PURITY",
        Decimal("95"),
        Decimal("100"),
        Decimal("98.4"),
        (
            ("MICROSCOPY", "Microscopic examination"),
            ("SENSORY", "Sensory and physical examination"),
        ),
    ),
    # "Other" is a free slot: a name typed by the technician, a value, and a
    # method. Its band is a unitless placeholder — nothing scientific is claimed
    # about a measurement nobody has defined — and its development value sits at
    # the *middle* of that band, so an untouched demo profile is not read as an
    # anomaly merely because its placeholder was written near an edge. The value
    # exists so the demo has something to edit; editing it is the point.
    (
        "OTHER",
        Decimal("0"),
        Decimal("100"),
        Decimal("50"),
        (
            ("BENCH", "Bench method"),
            ("IN_HOUSE", "In-house procedure"),
        ),
    ),
)

#: Development values are written to the middle of each band on purpose. They are
#: placeholders a technician edits, and a placeholder parked near the edge of its
#: own band would make every untouched demo look like an anomaly to the isolation
#: pass below. Middle-of-band says "nothing has happened here yet" in the only way
#: a number can.

#: Codes in this profile, in catalogue order.
PROFILE_CODES: tuple[str, ...] = tuple(row[0] for row in DEMO_PROFILE)

#: The parameters the demo mode marks as required, so a passing verdict needs a
#: complete picture: moisture (the platform's own shipped policy), plus pH and
#: HMF, which are the two measurements the demo's risk example varies. In
#: production the required set is whatever the laboratory decides, per parameter.
DEMO_REQUIRED_CODES: tuple[str, ...] = ("MOISTURE", "PH", "HMF")


def methods_for(code: str) -> list[dict[str, str]]:
    """The configured method options for a parameter, as stored rows."""
    for profile_code, _min, _max, _value, methods in DEMO_PROFILE:
        if profile_code == code:
            return [{"code": method_code, "label": label} for method_code, label in methods]
    return []


def install_demo_configuration(session: Session, *, force: bool = False) -> dict[str, object]:
    """Apply the development profile to the catalogue. Idempotent and non-destructive.

    A parameter is only touched when it carries no configured range yet (or when
    ``force`` is passed deliberately). Everything already configured by a person
    — a range with a source, a method list already chosen — is left alone, which
    is what makes this safe to run on every startup.
    """
    rows = session.query(LabParameter).all()
    configured: list[str] = []
    applied: list[str] = []
    refreshed: list[str] = []

    for parameter in rows:
        profile = next((row for row in DEMO_PROFILE if row[0] == parameter.code), None)
        if profile is None:
            continue
        _code, minimum, maximum, development_value, methods = profile

        # A person's configuration always wins, permanently.
        already_configured = parameter.reference_updated_by_id is not None or parameter.is_configured
        if already_configured and not force:
            # The range is not ours to touch. The development *placeholder* is, but
            # only while the range is still the demo's own: a parameter whose range
            # somebody configured keeps whatever value came with it, because the
            # placeholder belongs to whoever owns the range.
            if (
                parameter.reference_source == DEMO_SOURCE
                and parameter.development_value is not None
                and parameter.development_value != development_value
            ):
                parameter.development_value = development_value
                refreshed.append(parameter.code)
            configured.append(parameter.code)
            continue

        parameter.reference_min = minimum
        parameter.reference_max = maximum
        parameter.reference_source = DEMO_SOURCE
        parameter.development_value = development_value
        if force or not parameter.methods:
            parameter.methods = [{"code": code, "label": label} for code, label in methods]
        if parameter.code in DEMO_REQUIRED_CODES:
            parameter.is_required = True
        applied.append(parameter.code)

    session.commit()
    return {
        "applied": applied,
        "left_as_configured": configured,
        "development_values_refreshed": refreshed,
        "profile": list(PROFILE_CODES),
    }


def is_demo_source(source: str | None) -> bool:
    """True when a range's stated source is the development profile."""
    return bool(source) and source.strip().startswith("DEMO configuration")

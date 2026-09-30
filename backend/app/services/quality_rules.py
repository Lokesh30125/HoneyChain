"""How a measurement becomes a verdict — the platform's only judgement call.

Kept as pure functions, with no database and no HTTP, because this is the part of
Phase 6 that must be defensible line by line. Everything else in the phase records
facts; this module is where a fact is compared with a limit, and the rules are
deliberately narrow enough to read in one sitting.

The rules
---------
**A parameter is judged only against a configured range.** With no range
configured, a measured value is recorded and reported as ``NOT_EVALUATED``. The
platform does not know that 17.2 % moisture is acceptable, and will not imply
that it does: the range, and the text saying where the range came from, are
entered by an administrator.

**A test cannot pass by declaration.** The overall result is always computed here
from the recorded results. No request body in the API carries an overall result.

**Overall result.**
  1. a required parameter with no result          → ``INCONCLUSIVE``
  2. a recorded result with no reference range    → ``INCONCLUSIVE``
  3. a required parameter that failed             → ``FAIL``
  4. otherwise                                    → ``PASS``

Rule 2 is the one that keeps the platform honest: if the laboratory measured
something nobody has defined a limit for, the test has not established that the
honey is within specification, so it does not say that it is.

**A failed optional parameter does not fail the batch** — it is recorded and
reported, because it may be a measurement nobody set a limit for, and pretending
otherwise would be inventing a standard.

**An override is explicit.** An administrator may set a result by hand, but only
with a reason, only through an endpoint that audits it, and the test is marked as
overridden for every reader afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.enums import LabParameterStatus, LabResult


@dataclass(slots=True)
class EvaluatedResult:
    """One parameter's contribution to the verdict."""

    parameter_code: str
    parameter_name: str
    value: Decimal
    unit: str
    status: LabParameterStatus
    reference_min: Decimal | None
    reference_max: Decimal | None
    reference_source: str | None
    is_required: bool

    @property
    def reference_text(self) -> str | None:
        """The configured range as a sentence, or None when there is none."""
        if self.reference_min is None and self.reference_max is None:
            return None
        if self.reference_min is not None and self.reference_max is not None:
            return f"configured range {self.reference_min}–{self.reference_max} {self.unit}"
        if self.reference_min is not None:
            return f"configured minimum {self.reference_min} {self.unit}"
        return f"configured maximum {self.reference_max} {self.unit}"


@dataclass(slots=True)
class Verdict:
    """The outcome of a completed test, with the reasoning that produced it."""

    result: LabResult
    summary: str
    reasons: list[str] = field(default_factory=list)
    failed_parameters: list[str] = field(default_factory=list)
    unevaluated_parameters: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)

    @property
    def is_decision(self) -> bool:
        """True when the outcome settles the batch's fate."""
        return self.result.is_decision


def evaluate_parameter(
    *,
    value: Decimal,
    reference_min: Decimal | None,
    reference_max: Decimal | None,
) -> LabParameterStatus:
    """Compare one measured value with the range configured for its parameter."""
    if reference_min is None and reference_max is None:
        return LabParameterStatus.NOT_EVALUATED
    if reference_min is not None and value < reference_min:
        return LabParameterStatus.FAIL
    if reference_max is not None and value > reference_max:
        return LabParameterStatus.FAIL
    return LabParameterStatus.PASS


def decide(results: list[EvaluatedResult], required_codes: list[str]) -> Verdict:
    """Turn the recorded results into an overall result.

    ``required_codes`` comes from the parameter catalogue (the platform's review
    policy), not from the results, so a test cannot dodge a required measurement
    by simply not recording it.
    """
    recorded = {row.parameter_code for row in results}
    missing_required = sorted(code for code in required_codes if code not in recorded)
    unevaluated = sorted(
        row.parameter_code
        for row in results
        if row.status is LabParameterStatus.NOT_EVALUATED
    )
    required_failed = sorted(
        row.parameter_code
        for row in results
        if row.is_required and row.status is LabParameterStatus.FAIL
    )
    optional_failed = sorted(
        row.parameter_code
        for row in results
        if not row.is_required and row.status is LabParameterStatus.FAIL
    )

    reasons: list[str] = []

    if missing_required:
        reasons.append(
            "No result was recorded for the required parameter(s): "
            + ", ".join(missing_required)
            + "."
        )
    if unevaluated:
        reasons.append(
            "No reference range is configured for: "
            + ", ".join(unevaluated)
            + " — the measurements are recorded but nothing was compared against them."
        )
    if required_failed:
        reasons.append(
            "Required parameter(s) outside their configured range: "
            + ", ".join(required_failed)
            + "."
        )
    if optional_failed:
        reasons.append(
            "Optional parameter(s) outside their configured range (recorded, does not "
            "decide the test): " + ", ".join(optional_failed) + "."
        )
    if not reasons:
        reasons.append("Every recorded parameter is within its configured range.")

    if missing_required or unevaluated:
        result = LabResult.INCONCLUSIVE
    elif required_failed:
        result = LabResult.FAIL
    else:
        result = LabResult.PASS

    summary = _summarise(result, results, required_failed, optional_failed, unevaluated, missing_required)
    return Verdict(
        result=result,
        summary=summary,
        reasons=reasons,
        failed_parameters=sorted(required_failed + optional_failed),
        unevaluated_parameters=unevaluated,
        missing_required=missing_required,
    )


def _summarise(
    result: LabResult,
    results: list[EvaluatedResult],
    required_failed: list[str],
    optional_failed: list[str],
    unevaluated: list[str],
    missing_required: list[str],
) -> str:
    passed = sum(1 for row in results if row.status is LabParameterStatus.PASS)
    total = len(results)

    if result is LabResult.PASS:
        return (
            f"All {total} recorded parameter(s) are within their configured ranges"
            + (f"; {len(optional_failed)} optional parameter(s) were outside theirs." if optional_failed else ".")
        )
    if result is LabResult.FAIL:
        return (
            f"{len(required_failed)} required parameter(s) outside their configured range "
            f"({', '.join(required_failed)}); {passed} of {total} recorded parameter(s) passed."
        )
    parts = []
    if missing_required:
        parts.append(f"{len(missing_required)} required parameter(s) not measured")
    if unevaluated:
        parts.append(f"{len(unevaluated)} parameter(s) have no configured reference range")
    return (
        "No decision is possible yet: " + "; ".join(parts) + "."
        if parts
        else "No decision is possible yet."
    )


def batch_status_for(verdict: Verdict):
    """Which batch status a verdict implies — None when it decides nothing."""
    from app.models.enums import BatchStatus

    if verdict.result is LabResult.PASS:
        return BatchStatus.APPROVED
    if verdict.result is LabResult.FAIL:
        return BatchStatus.REJECTED
    return None


__all__ = [
    "EvaluatedResult",
    "Verdict",
    "batch_status_for",
    "decide",
    "evaluate_parameter",
]

"""Laboratory quality analysis — the AI stage of the batch workflow.

What it is, and what it is not
------------------------------
This module reads the measurements a laboratory has recorded on a test, compares
them with the ranges configured for each parameter, and adds a **multivariate
isolation check** that the per-parameter comparison cannot make on its own: a
value can sit inside its own range and still be odd next to the rest of the
batch's profile, and that is worth telling a technician about.

It is *development decision-support*. It is not a certified method, it is not a
substitute for the laboratory's own procedures, and it does not claim a validated
accuracy — there is no validated laboratory dataset in this project to train or
benchmark against, and the API says so in its own response rather than in a
footnote. What it does claim is narrower and true: it is a real implementation of
the isolation-forest algorithm, it is deterministic for a given set of
measurements, and every conclusion it reaches is followed by the numbers and the
configured ranges that produced it.

The isolation forest
--------------------
Isolation Forest (Liu, Ting & Zhou, 2008) scores a point by how quickly it is
isolated by random binary splits: anomalous points need fewer splits. The
implementation here is the algorithm itself — an ensemble of random trees over
the feature matrix, path-length scoring with the paper's normalisation constant
``c(n)`` — written in plain Python because the project deliberately carries no
scientific stack, and kept to a few dozen lines so it can be read and checked.
It is seeded, so the same measurements always produce the same score.

Two sources of judgement, reported separately
---------------------------------------------
* **Configured-range evaluation** — deterministic, and the only thing that can
  produce a FAIL. A measurement outside the range an administrator configured,
  with the source of that range quoted beside it.
* **Isolation score** — a statement about the shape of the profile, reported as a
  vulnerability with the parameters that drove it. It never fails a batch by
  itself; it raises a flag a person decides on.

Where there is no configured range, nothing is judged and the platform says
"not evaluated" — which is what makes a test inconclusive rather than passed.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import fmean

from app.models.enums import LabParameterStatus

#: The identity written onto every stored analysis, in the same shape the hive
#: engine uses. ``model_version`` changes when the scoring here changes, so an old
#: result can still be read back with what produced it.
MODEL_NAME = "IsolationForest"
MODEL_VERSION = "dev-v1"
ANALYSIS_SOURCE = "DEVELOPMENT"

#: The classifier half of the pipeline is deliberately *not* a trained model:
#: no validated dataset exists, and inventing accuracy would be a lie. It is the
#: configured ranges plus the isolation score, and it says so here.
CLASSIFIER_NOTE = (
    "Risk classification is rule-based over the configured reference ranges and the "
    "isolation score. No RandomForest classifier is trained or used: the project has no "
    "validated laboratory dataset, and no accuracy is claimed."
)

#: Isolation-forest shape. Small on purpose: a laboratory test has a handful of
#: parameters, and a deep forest over seven points would be memorisation dressed
#: up as modelling.
_TREES = 128
_SAMPLE_SIZE = 32
_MAX_DEPTH = 8
_SEED = 20260929

#: Scores above this are reported as a vulnerability. The paper's conventional
#: decision threshold for contamination around 10%.
_ANOMALY_THRESHOLD = 0.62
#: A score this high is reported as a likely outlier even with few parameters.
_STRONG_THRESHOLD = 0.72
#: How close to an edge of its own range a value counts as sitting at that edge.
#: ``0`` is the middle of a range and ``1`` is the edge, so this is the outer 15%.
_EDGE_POSITION = 0.85

#: Why a single isolated reading does not, on its own, hold a batch.
#:
#: On a profile of a dozen measurements the forest will *always* find the point
#: that sits furthest from the others — that is what the algorithm does — so
#: treating one flagged reading as a reason to stop everything would flag nearly
#: every test and the flag would stop meaning anything. What is worth stopping for
#: is a reading the ranges cannot explain: either it sits at the edge of its own
#: range, where a small slip takes it out of range, or the profile contains more
#: than one isolated measurement, which a single transcription error does not
#: usually produce. Anything less is reported as a remark on the analysis, with
#: the score beside it, and the decision stays with the person reading it.

_FEATURE_EPSILON = Decimal("0.0000001")


@dataclass(slots=True)
class MeasurementPoint:
    """One measured parameter, as the analysis sees it."""

    code: str
    name: str
    unit: str
    value: Decimal
    reference_min: Decimal | None
    reference_max: Decimal | None
    reference_source: str | None
    is_required: bool
    measurement_source: str
    method: str | None = None

    @property
    def configured(self) -> bool:
        return self.reference_min is not None or self.reference_max is not None

    @property
    def position(self) -> float | None:
        """Where the value sits relative to its configured range.

        ``0`` is the centre of the range and ``±1`` is an edge, so the number is
        comparable across parameters measured in different units — which is what
        lets one model look at the whole profile at once. ``None`` when nothing is
        configured: there is no frame of reference to place it in.
        """
        if not self.configured:
            return None
        low = float(self.reference_min) if self.reference_min is not None else None
        high = float(self.reference_max) if self.reference_max is not None else None
        value = float(self.value)
        if low is not None and high is not None:
            centre = (low + high) / 2
            half = (high - low) / 2
            if half <= 0:
                return 0.0 if value == centre else 6.0
            return (value - centre) / half
        if low is not None:
            span = max(abs(low), 1.0)
            return (value - low) / span
        span = max(abs(high), 1.0)
        return (value - high) / span

    def rule_status(self) -> LabParameterStatus:
        """The configured-range verdict for this measurement."""
        if not self.configured:
            return LabParameterStatus.NOT_EVALUATED
        if self.reference_min is not None and self.value < self.reference_min:
            return LabParameterStatus.FAIL
        if self.reference_max is not None and self.value > self.reference_max:
            return LabParameterStatus.FAIL
        return LabParameterStatus.PASS

    def reference_text(self) -> str | None:
        if not self.configured:
            return None
        low = self.reference_min if self.reference_min is not None else None
        high = self.reference_max if self.reference_max is not None else None
        if low is not None and high is not None:
            return f"{low}–{high} {self.unit}"
        if low is not None:
            return f"at least {low} {self.unit}"
        return f"at most {high} {self.unit}"


class IsolationForest:
    """A small, seeded isolation forest over a fixed feature matrix.

    Fitted on the points it is given and used to score those same points, which
    is what the algorithm is for: no training set is required, so the absence of a
    validated laboratory dataset is not a gap in it.

    A plain class rather than a dataclass because it carries built state — the
    trees — alongside its input, and building them in ``__init__`` is what makes
    the object immutable from the caller's point of view.
    """

    def __init__(self, data: list[list[float]], *, seed: int = _SEED) -> None:
        self.data = data
        self.seed = seed
        self._random = random.Random(seed)
        self._trees = self._build()

    # -- training ---------------------------------------------------------- #
    def _build(self) -> list[dict]:
        trees: list[dict] = []
        count = len(self.data)
        if count == 0:
            return trees
        size = min(_SAMPLE_SIZE, count)
        for _ in range(_TREES):
            if size < count:
                sample = self._random.sample(self.data, size)
            else:
                sample = [[*row] for row in self.data]
            trees.append(self._grow(sample, depth=0))
        return trees

    def _grow(self, rows: list[list[float]], *, depth: int) -> dict:
        if len(rows) <= 1 or depth >= _MAX_DEPTH:
            return {"size": len(rows)}
        dimensions = len(rows[0])
        candidates = [index for index in range(dimensions) if len({row[index] for row in rows}) > 1]
        if not candidates:
            return {"size": len(rows)}
        dimension = self._random.choice(candidates)
        values = [row[dimension] for row in rows]
        low, high = min(values), max(values)
        if math.isclose(low, high):
            return {"size": len(rows)}
        split = self._random.uniform(low, high)
        left = [row for row in rows if row[dimension] < split]
        right = [row for row in rows if row[dimension] >= split]
        return {
            "dimension": dimension,
            "split": split,
            "left": self._grow(left, depth=depth + 1),
            "right": self._grow(right, depth=depth + 1),
        }

    # -- scoring ----------------------------------------------------------- #
    def _path_length(self, point: list[float], node: dict, depth: int) -> float:
        if "dimension" not in node:
            return depth + _average_path_length(node.get("size", 1))
        branch = "left" if point[node["dimension"]] < node["split"] else "right"
        return self._path_length(point, node[branch], depth + 1)

    def score(self, point: list[float]) -> float:
        """The paper's anomaly score: higher means easier to isolate."""
        if not self._trees:
            return 0.0
        lengths = [self._path_length(point, tree, 0) for tree in self._trees]
        average = fmean(lengths)
        denominator = _average_path_length(len(self.data))
        if denominator <= 0:
            return 0.0
        return 2 ** (-average / denominator)


def _average_path_length(n: int) -> float:
    """``c(n)`` — the expected path length of an unsuccessful search in a BST."""
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2 * (math.log(n - 1) + 0.5772156649) - (2 * (n - 1) / n)


@dataclass(slots=True)
class LabQualityAnalysis:
    """The structured result stored on a test and shown in the workspace."""

    overall_status: str
    risk_level: str
    vulnerabilities: list[str] = field(default_factory=list)
    abnormal_parameters: list[str] = field(default_factory=list)
    passed_parameters: list[str] = field(default_factory=list)
    inconclusive_parameters: list[str] = field(default_factory=list)
    explanation: str = ""
    recommendation: str = ""
    isolation_score: float | None = None
    #: Readings the isolation pass found unusual but which the configured ranges
    #: account for — reported, and deliberately not escalated. See ``_EDGE_POSITION``.
    isolation_remarks: list[str] = field(default_factory=list)
    per_parameter: list[dict] = field(default_factory=list)
    model: str = MODEL_NAME
    model_version: str = MODEL_VERSION
    source: str = ANALYSIS_SOURCE
    classifier: str = CLASSIFIER_NOTE
    measurement_sources: dict[str, int] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    @property
    def has_vulnerabilities(self) -> bool:
        return bool(self.vulnerabilities)

    @property
    def blocks_packaging(self) -> bool:
        """A batch the analysis flagged may not be packed without a decision."""
        return self.overall_status in {"HOLD", "FAIL", "INCONCLUSIVE"}

    @classmethod
    def from_dict(cls, payload: dict | None) -> "LabQualityAnalysis":
        """Rebuild the analysis from the form it was stored in.

        The stored JSON is the record of what was concluded, so it is read back
        verbatim rather than recomputed: a stored HOLD stays a HOLD even after the
        ranges behind it are reconfigured.
        """
        payload = payload or {}
        return cls(
            overall_status=str(payload.get("overall_status", "INCONCLUSIVE")),
            risk_level=str(payload.get("risk_level", "UNKNOWN")),
            vulnerabilities=list(payload.get("vulnerabilities", [])),
            abnormal_parameters=list(payload.get("abnormal_parameters", [])),
            passed_parameters=list(payload.get("passed_parameters", [])),
            inconclusive_parameters=list(payload.get("inconclusive_parameters", [])),
            explanation=str(payload.get("explanation", "")),
            recommendation=str(payload.get("recommendation", "")),
            isolation_score=payload.get("isolation_score"),
            isolation_remarks=list(payload.get("isolation_remarks", [])),
            per_parameter=list(payload.get("per_parameter", [])),
            model=str(payload.get("model", MODEL_NAME)),
            model_version=str(payload.get("model_version", MODEL_VERSION)),
            source=str(payload.get("source", ANALYSIS_SOURCE)),
            classifier=str(payload.get("classifier", CLASSIFIER_NOTE)),
            measurement_sources=dict(payload.get("measurement_sources", {})),
            limitations=list(payload.get("limitations", [])),
        )

    def as_dict(self) -> dict:
        return {
            "overall_status": self.overall_status,
            "risk_level": self.risk_level,
            "vulnerabilities": list(self.vulnerabilities),
            "abnormal_parameters": list(self.abnormal_parameters),
            "passed_parameters": list(self.passed_parameters),
            "inconclusive_parameters": list(self.inconclusive_parameters),
            "explanation": self.explanation,
            "recommendation": self.recommendation,
            "isolation_score": (
                None if self.isolation_score is None else round(self.isolation_score, 4)
            ),
            "isolation_remarks": list(self.isolation_remarks),
            "per_parameter": list(self.per_parameter),
            "model": self.model,
            "model_version": self.model_version,
            "source": self.source,
            "classifier": self.classifier,
            "measurement_sources": dict(self.measurement_sources),
            "limitations": list(self.limitations),
        }


def _describe(point: MeasurementPoint) -> str:
    reference = point.reference_text()
    value = f"{point.value} {point.unit}".strip()
    if reference is None:
        return f"{point.name} measured {value}; no reference range is configured"
    return f"{point.name} measured {value} against a configured range of {reference}"


def analyse_measurements(points: list[MeasurementPoint]) -> LabQualityAnalysis:
    """Run the analysis over one test's measurements.

    Pure: no database, no clock, no configuration lookups beyond the parameters'
    own rows — so the same measurements always produce the same result, and the
    result can be recomputed and compared years later.
    """
    if not points:
        return LabQualityAnalysis(
            overall_status="INCONCLUSIVE",
            risk_level="UNKNOWN",
            explanation="No measurements have been recorded, so there is nothing to analyse.",
            recommendation="Record the laboratory measurements, then run the analysis again.",
            limitations=["The analysis only reads measurements that exist."],
        )

    abnormal: list[str] = []
    passed: list[str] = []
    inconclusive: list[str] = []
    detail_rows: list[dict] = []

    for point in points:
        status = point.rule_status()
        entry = {
            "parameter": point.code,
            "name": point.name,
            "value": str(point.value),
            "unit": point.unit,
            "reference": point.reference_text(),
            "reference_source": point.reference_source,
            "status": str(status),
            "measurement_source": point.measurement_source,
            "method": point.method,
            "is_required": point.is_required,
            "position_in_range": (
                None if point.position is None else round(point.position, 3)
            ),
        }
        if status is LabParameterStatus.FAIL:
            abnormal.append(point.code)
        elif status is LabParameterStatus.NOT_EVALUATED:
            inconclusive.append(point.code)
        else:
            passed.append(point.code)
        detail_rows.append(entry)

    # -- the isolation pass ------------------------------------------------- #
    scored = [point for point in points if point.position is not None]
    isolation_score: float | None = None
    outlier_codes: list[str] = []
    scores: dict[str, float] = {}
    if scored:
        matrix = [[round(point.position, 6)] for point in scored]
        forest = IsolationForest(matrix)
        scores = {point.code: forest.score([round(point.position, 6)]) for point in scored}
        isolation_score = max(scores.values())
        for point in scored:
            score = scores[point.code]
            entry = next(row for row in detail_rows if row["parameter"] == point.code)
            entry["isolation_score"] = round(score, 4)
            # A value inside its own range that the forest still finds hard to
            # place is reported with its score. Whether it *holds* the batch is
            # decided below, on the rule set out at ``_EDGE_POSITION``.
            if score >= _STRONG_THRESHOLD and point.code not in abnormal:
                outlier_codes.append(point.code)

    # An isolated reading escalates only when the ranges cannot account for it:
    # it sits at the edge of its range, or there is more than one of them.
    escalating = [
        code
        for code in outlier_codes
        if abs(next(point.position for point in scored if point.code == code)) >= _EDGE_POSITION
    ]
    remarks = [code for code in outlier_codes if code not in escalating]
    escalate_profile = len(outlier_codes) >= 2 or bool(escalating)

    vulnerabilities: list[str] = []
    if abnormal:
        failing = [row for row in detail_rows if row["status"] == str(LabParameterStatus.FAIL)]
        for row in failing:
            source = f" (range source: {row['reference_source']})" if row["reference_source"] else ""
            vulnerabilities.append(
                f"{row['name']} is outside its configured range: measured {row['value']} "
                f"{row['unit']}, range {row['reference']}{source}."
            )
    if len(scored) > 1 and escalate_profile and outlier_codes:
        names = ", ".join(
            row["name"] for row in detail_rows if row["parameter"] in outlier_codes
        )
        vulnerabilities.append(
            f"The measurement profile is unusual as a whole — {names} "
            f"{'is' if len(outlier_codes) == 1 else 'are'} isolated from the rest of the "
            "values recorded on this test (isolation score "
            f"{round(max(scores[code] for code in outlier_codes), 3):.3f})."
        )

    # -- the decision ------------------------------------------------------- #
    required_missing = [
        point.code for point in points if point.is_required and not point.configured
    ]
    required_failed = [
        point.code for point in points if point.is_required and point.code in abnormal
    ]

    if required_failed:
        overall_status = "FAIL"
        risk_level = "HIGH"
        recommendation = (
            "Hold this batch for review. A required parameter is outside its configured "
            "range, so the honey cannot be released to packaging."
        )
    elif abnormal:
        overall_status = "HOLD"
        risk_level = "HIGH"
        recommendation = "Hold batch for review: measurements fall outside their configured ranges."
    elif vulnerabilities:
        overall_status = "HOLD"
        risk_level = "MODERATE" if isolation_score and isolation_score < _STRONG_THRESHOLD else "HIGH"
        recommendation = (
            "Hold the batch for a person to review the flagged measurements, or record the "
            "decision and continue if the risk is acceptable."
        )
    elif inconclusive or required_missing:
        overall_status = "INCONCLUSIVE"
        risk_level = "UNKNOWN"
        recommendation = (
            "Record the outstanding measurements, or configure the reference ranges the "
            "laboratory uses. Nothing has been proven either way while these are missing."
        )
    else:
        overall_status = "PASS"
        risk_level = "LOW"
        recommendation = "Eligible for packaging."

    explanation_parts = [
        f"{len(passed)} of {len(points)} measurement(s) are inside their configured range"
        + (f", {len(abnormal)} outside it" if abnormal else "")
        + (f", and {len(inconclusive)} cannot be judged" if inconclusive else "")
        + ".",
    ]
    if isolation_score is not None:
        explanation_parts.append(
            f"The isolation forest scored the profile {isolation_score:.3f} "
            f"(threshold {_ANOMALY_THRESHOLD}); it reported "
            f"{len(outlier_codes)} isolated measurement(s) beyond what the ranges caught."
        )
    if remarks:
        names = ", ".join(row["name"] for row in detail_rows if row["parameter"] in remarks)
        explanation_parts.append(
            f"Recorded as a remark rather than a hold: {names} "
            f"{'is' if len(remarks) == 1 else 'are'} isolated from the rest of the profile but "
            "sits well inside the configured range, and a single such reading is what the "
            "isolation pass expects to see on a small profile."
        )
    if inconclusive:
        names = ", ".join(row["name"] for row in detail_rows if row["parameter"] in inconclusive)
        explanation_parts.append(
            f"No reference range is configured for {names}, so those readings are recorded "
            "and reported without being judged."
        )
    if required_failed:
        names = ", ".join(row["name"] for row in detail_rows if row["parameter"] in required_failed)
        explanation_parts.append(f"A required parameter failed: {names}.")
    explanation_parts.append(CLASSIFIER_NOTE)

    measurement_sources: dict[str, int] = {}
    for point in points:
        measurement_sources[point.measurement_source] = (
            measurement_sources.get(point.measurement_source, 0) + 1
        )

    limitations = [
        "Development decision-support: the ranges compared against are configured values, "
        "not a validated standard, and the model has no validated training dataset.",
    ]
    if measurement_sources.get("DEMO"):
        limitations.append(
            f"{measurement_sources['DEMO']} of {len(points)} measurement(s) are development "
            "values supplied by the platform, not readings taken by an instrument."
        )
    if not scored:
        limitations.append(
            "No parameter has a configured range, so the isolation check could not run."
        )

    return LabQualityAnalysis(
        overall_status=overall_status,
        risk_level=risk_level,
        vulnerabilities=vulnerabilities,
        abnormal_parameters=abnormal,
        passed_parameters=passed,
        inconclusive_parameters=inconclusive,
        explanation=" ".join(part for part in explanation_parts if part),
        recommendation=recommendation,
        isolation_score=isolation_score,
        isolation_remarks=remarks,
        per_parameter=detail_rows,
        measurement_sources=measurement_sources,
        limitations=limitations,
    )


def risk_override_available(analysis: LabQualityAnalysis | None, *, enabled: bool) -> bool:
    """Whether the development override may be offered for this analysis.

    It is offered when the flag is on *and* there is something to override: a
    flagged profile, a failure, or an inconclusive test. A clean pass needs no
    override, and the button must not appear for one.
    """
    if not enabled or analysis is None:
        return False
    if analysis.overall_status == "PASS":
        return False
    return analysis.overall_status in {"HOLD", "FAIL", "INCONCLUSIVE"} or analysis.has_vulnerabilities


__all__ = [
    "ANALYSIS_SOURCE",
    "MODEL_NAME",
    "MODEL_VERSION",
    "IsolationForest",
    "LabQualityAnalysis",
    "MeasurementPoint",
    "analyse_measurements",
    "risk_override_available",
]

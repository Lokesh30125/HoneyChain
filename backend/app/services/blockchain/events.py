"""What each traceability event says, and the key that makes it idempotent.

Two decisions live in this module, and both are deliberate.

**The payload is built by the backend, from records.** A caller says *what
happened* (a collection was completed, a shipment was dispatched) and hands over
the record it happened to. It cannot say what the ledger should read: the
``tx_type`` is chosen here, the fields are read from the database row here, and
the identifiers in the payload are the codes the rest of the platform prints
(``HC-BATCH-2026-000001``, ``HC-PKG-2026-000012``) rather than internal UUIDs —
so an auditor reading the chain, and a customer reading a traceability page, are
looking at the same names HoneyChain shows everywhere else.

**Only traceability goes on the chain.** No passwords, tokens, notes, laboratory
documents, raw telemetry or AI prompts appear in these payloads; the module is
the only place payloads are constructed, which is what makes that claim
checkable by reading one file. What is here is the shape of the supply chain: the
event, the records it concerns, the quantities that moved, and who recorded it.

The event id is derived from the record, never random — ``BATCH-<code>-CREATED``,
``DIST-<code>-DISPATCHED`` — so the same logical event always produces the same
key, and a retry, a double-click or a worker restart collides with the existing
row instead of writing a second transaction.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from app.models.enums import BlockchainEventType

#: How many laboratory parameters are summarised onto the ledger. The chain
#: carries the *result*; the full measurement set stays in HoneyChain's own
#: tables, where it is complete and queryable.
MAX_SUMMARY_PARAMETERS = 8


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _quantity(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(value))
    except Exception:  # pragma: no cover - a value that is not a number
        return None


def _label(value: Any) -> str | None:
    """A plain-English form of an enum value, for a payload a person reads."""
    if value is None:
        return None
    raw = getattr(value, "value", value)
    return str(raw)


def _actor_reference(user: Any) -> str | None:
    """How the acting account is named on the chain.

    The account's UUID, not its name or email: the ledger is a permissioned
    chain with a role model of its own, and it needs to *relate* an event to a
    person without carrying personal data about them. The name is one join away
    in HoneyChain for anyone entitled to it.
    """
    if user is None:
        return None
    identifier = getattr(user, "id", None)
    return str(identifier) if identifier is not None else None


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values so the chain does not fill with ``null`` fields."""
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


# --------------------------------------------------------------------------- #
# Identifiers that make each event unique
# --------------------------------------------------------------------------- #
def event_id(prefix: str, code: str | None, suffix: str) -> str:
    """``BATCH`` + ``HC-BATCH-2026-000001`` + ``CREATED`` → the idempotency key."""
    reference = (code or "UNKNOWN").strip().upper().replace(" ", "-")
    return f"{prefix.upper()}-{reference}-{suffix.upper().replace(' ', '-')}"


# --------------------------------------------------------------------------- #
# Collection and batch
# --------------------------------------------------------------------------- #
def collection_completed(
    collection: Any, *, batch: Any | None = None, source_hives: Iterable[Any] = ()
) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    beekeeper = getattr(collection, "beekeeper", None)
    cluster = getattr(collection, "cluster", None)
    return (
        event_id("COLLECTION", collection.collection_code, "COMPLETED"),
        BlockchainEventType.COLLECTION_COMPLETED,
        _clean(
            {
                "collection_id": collection.collection_code,
                "batch_id": getattr(batch, "batch_code", None),
                "cluster_id": getattr(cluster, "cluster_code", None),
                "beekeeper_id": getattr(beekeeper, "beekeeper_code", None),
                "hive_ids": [getattr(hive, "hive_code", None) for hive in source_hives],
                "quantity": _quantity(collection.total_quantity),
                "unit": _label(collection.unit),
                "collection_date": _text(collection.collection_date),
                "status": _label(collection.status),
            }
        ),
    )


def batch_created(batch: Any, *, collection: Any | None = None, source_hives: Iterable[Any] = ()) -> tuple[
    str, BlockchainEventType, dict[str, Any]
]:
    beekeeper = getattr(batch, "beekeeper", None)
    cluster = getattr(batch, "cluster", None)
    profile = getattr(beekeeper, "profile", None)
    location_parts = [
        part
        for part in (
            getattr(profile, "village", None) or getattr(cluster, "cluster_name", None),
            getattr(profile, "district", None) or getattr(cluster, "district", None),
            getattr(profile, "state", None) or getattr(cluster, "state", None),
        )
        if part
    ]
    return (
        event_id("BATCH", batch.batch_code, "CREATED"),
        BlockchainEventType.BATCH_CREATED,
        _clean(
            {
                "batch_id": batch.batch_code,
                "cluster_id": getattr(cluster, "cluster_code", None),
                "beekeeper_id": getattr(beekeeper, "beekeeper_code", None),
                "collection_id": getattr(collection, "collection_code", None),
                "source_hives": [getattr(hive, "hive_code", None) for hive in source_hives],
                "quantity": _quantity(batch.quantity),
                "unit": _label(batch.unit),
                "collection_date": _text(batch.collection_date),
                "location": ", ".join(location_parts) or None,
            }
        ),
    )


# --------------------------------------------------------------------------- #
# Processing
# --------------------------------------------------------------------------- #
def processing_started(run: Any, *, actor: Any = None) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    batch = getattr(run, "batch", None)
    unit = getattr(run, "unit", None)
    return (
        event_id("PROC", run.processing_code, "STARTED"),
        BlockchainEventType.PROCESSING_STARTED,
        _clean(
            {
                "processing_id": run.processing_code,
                "batch_id": getattr(batch, "batch_code", None),
                "processor_id": _actor_reference(getattr(run, "processor", None) or actor),
                "processing_unit": getattr(unit, "name", None),
                "processing_type": _processing_type(run),
                "input_quantity": _quantity(run.input_quantity),
                "unit": _label(run.unit),
                "status": _label(run.status),
            }
        ),
    )


def processing_completed(run: Any, *, actor: Any = None) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    batch = getattr(run, "batch", None)
    unit = getattr(run, "unit", None)
    return (
        event_id("PROC", run.processing_code, "COMPLETED"),
        BlockchainEventType.PROCESSING_COMPLETED,
        _clean(
            {
                "processing_id": run.processing_code,
                "batch_id": getattr(batch, "batch_code", None),
                "processor_id": _actor_reference(getattr(run, "processor", None) or actor),
                "processing_unit": getattr(unit, "name", None),
                "processing_type": _processing_type(run),
                "input_quantity": _quantity(run.input_quantity),
                "output_quantity": _quantity(run.output_quantity),
                "loss_quantity": _quantity(run.loss_quantity),
                "unit": _label(run.unit),
                "completed_at": _text(run.completion_time),
                "status": _label(run.status),
            }
        ),
    )


def _processing_type(run: Any) -> str | None:
    value = _label(run.processing_type)
    if value == "OTHER":
        # The operator's own words for what they did, which is the only honest
        # answer when the list did not contain it.
        return getattr(run, "processing_type_other", None) or "Other"
    return value.replace("_", " ").title() if value else None


# --------------------------------------------------------------------------- #
# Laboratory
# --------------------------------------------------------------------------- #
def lab_test_started(test: Any, *, actor: Any = None) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    batch = getattr(test, "batch", None)
    laboratory = getattr(test, "laboratory", None)
    return (
        event_id("LAB", test.test_code, "STARTED"),
        BlockchainEventType.LAB_TEST_STARTED,
        _clean(
            {
                "lab_test_id": test.test_code,
                "sample_code": test.sample_code,
                "batch_id": getattr(batch, "batch_code", None),
                "laboratory": getattr(laboratory, "name", None),
                "technician_id": _actor_reference(getattr(test, "technician", None) or actor),
                "sample_quantity": _quantity(test.sample_quantity),
                "sample_unit": _label(test.sample_unit),
                "round_number": test.round_number,
                "status": _label(test.status),
            }
        ),
    )


def quality_decision(
    test: Any,
    *,
    results: Iterable[Any] = (),
    actor: Any = None,
    previous_result: str | None = None,
    is_override: bool = False,
) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    """The laboratory's verdict, as the three events the chain distinguishes.

    A pass, a failure and a hold are different facts with different consequences
    — one releases the batch to packaging, one rejects it, one stops it and asks
    for a person — so they are three event types rather than one with a status
    field. An override that changes a recorded verdict adds its own event
    (:func:`proceeded_with_risk` or, for a corrected result, a second decision
    event); it never rewrites the first one.
    """
    batch = getattr(test, "batch", None)
    result = _label(test.overall_result)
    if result == "PASS":
        tx_type, suffix = BlockchainEventType.QUALITY_CHECKED, "QUALITY-CHECKED"
    elif result == "FAIL":
        tx_type, suffix = BlockchainEventType.QUALITY_FAILED, "QUALITY-FAILED"
    else:
        # INCONCLUSIVE, or nothing decided: the sample was measured and the
        # measurement did not decide the batch's fate.
        tx_type, suffix = BlockchainEventType.QUALITY_HOLD, "QUALITY-HOLD"

    payload = _clean(
        {
            "lab_test_id": test.test_code,
            "sample_code": test.sample_code,
            "batch_id": getattr(batch, "batch_code", None),
            "tested_by": _actor_reference(getattr(test, "technician", None) or actor),
            "decided_by": _actor_reference(actor),
            "result": result,
            "status": _label(test.status) if not test.completed_at else "COMPLETED",
            "batch_status": _label(getattr(batch, "status", None)),
            "previous_result": previous_result,
            "is_override": is_override or None,
            "override_reason": getattr(test, "override_reason", None) if is_override else None,
            "hold_reason": getattr(test, "hold_reason", None) if tx_type is BlockchainEventType.QUALITY_HOLD else None,
            "measurement_summary": measurement_summary(results),
            "risk_level": _label(getattr(test, "ai_risk_level", None)),
            "completed_at": _text(test.completed_at),
        }
    )
    return event_id("LAB", test.test_code, suffix), tx_type, payload


def measurement_summary(results: Iterable[Any], *, limit: int = MAX_SUMMARY_PARAMETERS) -> dict[str, Any]:
    """A handful of measured values, keyed by parameter code.

    The chain gets the shape of the result — which parameter, what was measured
    against what — and HoneyChain keeps every row, the methods, the instruments
    and the documents. Sending the full set would turn the ledger into a second
    laboratory database, which §32 of the specification forbids.
    """
    summary: dict[str, Any] = {}
    for row in list(results)[:limit]:
        entry = _clean(
            {
                "value": _quantity(row.value),
                "unit": _label(row.unit),
                "status": _label(row.status),
                "reference_min": _quantity(row.reference_min),
                "reference_max": _quantity(row.reference_max),
            }
        )
        if entry:
            summary[row.parameter_code] = entry
    return summary


def proceeded_with_risk(
    test: Any, *, actor: Any = None, reason: str | None = None
) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    batch = getattr(test, "batch", None)
    return (
        event_id("LAB", test.test_code, "PROCEEDED-WITH-RISK"),
        BlockchainEventType.PROCEEDED_WITH_RISK,
        _clean(
            {
                "lab_test_id": test.test_code,
                "batch_id": getattr(batch, "batch_code", None),
                "previous_result": _label(test.overall_result),
                "override_status": "APPROVED_WITH_RISK",
                "approved_by": _actor_reference(actor),
                "reason": reason or getattr(test, "risk_override", None) or getattr(test, "override_reason", None),
                "risk_level": _label(getattr(test, "ai_risk_level", None)),
                "status": _label(getattr(batch, "status", None)),
            }
        ),
    )


# --------------------------------------------------------------------------- #
# Packaging
# --------------------------------------------------------------------------- #
def packaging_started(run: Any, *, actor: Any = None) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    batch = getattr(run, "batch", None)
    unit = getattr(run, "packaging_unit", None)
    return (
        event_id("PKG", run.packaging_code, "STARTED"),
        BlockchainEventType.PACKAGING_STARTED,
        _clean(
            {
                "packaging_id": run.packaging_code,
                "batch_id": getattr(batch, "batch_code", None),
                "packaging_unit_id": getattr(unit, "unit_code", None),
                "packaging_unit": getattr(unit, "name", None),
                "packed_by": _actor_reference(actor),
                "package_size": _quantity(run.package_size),
                "planned_packages": run.number_of_packages,
                "input_quantity": _quantity(run.input_quantity),
                "unit": _label(run.unit),
                "status": _label(run.status),
            }
        ),
    )


def package_created(package: Any, *, run: Any = None, actor: Any = None) -> tuple[
    str, BlockchainEventType, dict[str, Any]
]:
    batch = getattr(package, "batch", None)
    packaging = run or getattr(package, "packaging", None)
    return (
        event_id("PACKAGE", package.package_code, "CREATED"),
        BlockchainEventType.PACKAGE_CREATED,
        _clean(
            {
                "package_id": package.package_code,
                "packaging_id": getattr(packaging, "packaging_code", None),
                "batch_id": getattr(batch, "batch_code", None),
                "sequence_number": package.sequence_number,
                "package_size": _quantity(package.package_size),
                "quantity": _quantity(package.quantity),
                "unit": _label(package.unit),
                "packaging_type": _label(package.packaging_type),
                "packaging_type_other": getattr(package, "packaging_type_other", None),
                "packaged_by": _actor_reference(actor),
                "status": _label(package.status),
            }
        ),
    )


def packaged(run: Any, *, actor: Any = None, package_codes: Iterable[str] = ()) -> tuple[
    str, BlockchainEventType, dict[str, Any]
]:
    batch = getattr(run, "batch", None)
    unit = getattr(run, "packaging_unit", None)
    return (
        event_id("PKG", run.packaging_code, "COMPLETED"),
        BlockchainEventType.PACKAGED,
        _clean(
            {
                "packaging_id": run.packaging_code,
                "batch_id": getattr(batch, "batch_code", None),
                "packaging_unit_id": getattr(unit, "unit_code", None),
                "packaging_unit": getattr(unit, "name", None),
                "packed_by": _actor_reference(actor),
                "package_count": run.number_of_packages,
                "package_size": _quantity(run.package_size),
                "total_packaged_quantity": _quantity(run.packaged_quantity),
                "unit": _label(run.unit),
                "package_ids": list(package_codes)[:50],
                "status": _label(run.status),
            }
        ),
    )


# --------------------------------------------------------------------------- #
# Distribution and retail
# --------------------------------------------------------------------------- #
def _shipment_payload(shipment: Any) -> dict[str, Any]:
    batch = getattr(shipment, "batch", None)
    package = getattr(shipment, "package", None)
    retailer = getattr(shipment, "retailer", None)
    return _clean(
        {
            "distribution_id": shipment.distribution_code,
            "batch_id": getattr(batch, "batch_code", None),
            "package_id": getattr(package, "package_code", None),
            "distributor_id": _actor_reference(getattr(shipment, "distributor", None)),
            "retailer_id": _actor_reference(retailer),
            "retailer_name": getattr(retailer, "name", None),
            "destination": shipment.destination,
            "destination_district": shipment.destination_district,
            "quantity": _quantity(shipment.quantity),
            "unit": _label(shipment.unit),
            "carrier": shipment.carrier,
            "tracking_reference": shipment.tracking_reference,
            "status": _label(shipment.status),
        }
    )


def distribution_created(shipment: Any, *, actor: Any = None) -> tuple[
    str, BlockchainEventType, dict[str, Any]
]:
    payload = _shipment_payload(shipment)
    payload["created_by"] = _actor_reference(actor)
    payload["expected_delivery_date"] = _text(shipment.expected_delivery_date)
    return (
        event_id("DIST", shipment.distribution_code, "CREATED"),
        BlockchainEventType.DISTRIBUTION_CREATED,
        _clean(payload),
    )


def distribution_dispatched(shipment: Any, *, actor: Any = None) -> tuple[
    str, BlockchainEventType, dict[str, Any]
]:
    payload = _shipment_payload(shipment)
    payload["dispatched_by"] = _actor_reference(actor)
    payload["dispatch_date"] = _text(shipment.dispatched_at or shipment.dispatch_date)
    return (
        event_id("DIST", shipment.distribution_code, "DISPATCHED"),
        BlockchainEventType.DISTRIBUTION_DISPATCHED,
        _clean(payload),
    )


def in_transit(shipment: Any, *, actor: Any = None) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    payload = _shipment_payload(shipment)
    payload["in_transit_at"] = _text(shipment.in_transit_at)
    payload["recorded_by"] = _actor_reference(actor)
    return (
        event_id("DIST", shipment.distribution_code, "IN-TRANSIT"),
        BlockchainEventType.IN_TRANSIT,
        _clean(payload),
    )


def delivered(shipment: Any, *, actor: Any = None) -> tuple[str, BlockchainEventType, dict[str, Any]]:
    payload = _shipment_payload(shipment)
    payload["delivered_at"] = _text(shipment.delivered_at)
    payload["recorded_by"] = _actor_reference(actor)
    return (
        event_id("DIST", shipment.distribution_code, "DELIVERED"),
        BlockchainEventType.DELIVERED,
        _clean(payload),
    )


def retailer_received(shipment: Any, *, actor: Any = None) -> tuple[
    str, BlockchainEventType, dict[str, Any]
]:
    payload = _shipment_payload(shipment)
    payload["status"] = "RECEIVED"
    payload["received_at"] = _text(shipment.received_at)
    payload["received_by"] = _actor_reference(getattr(shipment, "received_by", None) or actor)
    return (
        event_id("DIST", shipment.distribution_code, "RECEIVED"),
        BlockchainEventType.RETAILER_RECEIVED,
        _clean(payload),
    )


# --------------------------------------------------------------------------- #
# QR
# --------------------------------------------------------------------------- #
def qr_generated(package: Any, *, url: str, generated_at: datetime | None = None) -> tuple[
    str, BlockchainEventType, dict[str, Any]
]:
    batch = getattr(package, "batch", None)
    return (
        event_id("QR", package.package_code, "GENERATED"),
        BlockchainEventType.QR_GENERATED,
        _clean(
            {
                "package_id": package.package_code,
                "qr_id": f"QR-{package.package_code}",
                "batch_id": getattr(batch, "batch_code", None),
                "verification_url": url,
                "generated_at": _text(generated_at),
                "status": "ACTIVE",
            }
        ),
    )


def customer_qr_verified(package: Any, *, scans: int, verified_at: datetime) -> tuple[
    str, BlockchainEventType, dict[str, Any]
]:
    batch = getattr(package, "batch", None)
    return (
        event_id("QR", package.package_code, "VERIFIED"),
        BlockchainEventType.CUSTOMER_QR_VERIFIED,
        _clean(
            {
                "package_id": package.package_code,
                "qr_id": f"QR-{package.package_code}",
                "batch_id": getattr(batch, "batch_code", None),
                "verification_count": scans,
                "verification_event": "FIRST_VERIFICATION",
                "verified_at": _text(verified_at),
                "status": "VERIFIED",
            }
        ),
    )


def qr_identity(package: Any, base_url: str) -> str:
    """The string encoded in a package's QR.

    A link to the package's traceability page and nothing else. The code is the
    only identifier in it: no name, no address, no batch contents, no token that
    could be replayed — everything the page shows is resolved server-side from
    the package record, which is also what lets the page be improved later
    without reprinting a single label.
    """
    return f"{base_url.rstrip('/')}/{package.package_code}"


def new_verification_id() -> str:  # pragma: no cover - kept for symmetry/testing
    return str(uuid.uuid4())


__all__ = [
    "MAX_SUMMARY_PARAMETERS",
    "batch_created",
    "collection_completed",
    "customer_qr_verified",
    "delivered",
    "distribution_created",
    "distribution_dispatched",
    "event_id",
    "in_transit",
    "lab_test_started",
    "measurement_summary",
    "package_created",
    "packaged",
    "packaging_started",
    "proceeded_with_risk",
    "processing_completed",
    "processing_started",
    "qr_generated",
    "qr_identity",
    "quality_decision",
    "retailer_received",
]

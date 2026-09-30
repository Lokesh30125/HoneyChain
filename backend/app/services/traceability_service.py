"""The one place a batch's (or a package's) supply chain is gathered.

Every traceability screen — the batch's blockchain section, the KVIC and
beekeeper traceability pages, the distributor's shipment detail and the
customer's QR page — describes the same honey. Before this module each of them
queried the stage records for itself, which is how two screens came to disagree
about one batch. This service reads the records once, from the tables the
workflow modules own, and hands them to whichever read model needs them:

    cluster → batch → collection → beekeeper → source hives
            → processing runs → laboratory tests
            → packaging runs → packages → shipments → retailer receipt
            → blockchain events

Nothing here writes. Nothing here stores a copy. A stage is reported only when
the record that makes it true exists, and a package-scoped read narrows the
packaging, shipment and event rows to that package — a jar's page never shows a
batchmate's label, run or shipment.

Authorisation is the caller's job and is done before this service is reached
(``BatchService.get_batch`` for signed-in users; the public route allow-lists
what it prints). This module deliberately takes model instances, not ids, so it
cannot be used to reach a record the caller has not already been allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.blockchain import BlockchainEvent
from app.models.distribution import Distribution
from app.models.enums import PackageStatus
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollectionHive
from app.models.laboratory import LabTest
from app.models.packaging import HoneyPackage, PackagingRun
from app.models.processing import HoneyProcessing


@dataclass
class TraceRecords:
    """The real rows behind one batch's journey (optionally one package's)."""

    batch: HoneyBatch
    package: HoneyPackage | None = None
    collection: Any = None
    beekeeper: Any = None
    cluster: Any = None
    source_hives: list[HoneyCollectionHive] = field(default_factory=list)
    runs: list[HoneyProcessing] = field(default_factory=list)
    tests: list[LabTest] = field(default_factory=list)
    packaging_runs: list[PackagingRun] = field(default_factory=list)
    packages: list[HoneyPackage] = field(default_factory=list)
    shipments: list[Distribution] = field(default_factory=list)
    events: list[BlockchainEvent] = field(default_factory=list)

    @property
    def packaging(self) -> PackagingRun | None:
        """The packaging run that speaks for this view.

        For a package it is the run that made the package. For a batch it is the
        newest *completed* run — an open or cancelled run after it does not undo
        the packages an earlier run produced — and only when nothing completed,
        the newest run of any state.
        """
        if self.package is not None:
            return getattr(self.package, "packaging", None)
        completed = [run for run in self.packaging_runs if str(run.status) == "COMPLETED"]
        if completed:
            return completed[-1]
        return self.packaging_runs[-1] if self.packaging_runs else None


class TraceabilityService:
    """Reads the supply-chain records of one batch, or one package of it."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # Gathering
    # ------------------------------------------------------------------ #
    def for_batch(self, batch: HoneyBatch, *, package: HoneyPackage | None = None) -> TraceRecords:
        if package is not None and package.batch_id != batch.id:
            # A package is only ever read against the batch it was packed from.
            raise LookupError(
                f"Package {package.package_code} does not belong to batch {batch.batch_code}"
            )
        collection = getattr(batch, "collection", None)
        records = TraceRecords(
            batch=batch,
            package=package,
            collection=collection,
            beekeeper=getattr(batch, "beekeeper", None),
            cluster=getattr(batch, "cluster", None),
            source_hives=self._source_hives(collection),
            runs=self.processing_runs(batch),
            tests=self.lab_tests(batch),
            packaging_runs=self._packaging_runs(batch),
        )
        records.packages = [package] if package is not None else self._packages(batch)
        records.shipments = self._shipments([row.id for row in records.packages])
        records.events = (
            self.events_for_package(package) if package is not None else self.events_for_batch(batch)
        )
        return records

    def for_package(self, package: HoneyPackage) -> TraceRecords:
        return self.for_batch(package.batch, package=package)

    def processing_runs(self, batch: HoneyBatch) -> list[HoneyProcessing]:
        return list(
            self.session.execute(
                select(HoneyProcessing)
                .where(HoneyProcessing.batch_id == batch.id)
                .order_by(HoneyProcessing.created_at.asc(), HoneyProcessing.id.asc())
            ).scalars()
        )

    def lab_tests(self, batch: HoneyBatch) -> list[LabTest]:
        return list(
            self.session.execute(
                select(LabTest)
                .where(LabTest.batch_id == batch.id)
                .order_by(LabTest.created_at.asc(), LabTest.id.asc())
            ).scalars()
        )

    def shipments_for_package(self, package: HoneyPackage) -> list[Distribution]:
        return self._shipments([package.id])

    def events_for_batch(self, batch: HoneyBatch) -> list[BlockchainEvent]:
        return list(
            self.session.execute(
                select(BlockchainEvent)
                .where(BlockchainEvent.batch_id == batch.id)
                .order_by(BlockchainEvent.created_at.asc(), BlockchainEvent.id.asc())
            ).scalars()
        )

    def events_for_package(self, package: HoneyPackage) -> list[BlockchainEvent]:
        """A package's own events plus the batch's events about the batch itself.

        Batch-level rows (collection, processing, laboratory) are the same honey
        and belong on the jar's page. Rows about *another* package (its creation,
        its label, its shipments) do not, and neither do the rows of a packaging
        run that did not produce this package — so both the package and the
        packaging run are narrowed.
        """
        return list(
            self.session.execute(
                select(BlockchainEvent)
                .where(
                    BlockchainEvent.batch_id == package.batch_id,
                    or_(
                        BlockchainEvent.package_id.is_(None),
                        BlockchainEvent.package_id == package.id,
                    ),
                    or_(
                        BlockchainEvent.packaging_id.is_(None),
                        BlockchainEvent.packaging_id == package.packaging_id,
                    ),
                )
                .order_by(BlockchainEvent.created_at.asc(), BlockchainEvent.id.asc())
            ).scalars()
        )

    def _source_hives(self, collection: Any) -> list[HoneyCollectionHive]:
        if collection is None:
            return []
        return list(
            self.session.execute(
                select(HoneyCollectionHive)
                .where(HoneyCollectionHive.collection_id == collection.id)
                .order_by(HoneyCollectionHive.hive_code.asc())
            ).scalars()
        )

    def _packaging_runs(self, batch: HoneyBatch) -> list[PackagingRun]:
        return list(
            self.session.execute(
                select(PackagingRun)
                .where(PackagingRun.batch_id == batch.id)
                .order_by(PackagingRun.created_at.asc(), PackagingRun.id.asc())
            ).scalars()
        )

    def _packages(self, batch: HoneyBatch) -> list[HoneyPackage]:
        return list(
            self.session.execute(
                select(HoneyPackage)
                .where(HoneyPackage.batch_id == batch.id)
                .order_by(HoneyPackage.sequence_number.asc(), HoneyPackage.id.asc())
            ).scalars()
        )

    def _shipments(self, package_ids: list[Any]) -> list[Distribution]:
        if not package_ids:
            return []
        return list(
            self.session.execute(
                select(Distribution)
                .where(Distribution.package_id.in_(package_ids))
                .order_by(Distribution.created_at.asc(), Distribution.id.asc())
            ).scalars()
        )

    # ------------------------------------------------------------------ #
    # The signed-in read model: every stage's real record, side by side
    # ------------------------------------------------------------------ #
    def chain(self, records: TraceRecords) -> dict[str, Any]:
        """The whole chain for an authorised viewer, one section per stage.

        Each section is either the record(s) that exist or empty — an empty
        section *is* the answer "this stage has not happened", and the
        ``stages`` summary says the same thing in one line per stage.
        """
        batch = records.batch
        beekeeper = records.beekeeper
        cluster = records.cluster
        collection = records.collection
        live_shipments = [row for row in records.shipments if str(row.status) != "CANCELLED"]
        received = [row for row in live_shipments if row.received_at is not None]
        delivered = [row for row in live_shipments if str(row.status) == "DELIVERED"]
        packages = records.packages

        return {
            "scope": "package" if records.package is not None else "batch",
            "cluster": (
                {
                    "id": str(cluster.id),
                    "cluster_code": cluster.cluster_code,
                    "cluster_name": cluster.cluster_name,
                    "district": cluster.district,
                    "state": cluster.state,
                }
                if cluster is not None
                else None
            ),
            "batch": {
                "id": str(batch.id),
                "batch_code": batch.batch_code,
                "status": _label(batch.status),
                "quantity": _number(batch.quantity),
                "unit": _label(batch.unit),
                "collection_date": _date(batch.collection_date),
                "created_at": _moment(batch.created_at),
            },
            "collection": (
                {
                    "id": str(collection.id),
                    "collection_code": collection.collection_code,
                    "status": _label(collection.status),
                    "collection_date": _date(getattr(collection, "collection_date", None)),
                    "total_quantity": _number(getattr(collection, "total_quantity", None)),
                    "unit": _label(getattr(collection, "unit", None)),
                    "completed_at": _moment(getattr(collection, "completed_at", None)),
                }
                if collection is not None
                else None
            ),
            "beekeeper": (
                {
                    "id": str(beekeeper.id),
                    "beekeeper_code": beekeeper.beekeeper_code,
                    "name": getattr(getattr(beekeeper, "user", None), "name", None),
                    "district": beekeeper.district,
                    "state": beekeeper.state,
                }
                if beekeeper is not None
                else None
            ),
            "hives": [
                {
                    "hive_id": str(row.hive_id),
                    "hive_code": row.hive_code,
                    "quantity": _number(row.quantity),
                    "status": _label(getattr(getattr(row, "hive", None), "status", None)),
                }
                for row in records.source_hives
            ],
            "processing": [
                {
                    "id": str(run.id),
                    "processing_code": run.processing_code,
                    "status": _label(run.status),
                    "facility": getattr(getattr(run, "unit_ref", None), "name", None),
                    "input_quantity": _number(run.input_quantity),
                    "output_quantity": _number(run.output_quantity),
                    "completed_at": _moment(getattr(run, "completion_time", None)),
                }
                for run in records.runs
            ],
            "laboratory": [
                {
                    "id": str(test.id),
                    "test_code": test.test_code,
                    "sample_code": test.sample_code,
                    "round": test.round_number,
                    "status": _label(test.status),
                    "result": _label(test.overall_result),
                    "completed_at": _moment(test.completed_at),
                }
                for test in records.tests
            ],
            "packaging": [
                {
                    "id": str(run.id),
                    "packaging_code": run.packaging_code,
                    "status": _label(run.status),
                    "facility": getattr(getattr(run, "unit_ref", None), "name", None),
                    "packaged_quantity": _number(run.packaged_quantity),
                    "number_of_packages": run.number_of_packages,
                    "completed_at": _moment(getattr(run, "completion_time", None)),
                }
                for run in records.packaging_runs
                if records.package is None or run.id == records.package.packaging_id
            ],
            "packages": [
                {
                    "id": str(row.id),
                    "package_code": row.package_code,
                    "packaging_id": str(row.packaging_id),
                    "status": _label(row.status),
                    "package_size": _number(row.package_size),
                    "quantity": _number(row.quantity),
                    "unit": _label(row.unit),
                    "qr_issued": bool(row.qr_payload),
                    "qr_generated_at": _moment(row.qr_generated_at),
                    "qr_scans": row.qr_scan_count or 0,
                    "trace_url": f"/trace/{row.package_code}",
                }
                for row in packages
            ],
            "distribution": [
                {
                    "id": str(row.id),
                    "distribution_code": row.distribution_code,
                    "package_code": getattr(row.package, "package_code", None),
                    "status": _label(row.status),
                    "destination": row.destination,
                    "carrier": row.carrier,
                    "quantity": _number(row.quantity),
                    "dispatched_at": _moment(row.dispatched_at),
                    "in_transit_at": _moment(row.in_transit_at),
                    "delivered_at": _moment(row.delivered_at),
                }
                for row in records.shipments
            ],
            "retailer": [
                {
                    "distribution_code": row.distribution_code,
                    "package_code": getattr(row.package, "package_code", None),
                    "retailer": _shop_name(row.retailer),
                    "received_at": _moment(row.received_at),
                    "received_by": getattr(row.received_by, "name", None),
                }
                for row in received
            ],
            "stages": self._stage_summary(records, live_shipments, delivered, received),
        }

    @staticmethod
    def _stage_summary(records, live_shipments, delivered, received) -> list[dict[str, Any]]:
        """One line per stage: reached or not, and the record that says so."""
        packages = [row for row in records.packages if row.status is not PackageStatus.CANCELLED]
        completed_runs = [run for run in records.runs if str(run.status) == "COMPLETED"]
        decided = [test for test in records.tests if _label(test.overall_result) in ("PASS", "FAIL")]
        completed_packaging = [
            run for run in records.packaging_runs if str(run.status) == "COMPLETED"
        ]
        if records.package is not None:
            completed_packaging = [
                run for run in completed_packaging if run.id == records.package.packaging_id
            ]
        labelled = [row for row in packages if row.qr_payload]
        verified = [row for row in packages if row.qr_last_scanned_at]
        dispatched = [row for row in live_shipments if row.dispatched_at is not None]
        collection = records.collection

        def line(stage, label, reached, detail=None):
            return {"stage": stage, "label": label, "reached": bool(reached), "detail": detail}

        def of(part, whole, noun):
            return f"{len(part)} of {len(whole)} {noun}" if whole else None

        latest_decision = decided[-1] if decided else None
        return [
            line(
                "COLLECTION",
                "Collection",
                collection is not None and str(collection.status) == "COMPLETED",
                getattr(collection, "collection_code", None),
            ),
            line("BATCH", "Honey batch", True, records.batch.batch_code),
            line(
                "PROCESSING",
                "Processing",
                bool(completed_runs),
                completed_runs[-1].processing_code if completed_runs else None,
            ),
            line(
                "LABORATORY",
                "Laboratory",
                latest_decision is not None,
                (
                    f"{latest_decision.test_code}: {_label(latest_decision.overall_result)}"
                    if latest_decision is not None
                    else None
                ),
            ),
            line(
                "PACKAGING",
                "Packaging",
                bool(completed_packaging),
                completed_packaging[-1].packaging_code if completed_packaging else None,
            ),
            line("PACKAGE", "Packages", bool(packages), of(packages, packages, "packages")),
            line("QR", "QR labels issued", bool(labelled), of(labelled, packages, "packages")),
            line(
                "DISTRIBUTION",
                "Dispatched",
                bool(dispatched),
                f"{len(dispatched)} shipment(s)" if dispatched else None,
            ),
            line(
                "DELIVERED",
                "Delivered",
                bool(delivered),
                f"{len(delivered)} shipment(s)" if delivered else None,
            ),
            line(
                "RETAILER",
                "Retailer received",
                bool(received),
                f"{len(received)} shipment(s)" if received else None,
            ),
            line(
                "CONSUMER",
                "Verified by a customer",
                bool(verified),
                of(verified, packages, "packages") if verified else None,
            ),
            line(
                "BLOCKCHAIN",
                "Blockchain events",
                bool(records.events),
                f"{len(records.events)} event(s)" if records.events else None,
            ),
        ]


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _shop_name(user: Any) -> str | None:
    """How a retailer is named outside the account: the shop, not the person."""
    if user is None:
        return None
    return getattr(user, "organization", None) or getattr(user, "name", None)


def _label(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _moment(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


__all__ = ["TraceRecords", "TraceabilityService"]

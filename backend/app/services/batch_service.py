"""Honey batch reads — and nothing else.

Phase 6 changed what a batch *reports* without giving the batch a writer. The
timeline is now assembled from the processing runs and laboratory tests that exist
against the batch, and the detail carries a processing summary and a laboratory
summary — each read from the run or the test that produced it. There is still no
``create``, ``update`` or ``set_status`` in this file: a batch moves because
processing or the laboratory moved it, through
:mod:`app.services.batch_lifecycle`.

A batch is created by completing a collection and by nothing else. There is no
``create`` here, no ``update`` and no ``set_status``: the absence *is* the
enforcement of requirement 13. A caller cannot post a batch, cannot rename one,
cannot move one to ``PACKAGED`` and cannot attach it to a different harvest,
because no code path exists to do any of those things.

What this service does is assemble the record: the batch, the collection it came
from, the hives that contributed (through the collection's contribution rows, not
a second copy) and the AI context beside the actual harvest. The scope rules are
delegated to :class:`~app.services.collection_service.CollectionService`, so a
beekeeper sees their own batches and a cluster officer sees the batches of the
beekeepers in the clusters they oversee — the same single rows, never a copy.
"""

from __future__ import annotations

import logging
from decimal import Decimal
import uuid
from datetime import date

from fastapi import status

from app.core.exceptions import AppError, NotFoundError
from app.models.enums import (
    BatchStage,
    BatchStatus,
    CollectionStatus,
    LabParameterStatus,
    LabResult,
    LabTestStatus,
    ProcessingStatus,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.user import User
from app.repositories.batch_repository import BatchRepository
from app.repositories.distribution_repository import DistributionRepository
from app.repositories.packaging_repository import (
    PackageRepository,
    PackagingRepository,
    approved_quantity_for_batch,
)
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.laboratory_repository import LabTestRepository
from app.repositories.hive_repository import HiveRepository
from app.schemas.batch import (
    BatchDetail,
    BatchDistributionRef,
    BatchPackagingRef,
    BatchHiveRef,
    BatchLabResultRef,
    BatchLabTestRef,
    BatchListItem,
    BatchProcessingRef,
    BatchSummary,
    BatchTraceStage,
)
from app.services import batch_lifecycle
from app.services.packaging_service import display_packaging_type
from app.services.names import person_name
from app.services.collection_service import CollectionService

logger = logging.getLogger(__name__)

#: Nothing is "reserved" any more: Phase 7 builds the packaging and distribution
#: stages, so every stop on the timeline is reported from rows that exist. The
#: constant stays as an empty tuple so a reader can see the question was asked —
#: and answered — rather than the code having forgotten it.
_LATER_STAGES: tuple[BatchStage, ...] = ()


def _enum_value(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


def _label(hive) -> str:
    """A hive's status, spelled out. Kept for hive rows specifically."""
    status = getattr(hive, "status", None)
    return getattr(status, "label", None) or _enum_value(status) or "Unknown"


def _enum_label(value) -> str:
    """The plain-language label of any enum value that carries one.

    Distinct from :func:`_label` above, which reads a *hive's* status: passing a
    unit or a processing status through that one silently yields "Unknown",
    which is how a timeline ends up saying "12.9 Unknown" about a measurement in
    kilograms. The fallback here is the value itself, never a placeholder.
    """
    if value is None:
        return "—"
    return getattr(value, "label", None) or _enum_value(value) or "—"


#: The order the stages happen in. Used to say "processing is complete" only
#: because the batch has moved past it — the lifecycle moves a batch precisely
#: when a stage finishes, so this is a reading of records, not an assumption.
_BATCH_STATUS_ORDER: dict[str, int] = {
    "COLLECTED": 0,
    "PROCESSING": 1,
    "LAB_TESTING": 2,
    "APPROVED": 3,
    "REJECTED": 3,
    "PACKAGED": 4,
    "DISTRIBUTION": 5,
    "COMPLETED": 6,
}


class BatchService:
    """Read-only view of the batches that completed collections produced."""

    def __init__(self, session) -> None:  # noqa: ANN001 - Session from the dependency
        self.session = session
        self.batches = BatchRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.hives = HiveRepository(session)
        # Scope and serialisation of the collection side live in one place, so a
        # batch is never described differently from the collection it came from.
        self.collections = CollectionService(session)
        # The downstream modules: a batch row reports how far its own packaging
        # runs and shipments have got, read from their tables rather than guessed
        # from the batch's status.
        # The laboratory's records, for the stage column: read, never guessed.
        self.lab_tests = LabTestRepository(session)
        self.packaging = PackagingRepository(session)
        self.packages = PackageRepository(session)
        self.distributions = DistributionRepository(session)

    # ------------------------------------------------------------------ #
    # Scope
    # ------------------------------------------------------------------ #
    def _scope_filters(self, user: User) -> dict:
        """Scope for a batch listing.

        A beekeeper and a cluster officer keep the Phase-5 scope exactly as it was.
        The operational roles — processor, laboratory technician — are not confined
        to an apiary: they act on whichever batch reaches their stage, so their read
        scope is the workflow. The rows are the same rows for everyone; only the
        filter changes.

        The officer's filter is by cluster, applied in the query, and it carries the
        batches that name no cluster as well — the same batches the beekeeper sees —
        because a batch vanishing from the officer's list is how a missing cluster
        relationship stays missing. It is shown as "No cluster assigned" and can be
        repaired from the record itself.
        """
        return self.collections.workflow_scope_filters(user, include_unclustered=True)

    def assert_can_read(self, user: User, batch: HoneyBatch) -> None:
        """Refuse a caller who may not read this batch, in the caller's own words.

        Public because placing a batch in a cluster is a *write* that must first
        ask the read question — an officer may not put honey they cannot see into
        a cluster they can. The rule itself is unchanged and lives below.
        """
        self._assert_can_read(user, batch)

    def _assert_can_read(self, user: User, batch: HoneyBatch) -> None:
        if user.role == UserRole.BEEKEEPER:
            owner = self.collections.own_beekeeper(user)
            if batch.beekeeper_id != owner.id:
                raise NotFoundError(f"Batch {batch.id} not found", details={"resource": "batch"})
            return
        if user.role in (UserRole.KVIC_OFFICER, UserRole.COLLECTION_CENTER):
            cluster_ids = self.collections.officer_cluster_ids(user)
            if batch.cluster_id is not None and batch.cluster_id not in cluster_ids:
                raise NotFoundError(
                    f"Batch {batch.id} not found",
                    details={"resource": "batch", "reason": "outside your clusters"},
                )
            return
        if user.role == UserRole.ADMIN or self.collections.is_workflow_role(user):
            return
        raise AppError("Not permitted", status_code=status.HTTP_403_FORBIDDEN, code="FORBIDDEN")

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def list_batches(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: BatchStatus | None = None,
        cluster_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        hive_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        unclustered: bool = False,
        not_cluster_id: uuid.UUID | None = None,
    ) -> tuple[list[BatchListItem], int]:
        scope = self._scope_filters(user)

        if beekeeper_id is not None and user.role == UserRole.ADMIN:
            scope["beekeeper_id"] = beekeeper_id
        if cluster_id is not None:
            if user.role in (UserRole.KVIC_OFFICER, UserRole.COLLECTION_CENTER):
                if cluster_id not in self.collections.officer_cluster_ids(user):
                    return [], 0
            scope["cluster_id"] = cluster_id

        rows, total = self.batches.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            hive_id=hive_id,
            date_from=date_from,
            date_to=date_to,
            unclustered=unclustered,
            not_cluster_id=not_cluster_id,
            **scope,
        )
        # One pass of aggregates for the page, then one item per row — so the
        # downstream columns cost three queries per page, not three per batch.
        metrics = self._downstream_metrics([row.id for row in rows])
        # Same idea for the laboratory: the newest test of every batch on the page,
        # so the laboratory column is read from the records (see _laboratory_state)
        # without a query per row.
        latest = self.lab_tests.latest_by_batch([row.id for row in rows])
        return [
            self.to_list_item(row, metrics.get(row.id), latest.get(row.id)) for row in rows
        ], total

    def batches_for_cluster(self, cluster_id: uuid.UUID) -> list[BatchListItem]:
        """Every batch the cluster holds, as the same rows the batch tables show.

        Read straight from the cluster link (``honey_batches.cluster_id``) with no
        pagination: this feeds the cluster's own counters, which have to count all
        of its honey rather than the first page of it. The item shape is the one
        the batch lists use, so the counters and the table beneath them are
        arithmetically the same numbers.
        """
        rows = self.batches.for_cluster(cluster_id)
        metrics = self._downstream_metrics([row.id for row in rows])
        latest = self.lab_tests.latest_by_batch([row.id for row in rows])
        return [self.to_list_item(row, metrics.get(row.id), latest.get(row.id)) for row in rows]

    def get_batch(self, user: User, batch_id: uuid.UUID) -> BatchDetail:
        batch = self.batches.get_with_relations(batch_id)
        if batch is None:
            raise NotFoundError(f"Batch {batch_id} not found", details={"resource": "batch"})
        self._assert_can_read(user, batch)
        return self.to_detail(batch)

    def get_by_collection(self, user: User, collection_id: uuid.UUID) -> BatchDetail:
        """The batch a collection produced, reached through the collection.

        Useful exactly once per harvest, and 404 for an open or cancelled
        collection — a batch exists only after completion.
        """
        collection = self.collections.get_collection(user, collection_id)
        batch = self.batches.get_by_collection(collection.id)
        if batch is None:
            raise NotFoundError(
                f"Collection {collection.collection_code} has no batch",
                details={
                    "resource": "batch",
                    "collection_code": collection.collection_code,
                    "status": collection.status.value,
                },
            )
        return self.get_batch(user, batch.id)

    def source_hives(self, user: User, batch_id: uuid.UUID) -> list[BatchHiveRef]:
        """The hive records behind a batch, reached through its collection.

        Read from the hive registry rather than copied onto the batch, so a batch
        can never claim a hive that the registry does not have. The status shown is
        the hive's *current* status and the payload says so — a hive that has since
        been retired still traces here, because its honey is still in the batch.
        """
        detail = self.get_batch(user, batch_id)
        refs: list[BatchHiveRef] = []
        for source in detail.sources:
            hive = self.hives.get(source.hive_id)
            refs.append(
                BatchHiveRef(
                    hive_id=source.hive_id,
                    hive_code=source.hive_code,
                    status=_enum_value(getattr(hive, "status", None)) or "UNKNOWN",
                    status_label=_label(hive),
                    colony_strength=_enum_value(getattr(hive, "colony_strength", None)),
                    village=source.village if hive is None else hive.village,
                    district=source.district if hive is None else hive.district,
                    beekeeper_code=source.beekeeper_code,
                    note="Current registry state of the hive, not a harvest-time snapshot.",
                )
            )
        return refs

    def summary(self, user: User) -> BatchSummary:
        scope = self._scope_filters(user)
        counts = self.batches.count_by_status(**scope)
        totals = self.batches.totals(**scope)
        # Open harvests that have no batch yet — the worklist a beekeeper sees as
        # "complete this harvest to create its batch". Counted, not estimated.
        _rows, awaiting = self.collections.collections.search(
            page=1,
            page_size=1,
            has_batch=False,
            statuses=list(CollectionStatus.open_statuses()),
            **scope,
        )
        return BatchSummary(
            total=sum(counts.values()),
            by_status=counts,
            collected=counts.get(BatchStatus.COLLECTED.value, 0),
            batched_totals={unit: float(value) for unit, value in totals.items()},
            awaiting_collection_completion=awaiting,
        )

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #
    #: Plain-language labels for the downstream columns a cluster table shows. The
    #: values come from the stages' own records; these are only the words.
    _DOWNSTREAM_LABELS = {
        "NOT_STARTED": "Not started",
        "PENDING": "Pending",
        "IN_PROGRESS": "In progress",
        # The laboratory has not opened a test against the batch yet, so nobody has
        # taken a sample. Saying "awaiting a sample" would be a claim about work
        # that has not happened; saying what is true is enough.
        "AWAITING_TEST": "Awaiting a test",
        "INCONCLUSIVE": "Inconclusive",
        "COMPLETED": "Completed",
        "PARTIAL": "Partly packed",
        "APPROVED": "Approved",
        "REJECTED": "Rejected",
        "READY_FOR_DISPATCH": "Ready for dispatch",
        "DISPATCHED": "Dispatched",
        "IN_TRANSIT": "In transit",
        "DELIVERED": "Delivered",
        "CANCELLED": "Cancelled",
    }

    def _downstream_metrics(self, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
        """How far each batch has travelled, from the stage records, in three queries.

        Deliberately batched: a page of twenty batches costs three grouped queries
        rather than sixty, and every value still comes from the table that owns it.
        """
        if not batch_ids:
            return {}
        packed = self.packaging.packaged_quantity_by_batch(batch_ids)
        packages = self.packages.counts_by_batch(batch_ids)
        shipments = self.distributions.summary_by_batch(batch_ids)
        return {
            batch_id: {
                "packaged_quantity": packed.get(batch_id, Decimal("0")),
                "package_count": packages.get(batch_id, 0),
                "shipment_count": (shipments.get(batch_id) or {}).get("shipments", 0),
                "delivered_count": (shipments.get(batch_id) or {}).get("delivered", 0),
                "latest_shipment_status": (shipments.get(batch_id) or {}).get("latest_status"),
            }
            for batch_id in batch_ids
        }

    @staticmethod
    def _laboratory_state(
        batch: HoneyBatch,
        latest_test,
        position: int,
        rank: dict[str, int],
    ) -> str:
        """Where the batch stands with the laboratory, read from the test records.

        The batch's own status is the spine, and a *decided* verdict writes it, so the
        two agree for APPROVED and REJECTED. What the status cannot express is the
        case the laboratory closed as INCONCLUSIVE: the batch deliberately stays at
        ``LAB_TESTING`` — it is not approved and not rejected, and the sample may be
        retested — so reading the stage from the status alone would report it as still
        awaiting work that has already been done.

        The test, when there is one, is therefore the better source, and the fallback
        is the status:

        * a test that is closed follows its own result;
        * a test that is open means the laboratory is working on it;
        * no test at all means nobody has taken a sample yet.
        """
        if latest_test is not None:
            if str(latest_test.status) == LabTestStatus.COMPLETED.value:
                result = str(latest_test.overall_result)
                if result == LabResult.PASS.value:
                    return "APPROVED"
                if result == LabResult.FAIL.value:
                    return "REJECTED"
                if result == LabResult.INCONCLUSIVE.value:
                    return "INCONCLUSIVE"
            else:
                return "IN_PROGRESS"

        if str(batch.status) in (
            BatchStatus.LAB_TESTING.value,
            BatchStatus.APPROVED.value,
            BatchStatus.REJECTED.value,
            BatchStatus.PACKAGED.value,
            BatchStatus.DISTRIBUTION.value,
            BatchStatus.COMPLETED.value,
        ):
            if str(batch.status) == BatchStatus.APPROVED.value:
                return "APPROVED"
            if str(batch.status) == BatchStatus.REJECTED.value:
                return "REJECTED"
            if position >= rank["LAB_TESTING"]:
                return "IN_PROGRESS"
            return "AWAITING_TEST"
        return "NOT_STARTED"

    def _downstream_statuses(
        self,
        batch: HoneyBatch,
        metrics: dict | None = None,
        latest_test=None,
    ) -> dict[str, str]:
        """The four stage statuses of one batch, read from where they really live.

        The batch's own status is the spine — the lifecycle only moves it when a
        stage actually happened — and the packaging figures refine it, because a
        batch can be packed in several runs and "partly packed" is not the same
        fact as "packed".
        """
        status = batch.status
        rank = _BATCH_STATUS_ORDER
        position = rank.get(str(status), 0)

        processing = "NOT_STARTED"
        if position >= rank["LAB_TESTING"]:
            processing = "COMPLETED"
        elif str(status) == BatchStatus.PROCESSING.value:
            processing = "IN_PROGRESS"
        elif str(status) == BatchStatus.COLLECTED.value:
            processing = "PENDING"

        laboratory = self._laboratory_state(batch, latest_test, position, rank)

        packaging_status = "NOT_STARTED"
        if position >= rank["PACKAGED"]:
            packaging_status = "COMPLETED"
        if metrics is not None:
            packed = Decimal(metrics.get("packaged_quantity") or 0)
            approved = approved_quantity_for_batch(self.session, batch.id)
            if packed > 0:
                packaging_status = "PARTIAL" if approved and packed < approved else "COMPLETED"

        distribution = "NOT_STARTED"
        if metrics is not None and metrics.get("shipment_count"):
            distribution = metrics.get("latest_shipment_status") or "READY_FOR_DISPATCH"
        elif str(status) == BatchStatus.DISTRIBUTION.value:
            distribution = "DISPATCHED"
        elif str(status) == BatchStatus.COMPLETED.value:
            distribution = "DELIVERED"

        values = {
            "processing_status": processing,
            "laboratory_status": laboratory,
            "packaging_status": packaging_status,
            "distribution_status": distribution,
        }
        labelled: dict[str, str] = {}
        for key, value in values.items():
            labelled[key] = value
            labelled[f"{key}_label"] = self._DOWNSTREAM_LABELS.get(
                value, value.replace("_", " ").title()
            )
        return labelled

    def to_list_item(
        self,
        batch: HoneyBatch,
        metrics: dict | None = None,
        latest_test=None,
    ) -> BatchListItem:
        collection = batch.collection
        sources = self.collections.sources_of(collection) if collection is not None else []
        beekeeper = getattr(batch, "__dict__", {}).get("beekeeper") or self.beekeepers.get(
            batch.beekeeper_id
        )
        return BatchListItem(
            id=batch.id,
            batch_code=batch.batch_code,
            status=batch.status,
            status_label=batch.status.label,
            current_stage=batch.current_stage,
            current_stage_label=batch.current_stage.label,
            collection_id=batch.collection_id,
            collection_code=getattr(collection, "collection_code", None) or "",
            collection_date=batch.collection_date,
            quantity=batch.quantity,
            unit=batch.unit,
            unit_label=batch.unit.label,
            source_hive_count=batch.source_hive_count or len(sources),
            source_hive_codes=[row.hive_code for row in sources],
            beekeeper_id=batch.beekeeper_id,
            beekeeper_code=getattr(beekeeper, "beekeeper_code", None),
            beekeeper_name=self.collections.user_name(getattr(beekeeper, "user", None)),
            cluster_id=batch.cluster_id,
            cluster_code=getattr(batch.cluster, "cluster_code", None),
            cluster_name=getattr(batch.cluster, "cluster_name", None),
            ai_predicted_yield_kg=batch.ai_predicted_yield_kg,
            ai_prediction_hive_count=batch.ai_prediction_hive_count or 0,
            packaged_quantity=(metrics or {}).get("packaged_quantity", Decimal("0")),
            package_count=(metrics or {}).get("package_count", 0),
            **self._downstream_statuses(batch, metrics, latest_test),
            created_at=batch.created_at,
        )

    def to_detail(self, batch: HoneyBatch) -> BatchDetail:
        base = self.to_list_item(batch, None, self._latest_test_of(batch))
        collection = batch.collection
        if collection is None:  # pragma: no cover - the foreign key makes this unreachable
            raise NotFoundError(
                f"The collection behind batch {batch.batch_code} was not found",
                details={"resource": "collection"},
            )
        processing_count, processing = self.processing_summary_for(batch)
        test_count, laboratory = self.laboratory_summary_for(batch)
        packaging_ref = self.packaging_summary_for(batch)
        distribution_ref = self.distribution_summary_for(batch)
        allowed_next = [
            str(status) for status in batch_lifecycle.allowed_transitions(batch.status)
        ]
        return BatchDetail(
            **base.model_dump(),
            collection=self.collections.collection_ref_for_batch(batch),
            sources=self.collections.source_hives_for_batch(batch),
            ai_context=self.collections.snapshot_for_batch(batch),
            timeline=self.timeline(batch),
            prediction_difference_kg=batch.prediction_difference_kg,
            processing_count=processing_count,
            processing=processing,
            test_count=test_count,
            laboratory=laboratory,
            allowed_next_statuses=allowed_next,
            updated_at=batch.updated_at,
            editable_fields=[],
            packaging=packaging_ref,
            distribution=distribution_ref,
            # The stages the batch can actually move to next. They are read from
            # the transition table, so this list and the enforcement can never
            # disagree.
            next_possible_stages=[
                batch_lifecycle.STATUS_LABEL[status]
                for status in batch_lifecycle.allowed_transitions(batch.status)
            ],
        )

    def packaging_summary_for(self, batch: HoneyBatch):
        """What packaging has recorded for this batch, counted rather than copied.

        ``approved_quantity`` is the measured output of the batch's completed
        processing run — the honey that exists and passed the laboratory. Nothing
        is converted and no figure is assumed: the numbers are the ones the
        processing and packaging records already store.
        """
        runs = sorted(
            list(getattr(batch, "packaging_records", []) or []),
            key=lambda row: (row.created_at, str(row.id)),
        )
        completed = [row for row in runs if str(row.status) == "COMPLETED"]
        open_run = next((row for row in runs if getattr(row.status, "is_open", False)), None)
        latest = completed[-1] if completed else None
        packages = [
            package
            for package in (getattr(batch, "packages", []) or [])
            if latest is not None and package.packaging_id == latest.id
        ]
        approved = Decimal("0")
        completed_runs = [
            run
            for run in (getattr(batch, "processing_records", []) or [])
            if str(run.status) == "COMPLETED" and run.output_quantity is not None
        ]
        if completed_runs:
            approved = completed_runs[-1].output_quantity
        packaged_total = sum(
            (run.packaged_quantity or Decimal("0") for run in completed), Decimal("0")
        )
        remaining = approved - packaged_total
        reference = latest or open_run
        # The unit of the work in hand: the run's own when there is one, otherwise
        # the batch's — honey is measured in the unit it was harvested in.
        run_unit = getattr(reference, "unit", None) or batch.unit
        return BatchPackagingRef(
            run_count=len(runs),
            completed_count=len(completed),
            open_run_id=getattr(open_run, "id", None),
            open_run_code=getattr(open_run, "packaging_code", None),
            latest_run_id=getattr(latest, "id", None),
            latest_run_code=getattr(latest, "packaging_code", None),
            latest_status=str(latest.status) if latest is not None else None,
            latest_status_label=(
                str(latest.status).replace("_", " ").title() if latest is not None else None
            ),
            packaging_type=str(latest.packaging_type) if latest is not None else None,
            packaging_type_label=(
                str(latest.packaging_type).replace("_", " ").title() if latest is not None else None
            ),
            packaging_type_other=getattr(latest, "packaging_type_other", None),
            packaging_type_display=(
                display_packaging_type(latest) if latest is not None else None
            ),
            packaging_date=getattr(latest, "packaging_date", None),
            packaged_quantity=getattr(latest, "packaged_quantity", None),
            package_count=len(packages) or (getattr(latest, "number_of_packages", 0) or 0),
            approved_quantity=approved,
            packaged_total=packaged_total,
            remaining_quantity=remaining if remaining > 0 else Decimal("0"),
            unit=run_unit,
            unit_label=_enum_label(run_unit),
            packaged_by_name=person_name(getattr(latest, "packaged_by", None)),
            packaging_unit_name=getattr(getattr(latest, "unit_ref", None), "name", None),
        )

    def distribution_summary_for(self, batch: HoneyBatch):
        """Where this batch's packages have got to, from the shipment records."""
        shipments = sorted(
            list(getattr(batch, "distributions", []) or []),
            key=lambda row: (row.created_at, str(row.id)),
        )
        live = [row for row in shipments if str(row.status) != "CANCELLED"]
        delivered = [row for row in live if str(row.status) == "DELIVERED"]
        open_rows = [row for row in live if str(row.status) != "DELIVERED"]
        latest = (live or shipments)[-1] if (live or shipments) else None
        quantity = sum((row.quantity for row in live), Decimal("0"))
        return BatchDistributionRef(
            shipment_count=len(shipments),
            delivered_count=len(delivered),
            open_count=len(open_rows),
            latest_id=getattr(latest, "id", None),
            latest_code=getattr(latest, "distribution_code", None),
            latest_status=str(latest.status) if latest is not None else None,
            latest_status_label=(
                str(latest.status).replace("_", " ").title() if latest is not None else None
            ),
            destination=getattr(latest, "destination", None),
            retailer_name=person_name(getattr(latest, "retailer", None)),
            carrier=getattr(latest, "carrier", None),
            dispatched_at=getattr(latest, "dispatched_at", None),
            delivered_at=getattr(latest, "delivered_at", None),
            received_by_name=person_name(getattr(latest, "received_by", None)),
            quantity_dispatched=quantity,
            unit=getattr(latest, "unit", None),
            unit_label=(str(getattr(latest, "unit")).title() if latest is not None else None),
        )

    def timeline(self, batch: HoneyBatch) -> list[BatchTraceStage]:
        """The traceability timeline, written from the records rather than from the status.

        Every stop is derived from rows that exist: the collection is complete
        because the batch exists at all; processing is complete because a completed
        run exists against the batch; the laboratory stage is current while the
        batch is ``LAB_TESTING`` and complete once a test has decided it — with the
        outcome shown as its own field, so a rejected batch never reads as a
        completed success. Packaging is reported from the packaging runs, the
        distribution stage from the shipments, and the closing stage from whether
        every package of the batch has actually been received.

        Nothing here is written down twice: the timeline is a *reading* of the
        batch's records, so a beekeeper watching their own honey, a KVIC officer
        watching their cluster and a packaging unit working the batch all see the
        same stops because they are reading the same rows.
        """
        runs = list(getattr(batch, "processing_records", []) or [])
        completed_runs = [run for run in runs if run.status is ProcessingStatus.COMPLETED]
        open_run = next(
            (
                run
                for run in runs
                if run.status in (ProcessingStatus.PENDING, ProcessingStatus.IN_PROGRESS)
            ),
            None,
        )
        latest_run = completed_runs[-1] if completed_runs else open_run

        tests = list(getattr(batch, "lab_tests", []) or [])
        decided_tests = [
            test
            for test in tests
            if test.overall_result in (LabResult.PASS, LabResult.FAIL)
        ]
        open_test = next(
            (
                test
                for test in tests
                if test.status in (LabTestStatus.PENDING, LabTestStatus.IN_PROGRESS)
            ),
            None,
        )
        ordered_tests = sorted(
            tests, key=lambda test: (int(test.round_number or 0), test.created_at, str(test.id))
        )
        decided_ordered = [
            test for test in ordered_tests if test.overall_result in (LabResult.PASS, LabResult.FAIL)
        ]
        # Which test speaks for the laboratory stage: the newest one that says
        # something. A decided round (PASS/FAIL) counts, an open test counts, and so
        # does a test the laboratory closed without deciding it — otherwise a batch
        # whose sample came back INCONCLUSIVE would be reported as though no test had
        # ever been opened against it, which is exactly the kind of not-quite-true
        # status this stage must not carry. Ties are broken the same way everywhere:
        # newest round, then newest record, then id.
        candidates = [test for test in (decided_ordered[-1] if decided_ordered else None,) if test]
        candidates += [
            test
            for test in reversed(ordered_tests)
            if test.status in (LabTestStatus.PENDING, LabTestStatus.IN_PROGRESS)
        ][:1]
        candidates += [
            test
            for test in reversed(ordered_tests)
            if test.status is LabTestStatus.COMPLETED
            and test.overall_result is LabResult.INCONCLUSIVE
        ][:1]
        # A test the laboratory has *held* speaks for the batch as well: it carries
        # the measurements, the analysis and the reason, and without it the quality
        # stage would read "not started" on a batch that has been measured, analysed
        # and deliberately stopped.
        candidates += [
            test for test in reversed(ordered_tests) if test.status is LabTestStatus.HOLD
        ][:1]
        latest_test = (
            max(
                candidates,
                key=lambda test: (int(test.round_number or 0), test.created_at, str(test.id)),
            )
            if candidates
            else None
        )

        collection_code = getattr(batch.collection, "collection_code", None)
        stages: list[BatchTraceStage] = []

        for stage in BatchStage.ordered():
            if stage is BatchStage.COLLECTION:
                stages.append(
                    BatchTraceStage(
                        stage=stage,
                        label=stage.label,
                        state="completed",
                        reached=True,
                        is_current=batch.status is BatchStatus.COLLECTED,
                        detail=(
                            f"Harvest {collection_code} recorded from "
                            f"{batch.source_hive_count} hive(s)"
                        ),
                        recorded_at=batch.collection_date,
                        module_available=True,
                    )
                )
                continue

            if stage is BatchStage.PROCESSING:
                stages.append(self._processing_stage(batch, completed_runs, latest_run))
                continue

            if stage is BatchStage.LABORATORY:
                stages.append(self._laboratory_stage(batch, decided_tests, latest_test))
                continue

            if stage is BatchStage.AI_QUALITY:
                stages.append(self._ai_quality_stage(batch, latest_test))
                continue

            # Packaging and distribution are reported from their own records, and
            # the closing stage follows from them: a batch is complete when every
            # package of it has been received.
            if stage is BatchStage.PACKAGING:
                stages.append(self._packaging_stage(batch))
                continue

            if stage is BatchStage.DISTRIBUTION:
                stages.append(self._distribution_stage(batch))
                continue

            if stage is BatchStage.RETAILER:
                stages.append(self._retailer_stage(batch))
                continue

            stages.append(self._completed_stage(batch))
        return stages

    def _packaging_stage(self, batch: HoneyBatch) -> BatchTraceStage:
        stage = BatchStage.PACKAGING
        runs = sorted(
            list(getattr(batch, "packaging_records", []) or []),
            key=lambda row: (row.created_at, str(row.id)),
        )
        completed = [row for row in runs if str(row.status) == "COMPLETED"]
        open_run = next((row for row in runs if getattr(row.status, "is_open", False)), None)
        latest = completed[-1] if completed else None

        if latest is None and batch.status.blocks_packaging:
            # Nothing has been packed and nothing may be: the batch has not been
            # released, and the reason is the status it is actually in.
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="blocked",
                reached=False,
                is_current=batch.status is BatchStatus.LAB_HOLD,
                detail=f"Blocked: the batch is {_enum_label(batch.status).lower()}.",
                recorded_at=None,
                module_available=True,
                note=(
                    "Packaging takes a batch only once the laboratory has released it."
                    + (
                        " A held batch is released by opening a further test."
                        if batch.status is BatchStatus.LAB_HOLD
                        else ""
                    )
                ),
            )

        if latest is None:
            if open_run is not None:
                return BatchTraceStage(
                    stage=stage,
                    label=stage.label,
                    state="current",
                    reached=True,
                    is_current=batch.status in (BatchStatus.APPROVED, BatchStatus.PACKAGING_READY),
                    detail=(
                        f"Packing {open_run.packaging_code} is "
                        f"{str(open_run.status).replace('_', ' ').lower()}"
                    ),
                    recorded_at=open_run.start_time or open_run.created_at,
                    module_available=True,
                )
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="not_started",
                reached=False,
                is_current=False,
                detail=(
                    "Waiting for the packaging unit to open a run"
                    if batch.status in (BatchStatus.APPROVED, BatchStatus.PACKAGING_READY)
                    else None
                ),
                recorded_at=None,
                module_available=True,
            )

        packages = [
            package
            for package in (getattr(batch, "packages", []) or [])
            if package.packaging_id == latest.id
        ]
        # The packages themselves belong on the timeline: the chain the platform
        # promises is batch → run → package, so the codes that came out of this run
        # are named here from their own rows. A long run is summarised rather than
        # truncated silently — the count is always the real count.
        codes = sorted(package.package_code for package in packages)
        shown = ", ".join(codes[:6])
        if len(codes) > 6:
            shown = f"{shown} and {len(codes) - 6} more"
        detail = (
            f"{latest.packaging_code}: {latest.number_of_packages or len(packages)} package(s) "
            f"of {latest.package_size} {getattr(latest.unit, 'value', latest.unit)}"
        )
        if shown:
            detail = f"{detail} — {shown}"
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state="current" if batch.status is BatchStatus.PACKAGED else "completed",
            reached=True,
            is_current=batch.status is BatchStatus.PACKAGED,
            detail=detail,
            recorded_at=latest.completion_time or latest.created_at,
            module_available=True,
        )

    def _distribution_stage(self, batch: HoneyBatch) -> BatchTraceStage:
        stage = BatchStage.DISTRIBUTION
        shipments = sorted(
            list(getattr(batch, "distributions", []) or []),
            key=lambda row: (row.created_at, str(row.id)),
        )
        live = [row for row in shipments if str(row.status) != "CANCELLED"]
        if not live:
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="current" if batch.status is BatchStatus.PACKAGED else "not_started",
                reached=batch.status in (BatchStatus.PACKAGED,),
                is_current=batch.status is BatchStatus.PACKAGED,
                detail=(
                    "Packages are ready; no shipment has been raised yet"
                    if batch.status is BatchStatus.PACKAGED
                    else None
                ),
                recorded_at=None,
                module_available=True,
            )

        delivered = [row for row in live if str(row.status) == "DELIVERED"]
        latest = (delivered or live)[-1]
        if len(delivered) == len(live):
            state, is_current = "completed", batch.status is BatchStatus.DISTRIBUTION
        else:
            state, is_current = "current", True
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state=state,
            reached=True,
            is_current=is_current,
            detail=(
                f"{len(delivered)}/{len(live)} shipment(s) delivered — "
                f"latest {latest.distribution_code} to "
                f"{person_name(latest.retailer) or latest.destination}"
            ),
            recorded_at=latest.delivered_at or latest.dispatched_at or latest.created_at,
            module_available=True,
        )

    def _retailer_stage(self, batch: HoneyBatch) -> BatchTraceStage:
        """The shop's own confirmation, read from the shipments it was addressed to.

        Distribution and receipt are separate facts and are shown separately: a
        consignment that has left the packer and not yet been accepted reads
        "awaiting receipt", and only the receiver's own confirmation — recorded
        against their account, with the time it happened — closes the stage. The
        shop is named from the shipment's retailer, the same account that appears in
        that shop's inbound list; there is no second copy of the delivery here.
        """
        stage = BatchStage.RETAILER
        shipments = sorted(
            (row for row in (getattr(batch, "distributions", []) or []) if str(row.status) != "CANCELLED"),
            key=lambda row: (row.created_at, str(row.id)),
        )
        addressed = [row for row in shipments if row.retailer_id is not None]
        if not addressed:
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="not_started",
                reached=False,
                is_current=False,
                detail=(
                    "Shipments exist but none names a retailer to receive it"
                    if shipments
                    else "No shipment has been addressed to a retailer yet"
                ),
                recorded_at=None,
                module_available=True,
                note=(
                    "A shipment names the shop it is for; naming it is what lets that "
                    "shop see the consignment and confirm the receipt."
                    if shipments
                    else None
                ),
            )

        received = [row for row in addressed if row.received_at is not None]
        latest = (received or addressed)[-1]
        shop = person_name(latest.retailer) or "the retailer"
        if len(received) == len(addressed):
            detail = (
                f"Received by {shop}"
                if len(addressed) == 1
                else f"All {len(addressed)} shipment(s) received — latest by {shop}"
            )
            state, is_current = "completed", batch.status is BatchStatus.COMPLETED
            recorded_at = latest.received_at
        else:
            delivered_not_received = [
                row for row in addressed if row.received_at is None and row.delivered_at is not None
            ]
            waiting_on = (delivered_not_received or [row for row in addressed if row.received_at is None])
            shop = person_name(getattr(waiting_on[-1], "retailer", None)) or shop
            detail = (
                f"Delivered, awaiting receipt by {shop}"
                if delivered_not_received
                else f"On its way to {shop} — awaiting receipt"
            )
            if len(addressed) > 1:
                detail = f"{len(received)}/{len(addressed)} received — {detail}"
            state, is_current = "current", True
            recorded_at = latest.delivered_at or latest.dispatched_at
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state=state,
            reached=bool(received),
            is_current=is_current,
            detail=detail,
            recorded_at=recorded_at,
            module_available=True,
        )

    def _completed_stage(self, batch: HoneyBatch) -> BatchTraceStage:
        """The end of the journey: every package packed, shipped and received."""
        stage = BatchStage.COMPLETED
        done = batch.status is BatchStatus.COMPLETED
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state="completed" if done else "not_started",
            reached=done,
            is_current=done,
            detail=(
                "Every package of this batch has been delivered and received"
                if done
                else None
            ),
            recorded_at=batch.updated_at if done else None,
            module_available=True,
        )

    def _processing_stage(self, batch, completed_runs, latest_run) -> BatchTraceStage:
        stage = BatchStage.PROCESSING
        if completed_runs:
            run = completed_runs[-1]
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="completed",
                reached=True,
                is_current=False,
                detail=(
                    f"Processing {run.processing_code}: {run.input_quantity} → "
                    f"{run.output_quantity} {_enum_label(run.unit)}"
                    + (
                        f" ({run.loss_quantity} {_enum_label(run.unit)} less than the input)"
                        if run.loss_quantity is not None
                        else ""
                    )
                ),
                recorded_at=run.completion_time or run.updated_at,
                module_available=True,
                note=(
                    None
                    if len(completed_runs) == 1
                    else f"{len(completed_runs)} completed runs recorded on this batch."
                ),
            )
        if latest_run is not None:
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="current",
                reached=True,
                is_current=True,
                detail=(
                    f"Run {latest_run.processing_code} is {_enum_label(latest_run.status)}"
                    + (
                        " — no quantities recorded yet."
                        if latest_run.input_quantity is None and latest_run.output_quantity is None
                        else ""
                    )
                ),
                recorded_at=latest_run.start_time or latest_run.created_at,
                module_available=True,
                note="The batch becomes ready for the laboratory when this run is completed.",
            )
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state="not_started",
            reached=False,
            is_current=False,
            detail=None,
            recorded_at=None,
            module_available=True,
            note="No processing has been recorded on this batch yet.",
        )

    def _ai_quality_stage(self, batch, latest_test) -> BatchTraceStage:
        """What the quality analysis concluded from the measurements.

        Read from the test's own stored analysis — the model, version and source
        travelled with it — so the timeline shows what was actually concluded
        rather than recomputing it against ranges that may have been reconfigured
        since. A batch whose test has not been analysed says exactly that.
        """
        stage = BatchStage.AI_QUALITY
        analysis = getattr(latest_test, "ai_analysis", None) if latest_test is not None else None
        if not analysis:
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="not_started",
                reached=False,
                is_current=False,
                detail=None,
                recorded_at=None,
                module_available=True,
                note=(
                    "No quality analysis has been run on this batch's measurements."
                    if latest_test is not None
                    else "The analysis runs once a laboratory test has measurements on it."
                ),
            )

        status = str(analysis.get("overall_status", ""))
        risk = str(analysis.get("risk_level", ""))
        vulnerabilities = list(analysis.get("vulnerabilities", []))
        model = getattr(latest_test, "ai_model", None) or analysis.get("model")
        version = getattr(latest_test, "ai_model_version", None) or analysis.get("model_version")
        reasoning = str(analysis.get("explanation", "") or "")

        if latest_test is not None and getattr(latest_test, "risk_override", None):
            override = latest_test.risk_override
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="completed",
                reached=True,
                is_current=False,
                outcome="PROCEEDED_WITH_RISK",
                detail=(
                    f"Analysis flagged {len(vulnerabilities)} risk(s) at risk level {risk}; "
                    f"{override.get('user_name') or 'a named user'} recorded a decision to continue: "
                    f"{override.get('reason', '')}"
                ),
                recorded_at=getattr(latest_test, "overridden_at", None)
                or getattr(latest_test, "ai_analysed_at", None),
                module_available=True,
                note="Recorded as PROCEEDED_WITH_RISK, with the risks shown to the user kept on the test.",
            )

        if status == "PASS":
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="completed",
                reached=True,
                is_current=False,
                outcome="PASSED",
                detail=(
                    f"Analysis passed: no vulnerability detected and no abnormal parameter "
                    f"(risk level {risk})."
                ),
                recorded_at=getattr(latest_test, "ai_analysed_at", None),
                module_available=True,
                note=f"{model} {version} — development decision-support over the configured values.",
            )

        if status == "FAIL":
            state, outcome = "completed", "FAILED"
        elif status == "HOLD":
            state, outcome = "blocked", "RISK_DETECTED"
        else:
            state, outcome = "blocked", status or "INCONCLUSIVE"

        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state=state,
            reached=True,
            is_current=batch.status in (BatchStatus.LAB_HOLD, BatchStatus.PROCEEDED_WITH_RISK),
            outcome=outcome,
            detail=(
                f"Analysis {status} (risk level {risk})"
                + (f" — {len(vulnerabilities)} vulnerabilit{'y' if len(vulnerabilities) == 1 else 'ies'}: "
                   + "; ".join(vulnerabilities[:2])
                   if vulnerabilities
                   else "")
            ),
            recorded_at=getattr(latest_test, "ai_analysed_at", None),
            module_available=True,
            note=reasoning or None,
        )

    def _laboratory_stage(self, batch, decided_tests, latest_test) -> BatchTraceStage:
        stage = BatchStage.LABORATORY

        # A hold is a real state of the laboratory stage, and the timeline says so
        # in the words the review uses: measured, closed without a decision, and
        # waiting on a person. It also says the packaging floor cannot take it.
        if batch.status is BatchStatus.LAB_HOLD or (
            latest_test is not None and str(latest_test.status) == LabTestStatus.HOLD.value
        ):
            test = latest_test
            reason = getattr(test, "hold_reason", None) if test is not None else None
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="blocked",
                reached=True,
                is_current=True,
                outcome="ON_HOLD",
                detail=(
                    "On hold: the laboratory closed its test without a decision"
                    + (f" — {test.test_code}" if test is not None else "")
                    + (f". Reason: {reason}" if reason else ".")
                ),
                recorded_at=getattr(test, "held_at", None),
                module_available=True,
                note="Packaging is blocked while the batch is held. A further test releases it.",
            )

        if batch.status in (
            BatchStatus.APPROVED,
            BatchStatus.PACKAGING_READY,
            BatchStatus.PACKAGED,
            BatchStatus.DISTRIBUTION,
            BatchStatus.COMPLETED,
        ) and decided_tests:
            test = decided_tests[-1]  # the latest decided round, as ordered by the caller
            decision = str(batch.status)
            overrode = getattr(test, "risk_override", None)
            if overrode:
                return BatchTraceStage(
                    stage=stage,
                    label=stage.label,
                    state="completed",
                    reached=True,
                    is_current=False,
                    outcome="PROCEEDED_WITH_RISK",
                    detail=(
                        f"Test {test.test_code} ({test.sample_code}): "
                        f"{test.overall_result} — released to packaging with a recorded risk by "
                        f"{overrode.get('user_name') or 'a named user'}: {overrode.get('reason', '')}"
                    ),
                    recorded_at=test.completed_at or test.updated_at,
                    module_available=True,
                    note=(
                        "The risks the analysis found, the analysis itself and the user who "
                        "accepted them are stored on the test and in the audit log."
                    ),
                )
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="completed",
                reached=True,
                is_current=False,
                outcome=decision,
                detail=(
                    f"Test {test.test_code} ({test.sample_code}): "
                    f"{test.overall_result}"
                    + (
                        f" — {test.result_summary}"
                        if test.result_summary
                        else ""
                    )
                    + (" [outcome set by hand]" if test.is_override else "")
                ),
                recorded_at=test.completed_at or test.updated_at,
                module_available=True,
                note=(
                    "A retest may be opened against this batch; the records of both "
                    "tests are kept."
                ),
            )
        if latest_test is not None and str(latest_test.status) == LabTestStatus.COMPLETED.value:
            # Closed, not decided: the sample was tested and nothing was
            # established. The batch deliberately stays at LAB_TESTING — it is not
            # approved and not rejected — so this stage is finished while the batch
            # waits for a retest, and it says so instead of claiming progress.
            test = latest_test
            result = str(test.overall_result)
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="completed",
                reached=True,
                is_current=True,
                outcome=result,
                detail=(
                    f"Test {test.test_code} ({test.sample_code}) closed as {_enum_label(result)}"
                    + (f" — {test.result_summary}" if test.result_summary else "")
                ),
                recorded_at=test.completed_at or test.updated_at,
                module_available=True,
                note=(
                    "This honey was not approved for packaging and was not rejected "
                    "either: the test established nothing either way. A retest may be "
                    "opened against the batch."
                ),
            )
        if latest_test is not None:
            test = latest_test
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="current",
                reached=True,
                is_current=True,
                detail=(
                    f"Test {test.test_code} ({test.sample_code}) is {_enum_label(test.status)}"
                    + (
                        f" — {len(list(getattr(test, 'results', []) or []))} parameter(s) recorded"
                        if getattr(test, "results", None)
                        else " — no measurements recorded yet"
                    )
                ),
                recorded_at=test.sample_collected_at or test.created_at,
                module_available=True,
                note=(
                    "The batch's outcome is decided when the test is completed."
                ),
            )
        # A batch can also sit at LAB_TESTING with no test opened yet.
        has_completed_run = any(
            run.status is ProcessingStatus.COMPLETED
            for run in list(getattr(batch, "processing_records", []) or [])
        )
        if has_completed_run:
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="current",
                reached=True,
                is_current=True,
                detail="Awaiting laboratory testing — no test opened yet.",
                recorded_at=None,
                module_available=True,
                note="A laboratory technician opens a test against the completed processing run.",
            )
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state="not_started",
            reached=False,
            is_current=False,
            detail=None,
            recorded_at=None,
            module_available=True,
            note="No laboratory test has been recorded on this batch yet.",
        )

    # ------------------------------------------------------------------ #
    # Phase-6 summaries on the batch detail
    # ------------------------------------------------------------------ #
    def processing_summary_for(self, batch: HoneyBatch) -> tuple[int, BatchProcessingRef | None]:
        """The latest run on the batch, read from the run itself."""
        runs = list(getattr(batch, "processing_records", []) or [])
        if not runs:
            return 0, None
        latest = sorted(runs, key=lambda run: (run.created_at, str(run.id)))[-1]
        unit = getattr(latest, "unit_ref", None)
        loss_percent = None
        if latest.input_quantity not in (None, 0) and latest.output_quantity is not None:
            loss_percent = round(
                float(latest.loss_quantity or 0) / float(latest.input_quantity) * 100, 2
            )
        return len(runs), BatchProcessingRef(
            id=latest.id,
            processing_code=latest.processing_code,
            status=str(latest.status),
            status_label=_enum_label(latest.status),
            processing_type=str(latest.processing_type),
            processing_type_label=_enum_label(latest.processing_type),
            input_quantity=latest.input_quantity,
            output_quantity=latest.output_quantity,
            loss_quantity=latest.loss_quantity,
            loss_percent=loss_percent,
            unit=str(latest.unit),
            unit_label=_enum_label(latest.unit),
            processing_date=latest.processing_date,
            start_time=latest.start_time,
            completion_time=latest.completion_time,
            operator_name=getattr(getattr(latest, "operator", None), "full_name", None),
            processing_unit_name=getattr(unit, "name", None),
            notes=latest.notes,
        )

    @staticmethod
    def _latest_test_of(batch: HoneyBatch):
        """The newest test of a batch whose tests are already loaded, or None."""
        tests = list(getattr(batch, "lab_tests", []) or [])
        if not tests:
            return None
        # The newest round, with the id as the last resort — a row cannot be
        # reported as "the latest test" on the strength of a tied timestamp.
        return sorted(
            tests, key=lambda test: (int(test.round_number or 0), test.created_at, str(test.id))
        )[-1]

    def laboratory_summary_for(self, batch: HoneyBatch) -> tuple[int, BatchLabTestRef | None]:
        """The latest test on the batch, with its recorded values — nothing summarised away."""
        tests = list(getattr(batch, "lab_tests", []) or [])
        if not tests:
            return 0, None
        latest = self._latest_test_of(batch)
        results = list(getattr(latest, "results", []) or [])
        return len(tests), BatchLabTestRef(
            id=latest.id,
            test_code=latest.test_code,
            sample_code=latest.sample_code,
            status=str(latest.status),
            status_label=_enum_label(latest.status),
            overall_result=str(latest.overall_result),
            overall_result_label=_enum_label(latest.overall_result),
            result_summary=latest.result_summary,
            is_override=bool(latest.is_override),
            round_number=int(latest.round_number or 1),
            test_date=latest.test_date,
            completed_at=latest.completed_at,
            laboratory_name=getattr(getattr(latest, "laboratory", None), "name", None),
            technician_name=person_name(getattr(latest, "technician", None)),
            sample_quantity=getattr(latest, "sample_quantity", None),
            sample_unit=_enum_value(getattr(latest, "sample_unit", None)),
            sample_unit_label=_enum_label(getattr(latest, "sample_unit", None)),
            parameter_count=len(results),
            passed_count=sum(1 for row in results if row.status is LabParameterStatus.PASS),
            failed_count=sum(1 for row in results if row.status is LabParameterStatus.FAIL),
            unevaluated_count=sum(
                1 for row in results if row.status is LabParameterStatus.NOT_EVALUATED
            ),
            ai_status=latest.ai_status,
            ai_risk_level=latest.ai_risk_level,
            ai_summary=latest.ai_analysis,
            hold_reason=latest.hold_reason,
            held_at=latest.held_at,
            held_by=getattr(getattr(latest, "held_by", None), "full_name", None),
            released_with_risk=bool(latest.risk_override),
            risk_override=latest.risk_override,
            results=[
                BatchLabResultRef(
                    parameter_code=row.parameter_code,
                    parameter_name=row.parameter_name,
                    value=row.value,
                    unit=str(row.unit),
                    unit_label=_enum_label(row.unit),
                    status=str(row.status),
                    status_label=_enum_label(row.status),
                    evaluated=row.status is not LabParameterStatus.NOT_EVALUATED,
                    reference_min=row.reference_min,
                    reference_max=row.reference_max,
                    reference_source=row.reference_source,
                )
                for row in results
            ],
        )


__all__ = ["BatchService"]

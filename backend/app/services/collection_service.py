"""Collection business logic.

This is where the Phase-5 promises are actually kept. Three of them are load
bearing, and all three are enforced here rather than in a route or a React
component:

1. **The server decides who and where.** ``beekeeper_id`` comes from the
   authenticated user's own beekeeper record, and ``cluster_id`` from that
   record's *current* cluster link — the Phase-4.1 relationship, read fresh on
   every write. No request body can influence either, and a hive the caller does
   not own is rejected before anything is written, so a beekeeper cannot record
   honey from somebody else's hive.

2. **The harvested quantity is a fact; the AI yield is an estimate.** They live
   in separate columns. When an analysis exists its predicted yield is
   *snapshotted alongside* the weighed harvest so a batch can later show the two
   side by side; when none exists the AI fields stay ``NULL`` and the UI says so.
   Nothing is derived from an estimate and no estimate is ever presented as
   harvested honey.

3. **Completion is one transaction that produces exactly one batch.** The status
   change, the batch row, the link and the audit entries commit together or not
   at all. Retrying a completion returns the batch that already exists instead of
   creating a second one, and the unique constraint on ``honey_batches.collection_id``
   makes a duplicate impossible even under concurrency.

Codes are reserved inside the caller's transaction
(``DocumentSequence.next_value`` performs an atomic upsert), so two beekeepers
completing a harvest at the same instant cannot be handed the same code.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import status
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AppError, ConflictError, NotFoundError, ValidationError
from app.models.beekeeper import Beekeeper
from app.models.document_sequence import DocumentSequence
from app.models.enums import (
    BatchStage,
    BatchStatus,
    CollectionStatus,
    HiveStatus,
    UserRole,
)
from app.models.hive import Hive
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection, HoneyCollectionHive
from app.models.sensor_reading import SensorReading
from app.models.user import User
from app.repositories.ai_repository import AiAnalysisRepository
from app.repositories.batch_repository import BatchRepository
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.cluster_repository import ClusterRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.profile_repository import UserProfileRepository
from app.repositories.sensor_reading_repository import SensorReadingRepository
from app.schemas.collection import (
    CollectionAiContext,
    CollectionDetail,
    CollectionIotContext,
    CollectionListItem,
    CollectionSourceHive,
    CollectionSummary,
    EligibleHive,
    EligibleHiveList,
)
from app.services.audit_service import AuditService
from app.services.blockchain import BlockchainService
from app.services.cluster_resolution import cluster_for

logger = logging.getLogger(__name__)

#: Roles whose work *is* the supply chain rather than an apiary. They see the
#: operational queue — the batches that have arrived at their desk — which is a
#: different question from "whose honey is this". The distinction matters: a
#: processor reading a batch is not being granted the beekeeper's records, they
#: are being shown the work item they must act on, and their write horizon is
#: still bounded by their own permissions.
#:
#: Phase 7 adds the two downstream desks to the same list. A packaging unit works
#: the approved batches that reach its bench and a distributor works the packages
#: that were released to it; neither is granted a beekeeper's apiary, and neither
#: may write anything upstream of its own stage. Everyone else — a beekeeper, an
#: officer, an administrator — keeps exactly the scope they had, which is what
#: makes "KVIC and the beekeeper see the same records, never copies" true.
WORKFLOW_ROLES: tuple[UserRole, ...] = (
    UserRole.PROCESSOR,
    UserRole.LAB_TECHNICIAN,
    UserRole.PACKAGING_UNIT,
    UserRole.DISTRIBUTOR,
)

#: Roles whose read of the harvest records is bounded by the district on their
#: profile — the officer who oversees the apiaries and the collection centre that
#: receives their honey. Neither may write a collection: that belongs to the
#: beekeeper who harvested it, so the scope here narrows a read and grants nothing.
DISTRICT_SCOPED_ROLES: tuple[UserRole, ...] = (
    UserRole.KVIC_OFFICER,
    UserRole.COLLECTION_CENTER,
)

#: Hives a harvest may draw on. ``REMOVED`` is retired history and a hive under
#: maintenance is not in service; neither is offered or accepted.
HARVESTABLE_HIVE_STATUSES = (HiveStatus.ACTIVE, HiveStatus.INACTIVE)

#: What an *open* collection may change. Completed history is not on this list.
_EDITABLE_FIELDS = frozenset({"hives", "collection_date", "total_quantity", "unit", "status", "notes"})

#: How far either side of the harvest date a reading may sit and still be shown
#: as IoT context.
IOT_CONTEXT_WINDOW = timedelta(days=2)

#: A code's year is part of the code, so the sequence is only unique *within* a
#: year — which is all a six-digit serial needs.
_SEQUENCE_YEAR = "%Y"


def build_collection_code(sequence: str, *, when: datetime | None = None) -> str:
    """``HC-COL-<YYYY>-<NNNNNN>``, e.g. ``HC-COL-2026-000001``.

    ``sequence`` is the zero-padded segment ``DocumentSequence`` returns, so the
    serial keeps its width on every code in the year — including the first one.
    """
    year = (when or datetime.now(tz=timezone.utc)).year
    return f"HC-COL-{year}-{sequence}"


def build_batch_code(sequence: str, *, when: datetime | None = None) -> str:
    """``HC-BATCH-<YYYY>-<NNNNNN>``, e.g. ``HC-BATCH-2026-000001``."""
    year = (when or datetime.now(tz=timezone.utc)).year
    return f"HC-BATCH-{year}-{sequence}"


#: The traceability timeline, in order. Only the first stop exists in this phase.
_STAGE_ORDER = (
    BatchStage.COLLECTION,
    BatchStage.PROCESSING,
    BatchStage.LABORATORY,
    BatchStage.PACKAGING,
    BatchStage.DISTRIBUTION,
    BatchStage.COMPLETED,
)

_STAGE_DETAIL = {
    BatchStage.PROCESSING: "Reserved for the processing module — not implemented in this phase.",
    BatchStage.LABORATORY: "Reserved for the laboratory module — not implemented in this phase.",
    BatchStage.PACKAGING: "Reserved for the packaging module — not implemented in this phase.",
    BatchStage.DISTRIBUTION: "Reserved for the distribution module — not implemented in this phase.",
    BatchStage.COMPLETED: "Reserved for the end of the supply chain — not implemented in this phase.",
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _as_float(value) -> float | None:
    return None if value is None else float(value)


def _enum_value(value) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


class CollectionService:
    """Create, read, correct, complete and cancel honey collections."""

    def __init__(self, session) -> None:  # noqa: ANN001 - Session from the dependency
        self.session = session
        self.collections = CollectionRepository(session)
        self.batches = BatchRepository(session)
        self.hives = HiveRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.clusters = ClusterRepository(session)
        self.profiles = UserProfileRepository(session)
        self.readings = SensorReadingRepository(session)
        self.analyses = AiAnalysisRepository(session)
        self.audit = AuditService(session)
        # Traceability events are recorded through this service, in the same
        # transaction as the record change (import at module level, below).
        self.blockchain = BlockchainService(session)

    # ------------------------------------------------------------------ #
    # Scope — every read and write starts here
    # ------------------------------------------------------------------ #
    def own_beekeeper(self, user: User) -> Beekeeper:
        """The authenticated beekeeper's own record.

        The cluster is read from *this* record on every call, which is what makes
        the Phase-4.1 relationship flow into Phase 5 by itself: move a beekeeper
        to another cluster and the next harvest is recorded in the new one, with
        no collection-side migration and no cached copy to invalidate.
        """
        record = self.beekeepers.get_by_user_id(user.id)
        if record is None:
            raise AppError(
                "No beekeeper profile is linked to this account",
                status_code=status.HTTP_409_CONFLICT,
                code="BEEKEEPER_PROFILE_REQUIRED",
            )
        return record

    def officer_cluster_ids(self, user: User) -> list[uuid.UUID]:
        """Clusters a staff reader's harvest read is bounded to.

        The rule is the cluster registry itself: exactly the clusters this reader
        can already open at ``GET /clusters``, which every KVIC officer and
        collection centre may read in full. It is deliberately **not** derived from
        the profile's district any more. Deriving it there meant an officer whose
        profile said "Guntur" could open a cluster in another district from the
        registry and then not see a single harvest, batch, test, run or shipment
        recorded under it — the records existed, the relationship existed, and the
        officer was told they belonged to nobody. The registry is the authority for
        who may read a cluster, so it is the authority for what hangs off one.

        Retired clusters are *included*: deactivating a cluster retires it from new
        work, it does not hide the honey that was recorded under it, and the history
        of a retired cluster still has to be readable by the officer responsible for
        it. Nothing here widens any other role — this answers for the district-scoped
        staff roles alone, and each keeps every other restriction it had.
        """
        from sqlalchemy import select

        from app.models.kvic_cluster import KvicCluster

        # Every id, not the first page of them: a registry past 1000 clusters must
        # not silently drop the later clusters out of an officer's scope.
        return list(self.session.execute(select(KvicCluster.id)).scalars())

    def is_workflow_role(self, user: User) -> bool:
        """True for the operational roles that work the shared supply chain."""
        return user.role in WORKFLOW_ROLES

    def workflow_scope_filters(self, user: User, *, include_unclustered: bool = False) -> dict:
        """Read scope for the processing and laboratory modules.

        A processor or a laboratory technician is not confined to a district:
        they act on whichever batch reaches their stage, so their read scope is
        the workflow itself. Every other role keeps exactly the scope it had —
        a beekeeper their own apiary, a cluster officer their clusters — which is
        what makes requirement "KVIC sees the same records, never copies" true by
        construction: one row, filtered per reader.
        """
        if self.is_workflow_role(user) or user.role == UserRole.ADMIN:
            return {}
        filters = self.scope_filters(user)
        if not include_unclustered:
            # The processing, laboratory and packaging listings filter by cluster id
            # alone; only the batch and harvest registers also carry the rows that
            # have no cluster yet, which is why the flag is opt-in rather than
            # unconditional.
            filters.pop("include_unclustered", None)
        return filters

    def assert_record_scope(
        self,
        user: User,
        *,
        record,
        resource: str,
        resource_id,
    ) -> None:
        """Ownership check for a single record read outside a listing.

        Returns silently for the roles whose scope is the workflow, and answers
        404 — not 403 — for a record outside a beekeeper's or officer's scope, so
        an unauthorised id is indistinguishable from an id that does not exist.
        """
        if self.is_workflow_role(user) or user.role == UserRole.ADMIN:
            return
        if user.role == UserRole.BEEKEEPER:
            owner = self.own_beekeeper(user)
            beekeeper_id = getattr(record, "beekeeper_id", None)
            if beekeeper_id is not None and beekeeper_id == owner.id:
                return
            raise NotFoundError(f"{resource} {resource_id} not found", details={"resource": resource})
        if user.role in DISTRICT_SCOPED_ROLES:
            cluster_ids = self.officer_cluster_ids(user)
            cluster_id = getattr(record, "cluster_id", None)
            if cluster_id is None:
                # A record that carries no cluster is readable by the officer who
                # can already see it in their list. Refusing it here is what made a
                # harvest the officer could open from one screen vanish from the
                # next; the missing relationship is a data-quality problem to
                # report and repair, not a reason to hide the record.
                return
            if cluster_id in cluster_ids:
                return
            raise NotFoundError(
                f"{resource} {resource_id} not found",
                details={"resource": resource, "reason": "outside your clusters"},
            )
        raise AppError("Not permitted", status_code=status.HTTP_403_FORBIDDEN, code="FORBIDDEN")

    def scope_filters(self, user: User) -> dict:
        """Repository filters bounding a listing to what the caller may see.

        An officer with no clusters in scope gets ``beekeeper_ids=[]`` — an empty
        list matches nothing, whereas ``None`` would mean "no filter at all".
        """
        if user.role == UserRole.BEEKEEPER:
            owner = self.own_beekeeper(user)
            return {"beekeeper_id": owner.id}
        if user.role in DISTRICT_SCOPED_ROLES:
            # Scoped by cluster, in the query, rather than by the beekeepers who
            # belong to one. Membership can lag a cluster relationship and a
            # beekeeper can have none at all, so a beekeeper-derived filter drops
            # records that are legitimately in scope — the harvest is not visible
            # because the *beekeeper* row was not linked, which is a different
            # problem from the harvest not being theirs.
            return {"cluster_ids": self.officer_cluster_ids(user), "include_unclustered": True}
        if user.role == UserRole.ADMIN:
            return {}
        raise AppError("Not permitted", status_code=status.HTTP_403_FORBIDDEN, code="FORBIDDEN")

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def list_collections(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: CollectionStatus | None = None,
        beekeeper_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
        hive_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        has_batch: bool | None = None,
    ) -> tuple[list[CollectionListItem], int]:
        scope = self.scope_filters(user)

        # Optional narrowing. Staff may narrow and never widen: an officer may
        # filter to one of *their* clusters, and anything else returns nothing.
        if beekeeper_id is not None and user.role == UserRole.ADMIN:
            scope["beekeeper_id"] = beekeeper_id
        if cluster_id is not None:
            if (
                user.role in DISTRICT_SCOPED_ROLES
                and cluster_id not in self.officer_cluster_ids(user)
            ):
                return [], 0
            scope["cluster_id"] = cluster_id

        rows, total = self.collections.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            hive_id=hive_id,
            date_from=date_from,
            date_to=date_to,
            has_batch=has_batch,
            **scope,
        )
        return [self.to_list_item(row) for row in rows], total

    def get_collection(self, user: User, collection_id: uuid.UUID) -> CollectionDetail:
        collection = self.collections.get_with_sources(collection_id)
        if collection is None:
            raise NotFoundError(
                f"Collection {collection_id} not found", details={"resource": "collection"}
            )
        self._assert_can_read(user, collection)

        detail = self.to_detail(collection)
        detail.ai_context = self.ai_context_for(collection)
        detail.iot_context = self.iot_context_for(collection)
        # The actions belong to the beekeeper who recorded the harvest, and only
        # while it is open. Staff read the same row and are offered nothing: a
        # button the API would refuse is a lie the UI should not tell.
        is_owner = self._is_owner(user, collection)
        open_for_editing = is_owner and collection.status.is_open
        detail.can_edit = open_for_editing
        detail.can_complete = open_for_editing
        detail.can_cancel = open_for_editing
        return detail

    def summary(self, user: User) -> CollectionSummary:
        scope = self.scope_filters(user)
        counts = self.collections.count_by_status(**scope)
        harvested = self.collections.totals(**scope)
        open_totals = self.collections.totals(
            statuses=list(CollectionStatus.open_statuses()), **scope
        )
        _, batch_count = self.batches.search(page=1, page_size=1, **self._batch_scope(scope))

        return CollectionSummary(
            total=sum(counts.values()),
            by_status=counts,
            planned=counts.get(CollectionStatus.PLANNED.value, 0),
            in_progress=counts.get(CollectionStatus.IN_PROGRESS.value, 0),
            completed=counts.get(CollectionStatus.COMPLETED.value, 0),
            cancelled=counts.get(CollectionStatus.CANCELLED.value, 0),
            batches_created=batch_count,
            harvested_totals={unit: float(value) for unit, value in harvested.items()},
            open_quantity={unit: float(value) for unit, value in open_totals.items()},
        )

    def eligible_hives(self, user: User, *, include_all_statuses: bool = False) -> EligibleHiveList:
        """Hives the caller can start a harvest on.

        Returns an empty list with a note rather than a suggestion or a stand-in
        hive when they own none — the empty state in the UI is a true statement
        about the apiary.
        """
        if user.role != UserRole.BEEKEEPER:
            # Staff do not record harvests, so they are not shown a form they
            # could not submit.
            return EligibleHiveList(
                hives=[],
                total=0,
                eligible_statuses=[s.value for s in HARVESTABLE_HIVE_STATUSES],
                note="Collections are recorded by the beekeeper who owns the hives.",
            )

        owner = self.own_beekeeper(user)
        rows, _ = self.hives.search(
            page=1,
            page_size=200,
            beekeeper_id=owner.id,
            include_removed=include_all_statuses,
            order_by="hive_code",
            descending=False,
        )
        if not include_all_statuses:
            rows = [row for row in rows if row.status in HARVESTABLE_HIVE_STATUSES]
        hive_ids = [row.id for row in rows]
        analyses = self.analyses.latest_per_hive(hive_ids) if hive_ids else {}

        items: list[EligibleHive] = []
        for hive in rows:
            analysis = analyses.get(hive.id)
            reading = self.readings.latest_for_hive(hive.id)
            latest_harvest = self.collections.latest_for_hive(hive.id)
            items.append(
                EligibleHive(
                    id=hive.id,
                    hive_code=hive.hive_code,
                    status=hive.status.value,
                    status_label=hive.status.label,
                    village=hive.village,
                    district=hive.district,
                    total_collections=self.collections.count_for_hive(hive.id),
                    last_collection_date=latest_harvest.collection_date if latest_harvest else None,
                    last_collection_code=latest_harvest.collection_code if latest_harvest else None,
                    ai_predicted_yield_kg=_as_float(getattr(analysis, "predicted_yield_kg", None)),
                    ai_analyzed_at=getattr(analysis, "analyzed_at", None),
                    ai_health_status=_enum_value(getattr(analysis, "health_status", None)),
                    ai_data_quality=_enum_value(getattr(analysis, "data_quality", None)),
                    latest_weight_kg=_as_float(getattr(reading, "weight", None)),
                    latest_reading_at=getattr(reading, "timestamp", None),
                )
            )

        return EligibleHiveList(
            hives=items,
            total=len(items),
            eligible_statuses=[s.value for s in HARVESTABLE_HIVE_STATUSES],
            note="No eligible hives available for collection." if not items else None,
        )

    def hive_history(self, user: User, hive_id: uuid.UUID) -> list[CollectionListItem]:
        """Harvest history of one hive — owner-scoped, like every hive read."""
        hive = self._load_own_hive(user, hive_id)
        rows, _ = self.collections.search(page=1, page_size=100, hive_id=hive.id)
        return [self.to_list_item(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def create(self, user: User, payload) -> tuple[CollectionDetail, bool]:
        """Record a harvest. Returns ``(detail, reused)``.

        ``reused=True`` means the payload's ``client_reference`` already named a
        stored collection, so the caller gets that harvest back instead of a
        duplicate being written — which is what makes a resubmitted form safe.
        """
        owner = self.own_beekeeper(user) if user.role == UserRole.BEEKEEPER else None
        if owner is None:
            raise AppError(
                "Only the beekeeper who harvested the honey can record a collection",
                status_code=status.HTTP_403_FORBIDDEN,
                code="FORBIDDEN",
            )

        if payload.client_reference:
            existing = self.collections.find_by_client_reference(
                owner.id, payload.client_reference
            )
            if existing is not None:
                logger.info(
                    "Collection create was a retry of an existing record",
                    extra={"collection_code": existing.collection_code},
                )
                return self.get_collection(user, existing.id), True

        hives = self._resolve_source_hives(owner, payload.hives)
        quantities = {hive.id: payload.per_hive_quantity(hive.id) for hive in hives}
        total = self._resolve_total(payload.total_quantity, hives, quantities)

        # Which cluster this harvest belongs to follows from the records: the
        # beekeeper's own relationship first, then the hives being harvested (staff
        # place hives in clusters, and a beekeeper record is not always updated
        # when they do). It is never a payload field and never a client-supplied id,
        # and when the answer is not derivable the collection simply has no cluster
        # — which the KVIC screens render as "not in a cluster" rather than
        # attaching the honey to somebody else's.
        resolved_cluster, _source = cluster_for(beekeeper=owner, hives=hives)
        collection = HoneyCollection(
            collection_code=self._next_collection_code(),
            client_reference=payload.client_reference,
            beekeeper_id=owner.id,
            cluster_id=resolved_cluster,
            collection_date=payload.collection_date,
            total_quantity=total,
            unit=payload.unit,
            status=payload.status,
            notes=payload.notes,
            ai_prediction_hive_count=0,
        )

        try:
            self.session.add(collection)
            self.session.flush()
            analysed = self._attach_sources(collection, hives, quantities)
            self.audit.collection_created(
                collection,
                actor=user,
                source_hive_codes=[hive.hive_code for hive in hives],
                ai_analysis_hives=analysed,
            )
            self.collections.commit()
        except IntegrityError as exc:  # pragma: no cover - code collision is vanishingly rare
            self.collections.rollback()
            logger.warning("Collection create conflicted", extra={"error": str(exc)})
            raise ConflictError(
                "The collection could not be saved because its code was already taken",
                details={
                    "collection_code": collection.collection_code,
                    "hint": "Retry the request.",
                },
            ) from exc

        logger.info(
            "Collection recorded",
            extra={
                "collection_code": collection.collection_code,
                "beekeeper_code": owner.beekeeper_code,
                "hives": len(hives),
                "quantity": str(collection.total_quantity),
                "unit": collection.unit.value,
                "cluster_code": getattr(collection.cluster, "cluster_code", None),
            },
        )
        return self.get_collection(user, collection.id), False

    def update(self, user: User, collection_id: uuid.UUID, payload) -> CollectionDetail:
        """Correct an open harvest. Completed and cancelled harvests are history."""
        collection = self._load_for_write(user, collection_id)
        if collection.status.is_terminal:
            raise ConflictError(
                f"A {collection.status.label.lower()} collection can no longer be changed",
                details={
                    "collection_code": collection.collection_code,
                    "status": collection.status.value,
                    "hint": "A completed harvest is kept exactly as it was recorded.",
                },
            )

        fields = payload.model_dump(exclude_unset=True)
        unknown = set(fields) - _EDITABLE_FIELDS
        if unknown:  # pragma: no cover - the schema already forbids extras
            raise ValidationError(f"These fields cannot be updated: {', '.join(sorted(unknown))}")

        changed: list[str] = []

        if "hives" in fields:
            owner = self.own_beekeeper(user)
            hives = self._resolve_source_hives(owner, payload.hives or [])
            quantities = {hive.id: payload.per_hive_quantity(hive.id) for hive in hives}
            total = self._resolve_total(
                payload.total_quantity if "total_quantity" in fields else None, hives, quantities
            )
            for source in list(collection.sources):
                self.session.delete(source)
            self.session.flush()
            collection.total_quantity = total
            analysed = self._attach_sources(collection, hives, quantities)
            # The AI snapshot belongs to the hives that now make up the harvest,
            # so it is refreshed from the same stored analyses the create used.
            changed.extend(["hives", "total_quantity"])
            if analysed != collection.ai_prediction_hive_count:
                changed.append("ai_context")

        if "collection_date" in fields:
            collection.collection_date = payload.collection_date
            changed.append("collection_date")
        if "unit" in fields:
            collection.unit = payload.unit
            changed.append("unit")
        if "total_quantity" in fields and "hives" not in fields:
            collection.total_quantity = Decimal(payload.total_quantity)
            changed.append("total_quantity")
        if "status" in fields:
            collection.status = payload.status
            changed.append("status")
        if "notes" in fields:
            collection.notes = payload.notes
            changed.append("notes")

        if not changed:
            return self.get_collection(user, collection.id)

        self.audit.collection_updated(collection, actor=user, fields=changed)
        self.collections.commit()
        logger.info(
            "Collection updated",
            extra={"collection_code": collection.collection_code, "fields": ",".join(changed)},
        )
        return self.get_collection(user, collection.id)

    def complete(
        self, user: User, collection_id: uuid.UUID, payload=None
    ) -> tuple[CollectionDetail, HoneyBatch, bool]:
        """Complete a harvest and create the batch it produces, in one transaction.

        Returns ``(detail, batch, created)``. ``created=False`` means the harvest
        was already complete and the batch it produced is being returned — the
        retry path, where nothing is inserted, audited or counted twice.
        """
        collection = self._load_for_write(user, collection_id)

        if collection.status == CollectionStatus.COMPLETED:
            batch = self.batches.get_by_collection(collection.id)
            if batch is None:  # pragma: no cover - the 1:1 constraint makes this impossible
                raise ConflictError(
                    "This collection is marked complete but has no batch",
                    details={"collection_code": collection.collection_code},
                )
            logger.info(
                "Collection completion was a retry",
                extra={
                    "collection_code": collection.collection_code,
                    "batch_code": batch.batch_code,
                },
            )
            return self.get_collection(user, collection.id), batch, False

        if collection.status == CollectionStatus.CANCELLED:
            raise ConflictError(
                "A cancelled collection cannot be completed",
                details={
                    "collection_code": collection.collection_code,
                    "status": collection.status.value,
                    "hint": "Record a new collection for honey that was harvested.",
                },
            )

        sources = self.collections.source_rows(collection.id)
        self._assert_completable(collection, sources)

        previous_status = collection.status
        if payload is not None and payload.notes:
            collection.notes = payload.notes

        batch = self._build_batch(collection, sources)
        try:
            collection.status = CollectionStatus.COMPLETED
            collection.completed_at = _now()
            self.session.add(batch)
            self.session.flush()
            self.audit.collection_completed(
                collection, actor=user, previous=previous_status, batch_code=batch.batch_code
            )
            self.audit.batch_created(
                batch,
                actor=user,
                collection_code=collection.collection_code,
                source_hive_codes=[row.hive_code for row in sources],
            )
            # Two traceability events, written into this same transaction: the
            # harvest that was completed and the batch it produced. Both are
            # facts that happened here, and both are recorded whether or not the
            # blockchain service is reachable — the outbox carries them from the
            # moment this commits.
            self.blockchain.collection_completed(
                collection, batch=batch, source_hives=sources, actor=user
            )
            self.blockchain.batch_created(
                batch, collection=collection, source_hives=sources, actor=user
            )
            # One commit for the status change, the batch, both audit rows and
            # both traceability events. If any part fails, no batch exists and
            # the collection is still open.
            self.collections.commit()
        except IntegrityError as exc:
            self.collections.rollback()
            # The realistic cause is a concurrent completion of the same harvest:
            # the unique constraint on collection_id has already made the second
            # batch impossible, so the winner's batch is returned instead.
            logger.warning(
                "Batch creation conflicted — returning the batch that exists",
                extra={"collection_code": collection.collection_code, "error": str(exc)},
            )
            self.session.expire_all()
            existing = self.batches.get_by_collection(collection_id)
            if existing is None:
                raise ConflictError(
                    "The batch for this collection could not be created",
                    details={
                        "collection_code": collection.collection_code,
                        "hint": "Retry the request.",
                    },
                ) from exc
            return self.get_collection(user, collection_id), existing, False

        logger.info(
            "Collection completed and batch created",
            extra={
                "collection_code": collection.collection_code,
                "batch_code": batch.batch_code,
                "hives": len(sources),
            },
        )
        return self.get_collection(user, collection.id), batch, True

    def cancel(self, user: User, collection_id: uuid.UUID, payload=None) -> CollectionDetail:
        collection = self._load_for_write(user, collection_id)
        if collection.status == CollectionStatus.CANCELLED:
            return self.get_collection(user, collection.id)
        if collection.status == CollectionStatus.COMPLETED:
            raise ConflictError(
                "A completed collection cannot be cancelled",
                details={
                    "collection_code": collection.collection_code,
                    "hint": "Its honey has already been recorded as a batch.",
                },
            )

        previous = collection.status
        collection.status = CollectionStatus.CANCELLED
        collection.cancelled_at = _now()
        if payload is not None and payload.reason:
            collection.cancellation_reason = payload.reason
        self.audit.collection_cancelled(
            collection, actor=user, previous=previous, reason=collection.cancellation_reason
        )
        self.collections.commit()
        logger.info(
            "Collection cancelled",
            extra={"collection_code": collection.collection_code, "previous_status": previous.value},
        )
        return self.get_collection(user, collection.id)

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #
    def to_list_item(self, collection: HoneyCollection) -> CollectionListItem:
        sources = self.sources_of(collection)
        beekeeper = self._beekeeper_of(collection)
        batch = self._batch_of(collection)
        return CollectionListItem(
            id=collection.id,
            collection_code=collection.collection_code,
            status=collection.status,
            status_label=collection.status.label,
            collection_date=collection.collection_date,
            total_quantity=collection.total_quantity,
            unit=collection.unit,
            unit_label=collection.unit.label,
            source_hive_count=len(sources),
            source_hive_codes=[row.hive_code for row in sources],
            beekeeper_id=collection.beekeeper_id,
            beekeeper_code=getattr(beekeeper, "beekeeper_code", None),
            beekeeper_name=self.user_name(getattr(beekeeper, "user", None)),
            cluster_id=collection.cluster_id,
            cluster_code=getattr(collection.cluster, "cluster_code", None),
            cluster_name=getattr(collection.cluster, "cluster_name", None),
            has_batch=batch is not None,
            batch_id=getattr(batch, "id", None),
            batch_code=getattr(batch, "batch_code", None),
            ai_predicted_yield_kg=collection.ai_predicted_yield_kg,
            notes=collection.notes,
            created_at=collection.created_at,
            completed_at=collection.completed_at,
        )

    def to_detail(self, collection: HoneyCollection) -> CollectionDetail:
        base = self.to_list_item(collection)
        sources = [
            CollectionSourceHive(
                hive_id=row.hive_id,
                hive_code=row.hive_code,
                quantity=row.quantity,
                unit=collection.unit.value,
                unit_label=collection.unit.label,
                hive_status=_enum_value(getattr(getattr(row, "hive", None), "status", None)),
                village=getattr(getattr(row, "hive", None), "village", None),
                district=getattr(getattr(row, "hive", None), "district", None),
                ai_predicted_yield_kg=row.ai_predicted_yield_kg,
                ai_analysis_id=row.ai_analysis_id,
                notes=row.notes,
            )
            for row in self.sources_of(collection)
        ]
        return CollectionDetail(
            **base.model_dump(),
            sources=sources,
            cancelled_at=collection.cancelled_at,
            cancellation_reason=collection.cancellation_reason,
            client_reference=collection.client_reference,
            updated_at=collection.updated_at,
        )

    def ai_context_for(self, collection: HoneyCollection) -> CollectionAiContext:
        """The AI estimate beside the weighed harvest — or an honest "none"."""
        predicted = collection.ai_predicted_yield_kg
        if predicted is None:
            return CollectionAiContext(
                prediction_hive_count=0,
                actual_quantity=collection.total_quantity,
                note=(
                    "No AI yield estimate existed for the source hives when this harvest was "
                    "recorded, so there is nothing to compare the harvested quantity against."
                ),
            )
        return CollectionAiContext(
            predicted_yield_kg=predicted,
            prediction_hive_count=collection.ai_prediction_hive_count,
            captured_at=collection.ai_prediction_captured_at,
            actual_quantity=collection.total_quantity,
            difference_kg=collection.total_quantity - predicted,
            note=(
                "Predicted yield is the AI estimate recorded at harvest time, shown beside the "
                "quantity actually harvested. A single harvest cannot establish model accuracy."
            ),
        )

    def _ai_context_for(self, collection: HoneyCollection) -> CollectionAiContext:
        return self.ai_context_for(collection)

    def iot_context_for(self, collection: HoneyCollection) -> CollectionIotContext:
        """Sensor readings from the source hives, labelled as context.

        A hive weight contains the box, the frames and the bees, and this platform
        has no validated hive-weight-to-honey conversion, so no honey figure is
        derived from it. It is shown as what it is, from a labelled source.
        """
        sources = self.sources_of(collection)
        if not sources:
            return CollectionIotContext(has_data=False)

        latest: SensorReading | None = None
        for row in sources:
            reading = self.readings.latest_for_hive(row.hive_id)
            if reading is None or reading.timestamp is None:
                continue
            if latest is None or reading.timestamp > latest.timestamp:
                latest = reading

        if latest is None:
            return CollectionIotContext(has_data=False)

        # The readings are columns, not a document: each value is read as stored,
        # and a sensor that reported nothing keeps its NULL rather than a zero.
        hive = self.hives.get(latest.hive_id)
        source = _enum_value(getattr(latest, "source", None))
        return CollectionIotContext(
            has_data=True,
            hive_code=getattr(hive, "hive_code", None),
            device_id=str(latest.device_id) if getattr(latest, "device_id", None) else None,
            recorded_at=latest.timestamp,
            source=source,
            source_label=(
                "Simulated device feed"
                if source == "SIMULATOR"
                else ("Device feed" if source else None)
            ),
            temperature=_as_float(latest.temperature),
            humidity=_as_float(latest.humidity),
            weight=_as_float(latest.weight),
            vibration=_as_float(latest.vibration),
            acoustic_level=_as_float(latest.acoustic_level),
            note=(
                "Recent sensor readings from the source hives, shown for context only. Hive "
                "weight includes the box, frames and bees, and no honey quantity is derived "
                "from it."
            ),
        )

    def _iot_context_for(self, collection: HoneyCollection) -> CollectionIotContext:
        return self.iot_context_for(collection)

    # ------------------------------------------------------------------ #
    # Internals — scope checks
    # ------------------------------------------------------------------ #
    def _assert_can_write(self, user: User, collection: HoneyCollection) -> Beekeeper:
        """Only the beekeeper who recorded a harvest may change it.

        A non-owner gets 404 rather than 403, following the hive registry:
        whether somebody else's collection exists is not the caller's business.
        """
        if user.role != UserRole.BEEKEEPER:
            raise AppError(
                "Only the beekeeper who recorded a harvest can change it",
                status_code=status.HTTP_403_FORBIDDEN,
                code="FORBIDDEN",
            )
        owner = self.own_beekeeper(user)
        if collection.beekeeper_id != owner.id:
            raise NotFoundError(
                f"Collection {collection.id} not found",
                details={"resource": "collection"},
            )
        return owner

    def _assert_can_read(self, user: User, collection: HoneyCollection) -> None:
        if user.role == UserRole.BEEKEEPER:
            owner = self.own_beekeeper(user)
            if collection.beekeeper_id != owner.id:
                raise NotFoundError(
                    f"Collection {collection.id} not found",
                    details={"resource": "collection"},
                )
            return
        if user.role == UserRole.KVIC_OFFICER:
            cluster_ids = self.officer_cluster_ids(user)
            if collection.cluster_id is not None and collection.cluster_id not in cluster_ids:
                raise NotFoundError(
                    f"Collection {collection.id} not found",
                    details={"resource": "collection", "reason": "outside your clusters"},
                )
            return
        if user.role == UserRole.ADMIN:
            return
        raise AppError("Not permitted", status_code=status.HTTP_403_FORBIDDEN, code="FORBIDDEN")

    def _is_owner(self, user: User, collection: HoneyCollection) -> bool:
        if user.role != UserRole.BEEKEEPER:
            return False
        record = self.beekeepers.get_by_user_id(user.id)
        return record is not None and record.id == collection.beekeeper_id

    def _load_for_write(self, user: User, collection_id: uuid.UUID) -> HoneyCollection:
        collection = self.collections.get_with_sources(collection_id)
        if collection is None:
            raise NotFoundError(
                f"Collection {collection_id} not found", details={"resource": "collection"}
            )
        self._assert_can_write(user, collection)
        return collection

    def _load_own_hive(self, user: User, hive_id: uuid.UUID) -> Hive:
        owner = self.own_beekeeper(user)
        hive = self.hives.get(hive_id)
        if hive is None or hive.beekeeper_id != owner.id:
            raise NotFoundError(f"Hive {hive_id} not found", details={"resource": "hive"})
        return hive

    def _batch_scope(self, scope: dict) -> dict:
        return {
            key: value
            for key, value in scope.items()
            if key in {"beekeeper_id", "beekeeper_ids", "cluster_id", "cluster_ids", "include_unclustered"}
        }

    # ------------------------------------------------------------------ #
    # Internals — writes
    # ------------------------------------------------------------------ #
    def _assert_completable(
        self, collection: HoneyCollection, sources: list[HoneyCollectionHive]
    ) -> None:
        """What has to be true before a harvest can become a batch."""
        if not sources:
            raise ValidationError(
                "A collection cannot be completed without at least one source hive",
                details={"collection_code": collection.collection_code},
            )
        if collection.total_quantity is None or collection.total_quantity <= 0:
            raise ValidationError(
                "A collection cannot be completed without a harvested quantity",
                details={"collection_code": collection.collection_code},
            )
        missing = [row.hive_code for row in sources if row.quantity is None or row.quantity <= 0]
        if missing:
            raise ValidationError(
                "Every source hive needs a quantity greater than zero before completion",
                details={"collection_code": collection.collection_code, "hive_codes": missing},
            )

    def _resolve_total(self, total_quantity, hives: list[Hive], quantities: dict) -> Decimal:
        """The harvested total, taken from the parts rather than trusted blindly.

        With per-hive quantities the sum *is* the total — that is what makes the
        hive contributions add up to the batch. A single-hive harvest may state
        only the total, which is then that hive's contribution.
        """
        if total_quantity is None:
            total = sum((qty for qty in quantities.values() if qty is not None), Decimal("0"))
            if total <= 0:
                raise ValidationError("A collection needs a quantity greater than zero")
            return total

        total = Decimal(total_quantity)
        if len(hives) == 1 and quantities[hives[0].id] is None:
            quantities[hives[0].id] = total
        return total

    def _resolve_source_hives(self, owner: Beekeeper, sources) -> list[Hive]:
        """Load the requested hives; refuse anything the caller does not own.

        Missing and foreign hives are reported the same way on purpose —
        confirming that another beekeeper's hive exists would itself leak
        information.
        """
        if not sources:
            raise ValidationError("A collection needs at least one source hive")

        ids = [row.hive_id for row in sources]
        if len(set(ids)) != len(ids):
            raise ValidationError("The same hive cannot contribute twice to one collection")

        found: dict[uuid.UUID, Hive] = {}
        for hive_id in ids:
            hive = self.hives.get(hive_id)
            if hive is not None:
                found[hive.id] = hive

        unavailable_ids = [str(hive_id) for hive_id in ids if hive_id not in found]
        foreign = [hive.hive_code for hive in found.values() if hive.beekeeper_id != owner.id]
        if unavailable_ids or foreign:
            raise NotFoundError(
                "Some source hives were not found",
                details={
                    "resource": "hive",
                    **({"hive_ids": unavailable_ids} if unavailable_ids else {}),
                    **({"hive_codes": foreign} if foreign else {}),
                },
            )

        not_harvestable = [
            hive.hive_code
            for hive in found.values()
            if hive.status not in HARVESTABLE_HIVE_STATUSES
        ]
        if not_harvestable:
            raise ValidationError(
                "Some source hives are not available for harvesting",
                details={
                    "hive_codes": not_harvestable,
                    "allowed_statuses": [s.value for s in HARVESTABLE_HIVE_STATUSES],
                },
            )

        return [found[hive_id] for hive_id in ids]

    def _attach_sources(
        self, collection: HoneyCollection, hives: list[Hive], quantities: dict
    ) -> int:
        """Write one contribution row per hive and snapshot the AI estimate.

        Returns how many hives had a stored estimate. The estimate is read once,
        at this moment: nothing is recomputed, nothing is inferred for a hive
        without an analysis.
        """
        snapshot = self._snapshot_ai_estimates(hives)
        predicted_total = Decimal("0")
        captured_at: datetime | None = None

        for hive in hives:
            estimate = snapshot.get(hive.id)
            self.collections.add_source(
                collection,
                hive=hive,
                quantity=quantities[hive.id] or Decimal("0"),
                ai_predicted_yield_kg=estimate[0] if estimate else None,
                ai_analysis_id=estimate[1] if estimate else None,
            )
            if estimate is not None:
                predicted_total += estimate[0]
                captured_at = max(captured_at, estimate[2]) if captured_at else estimate[2]

        analysed = len(snapshot)
        collection.ai_predicted_yield_kg = predicted_total if analysed else None
        collection.ai_prediction_hive_count = analysed
        collection.ai_prediction_captured_at = captured_at
        self.session.flush()
        return analysed

    def _build_batch(
        self, collection: HoneyCollection, sources: list[HoneyCollectionHive]
    ) -> HoneyBatch:
        """The batch a completed harvest produces, copied from the collection.

        Everything here is a snapshot: the collection is the source of truth for
        these figures, and the batch keeps them exactly as they were so a later
        stage always reads what was harvested rather than a current guess.
        """
        predicted = sum(
            (row.ai_predicted_yield_kg for row in sources if row.ai_predicted_yield_kg is not None),
            Decimal("0"),
        )
        analysed = sum(1 for row in sources if row.ai_predicted_yield_kg is not None)
        return HoneyBatch(
            batch_code=self._next_batch_code(),
            collection_id=collection.id,
            beekeeper_id=collection.beekeeper_id,
            cluster_id=collection.cluster_id,
            collection_date=collection.collection_date,
            quantity=collection.total_quantity,
            unit=collection.unit,
            status=BatchStatus.COLLECTED,
            current_stage=BatchStage.COLLECTION,
            source_hive_count=len(sources),
            ai_predicted_yield_kg=predicted if analysed else None,
            ai_prediction_hive_count=analysed,
            prediction_difference_kg=(collection.total_quantity - predicted) if analysed else None,
        )

    def _snapshot_ai_estimates(
        self, hives: list[Hive]
    ) -> dict[uuid.UUID, tuple[Decimal, uuid.UUID, datetime]]:
        analyses = self.analyses.latest_per_hive([hive.id for hive in hives])
        snapshot: dict[uuid.UUID, tuple[Decimal, uuid.UUID, datetime]] = {}
        for hive_id, analysis in analyses.items():
            predicted = getattr(analysis, "predicted_yield_kg", None)
            if predicted is None:
                continue
            snapshot[hive_id] = (
                Decimal(str(predicted)),
                analysis.id,
                getattr(analysis, "analyzed_at", None) or analysis.created_at,
            )
        return snapshot

    def _next_collection_code(self) -> str:
        scope = f"COLLECTION:{datetime.now(tz=timezone.utc).strftime(_SEQUENCE_YEAR)}"
        return build_collection_code(self._reserve(scope, width=6))

    def _next_batch_code(self) -> str:
        scope = f"BATCH:{datetime.now(tz=timezone.utc).strftime(_SEQUENCE_YEAR)}"
        return build_batch_code(self._reserve(scope, width=6))

    def _reserve(self, scope: str, *, width: int) -> str:
        """Reserve the next serial inside the caller's transaction.

        The value participates in that transaction, so a rolled-back create does
        not consume a number and a retried one simply reserves the next.
        """
        return DocumentSequence.next_value(self.session, scope, width=width)

    def batch_list_item(self, batch: HoneyBatch):
        """One batch in list shape — used by the collection → batch endpoint."""
        from app.services.batch_service import BatchService

        return BatchService(self.session).to_list_item(batch)

    # ------------------------------------------------------------------ #
    # Batch-facing reads — a batch describes the harvest it came from
    # ------------------------------------------------------------------ #
    def collection_ref_for_batch(self, batch: HoneyBatch):
        """The harvest behind a batch, in the batch's own vocabulary."""
        from app.schemas.batch import BatchCollectionRef

        collection = self._collection_of_batch(batch)
        return BatchCollectionRef(
            id=collection.id,
            collection_code=collection.collection_code,
            status=collection.status.value,
            collection_date=collection.collection_date,
            total_quantity=collection.total_quantity,
            unit=collection.unit,
            unit_label=collection.unit.label,
            completed_at=collection.completed_at,
            notes=collection.notes,
            source_hive_count=len(self.sources_of(collection)),
        )

    def source_hives_for_batch(self, batch: HoneyBatch):
        """Per-hive contributions, read from the harvest's own rows.

        The quantities are the ones recorded when the harvest was made. The hive
        details beside them (status, village, district) are read from the registry
        as it stands now, and the payload says so, so a hive that has since been
        retired still traces here.
        """
        from app.schemas.batch import BatchSourceHive

        collection = self._collection_of_batch(batch)
        rows = self.sources_of(collection)
        total = collection.total_quantity
        beekeeper = self._beekeeper_of(collection)
        sources = []
        for row in rows:
            hive = self.hives.get(row.hive_id)
            quantity = Decimal(row.quantity)
            sources.append(
                BatchSourceHive(
                    hive_id=row.hive_id,
                    hive_code=row.hive_code,
                    hive_status=_enum_value(getattr(hive, "status", None)),
                    quantity=quantity,
                    unit=collection.unit.value,
                    unit_label=collection.unit.label,
                    contribution_share=(float(quantity / total) if total else None),
                    village=getattr(hive, "village", None),
                    district=getattr(hive, "district", None),
                    beekeeper_code=getattr(beekeeper, "beekeeper_code", None),
                )
            )
        return sources

    def snapshot_for_batch(self, batch: HoneyBatch):
        """The AI estimate captured at harvest time, beside what was harvested.

        Nothing is recomputed here: the stored snapshot is read back, so a batch
        always reports the estimate that was current when the honey was collected.
        """
        from app.schemas.batch import BatchAiContext, BatchAiPerHive

        collection = self._collection_of_batch(batch)
        predicted = collection.ai_predicted_yield_kg
        per_hive = [
            BatchAiPerHive(
                hive_id=row.hive_id,
                hive_code=row.hive_code,
                ai_predicted_yield_kg=row.ai_predicted_yield_kg,
                quantity=row.quantity,
            )
            for row in self.sources_of(collection)
        ]
        if predicted is None:
            return BatchAiContext(
                has_analysis=False,
                prediction_hive_count=0,
                actual_quantity=collection.total_quantity,
                per_hive=per_hive,
                note=(
                    "No AI yield estimate existed for the source hives when this harvest was "
                    "recorded, so there is nothing to compare the collected quantity against."
                ),
            )
        return BatchAiContext(
            has_analysis=True,
            predicted_yield_kg=predicted,
            prediction_hive_count=collection.ai_prediction_hive_count,
            captured_at=collection.ai_prediction_captured_at,
            actual_quantity=collection.total_quantity,
            difference_kg=collection.total_quantity - predicted,
            per_hive=per_hive,
            note=(
                "Predicted yield is the AI estimate stored for the source hives when this "
                "harvest was recorded, shown beside the quantity actually collected. The "
                "difference compares one estimate with one weighed harvest; it is not a "
                "statement about model accuracy."
            ),
        )

    def _collection_of_batch(self, batch: HoneyBatch) -> HoneyCollection:
        collection = getattr(batch, "__dict__", {}).get("collection")
        if collection is None:
            collection = self.collections.get(batch.collection_id)
        if collection is None:  # pragma: no cover - the foreign key makes this unreachable
            raise NotFoundError(
                f"The collection behind batch {batch.batch_code} was not found",
                details={"resource": "collection"},
            )
        return collection

    # ------------------------------------------------------------------ #
    # Internals — loaded relationships, with a fallback for detached rows
    # ------------------------------------------------------------------ #
    def sources_of(self, collection: HoneyCollection) -> list[HoneyCollectionHive]:
        loaded = getattr(collection, "__dict__", {}).get("sources")
        if loaded is not None:
            return list(loaded)
        return self.collections.source_rows(collection.id)

    def _beekeeper_of(self, collection: HoneyCollection) -> Beekeeper | None:
        loaded = getattr(collection, "__dict__", {}).get("beekeeper")
        if loaded is not None:
            return loaded
        return self.beekeepers.get(collection.beekeeper_id)

    def _batch_of(self, collection: HoneyCollection) -> HoneyBatch | None:
        loaded = getattr(collection, "__dict__", {}).get("batch")
        if loaded is not None:
            return loaded
        return self.batches.get_by_collection(collection.id)

    @staticmethod
    def user_name(user) -> str | None:
        if user is None:
            return None
        parts = [getattr(user, "first_name", None) or "", getattr(user, "last_name", None) or ""]
        full = " ".join(part for part in parts if part).strip()
        return full or getattr(user, "email", None)


__all__ = [
    "CollectionService",
    "build_collection_code",
    "build_batch_code",
    "HARVESTABLE_HIVE_STATUSES",
]

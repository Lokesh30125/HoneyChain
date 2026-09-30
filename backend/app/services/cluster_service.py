"""KVIC cluster business logic, including code generation and membership."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictError,
    DuplicateResourceError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.models.document_sequence import DocumentSequence, district_code
from app.models.enums import AuditAction
from app.models.kvic_cluster import KvicCluster
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.cluster_repository import ClusterRepository
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection
from app.models.hive import Hive
from app.models.laboratory import LabTest
from app.models.distribution import Distribution
from app.models.packaging import HoneyPackage, PackagingRun
from app.schemas.cluster import ClusterCreate, ClusterDependencies, ClusterUpdate
from app.services.audit_service import AuditService

logger = get_logger("service")


def _subquery_batch_ids(session, cluster_id: uuid.UUID):
    """The ids of the batches recorded under a cluster, as a subquery.

    Written as a subquery rather than a join so the same helper answers the
    laboratory, packaging and package counts, and so a cluster with no batches
    short-circuits to an empty ``IN`` rather than to zero rows by accident.
    """
    from sqlalchemy import select

    return select(HoneyBatch.id).where(HoneyBatch.cluster_id == cluster_id)

SEQUENCE_WIDTH = 3


def beekeeper_previous_id(cluster) -> uuid.UUID | None:
    """The cluster a beekeeper came from, or ``None`` when they had none.

    Passed to the hive move so that only the hives still following the beekeeper
    are touched: a hive placed in another cluster on purpose stays where it was
    put.
    """
    return cluster.id if cluster is not None else None


class ClusterService:
    """Create, read and maintain KVIC clusters and their membership."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.clusters = ClusterRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        # Hives follow their owner's membership, so this service needs to write
        # their cluster pointer as well as the beekeeper's.
        self.hives = HiveRepository(session)
        self.audit = AuditService(session)
        # Imported lazily: placing a batch in a cluster is the only thing here
        # that reads a batch, and the batch service imports the collection
        # service, which reaches back into the cluster repository — a module-level
        # import would close that circle at import time.
        from app.services.batch_service import BatchService

        self.batches = BatchService(session)

    # ------------------------------------------------------------------ #
    # Codes
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_cluster_code(district: str | None, sequence: str) -> str:
        return f"KVIC-{district_code(district)}-{sequence}"

    def generate_cluster_code(self, district: str | None) -> str:
        """Reserve the next cluster code for a district, e.g. ``KVIC-GNT-001``."""
        prefix = f"KVIC-{district_code(district)}"
        for attempt in range(5):
            sequence = DocumentSequence.next_value(
                self.session, f"CLUSTER:{prefix}", width=SEQUENCE_WIDTH + attempt
            )
            candidate = f"{prefix}-{sequence}"
            if not self.clusters.code_exists(candidate):
                return candidate
            logger.warning("Cluster code collision, retrying", extra={"candidate": candidate})
        raise ValidationError("Could not allocate a unique cluster code. Please retry.")

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, cluster_id: uuid.UUID) -> KvicCluster:
        cluster = self.clusters.get(cluster_id)
        if cluster is None:
            raise NotFoundError("KVIC cluster not found")
        return cluster

    def list_clusters(self, **filters) -> tuple[list[KvicCluster], int]:
        return self.clusters.search(**filters)

    def member_counts(self) -> dict[str, int]:
        """Member counts per cluster id (single aggregate query)."""
        return self.beekeepers.count_by_cluster()

    def batch_counts(self) -> dict[str, int]:
        """Batches per cluster id (single aggregate query).

        Counted from the same column the cluster's batch list reads
        (``honey_batches.cluster_id``), so a register showing "3 batches" and a
        cluster page listing three rows are the same fact, not two opinions.
        """
        from sqlalchemy import func, select

        rows = self.session.execute(
            select(HoneyBatch.cluster_id, func.count())
            .where(HoneyBatch.cluster_id.is_not(None))
            .group_by(HoneyBatch.cluster_id)
        ).all()
        return {str(cluster_id): int(count) for cluster_id, count in rows}

    def list_members(self, cluster_id: uuid.UUID, *, page: int = 1, page_size: int = 20):
        # Confirms the cluster exists, so a bad id yields 404 rather than [].
        self.get(cluster_id)
        return self.beekeepers.list_by_cluster(cluster_id, page=page, page_size=page_size)

    def filter_options(self) -> dict[str, list[str]]:
        return {"districts": self.clusters.distinct_districts()}

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def create_cluster(self, payload: ClusterCreate, *, actor: User) -> KvicCluster:
        """Create a cluster, generating the code when one was not supplied."""
        cluster_code = payload.cluster_code or self.generate_cluster_code(payload.district)

        if self.clusters.code_exists(cluster_code):
            raise DuplicateResourceError(
                f"Cluster code {cluster_code} is already in use",
                details={"field": "cluster_code"},
            )

        cluster = self.clusters.create(
            cluster_code=cluster_code,
            cluster_name=payload.cluster_name,
            district=payload.district,
            state=payload.state,
            description=payload.description,
            coordinator_name=payload.coordinator_name,
            coordinator_phone=payload.coordinator_phone,
            is_active=True,
        )

        self.audit.cluster_created(cluster, actor=actor)

        # The batches chosen on the create form are placed in the *same*
        # transaction as the cluster itself. An officer who picked a batch that
        # turns out to be spoken for gets a 409 and no cluster at all, rather
        # than an empty cluster they did not ask for and would have to clean up.
        chosen = list(getattr(payload, "batch_ids", []) or [])
        if chosen:
            self._place_batches(
                cluster,
                chosen,
                actor=actor,
                reassign=bool(getattr(payload, "reassign", False)),
                commit=False,
            )

        self.clusters.commit()

        logger.info(
            "Cluster created",
            extra={
                "cluster_code": cluster.cluster_code,
                "district": cluster.district,
                "batches": len(chosen),
            },
        )
        return cluster

    def update_cluster(
        self, cluster_id: uuid.UUID, payload: ClusterUpdate, *, actor: User
    ) -> KvicCluster:
        cluster = self.get(cluster_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return cluster

        updated = self.clusters.update(cluster, **changes)
        self.audit.cluster_updated(updated, actor=actor, changed_fields=sorted(changes))
        self.clusters.commit()
        return updated

    def set_status(
        self, cluster_id: uuid.UUID, *, is_active: bool, reason: str | None, actor: User
    ) -> KvicCluster:
        """Activate or deactivate a cluster.

        Deactivating does not unassign members — their beekeeper records remain
        historically accurate (they *were* in that cluster) and the UI marks the
        cluster as inactive. Reassigning is a deliberate, audited action.
        """
        cluster = self.get(cluster_id)

        if cluster.is_active == is_active:
            raise ValidationError(
                f"This cluster is already {'active' if is_active else 'inactive'}",
                details={"field": "is_active"},
            )

        updated = self.clusters.update(cluster, is_active=is_active)
        self.audit.cluster_status_changed(updated, actor=actor, is_active=is_active)
        if reason:
            self.audit.record(
                "CLUSTER_STATUS_CHANGED",
                actor=actor,
                entity_type="kvic_cluster",
                entity_id=cluster.id,
                metadata={"reason": reason},
                description=f"Reason: {reason}",
            )
        self.clusters.commit()
        return updated

    def assign_beekeeper(
        self, cluster_id: uuid.UUID, beekeeper_id: uuid.UUID, *, actor: User
    ) -> tuple[KvicCluster, object]:
        """Add a beekeeper to a cluster (``POST /clusters/{id}/beekeepers``).

        Membership is the *only* way a beekeeper becomes visible to a cluster, so
        this is a privileged action (``CLUSTER_MANAGE``) and it is audited twice
        over: once for the beekeeper, once as a relationship summary naming the
        hives that followed them.
        """
        cluster = self.get(cluster_id)
        if not cluster.is_active:
            raise ValidationError(
                "This cluster is inactive and cannot accept new members",
                details={"field": "cluster_id"},
            )

        beekeeper = self.beekeepers.get(beekeeper_id)
        if beekeeper is None:
            raise NotFoundError("Beekeeper not found")

        if beekeeper.kvic_cluster_id == cluster.id:
            raise ValidationError(
                "This beekeeper is already a member of the cluster",
                details={"field": "beekeeper_id"},
            )

        previous = self.clusters.get(beekeeper.kvic_cluster_id) if beekeeper.kvic_cluster_id else None
        updated = self.beekeepers.assign_cluster(beekeeper, cluster.id)
        moved = self.hives.set_cluster_for_beekeeper(
            beekeeper.id, cluster.id, previous_cluster_id=beekeeper_previous_id(previous)
        )
        # Their harvests follow too, so nothing the beekeeper already recorded goes
        # on reading as "no cluster assigned" now that the cluster exists.
        linked = self.backfill_records_for_beekeeper(beekeeper.id, cluster.id)
        self.audit.cluster_member_assigned(updated, actor=actor, cluster=cluster)
        self.audit.cluster_relationship_updated(
            updated,
            actor=actor,
            previous_cluster=previous,
            cluster=cluster,
            hives_followed=moved,
            records_linked=linked,
        )
        self.clusters.commit()
        return cluster, updated

    def remove_beekeeper(
        self, cluster_id: uuid.UUID, beekeeper_id: uuid.UUID, *, actor: User
    ) -> tuple[KvicCluster, object]:
        """Clear a beekeeper's membership, detaching their hives from the view.

        Nothing is deleted: the hives keep their readings, analyses and audit
        trail, and appear in the administrative worklist as hives without a
        cluster until they are placed again.
        """
        cluster = self.get(cluster_id)
        beekeeper = self.beekeepers.get(beekeeper_id)
        if beekeeper is None:
            raise NotFoundError("Beekeeper not found")

        if beekeeper.kvic_cluster_id != cluster.id:
            raise ValidationError(
                "This beekeeper is not a member of the cluster",
                details={"field": "beekeeper_id"},
            )

        updated = self.beekeepers.assign_cluster(beekeeper, None)
        detached = self.hives.set_cluster_for_beekeeper(
            beekeeper.id, None, previous_cluster_id=cluster.id
        )
        self.audit.cluster_member_assigned(updated, actor=actor, cluster=None)
        self.audit.cluster_relationship_updated(
            updated,
            actor=actor,
            previous_cluster=cluster,
            cluster=None,
            hives_followed=[],
            hives_detached=detached,
        )
        self.clusters.commit()
        return cluster, updated

    # ------------------------------------------------------------------ #
    # Putting honey batches in a cluster
    # ------------------------------------------------------------------ #
    # The relationship the KVIC screens manage is cluster → **honey batches**
    # (`honey_batches.cluster_id`), reached the other way round from membership:
    # a batch names the cluster, the batch's collection names the beekeeper, and
    # the beekeeper owns the hives. Nothing here creates a record — the batch,
    # its collection and its hives already exist and are left exactly as they
    # are. Only the one column that says *which cluster this honey belongs to*
    # is written, and only ever on the row that already holds it.
    #
    # The collection is written alongside the batch because the platform's own
    # backfill (`backfill_records_for_beekeeper`) maintains both halves together:
    # a harvest and the batch it produced are the same honey, and a cluster that
    # named one but not the other would contradict itself on its own harvest
    # panel. The beekeeper and hive links are never touched.
    def assign_batches(
        self,
        cluster_id: uuid.UUID,
        batch_ids: list[uuid.UUID],
        *,
        actor: User,
        reassign: bool = False,
    ) -> dict:
        """Place real honey batches in a cluster (``POST /clusters/{id}/batches``).

        Each batch is validated, then the *same row* is updated — a batch already
        in another cluster is refused unless the caller explicitly asks for a
        move, and the move is an update of that batch's own cluster link rather
        than a second relationship. Assigning a batch that is already here is not
        an error and not a duplicate: it is reported as ``already``.
        """
        cluster = self.get(cluster_id)
        return self._place_batches(cluster, batch_ids, actor=actor, reassign=reassign)

    def _place_batches(
        self,
        cluster: KvicCluster,
        batch_ids: list[uuid.UUID],
        *,
        actor: User,
        reassign: bool = False,
        commit: bool = True,
    ) -> dict:
        """The placement itself, shared by the create form and the batch endpoint.

        ``commit=False`` lets a caller place batches as part of a larger
        transaction — creating a cluster *with* its batches — without either half
        of the write becoming visible on its own.
        """
        if not cluster.is_active:
            raise ValidationError(
                "This cluster is inactive and cannot take new batches",
                details={"field": "cluster_id"},
            )

        assigned: list[HoneyBatch] = []
        already: list[HoneyBatch] = []
        elsewhere: list[HoneyBatch] = []
        moved: list[HoneyBatch] = []

        # De-duplicated in the order given, so one request cannot act twice on a
        # batch and the officer's list is answered in the order they sent it.
        unique_ids = list(dict.fromkeys(batch_ids))

        for batch_id in unique_ids:
            batch = self.session.get(HoneyBatch, batch_id)
            if batch is None:
                raise NotFoundError(
                    f"Batch {batch_id} not found", details={"resource": "batch"}
                )
            # Scope first: an officer cannot place honey they cannot read, whether
            # or not the id was guessed. Enforced here, not by hiding it in the UI.
            self.batches.assert_can_read(actor, batch)

            if batch.cluster_id == cluster.id:
                already.append(batch)
                continue
            if batch.cluster_id is not None:
                elsewhere.append(batch)
                if not reassign:
                    continue
                moved.append(batch)

            self._link_batch_to_cluster(batch, cluster)
            assigned.append(batch)

        if elsewhere and not reassign:
            # Refused as a whole rather than half-applied: the officer is told
            # which batches are already spoken for and what moving them means,
            # and nothing is written until they say so.
            listing = ", ".join(
                f"{batch.batch_code} ({self._cluster_label(batch)})" for batch in elsewhere[:10]
            )
            raise ConflictError(
                "Some of these batches already belong to another cluster: "
                f"{listing}. Moving a batch changes its cluster link on the same "
                "record — resend with `reassign: true` to do that deliberately.",
                details={
                    "field": "batch_ids",
                    "requires_reassign": True,
                    "batches": [
                        {
                            "batch_id": str(batch.id),
                            "batch_code": batch.batch_code,
                            "cluster_id": str(batch.cluster_id),
                            "cluster_code": getattr(batch.cluster, "cluster_code", None),
                            "cluster_name": getattr(batch.cluster, "cluster_name", None),
                        }
                        for batch in elsewhere
                    ],
                },
            )

        if assigned:
            self.audit.cluster_batches_assigned(
                cluster,
                actor=actor,
                batch_codes=[batch.batch_code for batch in assigned],
                moved_codes=[batch.batch_code for batch in moved],
            )
        if commit:
            self.clusters.commit()
            for batch in assigned + already:
                self.session.refresh(batch)
            count = self._batch_count(cluster.id)
        else:
            # Inside a larger transaction the row is read back from the session
            # this write already touched, so the caller sees what it just wrote.
            self.session.flush()
            count = self._batch_count(cluster.id)

        return {
            "cluster_id": cluster.id,
            "cluster_code": cluster.cluster_code,
            "assigned": [batch.batch_code for batch in assigned],
            "moved": [batch.batch_code for batch in moved],
            "already": [batch.batch_code for batch in already],
            "batch_count": count,
            "reassigned": bool(moved),
        }

    def detach_batch(self, cluster_id: uuid.UUID, batch_id: uuid.UUID, *, actor: User) -> dict:
        """Take a batch out of a cluster (``DELETE /clusters/{id}/batches/{batch_id}``).

        The batch, its collection, its beekeeper and its hives are untouched:
        what ends is the cluster link, which is why the honey goes on reading as
        "no cluster assigned" — the state it had before it was placed.
        """
        cluster = self.get(cluster_id)
        batch = self.session.get(HoneyBatch, batch_id)
        if batch is None:
            raise NotFoundError(f"Batch {batch_id} not found", details={"resource": "batch"})
        self.batches.assert_can_read(actor, batch)
        if batch.cluster_id != cluster.id:
            raise ValidationError(
                f"{batch.batch_code} is not in {cluster.cluster_code}",
                details={"field": "batch_id"},
            )

        code = batch.batch_code
        self._unlink_batch(batch)
        self.audit.cluster_batch_detached(cluster, actor=actor, batch_code=code, batch_id=batch.id)
        self.clusters.commit()
        return {
            "cluster_id": cluster.id,
            "cluster_code": cluster.cluster_code,
            "detached": code,
            "batch_count": self._batch_count(cluster.id),
        }

    def _cluster_label(self, batch: HoneyBatch) -> str:
        cluster = getattr(batch, "cluster", None)
        return getattr(cluster, "cluster_code", None) or "another cluster"

    def _link_batch_to_cluster(self, batch: HoneyBatch, cluster: KvicCluster) -> None:
        """Write the cluster link on the batch and on the harvest it came from."""
        batch.cluster_id = cluster.id
        collection = getattr(batch, "collection", None)
        if collection is not None:
            collection.cluster_id = cluster.id
        self.session.flush()

    def _unlink_batch(self, batch: HoneyBatch) -> None:
        """Clear the cluster link from the batch and from its harvest.

        Only cleared when the harvest currently names *this* cluster: a
        collection whose cluster was set for another reason keeps it.
        """
        cluster_id = batch.cluster_id
        batch.cluster_id = None
        collection = getattr(batch, "collection", None)
        if collection is not None and collection.cluster_id == cluster_id:
            collection.cluster_id = None
        self.session.flush()

    def _batch_count(self, cluster_id: uuid.UUID) -> int:
        from sqlalchemy import func, select

        return int(
            self.session.execute(
                select(func.count())
                .select_from(HoneyBatch)
                .where(HoneyBatch.cluster_id == cluster_id)
            ).scalar_one()
        )

    # ------------------------------------------------------------------ #
    # What is recorded under a cluster — and whether it may be removed
    # ------------------------------------------------------------------ #
    def dependencies(self, cluster: KvicCluster) -> ClusterDependencies:
        """Everything attached to a cluster, counted from the tables themselves.

        Each figure is its own ``SELECT count(*)`` against its own table, filtered
        by the cluster column that table actually has — which is also the check
        that the relationship exists end to end. A batch is counted through
        ``cluster_id``, which is the value that used to go missing; the fact that
        this count is non-zero is what proves the repair worked.
        """
        session = self.session

        def count(model, *conditions) -> int:
            from sqlalchemy import func, select

            statement = select(func.count()).select_from(model)
            for condition in conditions:
                statement = statement.where(condition)
            return int(session.execute(statement).scalar_one())

        hives = count(Hive, Hive.cluster_id == cluster.id)
        collections = count(HoneyCollection, HoneyCollection.cluster_id == cluster.id)
        batches = count(HoneyBatch, HoneyBatch.cluster_id == cluster.id)
        # A test belongs to a batch, not to a cluster: it is counted through the
        # batches that are in the cluster, which is the only relationship the data
        # actually records.
        laboratory_tests = count(
            LabTest,
            LabTest.batch_id.in_(
                _subquery_batch_ids(session, cluster.id)
            ),
        )
        packaging_runs = count(
            PackagingRun,
            PackagingRun.batch_id.in_(_subquery_batch_ids(session, cluster.id)),
        )
        packages = count(
            HoneyPackage,
            HoneyPackage.batch_id.in_(_subquery_batch_ids(session, cluster.id)),
        )
        # Shipments hang off packages rather than off the cluster, so they are
        # counted the same way a test is: through the batches that are in it.
        shipments = count(
            Distribution,
            Distribution.batch_id.in_(_subquery_batch_ids(session, cluster.id)),
        )
        return ClusterDependencies(
            # The beekeeper record names its cluster ``kvic_cluster_id``: the column
            # predates the workflow that now depends on it.
            beekeepers=self.beekeepers.count(kvic_cluster_id=cluster.id),
            hives=hives,
            collections=collections,
            batches=batches,
            laboratory_tests=laboratory_tests,
            packaging_runs=packaging_runs,
            packages=packages,
            shipments=shipments,
        )

    def deletion_blocker(self, cluster: KvicCluster) -> tuple[bool, ClusterDependencies, str | None]:
        """Whether a cluster may be removed, and the words for why it may not."""
        dependencies = self.dependencies(cluster)
        if dependencies.total == 0:
            return True, dependencies, None
        named = ", ".join(
            f"{label}: {value}" for label, value in dependencies.as_counts().items() if value
        )
        return (
            False,
            dependencies,
            (
                "Cannot delete this cluster because records are associated with it — "
                f"{named}. Those records are the history of honey that was harvested and packed, "
                "and this platform does not delete them to tidy the register. Deactivate the "
                "cluster instead: it takes no new members and every existing record keeps its place."
            ),
        )

    def delete_cluster(
        self, cluster_id: uuid.UUID, *, actor: User, reason: str | None = None
    ) -> dict:
        """Remove a cluster that has nothing recorded under it.

        Two refusals, in this order, and both are deliberate:

        1. **Records exist.** The cluster is the anchor of a real supply chain
           record — a beekeeper's apiary, a harvest, a batch, packages on a shelf.
           Deleting the anchor would not delete that history (nothing cascades),
           it would orphan it: the beekeeper would show as belonging to a cluster
           that no longer exists, and the traceability page would have a hole in
           it. So the request is refused with the counts, and deactivation is
           offered as the operation that achieves what the officer actually wants.
        2. **Membership exists.** A beekeeper is attached: same answer, for the
           same reason.

        An empty cluster is deleted, and the deletion is audited with the cluster's
        own code, name and district, so the audit log still says what was removed
        after the row is gone.
        """
        cluster = self.get(cluster_id)
        allowed, dependencies, blocker = self.deletion_blocker(cluster)
        if not allowed:
            raise ConflictError(blocker, details={**dependencies.as_counts(), "can_delete": False})

        snapshot = {
            "cluster_id": str(cluster.id),
            "cluster_code": cluster.cluster_code,
            "cluster_name": cluster.cluster_name,
            "district": cluster.district,
            "state": cluster.state,
            "reason": reason,
            "dependencies": dependencies.as_counts(),
        }
        self.audit.record(
            AuditAction.CLUSTER_DELETED,
            actor=actor,
            entity_type="kvic_cluster",
            entity_id=cluster.id,
            description=(
                f"Cluster {cluster.cluster_code} ({cluster.cluster_name}) removed — nothing was "
                "recorded under it"
            ),
            metadata=snapshot,
        )
        self.session.delete(cluster)
        self.session.commit()
        logger.info(
            "Cluster deleted",
            extra={"cluster_code": snapshot["cluster_code"], "actor_id": str(actor.id)},
        )
        return snapshot

    # ------------------------------------------------------------------ #
    # The harvest that came before the membership
    # ------------------------------------------------------------------ #
    def backfill_records_for_beekeeper(
        self, beekeeper_id: uuid.UUID, cluster_id: uuid.UUID
    ) -> dict[str, int]:
        """Give a beekeeper's un-clustered harvests the cluster they now belong to.

        The order of events in real life is often the other way round from the order
        in the data: a beekeeper harvests for a season, and *then* joins a cluster.
        Their collections were therefore stored with no cluster, because there was
        none to store — which is why their batches went on saying "no cluster
        assigned" long after the relationship existed.

        This runs as part of assigning the beekeeper, so that the officer's one
        action leaves nothing half-done. It is deliberately narrow:

        * only rows whose ``cluster_id`` is **NULL** are touched — a record that
          already names a cluster keeps it, because that is where it was made;
        * only rows belonging to **this** beekeeper, so no other apiary is dragged in;
        * the value written is the cluster the beekeeper was just placed in, which is
          the same value ``cluster_for`` would derive — the relationship, not a guess.

        Returns the counts, for the audit entry and for the officer's confirmation.
        """
        from sqlalchemy import update

        collections = self.session.execute(
            update(HoneyCollection)
            .where(
                HoneyCollection.beekeeper_id == beekeeper_id,
                HoneyCollection.cluster_id.is_(None),
            )
            .values(cluster_id=cluster_id)
        ).rowcount
        # Batches carry their own beekeeper pointer (they can be created from a
        # collection), so the same rule applies to them directly. A batch whose
        # collection was just filled in is matched here too, and one that already
        # had a cluster is left alone.
        batches = self.session.execute(
            update(HoneyBatch)
            .where(
                HoneyBatch.beekeeper_id == beekeeper_id,
                HoneyBatch.cluster_id.is_(None),
            )
            .values(cluster_id=cluster_id)
        ).rowcount
        if collections or batches:
            self.session.flush()
            logger.info(
                "Cluster link filled in from a membership",
                extra={
                    "beekeeper_id": str(beekeeper_id),
                    "cluster_id": str(cluster_id),
                    "collections": collections,
                    "batches": batches,
                },
            )
        return {"collections": collections, "batches": batches}

    def summary(self) -> dict:
        """Database-backed cluster counts (no estimates)."""
        all_clusters, total = self.list_clusters(page=1, page_size=1)
        active = self.clusters.count(is_active=True)
        inactive = self.clusters.count(is_active=False)
        member_counts = self.member_counts()
        return {
            "total": total,
            "active": active,
            "inactive": inactive,
            "members_assigned": sum(member_counts.values()),
            "unassigned_beekeepers": self.beekeepers.count()
            - sum(member_counts.values()),
        }

"""Data access for ``honey_batches``.

A batch is read-only in this phase, so this repository has reads and a single
create. The source hives of a batch are never queried from here directly: they
are reached through the collection (`batch → collection →
honey_collection_hives → hives`), which is the one place those relationships are
recorded.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.beekeeper import Beekeeper
from app.models.enums import BatchStatus
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection, HoneyCollectionHive
from app.repositories.base import BaseRepository


class BatchRepository(BaseRepository[HoneyBatch]):
    model = HoneyBatch

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_with_relations(self, batch_id: uuid.UUID) -> HoneyBatch | None:
        """One batch with its collection, sources, owner, cluster and their user."""
        statement = (
            select(HoneyBatch)
            .options(
                joinedload(HoneyBatch.cluster),
                joinedload(HoneyBatch.beekeeper).joinedload(Beekeeper.user),
                joinedload(HoneyBatch.collection).joinedload(HoneyCollection.cluster),
                joinedload(HoneyBatch.collection)
                .selectinload(HoneyCollection.sources)
                .joinedload(HoneyCollectionHive.hive),
            )
            .where(HoneyBatch.id == batch_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_collection(self, collection_id: uuid.UUID) -> HoneyBatch | None:
        """The batch a collection produced, if it already has one."""
        return self.get_by(collection_id=collection_id)

    def code_exists(self, code: str) -> bool:
        return self.exists(batch_code=code)

    def for_cluster(self, cluster_id: uuid.UUID) -> list[HoneyBatch]:
        """Every batch in one cluster, oldest harvest first — no page limit.

        Used by the cluster's own counters, which must count the whole cluster
        rather than a page of it. Ordering is by harvest date so the same query
        answers both a total and a stable list.
        """
        return list(
            self.session.execute(
                select(HoneyBatch)
                .options(
                    joinedload(HoneyBatch.collection),
                    joinedload(HoneyBatch.beekeeper),
                    joinedload(HoneyBatch.cluster),
                )
                .where(HoneyBatch.cluster_id == cluster_id)
                .order_by(HoneyBatch.collection_date.asc(), HoneyBatch.created_at.asc())
            )
            .unique()
            .scalars()
        )

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: BatchStatus | None = None,
        statuses: list[BatchStatus] | None = None,
        collection_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
        unclustered: bool = False,
        not_cluster_id: uuid.UUID | None = None,
        hive_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        order_by: str = "collection_date",
        descending: bool = True,
    ) -> tuple[list[HoneyBatch], int]:
        filters = []

        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(func.lower(HoneyBatch.batch_code).like(term))
        if status is not None:
            filters.append(HoneyBatch.status == status)
        if statuses:
            # A shortlist, for the screens that work more than one state at once —
            # the packaging worklist reads APPROVED *and* PACKAGED, because a
            # partly packed batch still has honey to pack.
            filters.append(HoneyBatch.status.in_(statuses))
        if collection_id is not None:
            filters.append(HoneyBatch.collection_id == collection_id)
        if beekeeper_id is not None:
            filters.append(HoneyBatch.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            filters.append(HoneyBatch.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            filters.append(HoneyBatch.cluster_id == cluster_id)
        if unclustered:
            # Only batches that name no cluster: the ones an officer has not yet
            # placed. Filtered *in the query*, so a page is never emptied after
            # the fact by dropping rows the database already counted.
            filters.append(HoneyBatch.cluster_id.is_(None))
        if not_cluster_id is not None:
            # Everything except the batches already in this cluster — both the
            # unplaced ones and the ones in another cluster, which the caller has
            # to see in order to decide whether to move them.
            filters.append(
                or_(HoneyBatch.cluster_id.is_(None), HoneyBatch.cluster_id != not_cluster_id)
            )
        if cluster_ids is not None:
            if include_unclustered:
                # A batch with no cluster is still a batch. Leaving it out of an
                # officer's list hides honey they are responsible for and makes the
                # missing relationship invisible instead of visible and repairable.
                filters.append(
                    or_(HoneyBatch.cluster_id.in_(cluster_ids), HoneyBatch.cluster_id.is_(None))
                )
            else:
                filters.append(HoneyBatch.cluster_id.in_(cluster_ids))
        if hive_id is not None:
            # A batch traces to a hive through its collection's source rows, so
            # "batches from this hive" is expressed the same way on every screen.
            filters.append(
                select(HoneyCollectionHive.id)
                .where(
                    HoneyCollectionHive.collection_id == HoneyBatch.collection_id,
                    HoneyCollectionHive.hive_id == hive_id,
                )
                .exists()
            )
        if date_from is not None:
            filters.append(HoneyBatch.collection_date >= date_from)
        if date_to is not None:
            filters.append(HoneyBatch.collection_date <= date_to)

        base = select(HoneyBatch).options(
            joinedload(HoneyBatch.cluster),
            joinedload(HoneyBatch.collection).selectinload(HoneyCollection.sources),
        )
        count_statement = select(func.count()).select_from(HoneyBatch)
        if filters:
            condition = and_(*filters)
            base = base.where(condition)
            count_statement = count_statement.where(condition)

        # A page of rows must be a stable page. Ordering by the collection date
        # alone leaves rows recorded on the same day in whatever order the database
        # happens to return them in, which is how a batch created a minute ago can
        # land on a later page than a batch created last week — and be reported as
        # "not reflected" when it is right there. The newest record of any given day
        # comes first, and the id makes the order total.
        column = getattr(HoneyBatch, order_by, HoneyBatch.collection_date)
        base = base.order_by(
            column.desc() if descending else column.asc(),
            HoneyBatch.created_at.desc(),
            HoneyBatch.id.desc(),
        )
        base = base.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(base).scalars().unique().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total

    def count_by_status(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
    ) -> dict[str, int]:
        statement = select(HoneyBatch.status, func.count()).group_by(HoneyBatch.status)
        if beekeeper_id is not None:
            statement = statement.where(HoneyBatch.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            statement = statement.where(HoneyBatch.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            statement = statement.where(HoneyBatch.cluster_id == cluster_id)
        if cluster_ids is not None:
            # The same rule the listing uses: an officer's figures must add up to the
            # rows on their screen, so a batch with no cluster yet is counted there
            # too rather than quietly lowering the total.
            statement = statement.where(
                or_(HoneyBatch.cluster_id.in_(cluster_ids), HoneyBatch.cluster_id.is_(None))
                if include_unclustered
                else HoneyBatch.cluster_id.in_(cluster_ids)
            )
        counts = {status.value: 0 for status in BatchStatus}
        for status, count in self.session.execute(statement).all():
            counts[str(getattr(status, "value", status))] = int(count)
        return counts

    def totals(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
        since: date | None = None,
    ) -> dict[str, Decimal]:
        """Batched quantity per unit (never summed across units)."""
        statement = (
            select(HoneyBatch.unit, func.coalesce(func.sum(HoneyBatch.quantity), 0)).group_by(
                HoneyBatch.unit
            )
        )
        if beekeeper_id is not None:
            statement = statement.where(HoneyBatch.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            statement = statement.where(HoneyBatch.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            statement = statement.where(HoneyBatch.cluster_id == cluster_id)
        if cluster_ids is not None:
            # The same rule the listing uses: an officer's figures must add up to the
            # rows on their screen, so a batch with no cluster yet is counted there
            # too rather than quietly lowering the total.
            statement = statement.where(
                or_(HoneyBatch.cluster_id.in_(cluster_ids), HoneyBatch.cluster_id.is_(None))
                if include_unclustered
                else HoneyBatch.cluster_id.in_(cluster_ids)
            )
        if since is not None:
            statement = statement.where(HoneyBatch.collection_date >= since)

        totals: dict[str, Decimal] = {}
        for unit, value in self.session.execute(statement).all():
            totals[str(getattr(unit, "value", unit))] = Decimal(value or 0)
        return totals

    def count_for_cluster(self, cluster_id: uuid.UUID) -> int:
        statement = (
            select(func.count())
            .select_from(HoneyBatch)
            .where(HoneyBatch.cluster_id == cluster_id)
        )
        return int(self.session.execute(statement).scalar_one())


__all__ = ["BatchRepository"]

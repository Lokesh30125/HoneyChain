"""Data access for ``honey_collections`` and their per-hive contributions.

The only queries in the codebase that read harvest records. Scope is decided by
the service, which passes the ids it resolved from the authenticated user —
``beekeeper_id`` for a beekeeper's own harvests, ``cluster_ids`` for the clusters
an officer oversees — so no query parameter can widen a result set here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.beekeeper import Beekeeper
from app.models.enums import CollectionStatus
from app.models.hive import Hive
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection, HoneyCollectionHive
from app.repositories.base import BaseRepository


class CollectionRepository(BaseRepository[HoneyCollection]):
    model = HoneyCollection

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_with_sources(self, collection_id: uuid.UUID) -> HoneyCollection | None:
        """One collection with everything a detail screen renders.

        Eagerly loads the sources, the hive behind each source, the owner's user
        record, the cluster and the batch, so serialisation never triggers a lazy
        load per row.
        """
        statement = (
            select(HoneyCollection)
            .options(
                selectinload(HoneyCollection.sources).joinedload(HoneyCollectionHive.hive),
                joinedload(HoneyCollection.beekeeper).joinedload(Beekeeper.user),
                joinedload(HoneyCollection.cluster),
                joinedload(HoneyCollection.batch),
            )
            .where(HoneyCollection.id == collection_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def source_rows(self, collection_id: uuid.UUID) -> list[HoneyCollectionHive]:
        statement = (
            select(HoneyCollectionHive)
            .options(joinedload(HoneyCollectionHive.hive))
            .where(HoneyCollectionHive.collection_id == collection_id)
            .order_by(HoneyCollectionHive.created_at.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def code_exists(self, code: str) -> bool:
        return self.exists(collection_code=code)

    def find_by_client_reference(
        self, beekeeper_id: uuid.UUID, client_reference: str
    ) -> HoneyCollection | None:
        """The collection a retried create refers to, if it was already stored."""
        return self.get_by(beekeeper_id=beekeeper_id, client_reference=client_reference)

    def hive_is_a_source(self, hive_id: uuid.UUID) -> bool:
        """Whether any harvest has ever drawn honey from this hive."""
        return self.session.execute(
            select(HoneyCollectionHive.id).where(HoneyCollectionHive.hive_id == hive_id).limit(1)
        ).scalars().first() is not None

    def count_for_hive(self, hive_id: uuid.UUID) -> int:
        statement = (
            select(func.count())
            .select_from(HoneyCollectionHive)
            .where(HoneyCollectionHive.hive_id == hive_id)
        )
        return int(self.session.execute(statement).scalar_one())

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: CollectionStatus | None = None,
        statuses: list[CollectionStatus] | None = None,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
        hive_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        has_batch: bool | None = None,
        order_by: str = "collection_date",
        descending: bool = True,
    ) -> tuple[list[HoneyCollection], int]:
        """Filtered, paginated harvest listing.

        ``beekeeper_ids`` / ``cluster_ids`` are the *served* scope: an empty list
        means "this caller may see nothing", which is why the service passes them
        explicitly rather than relying on a falsy ``None``.
        """
        filters = []

        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(HoneyCollection.collection_code).like(term),
                    func.lower(HoneyCollection.notes).like(term),
                )
            )
        if status is not None:
            filters.append(HoneyCollection.status == status)
        if statuses is not None:
            filters.append(HoneyCollection.status.in_(statuses))
        if beekeeper_id is not None:
            filters.append(HoneyCollection.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            filters.append(HoneyCollection.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            filters.append(HoneyCollection.cluster_id == cluster_id)
        if cluster_ids is not None:
            if include_unclustered:
                # Included for the same reason as batches: a harvest that names no
                # cluster belongs to whoever is responsible for the apiary it came
                # from, and hiding it does not link it.
                filters.append(
                    or_(
                        HoneyCollection.cluster_id.in_(cluster_ids),
                        HoneyCollection.cluster_id.is_(None),
                    )
                )
            else:
                filters.append(HoneyCollection.cluster_id.in_(cluster_ids))
        if hive_id is not None:
            filters.append(
                select(HoneyCollectionHive.id)
                .where(
                    HoneyCollectionHive.collection_id == HoneyCollection.id,
                    HoneyCollectionHive.hive_id == hive_id,
                )
                .exists()
            )
        if date_from is not None:
            filters.append(HoneyCollection.collection_date >= date_from)
        if date_to is not None:
            filters.append(HoneyCollection.collection_date <= date_to)
        if has_batch is not None:
            # Correlated on the outer row: a batch whose collection_id is *this*
            # collection. Without the correlation the EXISTS asks the database-wide
            # question "does any harvest have a batch?" and every row answers the
            # same way.
            produced = (
                select(HoneyBatch.id).where(HoneyBatch.collection_id == HoneyCollection.id).exists()
            )
            filters.append(produced if has_batch else ~produced)

        base = select(HoneyCollection).options(
            joinedload(HoneyCollection.cluster),
            selectinload(HoneyCollection.sources),
            joinedload(HoneyCollection.batch),
        )
        count_statement = select(func.count()).select_from(HoneyCollection)
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
        column = getattr(HoneyCollection, order_by, HoneyCollection.collection_date)
        base = base.order_by(
            column.desc() if descending else column.asc(),
            HoneyCollection.created_at.desc(),
            HoneyCollection.id.desc(),
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
        statement = select(HoneyCollection.status, func.count()).group_by(
            HoneyCollection.status
        )
        if beekeeper_id is not None:
            statement = statement.where(HoneyCollection.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            statement = statement.where(HoneyCollection.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            statement = statement.where(HoneyCollection.cluster_id == cluster_id)
        if cluster_ids is not None:
            statement = statement.where(
                or_(
                    HoneyCollection.cluster_id.in_(cluster_ids),
                    HoneyCollection.cluster_id.is_(None),
                )
                if include_unclustered
                else HoneyCollection.cluster_id.in_(cluster_ids)
            )
        counts = {status.value: 0 for status in CollectionStatus}
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
        statuses: list[CollectionStatus] | None = None,
        since: date | None = None,
    ) -> dict[str, Decimal]:
        """Quantity summed per unit for the given statuses (COMPLETED by default).

        Summed **per unit** rather than into one number: adding kilograms to grams
        would invent a conversion the beekeeper never made. A planned harvest has
        produced nothing yet, so it is not counted unless it is asked for — which
        is how the workspace reports "recorded but still open" separately.
        """
        selected = statuses if statuses else [CollectionStatus.COMPLETED]
        statement = (
            select(
                HoneyCollection.unit,
                func.coalesce(func.sum(HoneyCollection.total_quantity), 0),
            )
            .where(HoneyCollection.status.in_(selected))
            .group_by(HoneyCollection.unit)
        )
        if beekeeper_id is not None:
            statement = statement.where(HoneyCollection.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            statement = statement.where(HoneyCollection.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            statement = statement.where(HoneyCollection.cluster_id == cluster_id)
        if cluster_ids is not None:
            statement = statement.where(
                or_(
                    HoneyCollection.cluster_id.in_(cluster_ids),
                    HoneyCollection.cluster_id.is_(None),
                )
                if include_unclustered
                else HoneyCollection.cluster_id.in_(cluster_ids)
            )
        if since is not None:
            statement = statement.where(HoneyCollection.collection_date >= since)

        totals: dict[str, Decimal] = {}
        for unit, value in self.session.execute(statement).all():
            totals[str(getattr(unit, "value", unit))] = Decimal(value or 0)
        return totals

    def latest_for_hive(self, hive_id: uuid.UUID) -> HoneyCollection | None:
        statement = (
            select(HoneyCollection)
            .join(HoneyCollectionHive, HoneyCollectionHive.collection_id == HoneyCollection.id)
            .where(HoneyCollectionHive.hive_id == hive_id)
            .order_by(HoneyCollection.collection_date.desc(), HoneyCollection.created_at.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalars().first()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def add_source(
        self,
        collection: HoneyCollection,
        *,
        hive: Hive,
        quantity: Decimal,
        ai_predicted_yield_kg: Decimal | None = None,
        ai_analysis_id: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> HoneyCollectionHive:
        row = HoneyCollectionHive(
            collection_id=collection.id,
            hive_id=hive.id,
            hive_code=hive.hive_code,
            quantity=quantity,
            ai_predicted_yield_kg=ai_predicted_yield_kg,
            ai_analysis_id=ai_analysis_id,
            notes=notes,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def replace_sources(self, collection: HoneyCollection, rows: list[HoneyCollectionHive]) -> None:
        """Swap the contribution set of an *open* collection.

        Only ever called while a collection is editable: a completed harvest's
        sources are history.
        """
        for existing in list(collection.sources):
            self.session.delete(existing)
        collection.sources = rows
        self.session.flush()


__all__ = ["CollectionRepository"]

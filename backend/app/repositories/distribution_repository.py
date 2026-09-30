"""Data access for ``distributions`` — shipments of packages to retailers."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.distribution import Distribution
from app.models.enums import DistributionStatus
from app.models.honey_batch import HoneyBatch
from app.models.packaging import HoneyPackage, PackagingRun
from app.repositories.base import BaseRepository


def join_distribution_relations():
    """The eager loads every shipment payload needs, declared once.

    ``package_code``, ``batch_code`` and the destination all live on joined rows;
    without these the response would carry ``None`` where the identifiers belong.
    """
    return (
        joinedload(Distribution.package).joinedload(HoneyPackage.packaging),
        joinedload(Distribution.package)
        .joinedload(HoneyPackage.batch)
        .joinedload(HoneyBatch.beekeeper),
        joinedload(Distribution.package)
        .joinedload(HoneyPackage.batch)
        .joinedload(HoneyBatch.cluster),
        joinedload(Distribution.batch),
        joinedload(Distribution.distributor),
        joinedload(Distribution.retailer),
        joinedload(Distribution.received_by),
    )


class DistributionRepository(BaseRepository[Distribution]):
    model = Distribution

    def get_with_relations(self, distribution_id: uuid.UUID) -> Distribution | None:
        statement = (
            select(Distribution)
            .options(*join_distribution_relations())
            .where(Distribution.id == distribution_id)
            .execution_options(populate_existing=True)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_code(self, code: str) -> Distribution | None:
        return self.get_by(distribution_code=code)

    def code_exists(self, code: str) -> bool:
        return self.exists(distribution_code=code)

    def for_package(self, package_id: uuid.UUID) -> list[Distribution]:
        statement = (
            select(Distribution)
            .where(Distribution.package_id == package_id)
            .order_by(Distribution.created_at.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def for_batch(self, batch_id: uuid.UUID) -> list[Distribution]:
        statement = (
            select(Distribution)
            .options(*join_distribution_relations())
            .where(Distribution.batch_id == batch_id)
            .order_by(Distribution.created_at.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def for_retailer(self, retailer_id: uuid.UUID) -> list[Distribution]:
        statement = (
            select(Distribution)
            .options(*join_distribution_relations())
            .where(Distribution.retailer_id == retailer_id)
            .order_by(Distribution.created_at.desc(), Distribution.id.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def quantity_moved_for_package(
        self, package_id: uuid.UUID, *, statuses: list[DistributionStatus] | None = None
    ) -> Decimal:
        """How much of a package earlier shipments already account for.

        Cancelled shipments are excluded by the caller: a shipment that never
        left holds no quantity, which is what makes cancelling safe.
        """
        statement = select(func.coalesce(func.sum(Distribution.quantity), 0)).where(
            Distribution.package_id == package_id
        )
        if statuses:
            statement = statement.where(Distribution.status.in_(statuses))
        else:
            statement = statement.where(Distribution.status != DistributionStatus.CANCELLED)
        return Decimal(self.session.execute(statement).scalar_one() or 0)

    def summary_by_batch(self, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
        """How far each batch's shipments have got, in one query per page.

        Returns, per batch: how many shipments exist, how many have been received,
        and the status of the most recent one — which is what a cluster needs to
        say "in transit" or "delivered" about a batch without opening it.
        """
        if not batch_ids:
            return {}
        statement = (
            select(
                Distribution.batch_id,
                Distribution.status,
                func.count(),
                func.max(Distribution.created_at),
            )
            .where(Distribution.batch_id.in_(batch_ids))
            .group_by(Distribution.batch_id, Distribution.status)
        )
        summary: dict[uuid.UUID, dict] = {}
        latest: dict[uuid.UUID, tuple] = {}
        total_shipments: dict[uuid.UUID, int] = {}
        for batch_id, status, count, newest in self.session.execute(statement).all():
            entry = summary.setdefault(
                batch_id, {"shipments": 0, "delivered": 0, "latest_status": None}
            )
            entry["shipments"] += int(count)
            if str(status) == DistributionStatus.DELIVERED.value:
                entry["delivered"] += int(count)
            total_shipments[batch_id] = total_shipments.get(batch_id, 0) + int(count)
            if newest is not None and (batch_id not in latest or newest >= latest[batch_id][0]):
                latest[batch_id] = (newest, str(status))
        for batch_id, (_, status) in latest.items():
            summary[batch_id]["latest_status"] = status
        return summary

    def undelivered_for_batch(self, batch_id: uuid.UUID) -> int:
        """Shipments of a batch that are still open — the batch cannot be complete while any is."""
        statement = (
            select(func.count())
            .select_from(Distribution)
            .where(
                Distribution.batch_id == batch_id,
                Distribution.status.in_(
                    [
                        DistributionStatus.READY_FOR_DISPATCH,
                        DistributionStatus.DISPATCHED,
                        DistributionStatus.IN_TRANSIT,
                    ]
                ),
            )
        )
        return int(self.session.execute(statement).scalar_one())

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: DistributionStatus | None = None,
        statuses: list[DistributionStatus] | None = None,
        batch_id: uuid.UUID | None = None,
        package_id: uuid.UUID | None = None,
        distributor_id: uuid.UUID | None = None,
        retailer_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        awaiting_receipt: bool = False,
        require_retailer: bool = False,
        without_retailer: bool = False,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> tuple[list[Distribution], int]:
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(Distribution.distribution_code).like(term),
                    func.lower(Distribution.destination).like(term),
                    func.lower(HoneyPackage.package_code).like(term),
                    func.lower(HoneyBatch.batch_code).like(term),
                )
            )
        if status is not None:
            filters.append(Distribution.status == status)
        if statuses:
            filters.append(Distribution.status.in_(statuses))
        if batch_id is not None:
            filters.append(Distribution.batch_id == batch_id)
        if package_id is not None:
            filters.append(Distribution.package_id == package_id)
        if distributor_id is not None:
            filters.append(Distribution.distributor_id == distributor_id)
        if retailer_id is not None:
            filters.append(Distribution.retailer_id == retailer_id)
        if beekeeper_id is not None:
            # A beekeeper's shipments are those of their own batches — scoped in
            # the query, so the page and its total describe the same rows.
            filters.append(HoneyBatch.beekeeper_id == beekeeper_id)
        if awaiting_receipt:
            # Addressed, not cancelled, and not yet confirmed by the shop — which
            # includes a shipment the carrier has marked delivered.
            filters.append(Distribution.received_at.is_(None))
            filters.append(Distribution.status != DistributionStatus.CANCELLED)
        # A retailer's inbound list must contain shipments that name a retailer —
        # their own. Without this, a shipment recorded before a receiver was
        # required would appear in *every* retailer's list, because the filter
        # would read "addressed to me or to nobody".
        if require_retailer:
            filters.append(Distribution.retailer_id.is_not(None))
        if without_retailer:
            filters.append(Distribution.retailer_id.is_(None))

        statement = (
            select(Distribution)
            .join(HoneyPackage, Distribution.package_id == HoneyPackage.id)
            .join(HoneyBatch, Distribution.batch_id == HoneyBatch.id)
            .options(*join_distribution_relations())
        )
        count_statement = (
            select(func.count())
            .select_from(Distribution)
            .join(HoneyPackage, Distribution.package_id == HoneyPackage.id)
            .join(HoneyBatch, Distribution.batch_id == HoneyBatch.id)
        )
        if filters:
            condition = and_(*filters)
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(Distribution, order_by, Distribution.created_at)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(statement).scalars().unique().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total

    def count_by_status(
        self,
        *,
        distributor_id: uuid.UUID | None = None,
        retailer_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Shipments per state, bounded by the same scope the list uses."""
        statement = select(Distribution.status, func.count()).select_from(Distribution)
        if beekeeper_id is not None:
            statement = statement.join(HoneyBatch, Distribution.batch_id == HoneyBatch.id).where(
                HoneyBatch.beekeeper_id == beekeeper_id
            )
        if distributor_id is not None:
            statement = statement.where(Distribution.distributor_id == distributor_id)
        if retailer_id is not None:
            statement = statement.where(Distribution.retailer_id == retailer_id)
        statement = statement.group_by(Distribution.status)
        return {
            str(status.value if hasattr(status, "value") else status): int(count)
            for status, count in self.session.execute(statement).all()
        }


def retailer_package_summary(session, retailer_id: uuid.UUID) -> dict[str, int]:
    """How many packages a retailer holds, counted from the shipments that reached them."""
    statement = (
        select(Distribution.package_id)
        .where(
            Distribution.retailer_id == retailer_id,
            Distribution.status == DistributionStatus.DELIVERED,
        )
        .distinct()
    )
    package_ids = list(session.execute(statement).scalars().all())
    if not package_ids:
        return {"packages": 0, "delivered_shipments": 0}

    delivered = (
        select(func.count())
        .select_from(Distribution)
        .where(
            Distribution.retailer_id == retailer_id,
            Distribution.status == DistributionStatus.DELIVERED,
        )
    )
    in_transit = (
        select(func.count())
        .select_from(HoneyPackage)
        .where(HoneyPackage.id.in_(package_ids))
    )
    return {
        "packages": int(session.execute(in_transit).scalar_one()),
        "delivered_shipments": int(session.execute(delivered).scalar_one()),
    }

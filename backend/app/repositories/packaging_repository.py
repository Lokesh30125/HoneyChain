"""Data access for ``packaging_units``, ``packaging_records`` and ``packages``."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.enums import (
    BatchStatus,
    FacilityStatus,
    PackageStatus,
    PackagingStatus,
    ProcessingStatus,
)
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection
from app.models.packaging import HoneyPackage, PackagingRun, PackagingUnit
from app.models.processing import HoneyProcessing
from app.repositories.base import BaseRepository


class PackagingUnitRepository(BaseRepository[PackagingUnit]):
    model = PackagingUnit

    def get_by_code(self, code: str) -> PackagingUnit | None:
        return self.get_by(unit_code=code)

    def code_exists(self, code: str) -> bool:
        return self.exists(unit_code=code)

    def active_facilities(self) -> list[PackagingUnit]:
        """The packaging units currently accepting work, in a stable order."""
        statement = (
            select(PackagingUnit)
            .where(PackagingUnit.status == FacilityStatus.ACTIVE)
            .order_by(PackagingUnit.name.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def run_count(self, unit_id: uuid.UUID) -> int:
        """How many packing runs this facility has taken, from the stored rows.

        Counted rather than stored: a unit that has done nothing yet must read
        zero, and a counter column would be one more thing that can be wrong.
        """
        return int(
            self.session.execute(
                select(func.count())
                .select_from(PackagingRun)
                .where(PackagingRun.packaging_unit_id == unit_id)
            ).scalar_one()
        )

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
        district: str | None = None,
        order_by: str = "name",
        descending: bool = False,
    ) -> tuple[list[PackagingUnit], int]:
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(PackagingUnit.unit_code).like(term),
                    func.lower(PackagingUnit.name).like(term),
                    func.lower(PackagingUnit.district).like(term),
                )
            )
        if status is not None:
            filters.append(PackagingUnit.status == status)
        if district:
            filters.append(PackagingUnit.district == district)

        # The people who work here travel with the row: the unit register shows
        # them, and asking the database once beats asking it once per facility.
        statement = select(PackagingUnit).options(selectinload(PackagingUnit.members))
        count_statement = select(func.count()).select_from(PackagingUnit)
        if filters:
            condition = and_(*filters)
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(PackagingUnit, order_by, PackagingUnit.name)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(statement).scalars().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total


class PackagingRepository(BaseRepository[PackagingRun]):
    model = PackagingRun

    def get_with_relations(self, packaging_id: uuid.UUID) -> PackagingRun | None:
        """One packaging run with its batch, its facility, its actor and its packages."""
        statement = (
            select(PackagingRun)
            .options(
                *join_packaging_relations(),
                selectinload(PackagingRun.packages),
            )
            .where(PackagingRun.id == packaging_id)
            # The same object is often already in the session (a run was just
            # created or completed); populate_existing makes the eager loads
            # replace that cached state, so a response never shows the row as it
            # was before the write that just happened.
            .execution_options(populate_existing=True)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_code(self, code: str) -> PackagingRun | None:
        return self.get_by(packaging_code=code)

    def code_exists(self, code: str) -> bool:
        return self.exists(packaging_code=code)

    def open_for_batch(self, batch_id: uuid.UUID) -> PackagingRun | None:
        """The run under way for a batch, if there is one."""
        statement = select(PackagingRun).where(
            PackagingRun.batch_id == batch_id,
            PackagingRun.status.in_(PackagingStatus.open_statuses()),
        )
        return self.session.execute(statement).scalars().first()

    def for_batch(self, batch_id: uuid.UUID) -> list[PackagingRun]:
        statement = (
            select(PackagingRun)
            .options(selectinload(PackagingRun.packages))
            .where(PackagingRun.batch_id == batch_id)
            .order_by(PackagingRun.created_at.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def completed_for_batch(self, batch_id: uuid.UUID) -> list[PackagingRun]:
        statement = (
            select(PackagingRun)
            .where(
                PackagingRun.batch_id == batch_id,
                PackagingRun.status == PackagingStatus.COMPLETED,
            )
            .order_by(PackagingRun.created_at.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def packaged_quantity_by_batch(self, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        """Packed quantity per batch, in one query, for a page of rows.

        Only completed runs count: an open run has not packed anything yet, and a
        cancelled one never did.
        """
        if not batch_ids:
            return {}
        statement = (
            select(
                PackagingRun.batch_id,
                func.coalesce(func.sum(PackagingRun.packaged_quantity), 0),
            )
            .where(
                PackagingRun.batch_id.in_(batch_ids),
                PackagingRun.status == PackagingStatus.COMPLETED,
            )
            .group_by(PackagingRun.batch_id)
        )
        return {
            batch_id: Decimal(total or 0)
            for batch_id, total in self.session.execute(statement).all()
        }

    def packaged_quantity_for_batch(self, batch_id: uuid.UUID) -> Decimal:
        """How much of a batch has already left as packages, summed from the records.

        Only *completed* runs count: a run that was cancelled or is still open
        has not consumed any of the approved quantity yet.
        """
        statement = select(
            func.coalesce(func.sum(PackagingRun.packaged_quantity), 0)
        ).where(
            PackagingRun.batch_id == batch_id,
            PackagingRun.status == PackagingStatus.COMPLETED,
        )
        return Decimal(self.session.execute(statement).scalar_one() or 0)

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: PackagingStatus | None = None,
        statuses: list[PackagingStatus] | None = None,
        batch_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
        packaging_unit_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> tuple[list[PackagingRun], int]:
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(PackagingRun.packaging_code).like(term),
                    func.lower(HoneyBatch.batch_code).like(term),
                )
            )
        if status is not None:
            filters.append(PackagingRun.status == status)
        if statuses:
            filters.append(PackagingRun.status.in_(statuses))
        if batch_id is not None:
            filters.append(PackagingRun.batch_id == batch_id)
        if cluster_id is not None:
            # The batch's cluster, not a copy of it: a batch placed in (or moved
            # to) a cluster after it was packed is listed under that cluster.
            filters.append(HoneyBatch.cluster_id == cluster_id)
        if beekeeper_id is not None:
            filters.append(HoneyBatch.beekeeper_id == beekeeper_id)
        if packaging_unit_id is not None:
            filters.append(PackagingRun.packaging_unit_id == packaging_unit_id)

        statement = (
            select(PackagingRun)
            .join(HoneyBatch, PackagingRun.batch_id == HoneyBatch.id)
            .options(*join_packaging_relations())
        )
        count_statement = (
            select(func.count())
            .select_from(PackagingRun)
            .join(HoneyBatch, PackagingRun.batch_id == HoneyBatch.id)
        )
        if filters:
            condition = and_(*filters)
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(PackagingRun, order_by, PackagingRun.created_at)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(statement).scalars().unique().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total

    def count_by_status(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        packaging_unit_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Runs per state, bounded by the same scope the run list uses."""
        statement = select(PackagingRun.status, func.count()).select_from(PackagingRun)
        if beekeeper_id is not None:
            statement = statement.join(HoneyBatch, PackagingRun.batch_id == HoneyBatch.id).where(
                HoneyBatch.beekeeper_id == beekeeper_id
            )
        if packaging_unit_id is not None:
            statement = statement.where(PackagingRun.packaging_unit_id == packaging_unit_id)
        statement = statement.group_by(PackagingRun.status)
        return {
            str(status.value if hasattr(status, "value") else status): int(count)
            for status, count in self.session.execute(statement).all()
        }


class PackageRepository(BaseRepository[HoneyPackage]):
    model = HoneyPackage

    def counts_by_batch(self, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """How many packages each batch has produced, in one query."""
        if not batch_ids:
            return {}
        statement = (
            select(HoneyPackage.batch_id, func.count())
            .where(HoneyPackage.batch_id.in_(batch_ids))
            .group_by(HoneyPackage.batch_id)
        )
        return {batch_id: int(count) for batch_id, count in self.session.execute(statement).all()}

    def get_with_relations(self, package_id: uuid.UUID) -> HoneyPackage | None:
        statement = (
            select(HoneyPackage)
            .options(
                joinedload(HoneyPackage.batch).joinedload(HoneyBatch.beekeeper),
                joinedload(HoneyPackage.batch).joinedload(HoneyBatch.cluster),
                joinedload(HoneyPackage.batch)
                .joinedload(HoneyBatch.collection)
                .selectinload(HoneyCollection.sources),
                joinedload(HoneyPackage.packaging).joinedload(PackagingRun.unit_ref),
            )
            .where(HoneyPackage.id == package_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_code(self, code: str) -> HoneyPackage | None:
        return self.get_by(package_code=code)

    def code_exists(self, code: str) -> bool:
        return self.exists(package_code=code)

    def for_batch(self, batch_id: uuid.UUID) -> list[HoneyPackage]:
        statement = (
            select(HoneyPackage)
            .where(HoneyPackage.batch_id == batch_id)
            .order_by(HoneyPackage.sequence_number.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def for_packaging(self, packaging_id: uuid.UUID) -> list[HoneyPackage]:
        statement = (
            select(HoneyPackage)
            .where(HoneyPackage.packaging_id == packaging_id)
            .order_by(HoneyPackage.sequence_number.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: PackageStatus | None = None,
        statuses: list[PackageStatus] | None = None,
        batch_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
        packaging_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        packaging_unit_id: uuid.UUID | None = None,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> tuple[list[HoneyPackage], int]:
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(HoneyPackage.package_code).like(term),
                    func.lower(HoneyBatch.batch_code).like(term),
                )
            )
        if status is not None:
            filters.append(HoneyPackage.status == status)
        if statuses:
            filters.append(HoneyPackage.status.in_(statuses))
        if cluster_id is not None:
            filters.append(HoneyBatch.cluster_id == cluster_id)
        if beekeeper_id is not None:
            filters.append(HoneyBatch.beekeeper_id == beekeeper_id)
        if packaging_unit_id is not None:
            filters.append(
                HoneyPackage.packaging_id.in_(
                    select(PackagingRun.id).where(
                        PackagingRun.packaging_unit_id == packaging_unit_id
                    )
                )
            )
        if batch_id is not None:
            filters.append(HoneyPackage.batch_id == batch_id)
        if packaging_id is not None:
            filters.append(HoneyPackage.packaging_id == packaging_id)

        statement = (
            select(HoneyPackage)
            .join(HoneyBatch, HoneyPackage.batch_id == HoneyBatch.id)
            .options(
                joinedload(HoneyPackage.batch),
                joinedload(HoneyPackage.packaging).joinedload(PackagingRun.unit_ref),
            )
        )
        count_statement = (
            select(func.count())
            .select_from(HoneyPackage)
            .join(HoneyBatch, HoneyPackage.batch_id == HoneyBatch.id)
        )
        if filters:
            condition = and_(*filters)
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(HoneyPackage, order_by, HoneyPackage.created_at)
        # Every package of a run is written in one flush, so they share a
        # ``created_at`` to the microsecond: the primary column alone leaves the
        # order to the storage engine, which can change between queries and would
        # let a page boundary repeat or skip a package. The package's own number,
        # then its id, break the tie the same way every time.
        statement = statement.order_by(
            column.desc() if descending else column.asc(),
            HoneyPackage.sequence_number.desc(),
            HoneyPackage.id.asc(),
        )
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(statement).scalars().unique().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total

    def count_by_status(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        packaging_unit_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Packages per state, bounded by the same scope the package list uses."""
        statement = select(HoneyPackage.status, func.count()).select_from(HoneyPackage)
        if beekeeper_id is not None:
            statement = statement.join(HoneyBatch, HoneyPackage.batch_id == HoneyBatch.id).where(
                HoneyBatch.beekeeper_id == beekeeper_id
            )
        if packaging_unit_id is not None:
            statement = statement.where(
                HoneyPackage.packaging_id.in_(
                    select(PackagingRun.id).where(
                        PackagingRun.packaging_unit_id == packaging_unit_id
                    )
                )
            )
        statement = statement.group_by(HoneyPackage.status)
        return {
            str(status.value if hasattr(status, "value") else status): int(count)
            for status, count in self.session.execute(statement).all()
        }


def join_packaging_relations():
    """The eager loads every packaging payload needs, declared once.

    A packaging record is useless without the batch it packs and the person who
    packed it: ``batch_code``, the beekeeper and the cluster all come from the
    batch, and without the join they would serialise as ``None``.
    """
    return (
        joinedload(PackagingRun.batch).joinedload(HoneyBatch.collection),
        joinedload(PackagingRun.batch).joinedload(HoneyBatch.beekeeper),
        joinedload(PackagingRun.batch).joinedload(HoneyBatch.cluster),
        joinedload(PackagingRun.unit_ref),
        joinedload(PackagingRun.packaged_by),
    )


def approved_quantity_for_batch(session, batch_id: uuid.UUID) -> Decimal:
    """The honey an approved batch has available to pack.

    Read from the batch's *completed processing runs*, not from the collection:
    the collection is the harvest, the processing output is what actually exists
    as honey after the work, and that is the quantity the laboratory approved.
    Nothing is converted and nothing is assumed — the figures are the ones the
    processing record already stores.
    """
    statement = select(func.coalesce(func.sum(HoneyProcessing.output_quantity), 0)).where(
        HoneyProcessing.batch_id == batch_id,
        # Only a completed run produced honey. An open run's provisional output,
        # or a cancelled run's, is not honey anybody can pack.
        HoneyProcessing.status == ProcessingStatus.COMPLETED,
        HoneyProcessing.output_quantity.is_not(None),
    )
    return Decimal(session.execute(statement).scalar_one() or 0)


def approved_batch_statuses() -> tuple[BatchStatus, ...]:
    """The batch statuses a packaging run may be opened against.

    ``APPROVED`` (the laboratory decided), ``PACKAGING_READY`` (…and it has been
    released to the floor) and ``PACKAGED`` (a later run packs the remainder of a
    batch that has already been packed in part). Nothing else: a rejected batch may
    never be packed, a held or flagged one has an open question over it, and a
    batch still under testing has no verdict yet. The sealed-vocabulary answer a
    client sends cannot change any of that.
    """
    return PACKABLE_BATCH_STATUSES


#: Where a batch may be packed from. ``DISTRIBUTION`` is included because a batch
#: packed in part keeps its unpacked remainder after its first packages ship —
#: without it that remainder could never be packed and the batch never completed.
PACKABLE_BATCH_STATUSES: tuple[BatchStatus, ...] = (
    BatchStatus.APPROVED,
    BatchStatus.PACKAGING_READY,
    BatchStatus.PACKAGED,
    BatchStatus.DISTRIBUTION,
)

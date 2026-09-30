"""Data access for ``laboratories``, ``lab_parameters``, ``lab_tests`` and results."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.enums import AssignmentStatus, FacilityStatus, LabResult, LabTestStatus
from app.models.honey_batch import HoneyBatch
from app.models.honey_collection import HoneyCollection
from app.models.laboratory import LabParameter, Laboratory, LabTest, LabTestResult
from app.models.beekeeper import Beekeeper
from app.repositories.base import BaseRepository


class LaboratoryRepository(BaseRepository[Laboratory]):
    model = Laboratory

    def get_by_code(self, code: str) -> Laboratory | None:
        return self.get_by(laboratory_code=code)

    def code_exists(self, code: str) -> bool:
        return self.exists(laboratory_code=code)

    def active_facilities(self) -> list[Laboratory]:
        """The laboratories currently accepting work, in a stable order.

        On this repository rather than on the test repository: it is a query about
        laboratories, and this is where a reader looks for it.
        """
        statement = (
            select(Laboratory)
            .where(Laboratory.status == FacilityStatus.ACTIVE)
            .order_by(Laboratory.name.asc())
        )
        return list(self.session.execute(statement).scalars().all())

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
    ) -> tuple[list[Laboratory], int]:
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(Laboratory.laboratory_code).like(term),
                    func.lower(Laboratory.name).like(term),
                    func.lower(Laboratory.district).like(term),
                )
            )
        if status is not None:
            filters.append(Laboratory.status == status)
        if district:
            filters.append(Laboratory.district == district)

        statement = select(Laboratory)
        count_statement = select(func.count()).select_from(Laboratory)
        if filters:
            condition = and_(*filters)
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(Laboratory, order_by, Laboratory.name)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(statement).scalars().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total


class LabParameterRepository(BaseRepository[LabParameter]):
    model = LabParameter

    def get_by_code(self, code: str) -> LabParameter | None:
        return self.get_by(code=code)

    def all_parameters(self, *, active_only: bool = False) -> list[LabParameter]:
        statement = select(LabParameter)
        if active_only:
            statement = statement.where(LabParameter.is_active.is_(True))
        statement = statement.order_by(LabParameter.display_order.asc(), LabParameter.name.asc())
        return list(self.session.execute(statement).scalars().all())

    def required_parameters(self) -> list[LabParameter]:
        statement = (
            select(LabParameter)
            .where(LabParameter.is_active.is_(True), LabParameter.is_required.is_(True))
            .order_by(LabParameter.display_order.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def configured_count(self) -> int:
        statement = select(func.count()).select_from(LabParameter).where(
            or_(LabParameter.reference_min.is_not(None), LabParameter.reference_max.is_not(None))
        )
        return int(self.session.execute(statement).scalar_one())


class LabTestRepository(BaseRepository[LabTest]):
    model = LabTest

    def get_with_relations(self, test_id: uuid.UUID) -> LabTest | None:
        """One test with its results, its batch, its laboratory and its processing run."""
        statement = (
            select(LabTest)
            .options(
                selectinload(LabTest.results),
                joinedload(LabTest.assigned_technician),
                joinedload(LabTest.batch).joinedload(HoneyBatch.cluster),
                joinedload(LabTest.batch).joinedload(HoneyBatch.beekeeper),
                joinedload(LabTest.batch)
                .joinedload(HoneyBatch.collection)
                .selectinload(HoneyCollection.sources),
            )
            .where(LabTest.id == test_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_code(self, code: str) -> LabTest | None:
        return self.get_by(test_code=code)

    def code_exists(self, code: str) -> bool:
        return self.exists(test_code=code)

    def sample_code_exists(self, code: str) -> bool:
        return self.exists(sample_code=code)

    def for_batch(self, batch_id: uuid.UUID) -> list[LabTest]:
        """Every test of a batch, newest round first.

        Ordered by ``round_number`` rather than by ``created_at`` alone: two tests
        of one batch can be created within the same database transaction, where
        ``now()`` is identical for both, and a history whose order depends on a
        tie is not a history. The round is a stored, meaningful fact.
        """
        statement = (
            select(LabTest)
            .options(selectinload(LabTest.results))
            .where(LabTest.batch_id == batch_id)
            .order_by(LabTest.round_number.desc(), LabTest.created_at.desc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def latest_for_batch(self, batch_id: uuid.UUID) -> LabTest | None:
        statement = (
            select(LabTest)
            .options(selectinload(LabTest.results))
            .where(LabTest.batch_id == batch_id)
            .order_by(LabTest.round_number.desc(), LabTest.created_at.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalars().unique().first()

    def latest_by_batch(self, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, LabTest]:
        """The newest test of each batch, in one query.

        A page of batches must not cost one query per row, so the "latest round per
        batch" is asked for once. ``DISTINCT ON`` does exactly that on PostgreSQL;
        the tie-breakers match :meth:`latest_for_batch` so a single batch and a page
        never disagree about which test is the current one.
        """
        if not batch_ids:
            return {}
        statement = (
            select(LabTest)
            .where(LabTest.batch_id.in_(batch_ids))
            .order_by(
                LabTest.batch_id,
                LabTest.round_number.desc(),
                LabTest.created_at.desc(),
                LabTest.id.desc(),
            )
            .distinct(LabTest.batch_id)
        )
        rows = self.session.execute(statement).scalars().unique().all()
        return {row.batch_id: row for row in rows}

    def max_round(self, batch_id: uuid.UUID) -> int:
        statement = select(func.coalesce(func.max(LabTest.round_number), 0)).where(
            LabTest.batch_id == batch_id
        )
        return int(self.session.execute(statement).scalar_one())

    def result_for_parameter(
        self, test_id: uuid.UUID, parameter_code: str
    ) -> LabTestResult | None:
        statement = select(LabTestResult).where(
            LabTestResult.lab_test_id == test_id,
            LabTestResult.parameter_code == parameter_code,
        )
        return self.session.execute(statement).scalars().first()

    def results_for_test(self, test_id: uuid.UUID) -> list[LabTestResult]:
        statement = (
            select(LabTestResult)
            .where(LabTestResult.lab_test_id == test_id)
            .order_by(LabTestResult.created_at.asc(), LabTestResult.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: LabTestStatus | None = None,
        statuses: list[LabTestStatus] | None = None,
        overall_result: LabResult | None = None,
        batch_id: uuid.UUID | None = None,
        laboratory_id: uuid.UUID | None = None,
        technician_id: uuid.UUID | None = None,
        assigned_technician_id: uuid.UUID | None = None,
        assignment_status: AssignmentStatus | None = None,
        assignment_statuses: list[AssignmentStatus] | None = None,
        unassigned: bool | None = None,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
        date_from: date | None = None,
        date_to: date | None = None,
        order_by: str = "test_date",
        descending: bool = True,
    ) -> tuple[list[LabTest], int]:
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(LabTest.test_code).like(term),
                    func.lower(LabTest.sample_code).like(term),
                    func.lower(HoneyBatch.batch_code).like(term),
                )
            )
        if status is not None:
            filters.append(LabTest.status == status)
        if statuses is not None:
            filters.append(LabTest.status.in_(statuses))
        if overall_result is not None:
            filters.append(LabTest.overall_result == overall_result)
        if batch_id is not None:
            filters.append(LabTest.batch_id == batch_id)
        if laboratory_id is not None:
            filters.append(LabTest.laboratory_id == laboratory_id)
        if technician_id is not None:
            filters.append(LabTest.technician_id == technician_id)
        if assigned_technician_id is not None:
            filters.append(LabTest.assigned_technician_id == assigned_technician_id)
        if assignment_status is not None:
            filters.append(LabTest.assignment_status == assignment_status)
        if assignment_statuses is not None:
            filters.append(LabTest.assignment_status.in_(assignment_statuses))
        if unassigned is not None:
            filters.append(
                LabTest.assigned_technician_id.is_(None)
                if unassigned
                else LabTest.assigned_technician_id.is_not(None)
            )
        if beekeeper_id is not None:
            filters.append(HoneyBatch.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            filters.append(HoneyBatch.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            filters.append(HoneyBatch.cluster_id == cluster_id)
        if cluster_ids is not None:
            # An officer's list carries the records whose batch names no cluster as
            # well: they are the rows that need attention, and hiding them is how a
            # missing relationship stays missing.
            filters.append(
                or_(HoneyBatch.cluster_id.in_(cluster_ids), HoneyBatch.cluster_id.is_(None))
                if include_unclustered
                else HoneyBatch.cluster_id.in_(cluster_ids)
            )
        if date_from is not None:
            filters.append(LabTest.test_date >= date_from)
        if date_to is not None:
            filters.append(LabTest.test_date <= date_to)

        statement = (
            select(LabTest)
            .join(HoneyBatch, HoneyBatch.id == LabTest.batch_id)
            .options(
                selectinload(LabTest.results),
                joinedload(LabTest.assigned_technician),
                joinedload(LabTest.batch).joinedload(HoneyBatch.cluster),
                # The beekeeper's *account holder* is read for the name shown on a
                # row, so it is loaded here rather than lazily per row.
                joinedload(LabTest.batch)
                .joinedload(HoneyBatch.beekeeper)
                .joinedload(Beekeeper.user),
            )
        )
        count_statement = (
            select(func.count())
            .select_from(LabTest)
            .join(HoneyBatch, HoneyBatch.id == LabTest.batch_id)
        )
        if filters:
            condition = and_(*filters)
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(LabTest, order_by, LabTest.test_date)
        # ``test_date`` is a date, so several tests of one batch share it: the
        # round and the creation time are added as tiebreaks, because a listing
        # whose order depends on a tie is not a listing anyone can rely on.
        if descending:
            statement = statement.order_by(
                column.desc(), LabTest.round_number.desc(), LabTest.created_at.desc()
            )
        else:
            statement = statement.order_by(
                column.asc(), LabTest.round_number.asc(), LabTest.created_at.asc()
            )
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(statement).scalars().unique().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total

    def count_by_assignment(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
    ) -> dict[str, int]:
        """The laboratory's queues: unallocated, allocated, accepted, done.

        ``unassigned`` is what nobody is responsible for yet — it stays visible on
        the pending screen, which is the point: a sample must never disappear from
        the laboratory just because no name has been attached to it.
        """
        filters = []
        if beekeeper_id is not None:
            filters.append(HoneyBatch.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            filters.append(HoneyBatch.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            filters.append(HoneyBatch.cluster_id == cluster_id)
        if cluster_ids is not None:
            # An officer's list carries the records whose batch names no cluster as
            # well: they are the rows that need attention, and hiding them is how a
            # missing relationship stays missing.
            filters.append(
                or_(HoneyBatch.cluster_id.in_(cluster_ids), HoneyBatch.cluster_id.is_(None))
                if include_unclustered
                else HoneyBatch.cluster_id.in_(cluster_ids)
            )

        def _count(*conditions):
            statement = (
                select(func.count())
                .select_from(LabTest)
                .join(HoneyBatch, HoneyBatch.id == LabTest.batch_id)
                .where(*conditions)
            )
            if filters:
                statement = statement.where(and_(*filters))
            return int(self.session.execute(statement).scalar_one())

        open_statuses = LabTestStatus.open_statuses()
        return {
            "total": _count(),
            "unassigned": _count(
                LabTest.assigned_technician_id.is_(None),
                LabTest.status.in_(open_statuses),
            ),
            "assigned": _count(
                LabTest.assignment_status == AssignmentStatus.ASSIGNED,
                LabTest.status.in_(open_statuses),
            ),
            "accepted": _count(
                LabTest.assignment_status == AssignmentStatus.ACCEPTED,
                LabTest.status.in_(open_statuses),
            ),
            "unaccepted": _count(
                LabTest.assignment_status == AssignmentStatus.ASSIGNED,
            ),
            "completed": _count(LabTest.status == LabTestStatus.COMPLETED),
        }

    def open_counts_by_technician(self) -> dict[uuid.UUID, int]:
        """Open tests per technician, so allocation can see who is already busy.

        One grouped query rather than a count per person: the allocation dialog
        asks about every eligible technician at once.
        """
        statement = (
            select(LabTest.assigned_technician_id, func.count())
            .where(
                LabTest.assigned_technician_id.is_not(None),
                LabTest.status.in_(LabTestStatus.open_statuses()),
            )
            .group_by(LabTest.assigned_technician_id)
        )
        return {
            technician_id: int(count)
            for technician_id, count in self.session.execute(statement).all()
        }

    def count_by_status_and_result(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
    ) -> tuple[dict[str, int], dict[str, int]]:
        base = (
            select(LabTest)
            .join(HoneyBatch, HoneyBatch.id == LabTest.batch_id)
        )
        if beekeeper_id is not None:
            base = base.where(HoneyBatch.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            base = base.where(HoneyBatch.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            base = base.where(HoneyBatch.cluster_id == cluster_id)
        if cluster_ids is not None:
            base = base.where(HoneyBatch.cluster_id.in_(cluster_ids))

        by_status = {status.value: 0 for status in LabTestStatus}
        status_rows = self.session.execute(
            base.with_only_columns(LabTest.status, func.count()).group_by(LabTest.status)
        ).all()
        for status, count in status_rows:
            by_status[str(getattr(status, "value", status))] = int(count)

        by_result = {result.value: 0 for result in LabResult}
        result_rows = self.session.execute(
            base.with_only_columns(LabTest.overall_result, func.count()).group_by(
                LabTest.overall_result
            )
        ).all()
        for result, count in result_rows:
            by_result[str(getattr(result, "value", result))] = int(count)

        return by_status, by_result

    def sample_totals(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
    ) -> dict[str, Decimal]:
        aggregate = (
            select(LabTest.sample_unit, func.coalesce(func.sum(LabTest.sample_quantity), 0))
            .select_from(LabTest)
            .join(HoneyBatch, HoneyBatch.id == LabTest.batch_id)
            .group_by(LabTest.sample_unit)
        )
        if beekeeper_id is not None:
            aggregate = aggregate.where(HoneyBatch.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            aggregate = aggregate.where(HoneyBatch.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            aggregate = aggregate.where(HoneyBatch.cluster_id == cluster_id)
        if cluster_ids is not None:
            aggregate = aggregate.where(HoneyBatch.cluster_id.in_(cluster_ids))

        totals: dict[str, Decimal] = {}
        for unit, value in self.session.execute(aggregate).all():
            totals[str(getattr(unit, "value", unit))] = Decimal(value or 0)
        return totals

    def count_overrides(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
    ) -> int:
        """How many tests carry an outcome set by hand — reported, never hidden."""
        statement = (
            select(func.count())
            .select_from(LabTest)
            .join(HoneyBatch, HoneyBatch.id == LabTest.batch_id)
            .where(LabTest.is_override.is_(True))
        )
        if beekeeper_id is not None:
            statement = statement.where(HoneyBatch.beekeeper_id == beekeeper_id)
        if beekeeper_ids is not None:
            statement = statement.where(HoneyBatch.beekeeper_id.in_(beekeeper_ids))
        if cluster_id is not None:
            statement = statement.where(HoneyBatch.cluster_id == cluster_id)
        if cluster_ids is not None:
            statement = statement.where(
                or_(HoneyBatch.cluster_id.in_(cluster_ids), HoneyBatch.cluster_id.is_(None))
                if include_unclustered
                else HoneyBatch.cluster_id.in_(cluster_ids)
            )
        return int(self.session.execute(statement).scalar_one())

__all__ = [
    "LaboratoryRepository",
    "LabParameterRepository",
    "LabTestRepository",
]

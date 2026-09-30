"""Data access for ``processing_units`` and ``honey_processing_records``."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.enums import AssignmentStatus, ProcessingStatus
from app.models.honey_batch import HoneyBatch
from app.models.processing import HoneyProcessing, ProcessingUnit
from app.repositories.base import BaseRepository


class ProcessingUnitRepository(BaseRepository[ProcessingUnit]):
    model = ProcessingUnit

    def get_by_code(self, code: str) -> ProcessingUnit | None:
        return self.get_by(unit_code=code)

    def code_exists(self, code: str) -> bool:
        return self.exists(unit_code=code)

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
    ) -> tuple[list[ProcessingUnit], int]:
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(ProcessingUnit.unit_code).like(term),
                    func.lower(ProcessingUnit.name).like(term),
                    func.lower(ProcessingUnit.district).like(term),
                )
            )
        if status is not None:
            filters.append(ProcessingUnit.status == status)
        if district:
            filters.append(ProcessingUnit.district == district)

        statement = select(ProcessingUnit)
        count_statement = select(func.count()).select_from(ProcessingUnit)
        if filters:
            condition = and_(*filters)
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(ProcessingUnit, order_by, ProcessingUnit.name)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(statement).scalars().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total


class ProcessingRepository(BaseRepository[HoneyProcessing]):
    model = HoneyProcessing

    def get_with_relations(self, processing_id: uuid.UUID) -> HoneyProcessing | None:
        """One run with its batch (and that batch's collection), unit and operator."""
        statement = (
            select(HoneyProcessing)
            .options(
                joinedload(HoneyProcessing.unit_ref),
                joinedload(HoneyProcessing.processor),
                joinedload(HoneyProcessing.batch).joinedload(HoneyBatch.cluster),
                joinedload(HoneyProcessing.batch).joinedload(HoneyBatch.beekeeper),
            )
            .where(HoneyProcessing.id == processing_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_code(self, code: str) -> HoneyProcessing | None:
        return self.get_by(processing_code=code)

    def code_exists(self, code: str) -> bool:
        return self.exists(processing_code=code)

    def open_for_batch(self, batch_id: uuid.UUID) -> HoneyProcessing | None:
        """The run under way for a batch, if there is one.

        Mirrors the partial unique index in the database, so the service can give
        a helpful answer where the constraint would give an IntegrityError.
        """
        statement = (
            select(HoneyProcessing)
            .where(
                HoneyProcessing.batch_id == batch_id,
                HoneyProcessing.status.in_(ProcessingStatus.open_statuses()),
            )
            .order_by(HoneyProcessing.created_at.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalars().first()

    def open_counts_by_processor(self) -> dict[uuid.UUID, int]:
        """Open runs per processor, so a dispatcher can see who is already busy.

        One grouped query rather than a count per person: the assignment dialog
        asks about every eligible account at once, and N queries for N people is
        how a dropdown becomes slow.
        """
        statement = (
            select(HoneyProcessing.processor_id, func.count())
            .where(
                HoneyProcessing.processor_id.is_not(None),
                HoneyProcessing.status.in_(ProcessingStatus.open_statuses()),
            )
            .group_by(HoneyProcessing.processor_id)
        )
        return {
            processor_id: int(count)
            for processor_id, count in self.session.execute(statement).all()
        }

    def for_batch(self, batch_id: uuid.UUID) -> list[HoneyProcessing]:
        """Every run recorded against a batch, newest first — history included."""
        statement = (
            select(HoneyProcessing)
            .options(joinedload(HoneyProcessing.unit_ref))
            .where(HoneyProcessing.batch_id == batch_id)
            .order_by(HoneyProcessing.created_at.desc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: ProcessingStatus | None = None,
        statuses: list[ProcessingStatus] | None = None,
        batch_id: uuid.UUID | None = None,
        processing_unit_id: uuid.UUID | None = None,
        operator_id: uuid.UUID | None = None,
        processor_id: uuid.UUID | None = None,
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
        order_by: str = "processing_date",
        descending: bool = True,
    ) -> tuple[list[HoneyProcessing], int]:
        """Filtered, paginated runs.

        The scope filters (beekeeper / cluster) are applied to the *batch* the run
        belongs to, which is what makes a KVIC officer see exactly the work done on
        their cluster's honey and nothing else. No processing row is duplicated for
        them; the same row is filtered.
        """
        filters = []
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(HoneyProcessing.processing_code).like(term),
                    func.lower(HoneyBatch.batch_code).like(term),
                )
            )
        if status is not None:
            filters.append(HoneyProcessing.status == status)
        if statuses is not None:
            filters.append(HoneyProcessing.status.in_(statuses))
        if batch_id is not None:
            filters.append(HoneyProcessing.batch_id == batch_id)
        if processing_unit_id is not None:
            filters.append(HoneyProcessing.processing_unit_id == processing_unit_id)
        if operator_id is not None:
            filters.append(HoneyProcessing.operator_id == operator_id)
        if processor_id is not None:
            filters.append(HoneyProcessing.processor_id == processor_id)
        if assignment_status is not None:
            filters.append(HoneyProcessing.assignment_status == assignment_status)
        if assignment_statuses is not None:
            filters.append(HoneyProcessing.assignment_status.in_(assignment_statuses))
        if unassigned is not None:
            # No named processor: the work is still in the shared queue.
            filters.append(
                HoneyProcessing.processor_id.is_(None)
                if unassigned
                else HoneyProcessing.processor_id.is_not(None)
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
            filters.append(HoneyProcessing.processing_date >= date_from)
        if date_to is not None:
            filters.append(HoneyProcessing.processing_date <= date_to)

        statement = (
            select(HoneyProcessing)
            .join(HoneyBatch, HoneyBatch.id == HoneyProcessing.batch_id)
            .options(
                joinedload(HoneyProcessing.unit_ref),
                joinedload(HoneyProcessing.batch).joinedload(HoneyBatch.cluster),
                joinedload(HoneyProcessing.batch).joinedload(HoneyBatch.beekeeper),
            )
        )
        count_statement = (
            select(func.count())
            .select_from(HoneyProcessing)
            .join(HoneyBatch, HoneyBatch.id == HoneyProcessing.batch_id)
        )
        if filters:
            condition = and_(*filters)
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(HoneyProcessing, order_by, HoneyProcessing.processing_date)
        # The date alone ties for several runs on the same day; the code is the
        # stored, monotonic tiebreak.
        if descending:
            statement = statement.order_by(column.desc(), HoneyProcessing.created_at.desc(), HoneyProcessing.processing_code.desc())
        else:
            statement = statement.order_by(column.asc(), HoneyProcessing.created_at.asc(), HoneyProcessing.processing_code.asc())
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
        """How many *open* runs sit in each queue the processor screens show.

        ``unassigned`` is the shared pending queue, ``assigned`` is work allocated
        to somebody (not yet accepted), ``accepted`` is work taken on, and
        ``unaccepted`` is the processor's own to-do list: allocated to them and
        not yet started. Scope filters apply to the batch, exactly as they do in
        :meth:`search`, so a KVIC officer gets their own cluster's numbers.
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
                .select_from(HoneyProcessing)
                .join(HoneyBatch, HoneyBatch.id == HoneyProcessing.batch_id)
                .where(*conditions)
            )
            if filters:
                statement = statement.where(and_(*filters))
            return int(self.session.execute(statement).scalar_one())

        open_statuses = ProcessingStatus.open_statuses()
        return {
            "total": _count(),
            "unassigned": _count(
                HoneyProcessing.processor_id.is_(None),
                HoneyProcessing.status.in_(open_statuses),
            ),
            "assigned": _count(
                HoneyProcessing.assignment_status == AssignmentStatus.ASSIGNED,
                HoneyProcessing.status.in_(open_statuses),
            ),
            "accepted": _count(
                HoneyProcessing.assignment_status == AssignmentStatus.ACCEPTED,
                HoneyProcessing.status.in_(open_statuses),
            ),
            "unaccepted": _count(
                HoneyProcessing.assignment_status == AssignmentStatus.ASSIGNED,
            ),
        }

    def count_by_status(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        beekeeper_ids: list[uuid.UUID] | None = None,
        cluster_id: uuid.UUID | None = None,
        cluster_ids: list[uuid.UUID] | None = None,
        include_unclustered: bool = False,
    ) -> dict[str, int]:
        statement = (
            select(HoneyProcessing.status, func.count())
            .select_from(HoneyProcessing)
            .join(HoneyBatch, HoneyBatch.id == HoneyProcessing.batch_id)
            .group_by(HoneyProcessing.status)
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

        counts = {status.value: 0 for status in ProcessingStatus}
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
        completed_only: bool = True,
    ) -> dict[str, dict[str, float]]:
        """Input, output and loss per unit — only from runs that recorded figures."""
        statement = (
            select(
                HoneyProcessing.unit,
                func.coalesce(func.sum(HoneyProcessing.input_quantity), 0),
                func.coalesce(func.sum(HoneyProcessing.output_quantity), 0),
                func.coalesce(func.sum(HoneyProcessing.loss_quantity), 0),
            )
            .select_from(HoneyProcessing)
            .join(HoneyBatch, HoneyBatch.id == HoneyProcessing.batch_id)
            .group_by(HoneyProcessing.unit)
        )
        if completed_only:
            statement = statement.where(HoneyProcessing.status == ProcessingStatus.COMPLETED)
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

        totals: dict[str, dict[str, float]] = {}
        for unit, input_value, output_value, loss_value in self.session.execute(statement).all():
            totals[str(getattr(unit, "value", unit))] = {
                "input": float(input_value or 0),
                "output": float(output_value or 0),
                "loss": float(loss_value or 0),
            }
        return totals


__all__ = ["ProcessingRepository", "ProcessingUnitRepository"]

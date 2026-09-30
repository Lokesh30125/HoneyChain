"""Data access for ``hives`` — filtered listings, ownership scoping and counts."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.beekeeper import Beekeeper
from app.models.hive import Hive
from app.models.iot_device import IotDevice
from app.models.enums import ColonyStrength, HiveStatus
from app.repositories.base import BaseRepository


class HiveRepository(BaseRepository[Hive]):
    model = Hive

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_with_relations(self, hive_id: uuid.UUID) -> Hive | None:
        """Fetch a hive with the beekeeper, its user and cluster loaded.

        The detail screen needs the owner's name and the cluster code, and the
        IoT panel needs the attached devices, so all three are loaded eagerly
        rather than lazily during serialisation.
        """
        statement = (
            select(Hive)
            .options(
                joinedload(Hive.beekeeper).joinedload(Beekeeper.user),
                joinedload(Hive.cluster),
                selectinload(Hive.devices),
            )
            .where(Hive.id == hive_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def code_exists(self, code: str) -> bool:
        return self.exists(hive_code=code)

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: HiveStatus | None = None,
        beekeeper_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
        district: str | None = None,
        state: str | None = None,
        bee_species: str | None = None,
        colony_strength: ColonyStrength | None = None,
        has_device: bool | None = None,
        has_cluster: bool | None = None,
        include_removed: bool = False,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> tuple[list[Hive], int]:
        """Filtered, paginated directory query.

        ``beekeeper_id`` is how a beekeeper's own listing is scoped: the service
        resolves the caller's beekeeper record and passes its id here, so no
        request parameter can widen the result set.
        """
        filters = []

        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(Hive.hive_code).like(term),
                    func.lower(Hive.village).like(term),
                    func.lower(Hive.district).like(term),
                )
            )
        if status is not None:
            filters.append(Hive.status == status)
        if beekeeper_id is not None:
            filters.append(Hive.beekeeper_id == beekeeper_id)
        if cluster_id is not None:
            filters.append(Hive.cluster_id == cluster_id)
        if district:
            filters.append(func.lower(Hive.district) == district.strip().lower())
        if state:
            filters.append(func.lower(Hive.state) == state.strip().lower())
        if bee_species:
            filters.append(func.lower(Hive.bee_species) == bee_species.strip().lower())
        if colony_strength is not None:
            filters.append(Hive.colony_strength == colony_strength)
        if not include_removed:
            # REMOVED hives stay in the database for the audit trail but are out
            # of the working registry unless explicitly asked for.
            filters.append(Hive.status != HiveStatus.REMOVED)
        if has_device is not None:
            paired = select(IotDevice.id).where(IotDevice.hive_id == Hive.id).exists()
            filters.append(paired if has_device else ~paired)
        if has_cluster is not None:
            # ``has_cluster=False`` is the administrative worklist: hives whose
            # owner has no cluster yet, so nothing about them is visible to a
            # cluster view. They are listed, never silently assigned.
            filters.append(
                Hive.cluster_id.isnot(None) if has_cluster else Hive.cluster_id.is_(None)
            )

        base = select(Hive).options(joinedload(Hive.cluster), selectinload(Hive.devices))
        count_statement = select(func.count()).select_from(Hive)
        if filters:
            condition = and_(*filters)
            base = base.where(condition)
            count_statement = count_statement.where(condition)

        column = getattr(Hive, order_by, Hive.created_at)
        base = base.order_by(column.desc() if descending else column.asc())
        base = base.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(base).scalars().unique().all())
        total = int(self.session.execute(count_statement).scalar_one())
        return rows, total

    def list_for_beekeeper(self, beekeeper_id: uuid.UUID) -> list[Hive]:
        """Every hive owned by one beekeeper (used by the IoT dashboard)."""
        statement = (
            select(Hive)
            .options(selectinload(Hive.devices))
            .where(Hive.beekeeper_id == beekeeper_id)
            .order_by(Hive.hive_code.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    def ids_for_beekeeper(self, beekeeper_id: uuid.UUID) -> list[uuid.UUID]:
        statement = select(Hive.id).where(Hive.beekeeper_id == beekeeper_id)
        return [row[0] for row in self.session.execute(statement).all()]

    def ids_for_cluster(self, cluster_id: uuid.UUID) -> list[uuid.UUID]:
        """Every hive in one cluster — the scope for its devices, telemetry and AI.

        This is the single place a cluster's hive set is resolved: the cluster
        view, its counters and its AI summary all read from here, so there is no
        second definition of "which hives belong to cluster X".
        """
        statement = select(Hive.id).where(Hive.cluster_id == cluster_id)
        return [row[0] for row in self.session.execute(statement).all()]

    def list_for_cluster(self, cluster_id: uuid.UUID) -> list[Hive]:
        statement = (
            select(Hive)
            .options(joinedload(Hive.cluster), selectinload(Hive.devices))
            .where(Hive.cluster_id == cluster_id)
            .order_by(Hive.hive_code.asc())
        )
        return list(self.session.execute(statement).scalars().unique().all())

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #
    def count_by_status(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        statement = select(Hive.status, func.count()).group_by(Hive.status)
        if cluster_id is not None:
            statement = statement.where(Hive.cluster_id == cluster_id)
        if beekeeper_id is not None:
            statement = statement.where(Hive.beekeeper_id == beekeeper_id)
        rows = self.session.execute(statement).all()
        counts = {status.value: 0 for status in HiveStatus}
        for status, count in rows:
            counts[str(getattr(status, "value", status))] = int(count)
        return counts

    def count_all(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
    ) -> int:
        statement = select(func.count()).select_from(Hive)
        if cluster_id is not None:
            statement = statement.where(Hive.cluster_id == cluster_id)
        if beekeeper_id is not None:
            statement = statement.where(Hive.beekeeper_id == beekeeper_id)
        return int(self.session.execute(statement).scalar_one())

    def count_without_cluster(self) -> int:
        """Hives whose owner has no cluster — the outstanding administrative work."""
        statement = select(func.count()).select_from(Hive).where(Hive.cluster_id.is_(None))
        return int(self.session.execute(statement).scalar_one())

    # ------------------------------------------------------------------ #
    # Organisational writes
    # ------------------------------------------------------------------ #
    def set_cluster(self, hive: Hive, cluster_id: uuid.UUID | None) -> Hive:
        """Point one hive at a cluster (or at nothing). The only such write."""
        hive.cluster_id = cluster_id
        self.session.add(hive)
        self.session.flush()
        return hive

    def set_cluster_for_beekeeper(
        self,
        beekeeper_id: uuid.UUID,
        cluster_id: uuid.UUID | None,
        *,
        previous_cluster_id: uuid.UUID | None = None,
    ) -> list[str]:
        """Move a beekeeper's hives with them, returning the hive codes moved.

        A hive's cluster is *inherited* from its owner rather than chosen, so when
        the owner's membership changes the hives follow. Only hives that were
        still following the beekeeper are touched: a hive explicitly placed in
        another cluster by staff keeps that placement, which is why
        ``previous_cluster_id`` is compared rather than blindly overwritten.
        """
        statement = select(Hive).where(Hive.beekeeper_id == beekeeper_id)
        if previous_cluster_id is not None:
            statement = statement.where(Hive.cluster_id == previous_cluster_id)
        else:
            statement = statement.where(Hive.cluster_id.is_(None))
        moved: list[str] = []
        for hive in self.session.execute(statement).scalars().all():
            hive.cluster_id = cluster_id
            self.session.add(hive)
            moved.append(hive.hive_code)
        if moved:
            self.session.flush()
        return sorted(moved)

    def device_counts(
        self,
        *,
        beekeeper_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """How many hives have at least one device, and how many have none."""
        from sqlalchemy import distinct

        statement = select(func.count(distinct(IotDevice.hive_id)))
        hive_count = select(func.count()).select_from(Hive)
        if cluster_id is not None:
            statement = statement.join(Hive, IotDevice.hive_id == Hive.id).where(
                Hive.cluster_id == cluster_id
            )
            hive_count = hive_count.where(Hive.cluster_id == cluster_id)
        if beekeeper_id is not None:
            statement = statement.where(IotDevice.beekeeper_id == beekeeper_id)
            hive_count = hive_count.where(Hive.beekeeper_id == beekeeper_id)
        with_device = int(self.session.execute(statement).scalar_one())
        total = int(self.session.execute(hive_count).scalar_one())
        return {"total": total, "with_device": with_device, "without_device": max(total - with_device, 0)}

    def distinct_districts(self) -> list[str]:
        statement = (
            select(Hive.district)
            .where(Hive.district.is_not(None))
            .distinct()
            .order_by(Hive.district)
        )
        return [row[0] for row in self.session.execute(statement).all()]

    def distinct_bee_species(self) -> list[str]:
        statement = (
            select(Hive.bee_species)
            .where(Hive.bee_species.is_not(None))
            .distinct()
            .order_by(Hive.bee_species)
        )
        return [row[0] for row in self.session.execute(statement).all()]


__all__ = ["HiveRepository"]

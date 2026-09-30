"""Data access for ``kvic_clusters``."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.models.kvic_cluster import KvicCluster
from app.repositories.base import BaseRepository


class ClusterRepository(BaseRepository[KvicCluster]):
    model = KvicCluster

    def get_with_beekeepers(self, cluster_id: uuid.UUID) -> KvicCluster | None:
        statement = (
            select(KvicCluster)
            .options(joinedload(KvicCluster.beekeepers))
            .where(KvicCluster.id == cluster_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_code(self, code: str) -> KvicCluster | None:
        return self.get_by(cluster_code=code.strip().upper())

    def code_exists(self, code: str) -> bool:
        return self.exists(cluster_code=code.strip().upper())

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        district: str | None = None,
        state: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[KvicCluster], int]:
        filters = []
        if district:
            filters.append(func.lower(KvicCluster.district) == district.strip().lower())
        if state:
            filters.append(func.lower(KvicCluster.state) == state.strip().lower())
        if is_active is not None:
            filters.append(KvicCluster.is_active.is_(is_active))
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(KvicCluster.cluster_name).like(term),
                    func.lower(KvicCluster.cluster_code).like(term),
                    func.lower(KvicCluster.coordinator_name).like(term),
                )
            )

        query = select(KvicCluster)
        count_query = select(func.count()).select_from(KvicCluster)
        if filters:
            from sqlalchemy import and_

            combined = and_(*filters)
            query = query.where(combined)
            count_query = count_query.where(combined)

        total = int(self.session.execute(count_query).scalar_one())
        query = (
            query.order_by(KvicCluster.created_at.desc(), KvicCluster.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.session.execute(query).scalars().all()), total

    def distinct_districts(self) -> list[str]:
        statement = (
            select(KvicCluster.district).distinct().order_by(KvicCluster.district)
        )
        return [row for row in self.session.execute(statement).scalars().all() if row]

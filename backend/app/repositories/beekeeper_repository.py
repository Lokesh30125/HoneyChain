"""Data access for ``beekeepers`` — including filtered, paginated listings."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from app.models.beekeeper import Beekeeper
from app.models.enums import VerificationStatus
from app.models.user import User
from app.repositories.base import BaseRepository


class BeekeeperRepository(BaseRepository[Beekeeper]):
    model = Beekeeper

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_with_user(self, beekeeper_id: uuid.UUID) -> Beekeeper | None:
        """Fetch a beekeeper with its user and cluster eagerly loaded.

        Serialising a beekeeper needs ``user`` (name, email) and ``cluster``
        (name, code); loading them up front avoids N+1 queries when listing.
        """
        statement = (
            select(Beekeeper)
            .options(joinedload(Beekeeper.user), joinedload(Beekeeper.cluster))
            .where(Beekeeper.id == beekeeper_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def get_by_user_id(self, user_id: uuid.UUID) -> Beekeeper | None:
        statement = (
            select(Beekeeper)
            .options(joinedload(Beekeeper.user), joinedload(Beekeeper.cluster))
            .where(Beekeeper.user_id == user_id)
        )
        return self.session.execute(statement).scalars().unique().first()

    def code_exists(self, code: str) -> bool:
        return self.exists(beekeeper_code=code)

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        district: str | None = None,
        state: str | None = None,
        cluster_id: uuid.UUID | None = None,
        verification_status: VerificationStatus | None = None,
        bee_species: str | None = None,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> tuple[list[Beekeeper], int]:
        """Return ``(rows, total_count)`` for a filtered directory listing.

        Search matches the beekeeper code, the user's name and the user's email,
        so an officer can find a record from whichever identifier they have.
        """
        filters = []
        if district:
            filters.append(func.lower(Beekeeper.district) == district.strip().lower())
        if state:
            filters.append(func.lower(Beekeeper.state) == state.strip().lower())
        if cluster_id:
            filters.append(Beekeeper.kvic_cluster_id == cluster_id)
        if verification_status:
            filters.append(Beekeeper.verification_status == verification_status)
        if bee_species:
            filters.append(func.lower(Beekeeper.bee_species) == bee_species.strip().lower())

        query = select(Beekeeper).options(joinedload(Beekeeper.user), joinedload(Beekeeper.cluster))
        count_query = select(func.count()).select_from(Beekeeper).join(
            User, Beekeeper.user_id == User.id
        )

        if search:
            term = f"%{search.strip().lower()}%"
            condition = or_(
                func.lower(Beekeeper.beekeeper_code).like(term),
                func.lower(User.name).like(term),
                func.lower(User.email).like(term),
            )
            filters.append(condition)

        if filters:
            combined = and_(*filters)
            query = query.join(User, Beekeeper.user_id == User.id).where(combined)
            count_query = count_query.where(combined)

        total = int(self.session.execute(count_query).scalar_one())

        column = getattr(Beekeeper, order_by, Beekeeper.created_at)
        query = query.order_by(column.desc() if descending else column.asc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        rows = list(self.session.execute(query).scalars().unique().all())
        return rows, total

    def list_by_cluster(
        self, cluster_id: uuid.UUID, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[Beekeeper], int]:
        return self.search(page=page, page_size=page_size, cluster_id=cluster_id)

    def ids_in_clusters(self, cluster_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        """Every beekeeper id inside a set of clusters.

        The set of beekeeper ids *is* the scope of a cluster officer's harvest
        read: a collection is scoped to the beekeeper who recorded it, so bounding
        the beekeepers bounds the collections. Phase 4.1 made the same choice for
        hives, and the rule stays in one place.
        """
        if not cluster_ids:
            return []
        statement = (
            select(Beekeeper.id)
            .where(Beekeeper.kvic_cluster_id.in_(cluster_ids))
            .order_by(Beekeeper.beekeeper_code.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    # ------------------------------------------------------------------ #
    # Aggregates (used for lightweight, database-backed counts)
    # ------------------------------------------------------------------ #
    def count_by_verification_status(self) -> dict[str, int]:
        statement = select(Beekeeper.verification_status, func.count(Beekeeper.id)).group_by(
            Beekeeper.verification_status
        )
        return {
            str(status.value if isinstance(status, VerificationStatus) else status): int(total)
            for status, total in self.session.execute(statement).all()
        }

    def count_by_district(self, *, limit: int = 10) -> list[tuple[str | None, int]]:
        statement = (
            select(Beekeeper.district, func.count(Beekeeper.id))
            .group_by(Beekeeper.district)
            .order_by(func.count(Beekeeper.id).desc())
            .limit(limit)
        )
        return [(district, int(total)) for district, total in self.session.execute(statement).all()]

    def count_by_cluster(self) -> dict[str, int]:
        """Member counts keyed by cluster UUID (excludes unassigned)."""
        statement = (
            select(Beekeeper.kvic_cluster_id, func.count(Beekeeper.id))
            .where(Beekeeper.kvic_cluster_id.is_not(None))
            .group_by(Beekeeper.kvic_cluster_id)
        )
        return {str(cluster_id): int(total) for cluster_id, total in self.session.execute(statement).all()}

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def assign_cluster(self, beekeeper: Beekeeper, cluster_id: uuid.UUID | None) -> Beekeeper:
        return self.update(beekeeper, kvic_cluster_id=cluster_id)

    def distinct_districts(self) -> list[str]:
        statement = (
            select(Beekeeper.district)
            .where(Beekeeper.district.is_not(None))
            .distinct()
            .order_by(Beekeeper.district)
        )
        return [row for row in self.session.execute(statement).scalars().all() if row]

    def distinct_states(self) -> list[str]:
        statement = (
            select(Beekeeper.state)
            .where(Beekeeper.state.is_not(None))
            .distinct()
            .order_by(Beekeeper.state)
        )
        return [row for row in self.session.execute(statement).scalars().all() if row]

    def set_registration_date(self, beekeeper: Beekeeper, value: date) -> Beekeeper:
        return self.update(beekeeper, registration_date=value)


__all__ = ["BeekeeperRepository"]

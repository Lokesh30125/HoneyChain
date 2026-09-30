"""Generic repository — the only layer permitted to build SQLAlchemy queries.

Services depend on repositories rather than on ``Session`` query building, so a
future storage change (read replica, per-cluster sharding, caching) stays
contained in one place.

Equality filters are always passed through SQLAlchemy's parameter binding, so
no user input is ever interpolated into SQL text.
"""

from __future__ import annotations

from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Thin, explicit data-access helper for a single model."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, entity_id: Any) -> ModelT | None:
        """Fetch by primary key."""
        return self.session.get(self.model, entity_id)

    def get_by(self, **filters: Any) -> ModelT | None:
        """Fetch the first row matching every supplied equality filter."""
        statement = self._where(select(self.model), filters).limit(1)
        return self.session.execute(statement).scalars().first()

    def list(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
        **filters: Any,
    ) -> Sequence[ModelT]:
        """Return rows matching the filters, optionally ordered and paged."""
        statement = self._where(select(self.model), filters)
        if order_by:
            column = self._column(order_by)
            statement = statement.order_by(column.desc() if descending else column.asc())
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        return self.session.execute(statement).scalars().all()

    def count(self, **filters: Any) -> int:
        """Count rows matching the filters (used for pagination metadata)."""
        statement = self._where(select(func.count()).select_from(self.model), filters)
        return int(self.session.execute(statement).scalar_one())

    def exists(self, **filters: Any) -> bool:
        statement = self._where(select(self.model), filters).limit(1)
        return self.session.execute(statement).scalars().first() is not None

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def create(self, **values: Any) -> ModelT:
        """Insert a row and flush so database defaults/PKs are populated."""
        instance = self.model(**values)
        self.session.add(instance)
        self.session.flush()
        return instance

    def update(self, instance: ModelT, **values: Any) -> ModelT:
        for field, value in values.items():
            if not hasattr(instance, field):
                raise AttributeError(f"{type(instance).__name__} has no field '{field}'")
            setattr(instance, field, value)
        self.session.add(instance)
        self.session.flush()
        return instance

    def delete(self, instance: ModelT) -> None:
        self.session.delete(instance)
        self.session.flush()

    # ------------------------------------------------------------------ #
    # Transaction helpers — services own the unit of work
    # ------------------------------------------------------------------ #
    def commit(self) -> None:
        self.session.commit()

    def refresh(self, instance: ModelT) -> ModelT:
        self.session.refresh(instance)
        return instance

    def rollback(self) -> None:
        self.session.rollback()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _column(self, name: str):
        if not hasattr(self.model, name):
            raise AttributeError(f"{self.model.__name__} has no column '{name}'")
        return getattr(self.model, name)

    def _where(self, statement: Select[Any], filters: dict[str, Any]) -> Select[Any]:
        for field, value in filters.items():
            statement = statement.where(self._column(field) == value)
        return statement

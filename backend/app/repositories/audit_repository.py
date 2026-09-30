"""Data access for ``audit_logs`` (append-only)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    def record(
        self,
        *,
        action: str,
        user_id: uuid.UUID | None = None,
        actor_email: str | None = None,
        actor_role: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_metadata: dict | None = None,
        description: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        return self.create(
            action=action,
            user_id=user_id,
            actor_email=actor_email,
            actor_role=actor_role,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            event_metadata=event_metadata,
            description=description,
            ip_address=ip_address,
            user_agent=(user_agent or None) and user_agent[:255],
        )

    # ------------------------------------------------------------------ #
    # Review queries
    # ------------------------------------------------------------------ #
    def search(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        user_id: uuid.UUID | None = None,
        since: datetime | None = None,
    ) -> tuple[list[AuditLog], int]:
        filters = []
        if action:
            filters.append(AuditLog.action == action)
        if entity_type:
            filters.append(AuditLog.entity_type == entity_type)
        if entity_id:
            filters.append(AuditLog.entity_id == str(entity_id))
        if user_id:
            filters.append(AuditLog.user_id == user_id)
        if since:
            filters.append(AuditLog.created_at >= since)

        query = select(AuditLog)
        count_query = select(func.count()).select_from(AuditLog)
        if filters:
            from sqlalchemy import and_

            combined = and_(*filters)
            query = query.where(combined)
            count_query = count_query.where(combined)

        total = int(self.session.execute(count_query).scalar_one())
        query = (
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.session.execute(query).scalars().all()), total

    def for_entity(
        self, entity_type: str, entity_id: uuid.UUID | str, *, limit: int = 50
    ) -> list[AuditLog]:
        statement = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == str(entity_id))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.asc())
            .limit(limit)
        )
        return list(self.session.execute(statement).scalars().all())

    def recent_actions(self, *, hours: int = 24) -> dict[str, int]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        statement = (
            select(AuditLog.action, func.count(AuditLog.id))
            .where(AuditLog.created_at >= since)
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc())
        )
        return {action: int(total) for action, total in self.session.execute(statement).all()}

    def count_total(self) -> int:
        return int(self.session.execute(select(func.count()).select_from(AuditLog)).scalar_one())

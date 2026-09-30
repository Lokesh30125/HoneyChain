"""Data access for the ``users`` table."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.models.enums import UserRole
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    # -- Lookups -----------------------------------------------------------
    def get_by_email(self, email: str) -> User | None:
        """Case-insensitive lookup by email (emails are stored lower-cased)."""
        return self.get_by(email=self._normalise_email(email))

    def get_by_phone(self, phone: str) -> User | None:
        return self.get_by(phone=phone)

    def email_exists(self, email: str) -> bool:
        return self.exists(email=self._normalise_email(email))

    def phone_exists(self, phone: str) -> bool:
        return self.exists(phone=phone)

    # -- Writes ------------------------------------------------------------
    def create_user(
        self,
        *,
        name: str,
        email: str,
        password_hash: str,
        role: UserRole,
        phone: str | None = None,
        state: str | None = None,
        district: str | None = None,
        organization: str | None = None,
        is_active: bool = True,
    ) -> User:
        return self.create(
            name=name,
            email=self._normalise_email(email),
            phone=phone,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
            state=state,
            district=district,
            organization=organization,
        )

    def active_by_role(self, role: UserRole) -> list[User]:
        """Every switched-on account holding one role, alphabetically.

        The assignment dropdowns read this rather than a hardcoded list of names:
        an account an administrator creates appears here immediately, and one they
        switch off disappears, because the answer comes from the users table.
        """
        return list(
            self.session.execute(
                select(User)
                .where(User.role == role, User.is_active.is_(True))
                .order_by(func.lower(User.name), User.id)
            )
            .scalars()
            .all()
        )

    def record_login(self, user: User) -> User:
        return self.update(user, last_login_at=datetime.now(timezone.utc))

    def set_password(self, user: User, password_hash: str) -> User:
        return self.update(user, password_hash=password_hash)

    def set_active(self, user: User, is_active: bool) -> User:
        return self.update(user, is_active=is_active)

    # -- Aggregates (used by the Phase 1 admin summary) --------------------
    def count_by_role(self) -> dict[str, int]:
        statement = (
            select(User.role, func.count(User.id)).group_by(User.role).order_by(User.role)
        )
        return {str(role.value if isinstance(role, UserRole) else role): int(total)
                for role, total in self.session.execute(statement).all()}

    def count_active(self) -> int:
        return self.count(is_active=True)

    # -- Internals ---------------------------------------------------------
    @staticmethod
    def _normalise_email(email: str) -> str:
        return email.strip().lower()


__all__ = ["UserRepository", "uuid"]

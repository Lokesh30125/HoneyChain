"""User profile business logic."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateResourceError, NotFoundError
from app.core.logging import get_logger
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserUpdate

logger = get_logger("service")


class UserService:
    """Profile-level use cases for the authenticated user."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)

    def get_by_id(self, user_id) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    def update_profile(self, user: User, payload: UserUpdate) -> User:
        """Apply only the fields the client actually sent (PATCH semantics)."""
        changes = payload.model_dump(exclude_unset=True)

        if "phone" in changes and changes["phone"]:
            existing = self.users.get_by_phone(changes["phone"])
            if existing is not None and existing.id != user.id:
                raise DuplicateResourceError(
                    "This phone number is already linked to another account",
                    details={"field": "phone"},
                )

        if not changes:
            return user

        updated = self.users.update(user, **changes)
        self.users.commit()
        logger.info(
            "Profile updated",
            extra={"user_id": str(user.id), "fields": sorted(changes.keys())},
        )
        return updated

    def list_users(self, *, limit: int = 50, offset: int = 0, role: str | None = None):
        """Admin directory listing (used by the Phase 1 admin shell)."""
        filters = {"role": role} if role else {}
        return self.users.list(limit=limit, offset=offset, order_by="created_at", descending=True, **filters)

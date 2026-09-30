"""``user_profiles`` — optional personal and address details.

Kept as a separate table from ``users`` so the authentication row stays small and
fast, and so a profile can be created lazily: a user who registers with only the
mandatory fields simply has no profile row until they fill one in.

Every field is optional by design — the platform must not demand personal
information to create an account.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUID_TYPE, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User


class UserProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One-to-one extension of :class:`~app.models.user.User`."""

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # -- Personal ------------------------------------------------------------
    #: Stored as a relative path or URL. Upload handling arrives with the
    #: document/media module; Phase 2 accepts a URL only.
    profile_photo: Mapped[str | None] = mapped_column(String(512), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- Location ------------------------------------------------------------
    #: Mirrors the Indian administrative hierarchy so cluster mapping and
    #: district-level reporting can be derived without free-text parsing.
    village: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mandal: Mapped[str | None] = mapped_column(String(120), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "gender IS NULL OR gender IN ('male', 'female', 'other', 'prefer_not_to_say')",
            name="gender_allowed_values",
        ),
        CheckConstraint(
            "pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$'",
            name="pincode_format",
        ),
    )

    user: Mapped["User"] = relationship(back_populates="profile")

    @property
    def has_location(self) -> bool:
        return any([self.village, self.mandal, self.district, self.state, self.pincode])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserProfile user_id={self.user_id}>"


__all__ = ["UserProfile"]

"""``users`` table — the single identity record for every HoneyChain role."""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUID_TYPE, UUIDPrimaryKeyMixin
from app.models.enums import UserRole

if TYPE_CHECKING:  # pragma: no cover
    from app.models.beekeeper import Beekeeper
    from app.models.packaging import PackagingUnit
    from app.models.refresh_token import RefreshToken
    from app.models.user_profile import UserProfile


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A platform user.

    One table, one login flow, many roles. Role-specific profile data (hive
    counts, licence numbers, processing capacity, …) is linked from separate
    tables added by later phases — never by widening this one.
    """

    __tablename__ = "users"

    # -- Identity -----------------------------------------------------------
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)

    # -- Credentials --------------------------------------------------------
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # -- Authorisation ------------------------------------------------------
    role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            name="user_role",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default=UserRole.CONSUMER,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    #: Contact verification (email/phone confirmation). Distinct from
    #: ``Beekeeper.verification_status``, which records an officer's review of
    #: the beekeeper's apiary details. A new account starts unverified.
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # -- Optional profile fields (kept minimal; extended in later phases) ---
    state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: The packaging facility this account works for.
    #:
    #: A ``PACKAGING_UNIT`` account without one cannot do its job — the run it
    #: opens has to name the facility the honey was packed in, and the answer is
    #: not a free choice the operator makes per run. The administrator sets it when
    #: the account is created (or moves the account later), so the workspace knows
    #: the facility before the operator has to think about it.
    packaging_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("packaging_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="The packaging unit a PACKAGING_UNIT account works for.",
    )

    # -- Session bookkeeping ------------------------------------------------
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Set on every successful login; null until first sign-in.",
    )

    #: Set when an administrator deactivates the account — used to explain
    #: *why* a user is locked out rather than returning a bare 403.
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("length(name) >= 2", name="name_min_length"),
        Index("ix_users_role_active", "role", "is_active"),
    )

    # -- Relationships ------------------------------------------------------
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    #: Optional one-to-one profile. ``uselist=False`` makes it an object rather
    #: than a collection.
    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        passive_deletes=True,
    )

    #: The facility a packaging-unit account works for. Set by an administrator;
    #: never chosen by the account itself from a list of other organisations.
    packaging_unit: Mapped["PackagingUnit | None"] = relationship(  # noqa: F821
        foreign_keys=[packaging_unit_id],
        back_populates="members",
    )

    #: Present only for users with the BEEKEEPER role — created by the
    #: registration service, never for other roles.
    beekeeper: Mapped["Beekeeper | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        passive_deletes=True,
        foreign_keys="Beekeeper.user_id",
    )

    # -- Helpers ------------------------------------------------------------
    @property
    def first_name(self) -> str:
        return self.name.split(" ")[0]

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_beekeeper(self) -> bool:
        return self.role == UserRole.BEEKEEPER

    @property
    def location_label(self) -> str:
        """Compact location string, preferring the profile then the user row."""
        source = self.profile or self
        parts = [
            part
            for part in (
                getattr(source, "village", None),
                getattr(source, "district", None),
                getattr(source, "state", None),
            )
            if part
        ]
        return ", ".join(parts) if parts else "—"

    def __repr__(self) -> str:  # pragma: no cover - never logs credentials
        return f"<User id={self.id} role={self.role} active={self.is_active}>"

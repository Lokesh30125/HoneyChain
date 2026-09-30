"""``refresh_tokens`` table — server-side control over issued sessions.

Why store refresh tokens at all?

* **Real logout.** A stateless JWT cannot be cancelled; a server-side record
  lets ``POST /auth/logout`` revoke the session immediately.
* **Rotation with reuse detection.** Every refresh call issues a new token and
  revokes the previous one. If an already-revoked token is presented again we
  treat it as theft and revoke the whole family.
* **Auditability.** Each row records when and from where a session was created.

Only a SHA-256 *fingerprint* of the token is stored — never the token itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUID_TYPE, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single issued refresh token (one per login session)."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: SHA-256 fingerprint of the raw JWT. The raw value exists only in the
    #: response body of the issuing request and in the client's storage.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    #: ``jti`` claim of the refresh token; used to correlate rotations.
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: ``jti`` of the token that replaced this one (rotation chain auditing).
    replaced_by_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)

    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Coarse client fingerprint (hashed user-agent + IP) for audit display.
    device: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_refresh_tokens_user_active", "user_id", "revoked"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    @property
    def is_usable(self) -> bool:
        return not self.revoked and self.expires_at > datetime.now(self.expires_at.tzinfo)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RefreshToken user_id={self.user_id} revoked={self.revoked}>"

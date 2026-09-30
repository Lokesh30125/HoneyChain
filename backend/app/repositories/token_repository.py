"""Data access for ``refresh_tokens`` (session/revocation bookkeeping)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.models.refresh_token import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    # -- Lookups -----------------------------------------------------------
    def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return self.get_by(token_hash=token_hash)

    def get_by_jti(self, jti: str) -> RefreshToken | None:
        return self.get_by(jti=jti)

    # -- Writes ------------------------------------------------------------
    def issue(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        jti: str,
        expires_at: datetime,
        device: str | None = None,
    ) -> RefreshToken:
        return self.create(
            user_id=user_id,
            token_hash=token_hash,
            jti=jti,
            expires_at=expires_at,
            device=device,
        )

    def revoke(self, token: RefreshToken, *, reason: str) -> RefreshToken:
        return self.update(
            token,
            revoked=True,
            revoked_at=datetime.now(timezone.utc),
            revoke_reason=reason,
        )

    def revoke_all_for_user(self, user_id: uuid.UUID, *, reason: str) -> int:
        """Revoke every live session of a user. Returns the number revoked."""
        statement = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(
                revoked=True,
                revoked_at=datetime.now(timezone.utc),
                revoke_reason=reason,
            )
        )
        result = self.session.execute(statement)
        self.session.flush()
        return int(result.rowcount or 0)

    def touch(self, token: RefreshToken) -> RefreshToken:
        return self.update(token, last_used_at=datetime.now(timezone.utc))

    # -- Housekeeping ------------------------------------------------------
    def purge_expired(self, *, user_id: uuid.UUID | None = None) -> int:
        """Delete expired rows so the table does not grow without bound."""
        statement = self.session.query(RefreshToken).filter(
            RefreshToken.expires_at < datetime.now(timezone.utc)
        )
        if user_id is not None:
            statement = statement.filter(RefreshToken.user_id == user_id)
        deleted = statement.delete(synchronize_session=False)
        self.session.flush()
        return int(deleted or 0)

    def count_active_for_user(self, user_id: uuid.UUID) -> int:
        statement = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        return len(list(self.session.execute(statement).scalars().all()))

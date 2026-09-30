"""``document_sequences`` — atomic, gap-free document numbering.

Beekeeper codes (``BKR-GNT-00001``) and cluster codes must be unique and
human-readable. Deriving them from ``COUNT(*) + 1`` is unsafe: two concurrent
registrations compute the same number, and deleting a row silently reuses a
code that already appears on a printed record.

Instead each naming scope keeps a counter row, incremented inside the caller's
transaction with a single atomic UPSERT::

    INSERT INTO document_sequences (scope, last_value) VALUES (:scope, 1)
    ON CONFLICT (scope) DO UPDATE SET last_value = document_sequences.last_value + 1
    RETURNING last_value

The row lock taken by the UPSERT serialises concurrent callers, so two
registrations in the same district never collide, and codes are never reused
even if a beekeeper row is later deleted.
"""

from __future__ import annotations

import re

from sqlalchemy import Integer, String, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

#: Characters allowed in a generated code segment.
_SAFE_SEGMENT = re.compile(r"[^A-Z0-9]")

#: Dropped when abbreviating a single-word district, which is how Indian
#: district codes usually read: GUNTUR -> GNT, KRISHNA -> KRS.
_VOWELS = frozenset("AEIOU")


def district_code(district: str | None, *, fallback: str = "GEN") -> str:
    """Derive a short, stable prefix from a district name.

    ``"Guntur"`` → ``"GNT"``, ``"Krishna"`` → ``"KRS"``,
    ``"East Godavari"`` → ``"EGO"``, ``None`` → ``"GEN"``.

    An abbreviation rather than a phonetic code: it only needs to be short,
    readable and *stable for a given district name*, so a code printed on a
    beekeeper's record still makes sense years later.
    """
    if not district:
        return fallback

    # Anything that is not a letter or digit becomes a separator, so
    # "East Godavari" stays two words and gets two initials (EGA) rather than
    # collapsing into one long word.
    cleaned = _SAFE_SEGMENT.sub(" ", district.upper().replace("-", " "))
    words = [word for word in cleaned.split() if word]

    if not words:
        return fallback

    if len(words) == 1:
        word = words[0]
        consonants = [char for char in word if char not in _VOWELS]
        letters = consonants if len(consonants) >= 3 else list(word)
        return "".join(letters)[:3].ljust(3, "X")

    # Multi-word districts: one letter per word, then padded from the last word
    # so the code is always exactly three characters. "East Godavari" -> EGO.
    initials = "".join(word[0] for word in words)
    if len(initials) < 3:
        initials += words[-1][1:]
    return initials[:3].ljust(3, "X")


class DocumentSequence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named counter used to generate unique document references."""

    __tablename__ = "document_sequences"

    #: Naming scope, e.g. ``BEEKEEPER:BKR-GNT`` or ``CLUSTER:KVIC-GNT``.
    scope: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    @classmethod
    def next_value(cls, session, scope: str, *, width: int = 5) -> str:
        """Reserve and return the next formatted segment for ``scope``.

        The caller must be inside a transaction; the increment participates in
        it, so a rolled-back registration does not consume a number.
        """
        dialect = session.bind.dialect.name if session.bind is not None else "postgresql"

        if dialect == "postgresql":
            statement = (
                pg_insert(cls)
                .values(scope=scope, last_value=1)
                .on_conflict_do_update(
                    index_elements=[cls.scope],
                    set_={"last_value": cls.__table__.c.last_value + 1},
                )
                .returning(cls.__table__.c.last_value)
            )
            value = session.execute(statement).scalar_one()
        else:  # SQLite fallback used only by the test suite
            existing = session.execute(
                select(cls).where(cls.scope == scope)
            ).scalar_one_or_none()
            if existing is None:
                existing = cls(scope=scope, last_value=1)
                session.add(existing)
            else:
                existing.last_value = existing.last_value + 1
            session.flush()
            value = existing.last_value

        return str(value).zfill(width)

    @classmethod
    def peek(cls, session, scope: str) -> int:
        return int(
            session.execute(
                select(func.coalesce(cls.last_value, 0)).where(cls.scope == scope)
            ).scalar_one()
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DocumentSequence {self.scope}={self.last_value}>"


__all__ = ["DocumentSequence", "district_code"]

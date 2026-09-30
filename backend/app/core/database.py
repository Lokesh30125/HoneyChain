"""HoneyChain API — SQLAlchemy engine, session factory and FastAPI dependency.

The ORM is the single gate to PostgreSQL: repositories receive a ``Session`` and
never build connection strings themselves. Parameter binding is always handled
by SQLAlchemy, which is what protects the application from SQL injection.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger("db")

# Deterministic constraint names keep Alembic migrations diff-friendly.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every HoneyChain model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        identifier = getattr(self, "id", None)
        return f"<{self.__class__.__name__} id={identifier}>"


def build_engine(settings: Settings) -> Engine:
    """Create a pooled engine. PostgreSQL is required outside of test runs."""
    url = settings.DATABASE_URL
    if url.startswith("sqlite"):
        # Only tests/short-lived tooling may fall back to SQLite.
        if not settings.is_testing:
            logger.warning(
                "SQLite database configured outside the testing environment",
                extra={"environment": settings.ENVIRONMENT},
            )
        return create_engine(
            url,
            echo=settings.DATABASE_ECHO,
            future=True,
            connect_args={"check_same_thread": False},
        )

    return create_engine(
        url,
        echo=settings.DATABASE_ECHO,
        future=True,
        poolclass=QueuePool,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,  # transparently recycle dropped connections
        pool_recycle=1800,
    )


engine: Engine = build_engine(get_settings())

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


@event.listens_for(Engine, "handle_error")
def _log_database_error(exception_context: Any) -> None:
    """Structured logging for database level failures."""
    if isinstance(exception_context.original_exception, SQLAlchemyError):
        logger.error(
            "Database error",
            extra={
                "statement": str(exception_context.statement)[:500]
                if exception_context.statement
                else None,
                "error_type": type(exception_context.original_exception).__name__,
            },
        )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a transactional session.

    The session is committed explicitly by the service layer. Any exception
    rolls the transaction back and re-raises so the global error handler can
    translate it into the standard error envelope.
    """
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database_connection(settings: Settings | None = None) -> dict[str, Any]:
    """Lightweight readiness probe used by ``/api/v1/health/db``."""
    target = settings or get_settings()
    try:
        with engine.connect() as connection:
            value = connection.execute(text("SELECT 1")).scalar_one()
            version = connection.execute(text("SHOW server_version")).scalar_one() if (
                connection.dialect.name == "postgresql"
            ) else "n/a"
            connection.rollback()
        return {
            "connected": value == 1,
            "dialect": engine.dialect.name,
            "server_version": str(version),
            "environment": target.ENVIRONMENT,
        }
    except SQLAlchemyError as exc:
        logger.error(
            "Database readiness probe failed",
            extra={"error_type": type(exc).__name__},
        )
        return {
            "connected": False,
            "dialect": engine.dialect.name,
            "server_version": None,
            "environment": target.ENVIRONMENT,
        }

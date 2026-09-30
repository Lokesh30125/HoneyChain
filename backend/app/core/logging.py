"""HoneyChain API — structured logging configuration.

Design rules
------------
* Every log record is a structured event (JSON in non-development environments).
* ``RequestIdFilter`` attaches the correlation id of the active request.
* ``SensitiveDataFilter`` scrubs secrets that must never reach a log sink
  (passwords, tokens, API keys, connection strings).

Logger namespaces used across the codebase:

    honeychain.api        HTTP access / lifecycle events
    honeychain.auth       authentication + authorisation events
    honeychain.db         database errors and slow queries
    honeychain.service    business/service level events
    honeychain.blockchain reserved for Phase 3
    honeychain.iot        reserved for Phase 4
    honeychain.ai         reserved for Phase 5
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

from app.core.config import Settings

# --------------------------------------------------------------------------- #
# Request-scoped context
# --------------------------------------------------------------------------- #
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

REDACTED = "***redacted***"

# Field names that must never be logged, matched case-insensitively.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "new_password",
        "current_password",
        "confirm_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "jwt_secret_key",
        "secret",
        "api_key",
        "ai_api_key",
        "mqtt_password",
        "database_url",
        "cookie",
        "set-cookie",
    }
)

# Inline patterns inside free-text messages.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"postgresql(?:\+\w+)?://[^\s\"']+", re.I), "postgresql://***redacted***"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"), REDACTED),
    (re.compile(r"(?i)\b(password|token|api[_-]?key)\b\s*[=:]\s*(\S+)"), r"\1=" + REDACTED),
)


def set_request_id(request_id: str | None) -> None:
    _request_id.set(request_id)


def get_request_id() -> str | None:
    return _request_id.get()


def scrub(value: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive values from arbitrary structures."""
    if _depth > 6:  # guard against pathological / cyclical payloads
        return value
    if isinstance(value, dict):
        return {
            key: (REDACTED if str(key).lower() in SENSITIVE_KEYS else scrub(val, _depth + 1))
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(item, _depth + 1) for item in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


def scrub_text(message: str) -> str:
    for pattern, replacement in _PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class RequestIdFilter(logging.Filter):
    """Attach the active request id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class SensitiveDataFilter(logging.Filter):
    """Defence-in-depth scrubber applied to the rendered message and extras."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub_text(record.msg)

        # ``record.args`` must keep its original container type: logging does
        # ``msg % args``, so turning a tuple into a list breaks %d/%s records
        # (e.g. uvicorn's startup messages). Dict args are preserved for
        # mapping-style formatting.
        if record.args:
            scrubbed = scrub(record.args)
            if isinstance(record.args, tuple):
                record.args = tuple(scrubbed) if isinstance(scrubbed, list) else (scrubbed,)
            elif isinstance(record.args, dict) and isinstance(scrubbed, dict):
                record.args = scrubbed

        for key in list(record.__dict__.keys()):
            if key.lower() in SENSITIVE_KEYS:
                record.__dict__[key] = REDACTED
        return True


class DevelopmentFormatter(logging.Formatter):
    """Human-readable single-line output for local development."""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = getattr(record, "request_id", "-")
        base = (
            f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} "
            f"{record.levelname:<8} [{record.request_id}] {record.name}: {record.getMessage()}"
        )
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key
            not in logging.LogRecord("", 0, "", 0, "", (), None).__dict__
            and key not in {"request_id", "message", "asctime"}
        }
        if extras:
            base += " | " + " ".join(f"{k}={scrub_text(str(v))}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def _build_formatter(settings: Settings) -> logging.Formatter:
    if settings.LOG_JSON:
        try:
            from pythonjsonlogger.json import JsonFormatter  # python-json-logger >= 3
        except ImportError:  # pragma: no cover - fallback for v2 installs
            from pythonjsonlogger.jsonlogger import JsonFormatter  # type: ignore

        return JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
            json_ensure_ascii=False,
        )
    return DevelopmentFormatter()


def configure_logging(settings: Settings) -> None:
    """Install handlers on the root logger exactly once."""
    formatter = _build_formatter(settings)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    handler.addFilter(SensitiveDataFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)

    # Uvicorn keeps its own handlers; route them through ours for consistency.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    # SQLAlchemy is noisy at INFO; echo is opt-in through DATABASE_ECHO.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DATABASE_ECHO else logging.WARNING
    )

    # passlib 1.7.x cannot read the version string of bcrypt >= 4.1 and emits a
    # trapped-error warning on first use. It is cosmetic only, so we silence it
    # rather than upgrading passlib (bcrypt hashing itself is unaffected).
    logging.getLogger("passlib").setLevel(logging.ERROR)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced HoneyChain logger."""
    return logging.getLogger(name if name.startswith("honeychain") else f"honeychain.{name}")

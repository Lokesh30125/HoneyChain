"""Logging guarantees: secrets never reach a sink, and records still format."""

from __future__ import annotations

import json
import logging

from app.core.config import build_settings
from app.core.logging import (
    DevelopmentFormatter,
    RequestIdFilter,
    SensitiveDataFilter,
    REDACTED,
    scrub,
    scrub_text,
    set_request_id,
)


def _record(msg, args=None, **extra) -> logging.LogRecord:
    record = logging.LogRecord("honeychain.test", logging.INFO, __file__, 1, msg, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestScrubbing:
    def test_password_fields_are_redacted(self) -> None:
        scrubbed = scrub({"email": "a@b.com", "password": "SuperSecret123", "nested": {"token": "abc"}})

        assert scrubbed["email"] == "a@b.com"
        assert scrubbed["password"] == REDACTED
        assert scrubbed["nested"]["token"] == REDACTED

    def test_connection_strings_in_text_are_redacted(self) -> None:
        message = "Connecting with postgresql+psycopg://user:secretpw@db:5432/honeychain"

        assert "secretpw" not in scrub_text(message)
        assert "postgresql://***redacted***" in scrub_text(message)

    def test_key_value_secrets_in_text_are_redacted(self) -> None:
        assert "hunter2" not in scrub_text("login failed password=hunter2 for user")

    def test_jwt_in_text_is_redacted(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"

        assert token not in scrub_text(f"Authorization header {token} rejected")

    def test_filter_redacts_sensitive_extra_fields(self) -> None:
        record = _record("auth event", password="plain", access_token="t0ken")
        SensitiveDataFilter().filter(record)

        assert record.password == REDACTED
        assert record.access_token == REDACTED
        assert "plain" not in DevelopmentFormatter().format(record)


class TestRecordFormatting:
    def test_tuple_args_still_format(self) -> None:
        """Regression: redaction must not break ``msg % args`` (uvicorn startup logs)."""
        record = _record("Started server process [%d]", (1234,))
        SensitiveDataFilter().filter(record)

        assert isinstance(record.args, tuple)
        assert "1234" in DevelopmentFormatter().format(record)

    def test_string_args_still_format(self) -> None:
        record = _record("Uvicorn running on %s://%s:%d", ("http", "0.0.0.0", 8000))
        SensitiveDataFilter().filter(record)

        assert "http://0.0.0.0:8000" in DevelopmentFormatter().format(record)

    def test_request_id_filter_attaches_context(self) -> None:
        set_request_id("req-123")
        record = _record("hello", request_id="ignored")

        assert RequestIdFilter().filter(record) is True
        assert record.request_id == "req-123"
        set_request_id(None)

    def test_json_formatter_emits_valid_json(self) -> None:
        settings = build_settings("testing")
        settings.LOG_JSON = True
        # Build the JSON formatter directly to avoid mutating global log config.
        from app.core.logging import _build_formatter

        formatter = _build_formatter(settings)
        record = _record("User registered", user_id="1", role="BEEKEEPER")
        RequestIdFilter().filter(record)
        SensitiveDataFilter().filter(record)

        parsed = json.loads(formatter.format(record))
        assert parsed["message"] == "User registered"
        assert parsed["logger"] == "honeychain.test"

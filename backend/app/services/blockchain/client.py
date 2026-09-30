"""The one client that speaks to the blockchain service.

Every HTTP call HoneyChain makes to the ledger goes through this module. Nothing
else in the codebase builds the URL, opens a socket or formats a submission — so
the timeout, the retry policy, the response validation, the structured logging
and the error shapes are decided once, in one place, and cannot drift apart
between modules.

The service it speaks to is external and already running::

    GET  {BLOCKCHAIN_BASE_URL}/transactions
    POST {BLOCKCHAIN_BASE_URL}/transactions

It is configured, never hard-coded (``app.core.config``), and it is *not*
HoneyChain's database: an outage here must not stop honey from being harvested,
packed or shipped. Every failure is therefore returned as a value
(:class:`BlockchainUnavailable` / :class:`BlockchainRejected`), never raised into
the middle of a workflow — the caller decides to retry, and the outbox row keeps
the record of what happened.

Only ``urllib.request`` is used. The runtime requirement list of this project
carries no HTTP client library beyond the web framework itself, and adding one
for two calls is not worth the dependency.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings

logger = logging.getLogger("honeychain.blockchain")


# --------------------------------------------------------------------------- #
# Errors — returned to callers, never raised through a workflow boundary
# --------------------------------------------------------------------------- #
class BlockchainError(RuntimeError):
    """Base class for anything that stopped an event reaching the ledger."""

    #: Short, stable phrase used as ``last_error`` on the outbox row.
    summary = "blockchain error"

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.summary, "message": self.message, **self.detail}


class BlockchainUnavailable(BlockchainError):
    """The service could not be reached, or did not answer in time.

    Retryable, and the only kind of failure the worker retries by itself.
    """

    summary = "service unavailable"


class BlockchainRejected(BlockchainError):
    """The service answered, and refused.

    Not retried automatically: the same body would be refused again, and the
    operator needs to see the actual answer rather than a retry loop.
    """

    summary = "transaction rejected"


class BlockchainMisconfigured(BlockchainError):
    """No service is configured, or the configured URL is unusable."""

    summary = "not configured"


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Transaction:
    """One transaction as the ledger service reports it.

    ``raw`` keeps the service's own object so the Admin ledger can show exactly
    what the chain holds, including fields HoneyChain does not model.
    """

    tx_id: str
    tx_type: str
    batch_id: str | None
    payload: dict[str, Any]
    timestamp: str | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, body: dict[str, Any]) -> "Transaction":
        return cls(
            tx_id=str(body.get("tx_id") or ""),
            tx_type=str(body.get("tx_type") or ""),
            batch_id=(str(body["batch_id"]) if body.get("batch_id") else None),
            payload=body.get("payload") or {},
            timestamp=body.get("timestamp"),
            raw=body,
        )


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
class BlockchainClient:
    """Thin, synchronous, dependency-free client for the ledger service.

    Synchronous on purpose: the submitting code paths are FastAPI request
    handlers and a background worker, and the outbox means nothing waits on the
    network that a person is waiting for.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # -- Configuration ------------------------------------------------------ #
    @property
    def enabled(self) -> bool:
        return bool(self.settings.BLOCKCHAIN_ENABLED)

    @property
    def base_url(self) -> str:
        return (self.settings.BLOCKCHAIN_BASE_URL or "").rstrip("/")

    @property
    def configured(self) -> bool:
        """Whether a usable base URL is set. Separate from ``enabled`` so the
        platform can say *which* of the two is missing when it reports health."""
        url = self.base_url
        return url.startswith("http://") or url.startswith("https://")

    @property
    def transactions_url(self) -> str:
        return f"{self.base_url}/transactions"

    @property
    def timeout_seconds(self) -> float:
        return max(self.settings.BLOCKCHAIN_TIMEOUT_MS, 1) / 1000.0

    def _require_configured(self) -> None:
        if not self.enabled:
            raise BlockchainMisconfigured(
                "Blockchain integration is switched off (BLOCKCHAIN_ENABLED=false).",
                detail={"configured": False, "enabled": False,},
            )
        if not self.configured:
            raise BlockchainMisconfigured(
                "No blockchain service is configured; set BLOCKCHAIN_BASE_URL.",
                detail={"configured": False, "enabled": True},
            )

    # -- HTTP --------------------------------------------------------------- #
    def _request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")

        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                raw = response.read().decode("utf-8") or "null"
                status = response.status
        except urllib.error.HTTPError as error:
            # The service answered: this is a refusal, not an outage. Its body is
            # read and kept, because "500 Server Error" alone helps nobody.
            detail = self._error_body(error)
            logger.warning(
                "blockchain request refused",
                extra={
                    "event": "blockchain_request",
                    "method": method,
                    "url": url,
                    "http_status": error.code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                },
            )
            raise BlockchainRejected(
                f"The blockchain service answered {error.code} {error.reason}.",
                detail={"http_status": error.code, "body": detail},
            ) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            logger.warning(
                "blockchain service unreachable",
                extra={
                    "event": "blockchain_request",
                    "method": method,
                    "url": url,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                },
                exc_info=error,
            )
            raise BlockchainUnavailable(
                f"The blockchain service could not be reached: {error}",
                detail={"reason": str(error)},
            ) from error

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise BlockchainRejected(
                "The blockchain service returned a body that is not JSON.",
                detail={"body_preview": raw[:200]},
            ) from error

        logger.info(
            "blockchain request",
            extra={
                "event": "blockchain_request",
                "method": method,
                "url": url,
                "http_status": status,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
        return parsed

    @staticmethod
    def _error_body(error: urllib.error.HTTPError) -> str:
        try:
            return error.read().decode("utf-8")[:500]
        except Exception:  # pragma: no cover - a body that cannot be read
            return ""

    # -- API ---------------------------------------------------------------- #
    def get_transactions(self) -> list[Transaction]:
        """``GET /transactions`` — the whole ledger, as the service reports it.

        Returned to the Admin ledger and to a batch's traceability, where the
        list is filtered down to the batch in question before it is answered. It
        is never sent to a browser wholesale.
        """
        self._require_configured()
        body = self._request("GET", self.transactions_url)
        rows = self._as_transaction_list(body)
        return [Transaction.from_payload(row) for row in rows]

    def create_transaction(
        self, *, tx_type: str, batch_id: str, payload: dict[str, Any]
    ) -> Transaction:
        """``POST /transactions`` — submit one traceability event.

        The body is exactly the shape the service documents: ``tx_type``,
        ``batch_id`` and ``payload``. Nothing else is added and nothing is
        renamed, so the ledger's own records stay readable without HoneyChain.
        """
        self._require_configured()
        if not tx_type or not batch_id:
            raise BlockchainRejected(
                "A transaction needs a tx_type and a batch_id.",
                detail={"tx_type": tx_type, "batch_id": batch_id},
            )
        body = {"tx_type": tx_type, "batch_id": batch_id, "payload": payload}
        answer = self._request("POST", self.transactions_url, body=body)
        row = self._as_transaction_object(answer)
        transaction = Transaction.from_payload(row)
        if not transaction.tx_id:
            # Accepted but unattributable: without a tx_id there is nothing to
            # show an auditor, so this is treated as a failure rather than
            # recorded as a confirmed event with a blank identifier.
            raise BlockchainRejected(
                "The blockchain service accepted the request but returned no tx_id.",
                detail={"response": json.dumps(row)[:500]},
            )
        return transaction

    # -- Response shapes ---------------------------------------------------- #
    @staticmethod
    def _as_transaction_list(body: Any) -> list[dict[str, Any]]:
        """The service's list answer, in either of its two documented shapes.

        ``GET /transactions`` returns a bare array today. An envelope
        (``{"data": [...]}`` / ``{"transactions": [...]}``) is also accepted so
        a service that wraps its answers does not break the ledger.
        """
        if isinstance(body, list):
            return [row for row in body if isinstance(row, dict)]
        if isinstance(body, dict):
            for key in ("data", "transactions", "items", "results"):
                value = body.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
        raise BlockchainRejected(
            "The blockchain service returned an unexpected list shape.",
            detail={"body_preview": json.dumps(body)[:200]},
        )

    @staticmethod
    def _as_transaction_object(body: Any) -> dict[str, Any]:
        if isinstance(body, dict):
            for key in ("data", "transaction", "result"):
                value = body.get(key)
                if isinstance(value, dict):
                    return value
            return body
        if isinstance(body, list) and body and isinstance(body[0], dict):
            # Some services answer a POST with the full list. The newest entry
            # is the one just written.
            return body[0]
        raise BlockchainRejected(
            "The blockchain service returned an unexpected transaction shape.",
            detail={"body_preview": json.dumps(body)[:200]},
        )

    # -- Health ------------------------------------------------------------- #
    def probe(self) -> dict[str, Any]:
        """A real connectivity check for the health screen.

        Reports what actually happened — including the error text when the
        service is unreachable — rather than a boolean derived from whether a
        URL was typed into a configuration file.
        """
        if not self.enabled:
            return {
                "configured": self.configured,
                "enabled": False,
                "reachable": False,
                "base_url": self.base_url or None,
                "message": "Blockchain integration is switched off.",
            }
        if not self.configured:
            return {
                "configured": False,
                "enabled": True,
                "reachable": False,
                "base_url": None,
                "message": "No blockchain service is configured (BLOCKCHAIN_BASE_URL).",
            }
        started = time.monotonic()
        try:
            transactions = self.get_transactions()
        except BlockchainError as error:
            return {
                "configured": True,
                "enabled": True,
                "reachable": False,
                "base_url": self.base_url,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "message": error.message,
            }
        return {
            "configured": True,
            "enabled": True,
            "reachable": True,
            "base_url": self.base_url,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "ledger_transactions": len(transactions),
            "latest_timestamp": max(
                (row.timestamp for row in transactions if row.timestamp), default=None
            ),
            "message": "Connected.",
        }

    def url_for(self, path: str, **query: Any) -> str:
        """Build a URL on the service (used by nothing but diagnostics)."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode({k: v for k, v in query.items() if v})}"
        return url


def blockchain_client(settings: Settings | None = None) -> BlockchainClient:
    """The client for the running process."""
    return BlockchainClient(settings)


__all__ = [
    "BlockchainClient",
    "BlockchainError",
    "BlockchainMisconfigured",
    "BlockchainRejected",
    "BlockchainUnavailable",
    "Transaction",
    "blockchain_client",
]

"""A stand-in for the blockchain service, for tests that must not depend on it.

The real service is an external system: it can be down, it can be slow, and a
test suite must not write to the live ledger. This module runs a tiny HTTP server
in a background thread that speaks the same two endpoints with the same shapes,
and gives the tests three things the real service cannot:

* **control** — ``offline()`` drops connections (an outage), ``reject_next()``
  answers 500 (a refusal), and every received request is recorded so a test can
  assert *exactly* what HoneyChain sent and how many times;
* **isolation** — each test gets a fresh ledger, so an assertion about a
  transaction count means something;
* **a legacy ledger** — it starts with transactions that HoneyChain did not
  write, because the real one does too, and the platform's promise not to touch
  them has to be testable.

It is a stub of the *service*, never a stub of HoneyChain's own logic: the
events, the outbox, the retries and the payloads are the real code paths.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

#: Transactions the stub's ledger contains before HoneyChain writes anything,
#: mirroring the ones already on the real chain (older test/demonstration rows
#: with no matching HoneyChain record).
LEGACY_TRANSACTIONS: list[dict[str, Any]] = [
    {
        "tx_id": "a" * 64,
        "tx_type": "BATCH_CREATED",
        "batch_id": "HC-REAL-001",
        "payload": {"batch_id": "HC-REAL-001", "honey_type": "Forest Honey", "quantity_kg": 25},
        "timestamp": "2026-09-22T23:50:16.565Z",
    },
    {
        "tx_id": "b" * 64,
        "tx_type": "QUALITY_CHECKED",
        "batch_id": "TEST-001",
        "payload": {"result": "PASS", "status": "PASSED"},
        "timestamp": "2026-09-23T09:10:02.001Z",
    },
    {
        "tx_id": "c" * 64,
        "tx_type": "QR_GENERATED",
        "batch_id": "HC-GNT-2026-001",
        "payload": {"package_id": "PKG-000001", "qr_id": "QR-PKG-000001", "status": "ACTIVE"},
        "timestamp": "2026-09-24T11:30:45.900Z",
    },
]


class BlockchainStub:
    """A running fake of the ledger service."""

    def __init__(self, *, legacy: bool = True) -> None:
        self.transactions: list[dict[str, Any]] = [dict(row) for row in LEGACY_TRANSACTIONS] if legacy else []
        self.posted: list[dict[str, Any]] = []
        self.get_count = 0
        self._offline = False
        self._reject_next = 0
        self._lock = threading.Lock()
        self._counter = 0

        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # noqa: D102 - silence the test output
                return

            # -- GET /transactions ------------------------------------- #
            def do_GET(self):  # noqa: N802 - http.server's interface
                if self.path.split("?")[0] != "/transactions":
                    self.send_error(404)
                    return
                with stub._lock:
                    stub.get_count += 1
                    if stub._offline:
                        self.close_connection = True
                        return  # drop the connection: an outage, not an error page
                    body = json.dumps(stub.transactions).encode()
                self._respond(200, body)

            # -- POST /transactions ------------------------------------ #
            def do_POST(self):  # noqa: N802
                if self.path.split("?")[0] != "/transactions":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode() if length else "{}"
                with stub._lock:
                    if stub._offline:
                        self.close_connection = True
                        return
                    if stub._reject_next > 0:
                        stub._reject_next -= 1
                        self.send_error(500, "ledger node unavailable")
                        return
                    stub.record(raw)
                    body = json.dumps(stub.transactions[-1]).encode()
                self._respond(201, body)

            def _respond(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # -- Lifecycle ---------------------------------------------------------- #
    def start(self) -> "BlockchainStub":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    # -- Control ------------------------------------------------------------ #
    def offline(self, value: bool = True) -> None:
        with self._lock:
            self._offline = value

    def reject_next(self, count: int = 1) -> None:
        with self._lock:
            self._reject_next = count

    def record(self, raw: str) -> dict[str, Any]:
        """Append a submission exactly as a ledger would, and keep the request."""
        payload = json.loads(raw)
        self._counter += 1
        digest = hashlib.sha256(
            f"{payload.get('tx_type')}|{payload.get('batch_id')}|{self._counter}".encode()
        ).hexdigest()
        transaction = {
            "tx_id": digest,
            "tx_type": payload.get("tx_type"),
            "batch_id": payload.get("batch_id"),
            "payload": payload.get("payload") or {},
            "timestamp": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        self.transactions.append(transaction)
        self.posted.append(payload)
        return transaction

    # -- Assertions helpers ------------------------------------------------- #
    def type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.posted:
            counts[row["tx_type"]] = counts.get(row["tx_type"], 0) + 1
        return counts

    def submissions_for(self, tx_type: str) -> list[dict[str, Any]]:
        return [row for row in self.posted if row.get("tx_type") == tx_type]

    def latest(self, tx_type: str) -> dict[str, Any] | None:
        rows = self.submissions_for(tx_type)
        return rows[-1] if rows else None


__all__ = ["BlockchainStub", "LEGACY_TRANSACTIONS"]

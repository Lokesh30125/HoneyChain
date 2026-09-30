"""The outbox worker: what makes a failed submission recover on its own.

A transaction that could not be written — the blockchain service was restarting,
the network was down, the request timed out — sits in the outbox as ``PENDING``
or ``FAILED``. This worker sweeps those rows every few seconds and submits them
again, so the ledger catches up by itself and nobody has to notice an outage for
the history to be complete.

It is deliberately small and deliberately optional:

* it runs inside the API process (one asyncio task, started in the application
  lifespan) because a database-backed outbox needs no new infrastructure — no
  broker, no second service, no cron;
* it can be switched off (``BLOCKCHAIN_OUTBOX_WORKER_ENABLED=false``) for tests
  and for deployments that would rather drive ``POST /blockchain/sync`` from
  their own scheduler;
* it never raises into the application: a sweep that fails is logged and the
  loop waits for the next tick, because the events are safe in the database
  either way.

The submission itself is synchronous and short (an HTTP POST to one service), and
each sweep is bounded, so the task cannot starve the request handlers.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.blockchain.service import BlockchainService

logger = logging.getLogger("honeychain.blockchain")

#: Stop the loop after this many consecutive failures, so a database that has
#: gone away does not fill the log with one line every few seconds forever.
MAX_CONSECUTIVE_FAILURES = 5


async def run_outbox_worker() -> None:
    """Sweep the outbox on an interval until the application shuts down."""
    settings = get_settings()
    interval = max(float(settings.BLOCKCHAIN_OUTBOX_POLL_SECONDS), 1.0)
    failures = 0
    logger.info("blockchain outbox worker started", extra={"interval_seconds": interval})
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                result = await asyncio.to_thread(_sweep_once)
                failures = 0
                if result.get("submitted"):
                    logger.info("blockchain outbox sweep", extra=result)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - a database that went away
                failures += 1
                logger.warning(
                    "blockchain outbox sweep failed (%s/%s)",
                    failures,
                    MAX_CONSECUTIVE_FAILURES,
                    exc_info=True,
                )
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error("blockchain outbox worker stopping after repeated failures")
                    return
    except asyncio.CancelledError:  # pragma: no cover - shutdown path
        logger.info("blockchain outbox worker stopped")


def _sweep_once() -> dict:
    """One sweep, in its own session and its own database transaction.

    A separate session from the request handlers on purpose: the worker must
    never enqueue its submissions behind a request that is holding a lock, and a
    failure here must not roll back anybody's work.
    """
    session = SessionLocal()
    try:
        return BlockchainService(session).sweep()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = ["MAX_CONSECUTIVE_FAILURES", "run_outbox_worker"]

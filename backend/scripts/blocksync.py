#!/usr/bin/env python
"""Synchronise HoneyChain's blockchain outbox with the traceability service.

The application already submits events as the workflow runs; the outbox worker
inside the API process retries anything that failed. This script is the
operator's view of that same outbox — for a cron job, a deploy check, or a
person who wants to see what the chain is owed before the next sweep.

Usage
-----
    .venv/bin/python scripts/blocksync.py status
    .venv/bin/python scripts/blocksync.py pending
    .venv/bin/python scripts/blocksync.py failed
    .venv/bin/python scripts/blocksync.py sync [--limit N] [--quiet]
    .venv/bin/python scripts/blocksync.py retry <event_id>

``status`` prints the counts and the last error; ``sync`` runs one sweep and
exits non-zero while anything is still failed, so a cron job fails loudly
instead of reporting success over a chain that never received the events.
Nothing here invents a transaction: an event moves to CONFIRMED only when the
service answered with a tx_id, exactly as it does in the running application.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.models.blockchain import BlockchainEvent  # noqa: E402
from app.models.enums import BlockchainStatus  # noqa: E402
from app.services.blockchain.service import BlockchainService  # noqa: E402

logger = get_logger("blockchain")


def _print_counts(service: BlockchainService, *, as_json: bool) -> dict:
    counts = service.counts()
    probe = service.client.probe()
    payload = {
        "service": {
            "base_url": probe.get("base_url"),
            "enabled": probe.get("enabled"),
            "reachable": probe.get("reachable"),
            "ledger_transactions": probe.get("ledger_transactions"),
            "message": probe.get("message"),
        },
        "outbox": counts,
    }
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return counts

    service_state = "reachable" if probe.get("reachable") else (probe.get("message") or "unreachable")
    print(f"Blockchain service : {probe.get('base_url')} ({service_state})")
    print(f"Ledger transactions: {probe.get('ledger_transactions')}")
    print(
        "Outbox             : "
        f"{counts['total']} recorded · {counts['pending']} pending · "
        f"{counts['submitted']} submitted · {counts['confirmed']} confirmed · "
        f"{counts['failed']} failed"
    )
    if counts.get("last_confirmed_event"):
        print(
            f"Last confirmation  : {counts['last_confirmed_event']} → "
            f"{counts['last_confirmed_tx_id']} at {counts['last_confirmed_at']}"
        )
    failed_rows = _rows(BlockchainStatus.FAILED)
    if failed_rows:
        newest = failed_rows[0]
        print(f"Last error         : {newest.event_id}: {newest.last_error}")
    return counts


def _rows(status: BlockchainStatus, *, limit: int = 500) -> list[BlockchainEvent]:
    """Outbox rows in one state, oldest first — the operator's worklist."""
    session = SessionLocal()
    try:
        rows = list(
            session.execute(
                select(BlockchainEvent)
                .where(BlockchainEvent.status == status)
                .order_by(BlockchainEvent.created_at, BlockchainEvent.id)
                .limit(limit)
            ).scalars()
        )
        # Detach with the values already loaded, so the printer may run after
        # the session closes without a lazy load.
        session.expunge_all()
        return rows
    finally:
        session.close()


def _print_events(rows, status_label: str) -> None:
    if not rows:
        print(f"No {status_label} events.")
        return
    print(f"{len(rows)} {status_label} event(s):")
    for row in rows:
        print(
            f"  {row.event_id:<52} {str(row.tx_type):<24} "
            f"attempts={row.attempt_count} {row.last_error or ''}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HoneyChain → blockchain outbox synchroniser")
    parser.add_argument(
        "command",
        choices=["status", "pending", "failed", "sync", "retry"],
        help="what to do",
    )
    parser.add_argument("event_id", nargs="?", help="event id for retry")
    parser.add_argument("--limit", type=int, default=None, help="maximum events to sweep")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--quiet", action="store_true", help="only print the result of a sync")
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        service = BlockchainService(session)

        if args.command == "status":
            _print_counts(service, as_json=args.json)
            return 0

        if args.command in ("pending", "failed"):
            rows = _rows(BlockchainStatus(args.command.upper()))
            if args.json:
                print(json.dumps([service.to_event_read(row) for row in rows], indent=2, default=str))
                return 0
            _print_events(rows, args.command)
            return 0

        if args.command == "sync":
            if not args.quiet:
                _print_counts(service, as_json=False)
            result = service.sweep(limit=args.limit)
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(
                    f"Sweep: {result['submitted']} submitted · {result['confirmed']} confirmed · "
                    f"{result['failed']} failed · {result.get('skipped', 0)} skipped · "
                    f"{result['outstanding']} still outstanding"
                )
                if not result.get("enabled", True):
                    print(
                        "The blockchain integration is switched off "
                        "(BLOCKCHAIN_ENABLED=false): the events are recorded as SKIPPED, "
                        "and the next sweep after it is switched on writes them to the chain."
                    )
            # Non-zero while events are still owed to the chain: a cron job that
            # reports success while the outbox is failing would be the same
            # untruth this layer exists to prevent.
            return 1 if result["outstanding"] else 0

        # retry
        if not args.event_id:
            parser.error("retry needs an event id")
        event = service._load_by_event_id(args.event_id.strip())  # noqa: SLF001 - operator tool
        if event is None:
            print(f"No event with id {args.event_id!r} is recorded in HoneyChain.")
            return 2
        event = service.retry(event)
        if args.json:
            print(json.dumps(service.to_event_read(event), indent=2, default=str))
        else:
            print(
                f"{event.event_id}: {event.status}"
                + (f" → {event.tx_id}" if event.tx_id else "")
                + (f" ({event.last_error})" if event.last_error else "")
            )
        return 0 if str(event.status) == "CONFIRMED" else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

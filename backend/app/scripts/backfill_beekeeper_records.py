"""Create beekeeper records for accounts that predate the Phase-2 module.

Phase 2 gives every ``BEEKEEPER`` user a row in ``beekeepers``. Accounts that
registered before the module existed only have the user row, which means their
"My Beekeeper Profile" screen has nothing to show and the directory silently
omits them. This one-off maintenance script fills that gap.

It is **idempotent**: an account that already owns a beekeeper record is skipped,
and the record it creates is exactly what a registration with no apiary details
produces (status ``PENDING``, no cluster, an opening verification-history entry).

Usage::

    python -m app.scripts.backfill_beekeeper_records --dry-run
    python -m app.scripts.backfill_beekeeper_records
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import build_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging, get_logger
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.schemas.beekeeper import BeekeeperCreate
from app.services.beekeeper_service import BeekeeperService

logger = get_logger("seed")


@dataclass
class BackfillReport:
    """Summary of a run, printed at the end so the output is greppable."""

    scanned: int = 0
    created_count: int = 0
    skipped: int = 0
    dry_run: bool = False

    def render(self) -> str:
        verb = "would be created" if self.dry_run else "created"
        lines = [
            f"  accounts scanned      {self.scanned}",
            f"  records already there {self.skipped}",
            f"  records {verb:<20} {self.created_count}",
        ]
        if self.dry_run:
            lines.append("  (dry run — nothing was written)")
        return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create missing beekeeper records for existing BEEKEEPER accounts."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing anything.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Also backfill accounts that have been deactivated.",
    )
    return parser.parse_args(argv)


def backfill(session: Session, *, dry_run: bool = False, include_inactive: bool = False) -> BackfillReport:
    report = BackfillReport(dry_run=dry_run)
    users = list(
        session.scalars(
            select(User).where(User.role == UserRole.BEEKEEPER).order_by(User.created_at)
        )
    )
    beekeepers = BeekeeperRepository(session)
    service = BeekeeperService(session)

    for user in users:
        if not include_inactive and not user.is_active:
            continue
        report.scanned += 1

        if beekeepers.get_by_user_id(user.id) is not None:
            report.skipped += 1
            print(f"  [ok]      {user.email} already has a beekeeper record")
            continue

        if dry_run:
            report.created_count += 1
            print(f"  [missing] {user.email} would get a PENDING beekeeper record")
            continue

        beekeeper = service.create_for_user(user, BeekeeperCreate())
        report.created_count += 1
        logger.info(
            "Backfilled beekeeper record",
            extra={"beekeeper_code": beekeeper.beekeeper_code, "user_id": str(user.id)},
        )
        print(f"  [created] {beekeeper.beekeeper_code} for {user.email}")

    return report


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = build_settings()
    configure_logging(settings)

    if settings.is_production:
        print("Refusing to run against a production database.", flush=True)
        return 2

    print("Beekeeper backfill — Phase 1 accounts → Phase 2 records")
    with SessionLocal() as session:
        report = backfill(session, dry_run=args.dry_run, include_inactive=args.include_inactive)
        if not args.dry_run:
            session.commit()

    print()
    print(report.render())
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())

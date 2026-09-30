"""Re-evaluate device statuses and mark devices that have gone quiet OFFLINE.

A device's status is *derived* from ``last_seen`` (see
``DeviceService.derive_status``). The API computes it on read, so the dashboard
is always correct; this job is what keeps the **stored** column in step and
appends a ``DEVICE_STATUS_CHANGED`` audit entry the moment a device stops
reporting. Without it, the audit log would have no record of a node dying — only
of the packets it sent while alive.

Run it from cron / Task Scheduler / a container sidecar::

    */15 * * * * cd /srv/honeychain/backend && .venv/bin/python -m app.scripts.device_status_sweep

Options::

    --dry-run        report what would change, write nothing
    --threshold N    treat a device as offline after N seconds of silence
                     (default: DEVICE_OFFLINE_THRESHOLD_SECONDS from config)

MAINTENANCE devices are never touched: that status is an operator decision.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from app.core.config import build_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.models.enums import DeviceStatus
from app.repositories.iot_device_repository import IotDeviceRepository
from app.services.device_service import DeviceService


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep device statuses (offline detection).")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing them.")
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Seconds of silence before a device counts as offline.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = build_settings()
    configure_logging(settings)

    if args.threshold is not None:
        if args.threshold < 60:
            print("A threshold below 60s would flap on a single lost packet.", file=sys.stderr)
            return 2
        settings.DEVICE_OFFLINE_THRESHOLD_SECONDS = args.threshold

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.DEVICE_OFFLINE_THRESHOLD_SECONDS)

    with SessionLocal() as session:
        repository = IotDeviceRepository(session)
        service = DeviceService(session, settings)

        stale = repository.stale(cutoff=cutoff)
        print(
            f"Devices silent for more than {settings.DEVICE_OFFLINE_THRESHOLD_SECONDS}s: {len(stale)}"
        )

        changed: list[tuple[str, str, str]] = []
        for device in stale:
            derived = service.derive_status(device)
            if derived == device.status:
                continue
            changed.append((device.device_id, str(device.status), str(derived)))
            if not args.dry_run:
                device.status = derived
                # ``actor=None`` and ``automatic=True``: this is the platform's
                # own observation, not something an operator did.
                service.audit.device_status_changed(
                    device,
                    actor=None,
                    previous=changed[-1][1],
                    new=derived,
                    automatic=True,
                )

        if args.dry_run:
            for device_id, previous, new in changed:
                print(f"  [would change] {device_id}: {previous} → {new}")
            print("Dry run: nothing was written.")
            return 0

        if changed:
            session.commit()
            for device_id, previous, new in changed:
                print(f"  [changed] {device_id}: {previous} → {new}")
        else:
            print("  [unchanged] every reporting device is within the threshold")

    maintenance = [
        device.device_id
        for device in stale
        if device.status == DeviceStatus.MAINTENANCE
    ]
    if maintenance:
        print(f"  [skipped] {len(maintenance)} device(s) in MAINTENANCE")

    print(f"{len(changed)} device(s) updated.")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())

"""Re-apply the development profile's placeholder values to the catalogue.

The demo profile is configuration, and configuration changes: the placeholder
values it writes are the ones a technician edits, so they are kept in step with
the profile rather than being frozen at whatever the first install wrote.

Deliberately narrower than a migration. It refreshes only what the profile still
owns:

* a parameter whose range is *still* the demo's own gets the profile's current
  development value;
* a parameter a person has configured — a range with their own source — is not
  touched at all, including its value.

Idempotent: running it twice changes nothing the second time.

Usage::

    python -m app.scripts.refresh_demo_profile
"""

from __future__ import annotations

import sys

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.services.lab_demo_profile import install_demo_configuration


def main() -> int:
    settings = get_settings()
    configure_logging(settings)
    if not settings.LAB_DEMO_CONFIGURATION_ENABLED:
        print(
            "LAB_DEMO_CONFIGURATION_ENABLED is off: this installation runs on ranges a "
            "person configured, and the development profile writes nothing."
        )
        return 0

    with SessionLocal() as session:
        result = install_demo_configuration(session)
    print(f"Development values refreshed: {result['development_values_refreshed'] or 'none'}")
    print(f"Already configured, left untouched: {result['left_as_configured'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

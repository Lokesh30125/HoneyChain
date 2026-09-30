"""Provision an administrator (or any privileged role) account.

The API deliberately refuses self-registration for ``ADMIN``, ``KVIC_OFFICER``
and ``LAB_TECHNICIAN`` to prevent privilege escalation. Those accounts are
created here, by someone with server access, or by an existing administrator
through the API in a later phase.

Usage::

    python -m app.scripts.create_admin --email admin@example.org \\
        --name "Platform Administrator" --role ADMIN

    # Read the password from the environment instead of prompting:
    DEFAULT_ADMIN_PASSWORD=... python -m app.scripts.create_admin --email admin@example.org \\
        --name "Platform Administrator"

The password is never echoed, never written to a log, and never stored in
plaintext — only the bcrypt hash reaches the database.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy.orm import Session

from app.core.config import build_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.core.exceptions import DuplicateResourceError
from app.core.security import hash_password
from app.models.enums import UserRole
from app.repositories.user_repository import UserRepository

MIN_PASSWORD_LENGTH = 8


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a privileged HoneyChain account.")
    parser.add_argument("--email", required=True, help="Account email address (login id).")
    parser.add_argument("--name", required=True, help="Display name.")
    parser.add_argument(
        "--role",
        default=UserRole.ADMIN.value,
        choices=[role.value for role in (UserRole.ADMIN, UserRole.KVIC_OFFICER, UserRole.LAB_TECHNICIAN)],
        help="Privileged role to grant (default: ADMIN).",
    )
    parser.add_argument("--phone", default=None, help="Optional phone number.")
    parser.add_argument("--state", default=None, help="Optional state.")
    parser.add_argument("--district", default=None, help="Optional district.")
    parser.add_argument("--organization", default=None, help="Optional organisation.")
    parser.add_argument(
        "--password",
        default=None,
        help="Password. Prefer the DEFAULT_ADMIN_PASSWORD environment variable or the prompt "
        "so the value does not end up in your shell history.",
    )
    return parser.parse_args(argv)


def _resolve_password(args: argparse.Namespace) -> str:
    password = args.password or os.getenv("DEFAULT_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords do not match.", file=sys.stderr)
            raise SystemExit(1)
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        raise SystemExit(1)
    return password


def create_admin(session: Session, args: argparse.Namespace, password: str) -> str:
    """Create the account. Returns the new user's id as a string."""
    users = UserRepository(session)

    if users.email_exists(args.email):
        raise DuplicateResourceError(f"An account with email {args.email} already exists.")
    if args.phone and users.phone_exists(args.phone):
        raise DuplicateResourceError(f"An account with phone {args.phone} already exists.")

    user = users.create_user(
        name=args.name,
        email=args.email,
        password_hash=hash_password(password),
        role=UserRole(args.role),
        phone=args.phone,
        state=args.state,
        district=args.district,
        organization=args.organization,
    )
    users.commit()
    return str(user.id)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = build_settings()
    # Route logs through the application configuration (keeps third-party
    # library noise, including passlib's cosmetic bcrypt version warning, out
    # of the operator's console).
    configure_logging(settings)
    print(f"Environment : {settings.ENVIRONMENT}")
    print(f"Database    : {settings.DATABASE_URL.split('@')[-1]}")

    password = _resolve_password(args)

    session = SessionLocal()
    try:
        user_id = create_admin(session, args, password)
    except DuplicateResourceError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        session.close()

    # Never print the password or the hash.
    print(f"Created {args.role} account: {args.email} (id: {user_id})")
    print("Sign in at the web application to continue.")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())

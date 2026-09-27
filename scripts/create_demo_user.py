"""Create (or update) the development-only demo account.

Seeds ``demo@nexusai.local`` / ``NexusDemo@2026!`` using the SAME bcrypt
``hash_password`` as the application — no second auth system, no plaintext in
the database. The user is created directly in the DB (bypassing the register
endpoint's ``EmailStr`` validation, which rejects the special-use ``.local``
domain) so that the normal login flow (OAuth2 form -> verify_password -> JWT)
works unchanged.

Guards:
  - refuses to run when ``settings.is_production`` (APP_ENV in {production, prod})
  - idempotent: re-running updates nothing unless ``--reset-password`` is passed

Usage:
    .venv/Scripts/python.exe scripts/create_demo_user.py
    .venv/Scripts/python.exe scripts/create_demo_user.py --reset-password
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

DEMO_EMAIL = "demo@nexusai.local"
DEMO_PASSWORD = "NexusDemo@2026!"
DEMO_FULL_NAME = "Demo User"


def _configure_env() -> None:
    """Match the local dev/preview DB (SQLite) unless the caller overrides.

    Must run before importing ``app.config`` — settings are read once at import.
    Mirrors scripts/loadtest_server.py so the seeded user lands in the same
    database the local dev server serves.
    """
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.loadtest.db")
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("SECRET_KEY", "loadtest-secret")


async def _seed(reset_password: bool) -> int:
    from sqlalchemy import select

    from sqlalchemy import create_engine

    from app.config import settings
    from app.db.models import Base
    from app.db.models.tenant import Tenant
    from app.db.models.user import User
    from app.db.session import get_sessionmaker
    from app.security.auth import hash_password, verify_password

    if settings.is_production:
        print(
            "REFUSED: APP_ENV is production — the demo account is "
            "development-only. Set APP_ENV=development to seed it."
        )
        return 2

    # Make sure the schema exists (same trick as the loadtest server: sync
    # driver, no event loop needed) so the script works on a fresh checkout.
    engine = create_engine(settings.sync_database_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    maker = get_sessionmaker()
    async with maker() as db:
        user = (
            await db.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one_or_none()

        if user is not None:
            if reset_password:
                user.hashed_password = hash_password(DEMO_PASSWORD)
                await db.commit()
                print(f"Password reset for existing demo user {DEMO_EMAIL}.")
            elif not verify_password(DEMO_PASSWORD, user.hashed_password):
                print(
                    f"Demo user {DEMO_EMAIL} exists but the password differs. "
                    "Re-run with --reset-password to set it back to the documented "
                    "demo password."
                )
                return 1
            else:
                print(f"Demo user already exists (no changes made): {DEMO_EMAIL}")
            print(
                "\nDemo account ready.\n\n"
                f"Email: {DEMO_EMAIL}\n"
                f"Password: {DEMO_PASSWORD}\n"
                f"Tenant: {user.tenant_id}"
            )
            return 0

        # Mirror app.api.v1.auth.register: provision a single-user tenant.
        tenant = Tenant(
            name="Demo workspace (dev only)",
            slug="demo-workspace",
            chroma_collection_prefix="demo-workspace",
        )
        db.add(tenant)
        await db.flush()  # assign tenant.id

        user = User(
            email=DEMO_EMAIL,
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name=DEMO_FULL_NAME,
            tenant_id=tenant.id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        print(
            "\nDemo account ready.\n\n"
            f"Email: {DEMO_EMAIL}\n"
            f"Password: {DEMO_PASSWORD}\n"
            f"Tenant: {user.tenant_id}\n"
            f"User id: {user.id}"
        )
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="If the demo user exists, reset its password to the documented value.",
    )
    args = parser.parse_args()
    _configure_env()
    try:
        sys.exit(asyncio.run(_seed(args.reset_password)))
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":
    main()

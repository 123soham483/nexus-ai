"""SQLAlchemy declarative base and shared column-type helpers.

Design note (BRAIN.md D2): we use SQLAlchemy 2.0 *generic* types (``Uuid``,
``JSON``, ``DateTime``) rather than Postgres-specific ``UUID``/``JSONB`` so the
exact same models run on both asyncpg/Postgres (prod) and aiosqlite/SQLite
(fast local tests). This keeps the whole test suite runnable in a venv with no
database server.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now (avoids the deprecated naive datetime.utcnow)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base all ORM models inherit from."""


class UUIDPrimaryKeyMixin:
    """Adds a UUID primary key generated application-side."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Adds created_at / updated_at columns.

    ``created_at`` is set on insert; ``updated_at`` refreshes on every update
    (both via Python defaults so behaviour is identical across SQLite/Postgres).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )

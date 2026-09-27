"""Async SQLAlchemy engine + session factory.

Exposes:
- ``engine``               the process-wide async engine
- ``AsyncSessionLocal``    an async_sessionmaker
- ``get_session``          FastAPI dependency yielding a session
- ``init_engine`` / ``dispose_engine`` lifecycle helpers used by app startup/shutdown

The engine is created lazily from ``settings.DATABASE_URL`` so importing this
module never opens a connection (important for tests that override the URL).
"""
from __future__ import annotations

from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Module-level singletons, initialised on first use.
_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def _build_engine(url: str) -> AsyncEngine:
    """Create an async engine, applying pool options only for non-SQLite URLs.

    SQLite (used in tests) does not accept pool_size/max_overflow, so we branch.
    """
    if url.startswith("sqlite"):
        return create_async_engine(url, echo=settings.DATABASE_ECHO, future=True)
    return create_async_engine(
        url,
        echo=settings.DATABASE_ECHO,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
        future=True,
    )


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = _build_engine(settings.DATABASE_URL)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory, creating it on first call."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session and always closes it."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the engine on shutdown (closes all pooled connections)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


# Backwards-friendly aliases used elsewhere in the codebase.
AsyncSessionLocal = get_sessionmaker


from contextlib import asynccontextmanager

@asynccontextmanager
async def get_session_context():
    """Session context manager used by the Celery worker.

    Commits on success. On exception it ROLLS BACK only un-committed changes and
    still closes the session, but the exception propagates unchanged — crucially
    WITHOUT discarding work the caller already committed mid-block. The
    orchestrator's failure path (task status FAILED + failure traces) relies on
    this: it persists the failure state while the exception is still propagating,
    so a blanket rollback here used to erase it and leave tasks in `pending`
    forever (BRAIN.md bug T1).
    """
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            # Undo only this session's uncommitted work; the exception must keep
            # propagating so Celery sees the failure. Do NOT discard data that
            # the handler itself already flushed+committed (failure traces).
            await session.rollback()
            raise

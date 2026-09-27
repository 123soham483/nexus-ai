"""Shared pytest fixtures.

Provides an in-memory async SQLite database (schema built from the ORM models
via ``create_all``), a fakeredis client, and a FastAPI test client wired to use
them. No real Postgres/Redis/Chroma/LLM is required for the suite to run.
"""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Importing the models package registers all tables on Base.metadata.
from app.db.models import Base


# A file-less shared in-memory SQLite DB, one engine per test for isolation.
TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def db_engine():
    """Create a fresh in-memory async engine with the full schema."""
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session bound to the in-memory test engine."""
    maker = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def fake_redis():
    """An async fakeredis client (drop-in for redis.asyncio.Redis)."""
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture(autouse=True)
def _tracing_disabled(monkeypatch):
    """Keep the suite free of a live OpenTelemetry pipeline.

    Tracing is on by default in production, but a unit test must never build a
    real tracer: it would spawn a BatchSpanProcessor thread and try to export to
    an OTLP endpoint that does not exist. Tracer behaviour is tested directly
    with an injected fake tracer.
    """
    from app.config import settings
    from app.observability import tracer as tracer_module
    from app.observability.tracer import NexusTracer

    monkeypatch.setattr(settings, "ENABLE_OPENTELEMETRY", False, raising=False)
    original = tracer_module.get_tracer()
    noop = NexusTracer(enabled=False)
    tracer_module.set_tracer(noop)
    yield
    tracer_module.set_tracer(original)


@pytest.fixture(autouse=True)
def _sandbox_execution_disabled(monkeypatch):
    """No test may spawn a real container.

    The suite runs without Postgres, Redis, Chroma or an LLM, and it must not
    need a Docker daemon either. With Docker installed (but idle) the
    TesterAgent would otherwise probe the daemon and, if it happened to be
    running, execute generated test code in a container — slow, flaky, and not
    what a unit test is for. Sandbox behaviour is tested directly with an
    injected runner, and agent tests inject a fake sandbox (which bypasses this
    flag).
    """
    from app.config import settings

    monkeypatch.setattr(settings, "SANDBOX_ENABLED", False, raising=False)


@pytest.fixture(autouse=True)
def _celery_dispatch_in_tests(monkeypatch):
    """Keep HTTP tests on the Celery delay() path even if .env uses inline."""
    from app.config import settings

    monkeypatch.setattr(settings, "TASK_DISPATCH", "celery", raising=False)


@pytest.fixture
def anyio_backend():
    """Force anyio-based libs to use asyncio (not trio) in tests."""
    return "asyncio"

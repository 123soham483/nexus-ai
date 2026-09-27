"""Integration-test fixtures: a live ASGI app wired to in-memory DB + fakeredis."""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.session import get_session
from app.security import redis_client


@pytest_asyncio.fixture
async def app_client():
    """Yield an httpx AsyncClient bound to the real FastAPI app.

    The DB dependency is overridden to use a shared in-memory SQLite engine and
    the Redis client is swapped for fakeredis, so the whole HTTP stack runs with
    no external services.
    """
    # Fresh in-memory DB with schema. Use a single shared connection so all
    # sessions see the same in-memory database.
    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session():
        async with maker() as session:
            yield session

    # Inject fakeredis as the shared client.
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.set_redis(fake)

    # Import here so app construction happens after overrides are ready.
    from app.main import app

    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await fake.aclose()
    await engine.dispose()
    redis_client.set_redis(None)


@pytest_asyncio.fixture
async def api(db_session):
    """A TestClient wired to the given (seeded) db_session.

    Unlike ``app_client`` (which owns a fresh in-memory DB), this lets tests
    seed Tenant/User/Task/AgentRun rows directly through ``db_session`` and then
    hit the API against that same data. fakeredis is injected for the auth
    blacklist check.
    """
    import fakeredis.aioredis
    from fastapi.testclient import TestClient

    from app.security import redis_client
    from app.db.session import get_session
    from app.main import app

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.set_redis(fake)

    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        redis_client.set_redis(None)
        await fake.aclose()


@pytest_asyncio.fixture
async def make_user(db_session):
    """Factory creating a tenant + user; returns (tenant, user, auth_headers)."""
    import uuid as _uuid

    from app.db.models import Tenant, User
    from app.security.auth import create_access_token

    async def _make(email, *, tenant_kwargs=None, user_kwargs=None):
        slug = email.split("@")[0].replace(".", "-") + "-" + _uuid.uuid4().hex[:6]
        tenant = Tenant(
            name=slug,
            slug=slug,
            chroma_collection_prefix=slug,
            **(tenant_kwargs or {}),
        )
        db_session.add(tenant)
        await db_session.flush()
        user = User(
            email=email,
            hashed_password="x",
            full_name="Test User",
            tenant_id=tenant.id,
            **(user_kwargs or {}),
        )
        db_session.add(user)
        await db_session.commit()
        token = create_access_token(str(user.id), str(user.tenant_id))
        return tenant, user, {"Authorization": f"Bearer {token}"}

    return _make

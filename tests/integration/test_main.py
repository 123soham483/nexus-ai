"""Integration tests for main.py (Step 1.15)."""
from __future__ import annotations

import pytest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.db.models import Trace, Tenant, User, Task
from app.db.models.enums import TaskStatus


def test_health_endpoint():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_docs_page():
    client = TestClient(app)
    r = client.get("/docs")
    assert r.status_code == 200


def test_me_without_token_unauthorized():
    client = TestClient(app)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_websocket_connect_and_receives_traces(db_session):
    # Setup test Tenant/User/Task/Traces in the SQLite DB
    tenant = Tenant(name="Acme WebSockets", slug="acme-ws", chroma_collection_prefix="acme-ws")
    db_session.add(tenant)
    await db_session.flush()

    user = User(email="ws@acme.com", hashed_password="password", full_name="WS User", tenant_id=tenant.id)
    db_session.add(user)
    await db_session.flush()

    task = Task(user_id=user.id, tenant_id=tenant.id, goal="ws test goal")
    db_session.add(task)
    await db_session.flush()

    trace1 = Trace(task_id=task.id, event_type="task_started", event_data={"hello": "world"}, sequence_number=1)
    trace2 = Trace(task_id=task.id, event_type="routing_complete", event_data={"chosen": "coder"}, sequence_number=2)
    db_session.add_all([trace1, trace2])
    await db_session.commit()

    # Override db session dependency to use the test session containing our seed data
    async def _override_session():
        yield db_session

    from app.db.session import get_session
    app.dependency_overrides[get_session] = _override_session

    client = TestClient(app)
    try:
        with client.websocket_connect(f"/ws/{task.id}") as ws:
            # We should immediately receive historical traces in order
            msg1 = ws.receive_json()
            assert msg1["event"] == "task_started"
            assert msg1["data"] == {"hello": "world"}
            assert msg1["sequence"] == 1

            msg2 = ws.receive_json()
            assert msg2["event"] == "routing_complete"
            assert msg2["data"] == {"chosen": "coder"}
            assert msg2["sequence"] == 2
    finally:
        app.dependency_overrides.clear()


@patch("app.workers.task_worker.execute_task_worker.delay")
@pytest.mark.asyncio
async def test_post_task_end_to_end_dispatches_celery(mock_delay, db_session):
    tenant = Tenant(name="Acme Celery E2E", slug="acme-celery", chroma_collection_prefix="acme-celery")
    db_session.add(tenant)
    await db_session.flush()

    user = User(email="celery@acme.com", hashed_password="password", full_name="Celery User", tenant_id=tenant.id)
    db_session.add(user)
    await db_session.commit()

    # Generate token
    from app.security.auth import create_access_token
    token = create_access_token(str(user.id), str(user.tenant_id))

    # get_current_user checks the Redis blacklist — inject fakeredis so the
    # test never touches a real Redis server.
    import fakeredis.aioredis
    from app.security import redis_client

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client.set_redis(fake)

    async def _override_session():
        yield db_session

    from app.db.session import get_session
    app.dependency_overrides[get_session] = _override_session

    client = TestClient(app)
    try:
        r = client.post(
            "/api/v1/tasks/",
            json={"goal": "implement mergesort in python"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 201
        data = r.json()
        assert data["goal"] == "implement mergesort in python"
        assert data["status"] == "pending"

        # Verify Celery delay was called
        mock_delay.assert_called_once()
    finally:
        app.dependency_overrides.clear()
        redis_client.set_redis(None)
        await fake.aclose()

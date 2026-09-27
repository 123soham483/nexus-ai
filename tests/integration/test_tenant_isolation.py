"""Cross-tenant isolation integration tests (Step 4.4)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models.task import Task
from app.db.tenant_isolation import TenantIsolationMiddleware


async def _auth(app_client, email: str):
    r = await app_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepassword123", "full_name": "T"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@patch("app.workers.task_worker.execute_task_worker.delay")
@pytest.mark.asyncio
async def test_tenant_a_cannot_list_tenant_b_tasks(mock_delay, app_client):
    headers_a = await _auth(app_client, "iso-list-a@example.com")
    headers_b = await _auth(app_client, "iso-list-b@example.com")

    r = await app_client.post(
        "/api/v1/tasks/",
        json={"goal": "Write a Python hello world function for testing"},
        headers=headers_a,
    )
    assert r.status_code == 201

    list_b = await app_client.get("/api/v1/tasks/", headers=headers_b)
    assert list_b.status_code == 200
    ids = {t["id"] for t in list_b.json()["tasks"]}
    assert r.json()["id"] not in ids


@patch("app.workers.task_worker.execute_task_worker.delay")
@pytest.mark.asyncio
async def test_tenant_a_cannot_get_tenant_b_task_by_id(mock_delay, app_client):
    headers_a = await _auth(app_client, "iso-get-a@example.com")
    headers_b = await _auth(app_client, "iso-get-b@example.com")

    created = await app_client.post(
        "/api/v1/tasks/",
        json={"goal": "Build a REST API with FastAPI for tenant isolation test"},
        headers=headers_a,
    )
    task_id = created.json()["id"]

    r = await app_client.get(f"/api/v1/tasks/{task_id}", headers=headers_b)
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_tenant_a_cannot_search_tenant_b_memory(app_client, monkeypatch):
    headers_a = await _auth(app_client, "mem-a@example.com")
    headers_b = await _auth(app_client, "mem-b@example.com")

    seen_prefixes = []

    class FakeLTM:
        async def search_similar_tasks(self, query, n_results=5, min_quality_score=0.7):
            return []

    def _build(prefix):
        seen_prefixes.append(prefix)
        return FakeLTM()

    monkeypatch.setattr("app.api.v1.memory._build_memory", _build)

    await app_client.post(
        "/api/v1/memory/search",
        json={"query": "secret task content here", "collection": "tasks"},
        headers=headers_a,
    )
    await app_client.post(
        "/api/v1/memory/search",
        json={"query": "secret task content here", "collection": "tasks"},
        headers=headers_b,
    )
    assert len(seen_prefixes) == 2
    assert seen_prefixes[0] != seen_prefixes[1]


@pytest.mark.asyncio
async def test_verify_query_detects_tenant_filter(db_session, make_user):
    tenant, user, _ = await make_user("verify@example.com")
    TenantIsolationMiddleware.apply(db_session, str(tenant.id))
    q = select(Task).where(Task.tenant_id == tenant.id)
    assert TenantIsolationMiddleware.verify_query(q, str(tenant.id)) is True

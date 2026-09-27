"""Integration tests for the HITL approval API (Phase 2.14)."""
from __future__ import annotations

import pytest
import uuid
from unittest.mock import patch

from app.hitl import default_store

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _clean_store():
    """The shared store persists across tests — reset it around each one."""
    await default_store.clear()
    yield
    await default_store.clear()


async def _get_auth_headers(app_client, email="hitl@acme.com"):
    r = await app_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepassword", "full_name": "HITL User"},
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _create_task(app_client, headers, goal="approve this deployment"):
    r = await app_client.post("/api/v1/tasks/", json={"goal": goal}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _seed_pending_request(task_id, reason="needs approval"):
    return await default_store.create(
        task_id=task_id,
        agent_type="hitl_controller",
        goal="approve this deployment",
        reason=reason,
    )


@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_resolve_approves_pending_request(mock_delay, app_client):
    headers = await _get_auth_headers(app_client, "hitl1@acme.com")
    task_id = await _create_task(app_client, headers)
    request = await _seed_pending_request(task_id)

    r = await app_client.post(
        f"/api/v1/tasks/{task_id}/hitl/resolve",
        json={"request_id": request.id, "approved": True, "note": "ship it"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "approved"
    assert data["task_id"] == task_id
    # The response serializes ids canonically (dashed); the store's are hex.
    assert str(uuid.UUID(data["id"])) == str(uuid.UUID(request.id))
    assert data["reason"] == "needs approval"
    assert data["note"] == "ship it"
    assert data["resolved_by"]

    # The store reflects the decision.
    stored = await default_store.get(request.id)
    assert stored.status == "approved"
    assert stored.note == "ship it"


@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_resolve_rejects_pending_request(mock_delay, app_client):
    headers = await _get_auth_headers(app_client, "hitl2@acme.com")
    task_id = await _create_task(app_client, headers)
    request = await _seed_pending_request(task_id)

    r = await app_client.post(
        f"/api/v1/tasks/{task_id}/hitl/resolve",
        json={"request_id": request.id, "approved": False},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_resolve_unknown_request_404(mock_delay, app_client):
    headers = await _get_auth_headers(app_client, "hitl3@acme.com")
    task_id = await _create_task(app_client, headers)

    r = await app_client.post(
        f"/api/v1/tasks/{task_id}/hitl/resolve",
        json={"request_id": "99999999-8888-7777-6666-555555555555", "approved": True},
        headers=headers,
    )
    assert r.status_code == 404
    assert "not found" in r.json()["error"].lower()


@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_resolve_already_resolved_409(mock_delay, app_client):
    headers = await _get_auth_headers(app_client, "hitl4@acme.com")
    task_id = await _create_task(app_client, headers)
    request = await _seed_pending_request(task_id)
    await default_store.resolve(request.id, approved=True)

    r = await app_client.post(
        f"/api/v1/tasks/{task_id}/hitl/resolve",
        json={"request_id": request.id, "approved": False},
        headers=headers,
    )
    assert r.status_code == 409
    assert "already resolved" in r.json()["error"].lower()


@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_resolve_cross_tenant_404(mock_delay, app_client):
    headers_a = await _get_auth_headers(app_client, "hitl5a@acme.com")
    headers_b = await _get_auth_headers(app_client, "hitl5b@acme.com")
    task_id = await _create_task(app_client, headers_a)
    request = await _seed_pending_request(task_id)

    r = await app_client.post(
        f"/api/v1/tasks/{task_id}/hitl/resolve",
        json={"request_id": request.id, "approved": True},
        headers=headers_b,
    )
    assert r.status_code == 404
    assert "task not found" in r.json()["error"].lower()


@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_list_pending_hitl_requests(mock_delay, app_client):
    headers = await _get_auth_headers(app_client, "hitl6@acme.com")
    task_id = await _create_task(app_client, headers)
    request = await _seed_pending_request(task_id, reason="first approval")
    await _seed_pending_request(task_id, reason="second approval")

    r = await app_client.get(f"/api/v1/tasks/{task_id}/hitl/pending", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert {d["reason"] for d in data} == {"first approval", "second approval"}

    # Resolving one removes it from the pending list.
    await default_store.resolve(request.id, approved=True)
    r2 = await app_client.get(f"/api/v1/tasks/{task_id}/hitl/pending", headers=headers)
    assert len(r2.json()) == 1


@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_hitl_history_returns_pending_and_resolved(mock_delay, app_client):
    headers = await _get_auth_headers(app_client, "hitl7@acme.com")
    task_id = await _create_task(app_client, headers)
    r1 = await _seed_pending_request(task_id, reason="first approval")
    r2 = await _seed_pending_request(task_id, reason="second approval")
    await default_store.resolve(r1.id, approved=True, resolved_by="human-1")

    r = await app_client.get(f"/api/v1/tasks/{task_id}/hitl/history", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    by_reason = {d["reason"]: d for d in data}
    assert by_reason["first approval"]["status"] == "approved"
    assert by_reason["first approval"]["resolved_by"]
    assert by_reason["second approval"]["status"] == "pending"


@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_resolve_requires_auth(mock_delay, app_client):
    r = await app_client.post(
        "/api/v1/tasks/00000000-0000-0000-0000-000000000000/hitl/resolve",
        json={"request_id": "11111111-2222-3333-4444-555555555555", "approved": True},
    )
    assert r.status_code == 401

"""Security hardening integration tests (Step 4.5)."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_null_byte_in_goal_returns_422(app_client):
    r_reg = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "null@example.com",
            "password": "securepassword123",
            "full_name": "N",
        },
    )
    headers = {"Authorization": f"Bearer {r_reg.json()['access_token']}"}
    r = await app_client.post(
        "/api/v1/tasks/",
        json={"goal": "valid start\x00hidden null byte test goal"},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_rate_limit_overflow_returns_429(app_client, monkeypatch):
    from unittest.mock import patch
    from app.security import rate_limiter

    monkeypatch.setitem(rate_limiter.ENDPOINT_LIMITS, ("POST", "/api/v1/tasks/"), 2)
    r_reg = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "rate@example.com",
            "password": "securepassword123",
            "full_name": "R",
        },
    )
    headers = {"Authorization": f"Bearer {r_reg.json()['access_token']}"}
    payload = {"goal": "Write integration tests for the rate limiter endpoint"}
    with patch("app.workers.task_worker.execute_task_worker.delay"):
        for _ in range(2):
            assert (
                await app_client.post("/api/v1/tasks/", json=payload, headers=headers)
            ).status_code == 201
        blocked = await app_client.post("/api/v1/tasks/", json=payload, headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_retry_after_header_on_rate_limit(app_client, make_user, monkeypatch):
    from app.security import rate_limiter

    monkeypatch.setitem(rate_limiter.ENDPOINT_LIMITS, ("POST", "/api/v1/auth/login"), 1)
    data = {"username": "nobody@example.com", "password": "wrong"}
    await app_client.post("/api/v1/auth/login", data=data)
    r = await app_client.post("/api/v1/auth/login", data=data)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


@pytest.mark.asyncio
async def test_rate_limit_remaining_decrements(app_client, monkeypatch):
    from unittest.mock import patch
    from app.security import rate_limiter

    monkeypatch.setitem(rate_limiter.ENDPOINT_LIMITS, ("POST", "/api/v1/tasks/"), 5)
    r_reg = await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "remain@example.com",
            "password": "securepassword123",
            "full_name": "R",
        },
    )
    headers = {"Authorization": f"Bearer {r_reg.json()['access_token']}"}
    payload = {"goal": "Check that X-RateLimit-Remaining decreases on each call"}
    with patch("app.workers.task_worker.execute_task_worker.delay"):
        r1 = await app_client.post("/api/v1/tasks/", json=payload, headers=headers)
        r2 = await app_client.post("/api/v1/tasks/", json=payload, headers=headers)
    assert int(r1.headers["X-RateLimit-Remaining"]) > int(
        r2.headers["X-RateLimit-Remaining"]
    )


@pytest.mark.asyncio
async def test_500_response_has_no_stack_trace(app_client, monkeypatch):
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    @app.get("/api/v1/_test_boom")
    async def _boom():
        raise RuntimeError("secret internals")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/_test_boom")
    assert r.status_code == 500
    text = r.text.lower()
    assert "traceback" not in text
    assert "secret internals" not in text
    assert r.json()["code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_request_id_header_present(app_client):
    r = await app_client.get("/health")
    assert "X-Request-ID" in r.headers
    assert len(r.headers["X-Request-ID"]) >= 32


@pytest.mark.asyncio
async def test_sixth_login_attempt_rate_limited(app_client, monkeypatch):
    from app.security import rate_limiter

    monkeypatch.setitem(rate_limiter.ENDPOINT_LIMITS, ("POST", "/api/v1/auth/login"), 5)
    data = {"username": "brute@example.com", "password": "nope"}
    for _ in range(5):
        await app_client.post("/api/v1/auth/login", data=data)
    r = await app_client.post("/api/v1/auth/login", data=data)
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_invalid_jwt_structured_401(app_client):
    r = await app_client.get(
        "/api/v1/tasks/",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "UNAUTHORIZED"
    assert "request_id" in body


@pytest.mark.asyncio
async def test_cross_tenant_task_access_404(app_client):
    from unittest.mock import patch

    async def _reg(email):
        r = await app_client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "securepassword123", "full_name": "X"},
        )
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    headers_a = await _reg("cross-a@example.com")
    headers_b = await _reg("cross-b@example.com")
    with patch("app.workers.task_worker.execute_task_worker.delay"):
        created = await app_client.post(
            "/api/v1/tasks/",
            json={"goal": "Cross tenant access should return 404 not 403 for safety"},
            headers=headers_a,
        )
    r = await app_client.get(f"/api/v1/tasks/{created.json()['id']}", headers=headers_b)
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"

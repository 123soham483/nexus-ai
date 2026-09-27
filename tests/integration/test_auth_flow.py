"""End-to-end auth flow tests against the real ASGI app."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_register_login_me_flow(app_client):
    # Register
    r = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "supersecret", "full_name": "Alice"},
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    # /me with the access token
    r = await app_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["email"] == "alice@example.com"
    assert me["full_name"] == "Alice"
    assert "hashed_password" not in me
    assert me["tenant_id"]


async def test_login_returns_tokens(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "hunter2hunter2"},
    )
    # OAuth2 password flow uses form fields
    r = await app_client.post(
        "/api/v1/auth/login",
        data={"username": "bob@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


async def test_login_wrong_password_401(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "rightpassword"},
    )
    r = await app_client.post(
        "/api/v1/auth/login",
        data={"username": "carol@example.com", "password": "wrongpassword"},
    )
    assert r.status_code == 401


async def test_duplicate_email_409(app_client):
    payload = {"email": "dave@example.com", "password": "password123"}
    r1 = await app_client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = await app_client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 409


async def test_me_without_token_401(app_client):
    r = await app_client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_refresh_issues_new_access_token(app_client):
    reg = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "erin@example.com", "password": "password123"},
    )
    refresh_token = reg.json()["refresh_token"]
    r = await app_client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


async def test_logout_blacklists_token(app_client):
    reg = await app_client.post(
        "/api/v1/auth/register",
        json={"email": "frank@example.com", "password": "password123"},
    )
    access = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    # Works before logout
    assert (await app_client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    # Logout
    out = await app_client.post("/api/v1/auth/logout", headers=headers)
    assert out.status_code == 200

    # Same token now rejected
    assert (await app_client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_health_endpoint(app_client):
    r = await app_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

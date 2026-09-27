"""Focused tests for the dev-only demo account (scripts/create_demo_user.py).

The demo account is seeded straight into the DB (bypassing the register
endpoint's EmailStr validation, which rejects the special-use ``.local``
domain), so the tests prove the *documented login flow* still works for it:
OAuth2 form login -> JWT -> authenticated task access -> /auth/me.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

DEMO_EMAIL = "demo@nexusai.local"
DEMO_PASSWORD = "NexusDemo@2026!"


async def _seed_demo_user(db_session):
    """Mirror scripts/create_demo_user.py: same models, same hash_password."""
    from app.db.models.tenant import Tenant
    from app.db.models.user import User
    from app.security.auth import hash_password

    tenant = Tenant(
        name="Demo workspace (dev only)",
        slug="demo-workspace",
        chroma_collection_prefix="demo-workspace",
    )
    db_session.add(tenant)
    await db_session.flush()
    user = User(
        email=DEMO_EMAIL,
        hashed_password=hash_password(DEMO_PASSWORD),
        full_name="Demo User",
        tenant_id=tenant.id,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_demo_user_can_authenticate(db_session, api):
    """demo user can authenticate — POST /api/v1/auth/login (OAuth2 form)."""
    await _seed_demo_user(db_session)

    r = api.post(
        "/api/v1/auth/login",
        data={"username": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"


async def test_demo_user_wrong_password_rejected(db_session, api):
    await _seed_demo_user(db_session)

    r = api.post(
        "/api/v1/auth/login",
        data={"username": DEMO_EMAIL, "password": "wrong-password"},
    )
    assert r.status_code == 401


async def test_demo_user_can_access_authenticated_task_endpoint(db_session, api):
    """demo user can access authenticated task endpoint — GET /tasks/ + create."""
    await _seed_demo_user(db_session)

    tokens = api.post(
        "/api/v1/auth/login",
        data={"username": DEMO_EMAIL, "password": DEMO_PASSWORD},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Authenticated list (the request the dashboard makes right after login):
    r = api.get("/api/v1/tasks/", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"tasks": [], "total": 0, "limit": 20, "offset": 0}

    # And task creation with the demo credentials:
    with patch_demo_dispatch():
        r_create = api.post(
            "/api/v1/tasks/",
            json={"goal": "Create a simple Python function that calculates the factorial of a number."},
            headers=headers,
        )
    assert r_create.status_code == 201, r_create.text
    assert r_create.json()["status"] == "pending"

    r_list = api.get("/api/v1/tasks/", headers=headers)
    assert r_list.status_code == 200
    assert r_list.json()["total"] == 1


async def test_demo_user_me_returns_local_email_without_500(db_session, api):
    """GET /auth/me used to 500 (ResponseValidationError) because UserOut.email
    was an EmailStr and email-validator rejects the `.local` special-use domain
    at serialisation time. It must return the stored email as plain JSON."""
    await _seed_demo_user(db_session)

    tokens = api.post(
        "/api/v1/auth/login",
        data={"username": DEMO_EMAIL, "password": DEMO_PASSWORD},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = api.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == DEMO_EMAIL
    assert body["is_superuser"] is False


def patch_demo_dispatch():
    """Task creation dispatches to Celery; tests must not need a broker."""
    from unittest.mock import patch

    return patch("app.workers.task_worker.execute_task_worker.delay")

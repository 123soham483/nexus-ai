"""HallucinationScorer persistence (Step 4.3)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import Task, Tenant, User
from app.db.models.enums import TaskStatus
from app.db.models.hallucination_score import HallucinationScoreRecord
from app.observability.hallucination_scorer import HallucinationScorer


async def _seed_task(db_session, tenant_id, user_id):
    task = Task(
        user_id=user_id,
        tenant_id=tenant_id,
        goal="test goal for hallucination scorer",
        status=TaskStatus.COMPLETED,
    )
    db_session.add(task)
    await db_session.flush()
    return task


@pytest.mark.asyncio
async def test_record_score_persists_row(db_session, fake_redis):
    tenant = Tenant(name="t", slug="t-scorer", chroma_collection_prefix="t")
    db_session.add(tenant)
    await db_session.flush()
    user = User(
        email="h@example.com",
        hashed_password="x",
        full_name="H",
        tenant_id=tenant.id,
    )
    db_session.add(user)
    await db_session.flush()
    task = await _seed_task(db_session, tenant.id, user.id)
    tenant_id = str(tenant.id)
    task_id = str(task.id)
    scorer = HallucinationScorer(db_session=db_session, redis_client=fake_redis)
    await scorer.record_score(task_id, "hallucination_detector", 0.92, "pass", tenant_id)
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(HallucinationScoreRecord).where(
                HallucinationScoreRecord.task_id == uuid.UUID(task_id)
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].score == 0.92


@pytest.mark.asyncio
async def test_get_tenant_average_from_redis(db_session, fake_redis):
    tenant = Tenant(name="t2", slug="t2", chroma_collection_prefix="t2")
    db_session.add(tenant)
    await db_session.flush()
    user = User(email="h2@example.com", hashed_password="x", full_name="H", tenant_id=tenant.id)
    db_session.add(user)
    await db_session.flush()
    t1 = await _seed_task(db_session, tenant.id, user.id)
    t2 = await _seed_task(db_session, tenant.id, user.id)
    tenant_id = str(tenant.id)
    scorer = HallucinationScorer(db_session=db_session, redis_client=fake_redis)
    await scorer.record_score(str(t1.id), "hallucination_detector", 0.8, "pass", tenant_id)
    await scorer.record_score(str(t2.id), "hallucination_detector", 1.0, "pass", tenant_id)
    avg = await scorer.get_tenant_average(tenant_id)
    assert avg == 0.9


@pytest.mark.asyncio
async def test_get_agent_scores_filters_by_agent(db_session, fake_redis):
    tenant = Tenant(name="t3", slug="t3", chroma_collection_prefix="t3")
    db_session.add(tenant)
    await db_session.flush()
    user = User(email="h3@example.com", hashed_password="x", full_name="H", tenant_id=tenant.id)
    db_session.add(user)
    await db_session.flush()
    t1 = await _seed_task(db_session, tenant.id, user.id)
    t2 = await _seed_task(db_session, tenant.id, user.id)
    tenant_id = str(tenant.id)
    scorer = HallucinationScorer(db_session=db_session, redis_client=fake_redis)
    await scorer.record_score(str(t1.id), "coder", 0.5, "fail", tenant_id)
    await scorer.record_score(str(t2.id), "hallucination_detector", 0.95, "pass", tenant_id)
    scores = await scorer.get_agent_scores("coder", tenant_id)
    assert len(scores) == 1
    assert scores[0]["score"] == 0.5


@pytest.mark.asyncio
async def test_get_tenant_breakdown_includes_recent(db_session, fake_redis):
    tenant = Tenant(name="t4", slug="t4", chroma_collection_prefix="t4")
    db_session.add(tenant)
    await db_session.flush()
    user = User(email="h4@example.com", hashed_password="x", full_name="H", tenant_id=tenant.id)
    db_session.add(user)
    await db_session.flush()
    task = await _seed_task(db_session, tenant.id, user.id)
    tenant_id = str(tenant.id)
    scorer = HallucinationScorer(db_session=db_session, redis_client=fake_redis)
    await scorer.record_score(str(task.id), "hallucination_detector", 0.88, "pass", tenant_id)
    data = await scorer.get_tenant_breakdown(tenant_id)
    assert "tenant_average" in data
    assert "by_agent" in data
    assert len(data["recent"]) >= 1

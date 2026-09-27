"""Tests for the ORM models: creation, relationships, enums, JSON columns."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import AgentRun, CostRecord, Task, TaskStatus, Tenant, Trace, User


async def _make_tenant_and_user(session):
    tenant = Tenant(
        name="Acme",
        slug="acme",
        chroma_collection_prefix="acme",
    )
    session.add(tenant)
    await session.flush()  # assign tenant.id

    user = User(
        email="dev@acme.test",
        hashed_password="not-a-real-hash",
        full_name="Dev User",
        tenant_id=tenant.id,
    )
    session.add(user)
    await session.flush()
    return tenant, user


async def test_create_tenant_and_user(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    await db_session.commit()

    assert isinstance(tenant.id, uuid.UUID)
    assert tenant.is_active is True
    assert tenant.monthly_budget_usd == 100.0
    assert user.tenant_id == tenant.id
    assert user.is_active is True
    assert user.is_superuser is False


async def test_task_defaults_and_enum(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="Build a REST API")
    db_session.add(task)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(Task).where(Task.id == task.id))
    ).scalar_one()

    assert fetched.status == TaskStatus.PENDING
    assert fetched.context == {}
    assert fetched.agents_spawned == []
    assert fetched.actual_cost_usd == 0.0
    assert fetched.created_at is not None


async def test_task_json_columns_roundtrip(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(
        user_id=user.id,
        tenant_id=tenant.id,
        goal="Do something with structured context",
        context={"language": "python", "steps": [1, 2, 3]},
        agents_spawned=["coder", "tester"],
        routing_decision={"reasoning": "because"},
    )
    db_session.add(task)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(Task).where(Task.id == task.id))
    ).scalar_one()
    assert fetched.context["language"] == "python"
    assert fetched.context["steps"] == [1, 2, 3]
    assert fetched.agents_spawned == ["coder", "tester"]
    assert fetched.routing_decision["reasoning"] == "because"


async def test_relationships_backpopulate(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="A goal")
    db_session.add(task)
    await db_session.flush()

    run = AgentRun(
        task_id=task.id,
        agent_type="coder",
        agent_id="coder-1",
        llm_provider="claude",
        llm_model="claude-sonnet-4-6",
    )
    trace = Trace(task_id=task.id, event_type="task_started", sequence_number=0)
    cost = CostRecord(
        task_id=task.id,
        user_id=user.id,
        tenant_id=tenant.id,
        llm_model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.012,
    )
    db_session.add_all([run, trace, cost])
    await db_session.commit()

    # Reload task and traverse relationships
    fetched = (
        await db_session.execute(
            select(Task).where(Task.id == task.id)
        )
    ).scalar_one()
    await db_session.refresh(fetched, attribute_names=["agent_runs", "traces"])
    assert len(fetched.agent_runs) == 1
    assert fetched.agent_runs[0].agent_type == "coder"
    assert len(fetched.traces) == 1
    assert fetched.traces[0].event_type == "task_started"


async def test_agent_run_defaults(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="g")
    db_session.add(task)
    await db_session.flush()

    run = AgentRun(
        task_id=task.id,
        agent_type="tester",
        agent_id="tester-1",
        llm_provider="gemini",
        llm_model="gemini/gemini-2.5-flash",
    )
    db_session.add(run)
    await db_session.commit()

    assert run.status == "running"
    assert run.tools_called == []
    assert run.hallucination_detected is False
    assert run.cost_usd == 0.0

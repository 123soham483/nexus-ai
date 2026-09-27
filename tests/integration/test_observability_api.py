"""Integration tests for the Observability API: metrics and traces (tenant-scoped)."""
from __future__ import annotations

import pytest

from app.db.models import Task, TaskStatus, AgentRun, Trace

pytestmark = pytest.mark.integration


def test_metrics_requires_auth(api):
    r = api.get("/api/v1/observability/metrics")
    assert r.status_code == 401


async def test_metrics_empty_tenant_returns_zeros(api, make_user):
    _, _, headers = await make_user("obs1@acme.com")
    r = api.get("/api/v1/observability/metrics", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_tasks"] == 0
    assert data["tasks_by_status"] == {}
    assert data["total_agent_runs"] == 0
    assert data["total_cost_usd"] == 0.0
    assert data["total_tokens"] == 0
    assert data["avg_quality_score"] is None
    assert data["avg_duration_seconds"] is None


async def test_metrics_aggregates_seeded_data(api, make_user, db_session):
    tenant, user, headers = await make_user("obs2@acme.com")

    t1 = Task(user_id=user.id, tenant_id=tenant.id, goal="completed task",
              status=TaskStatus.COMPLETED, actual_cost_usd=1.0, tokens_used=100,
              quality_score=0.8, duration_seconds=10.0)
    t2 = Task(user_id=user.id, tenant_id=tenant.id, goal="failed task",
              status=TaskStatus.FAILED, actual_cost_usd=0.5, tokens_used=50)
    db_session.add_all([t1, t2])
    await db_session.flush()

    db_session.add_all([
        AgentRun(task_id=t1.id, agent_type="coder", agent_id="a1", llm_provider="claude",
                 llm_model="anthropic/claude-sonnet-4-6", status="completed"),
        AgentRun(task_id=t1.id, agent_type="tester", agent_id="a2", llm_provider="gemini-flash",
                 llm_model="gemini/gemini-2.5-flash", status="completed"),
    ])
    await db_session.commit()

    r = api.get("/api/v1/observability/metrics", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_tasks"] == 2
    assert data["tasks_by_status"] == {"completed": 1, "failed": 1}
    assert data["total_agent_runs"] == 2
    assert data["total_cost_usd"] == pytest.approx(1.5)
    assert data["total_tokens"] == 150
    assert data["avg_quality_score"] == pytest.approx(0.8)
    assert data["avg_duration_seconds"] == pytest.approx(10.0)


async def test_metrics_are_tenant_isolated(api, make_user, db_session):
    tenant_a, user_a, headers_a = await make_user("obs3a@acme.com")
    _, _, headers_b = await make_user("obs3b@acme.com")

    task = Task(user_id=user_a.id, tenant_id=tenant_a.id, goal="a task",
                status=TaskStatus.COMPLETED, actual_cost_usd=2.0)
    db_session.add(task)
    await db_session.commit()

    data_a = api.get("/api/v1/observability/metrics", headers=headers_a).json()
    data_b = api.get("/api/v1/observability/metrics", headers=headers_b).json()
    assert data_a["total_tasks"] == 1
    assert data_a["total_cost_usd"] == pytest.approx(2.0)
    assert data_b["total_tasks"] == 0
    assert data_b["total_cost_usd"] == 0.0


async def test_traces_are_tenant_scoped_and_filterable(api, make_user, db_session):
    tenant_a, user_a, headers_a = await make_user("obs4a@acme.com")
    _, user_b, headers_b = await make_user("obs4b@acme.com")

    task_a = Task(user_id=user_a.id, tenant_id=tenant_a.id, goal="a task")
    task_b = Task(user_id=user_b.id, tenant_id=user_b.tenant_id, goal="b task")
    db_session.add_all([task_a, task_b])
    await db_session.flush()

    db_session.add_all([
        Trace(task_id=task_a.id, event_type="task_started", event_data={"goal": "a"},
              sequence_number=1),
        Trace(task_id=task_a.id, event_type="task_completed", event_data={},
              sequence_number=2),
        Trace(task_id=task_b.id, event_type="task_started", event_data={"goal": "b"},
              sequence_number=1),
    ])
    await db_session.commit()

    # Tenant A sees only A's traces (newest first).
    r_a = api.get("/api/v1/observability/traces", headers=headers_a)
    assert r_a.status_code == 200, r_a.text
    data_a = r_a.json()
    assert len(data_a) == 2
    assert {t["event_type"] for t in data_a} == {"task_started", "task_completed"}

    # Tenant B sees only B's trace.
    r_b = api.get("/api/v1/observability/traces", headers=headers_b)
    assert len(r_b.json()) == 1
    assert r_b.json()[0]["task_id"] == str(task_b.id)

    # Event-type filter.
    filtered = api.get(
        "/api/v1/observability/traces", params={"event_type": "task_completed"},
        headers=headers_a,
    )
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["event_type"] == "task_completed"

    # Task filter narrows to that task.
    by_task = api.get(
        "/api/v1/observability/traces", params={"task_id": str(task_a.id)},
        headers=headers_a,
    )
    assert len(by_task.json()) == 2


def test_traces_requires_auth(api):
    r = api.get("/api/v1/observability/traces")
    assert r.status_code == 401

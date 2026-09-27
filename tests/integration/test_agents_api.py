"""Integration tests for the Agents API: registry listing and stats (tenant-scoped)."""
from __future__ import annotations

import pytest

from app.db.models import Task, TaskStatus, AgentRun

pytestmark = pytest.mark.integration


def test_list_agents_requires_auth(api):
    r = api.get("/api/v1/agents/")
    assert r.status_code == 401


async def test_list_agents_returns_all_types(api, make_user):
    _, _, headers = await make_user("agents1@acme.com")
    r = api.get("/api/v1/agents/", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    by_type = {a["agent_type"]: a for a in data}
    # The full Phase 2 roster (15 types incl. the non-LLM hitl_controller).
    assert len(data) == 15
    assert by_type["coder"]["model"] == "gemini/gemini-2.5-flash"
    assert by_type["coder"]["implemented"] is True
    assert by_type["coder"]["llm_agent"] is True
    assert by_type["hitl_controller"]["implemented"] is True
    assert by_type["hitl_controller"]["llm_agent"] is False
    assert by_type["tester"]["model"] == "gemini/gemini-2.5-flash"


async def test_stats_empty_tenant(api, make_user):
    _, _, headers = await make_user("agents2@acme.com")
    r = api.get("/api/v1/agents/stats", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["agents"] == []
    assert data["total_runs"] == 0


async def test_stats_aggregate_runs_success_and_cost(api, make_user, db_session):
    tenant, user, headers = await make_user("agents3@acme.com")
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="stats task",
                status=TaskStatus.COMPLETED)
    db_session.add(task)
    await db_session.flush()

    db_session.add_all([
        AgentRun(task_id=task.id, agent_type="coder", agent_id="a1", llm_provider="claude",
                 llm_model="anthropic/claude-sonnet-4-6", status="completed",
                 cost_usd=0.1, duration_seconds=5.0),
        AgentRun(task_id=task.id, agent_type="coder", agent_id="a2", llm_provider="claude",
                 llm_model="anthropic/claude-sonnet-4-6", status="completed",
                 cost_usd=0.2, duration_seconds=7.0),
        AgentRun(task_id=task.id, agent_type="tester", agent_id="a3", llm_provider="gemini-flash",
                 llm_model="gemini/gemini-2.5-flash", status="failed",
                 cost_usd=0.05, duration_seconds=3.0),
    ])
    await db_session.commit()

    r = api.get("/api/v1/agents/stats", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_runs"] == 3
    by_type = {a["agent_type"]: a for a in data["agents"]}
    assert by_type["coder"]["run_count"] == 2
    assert by_type["coder"]["success_count"] == 2
    assert by_type["coder"]["success_rate"] == pytest.approx(1.0)
    assert by_type["coder"]["total_cost_usd"] == pytest.approx(0.3)
    assert by_type["coder"]["avg_duration_seconds"] == pytest.approx(6.0)
    assert by_type["tester"]["run_count"] == 1
    assert by_type["tester"]["success_count"] == 0
    assert by_type["tester"]["success_rate"] == 0.0


async def test_stats_are_tenant_isolated(api, make_user, db_session):
    tenant_a, user_a, headers_a = await make_user("agents4a@acme.com")
    _, user_b, headers_b = await make_user("agents4b@acme.com")

    task_a = Task(user_id=user_a.id, tenant_id=tenant_a.id, goal="a task")
    task_b = Task(user_id=user_b.id, tenant_id=user_b.tenant_id, goal="b task")
    db_session.add_all([task_a, task_b])
    await db_session.flush()

    db_session.add_all([
        AgentRun(task_id=task_a.id, agent_type="coder", agent_id="a1", llm_provider="claude",
                 llm_model="anthropic/claude-sonnet-4-6", status="completed", cost_usd=0.1),
        AgentRun(task_id=task_b.id, agent_type="coder", agent_id="b1", llm_provider="claude",
                 llm_model="anthropic/claude-sonnet-4-6", status="completed", cost_usd=0.9),
    ])
    await db_session.commit()

    data_a = api.get("/api/v1/agents/stats", headers=headers_a).json()
    data_b = api.get("/api/v1/agents/stats", headers=headers_b).json()
    assert data_a["total_runs"] == 1
    assert data_a["agents"][0]["total_cost_usd"] == pytest.approx(0.1)
    assert data_b["total_runs"] == 1
    assert data_b["agents"][0]["total_cost_usd"] == pytest.approx(0.9)

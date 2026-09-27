"""Integration tests for the Cost API: estimate, budget, history (tenant-scoped)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Task, CostRecord

pytestmark = pytest.mark.integration


def test_estimate_requires_auth(api):
    r = api.post("/api/v1/cost/estimate", json={"agent_types": ["coder"]})
    assert r.status_code == 401


async def test_estimate_returns_per_agent_breakdown(api, make_user):
    _, _, headers = await make_user("cost1@acme.com")
    r = api.post(
        "/api/v1/cost/estimate",
        json={"agent_types": ["coder", "tester"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["agents"]) == 2
    by_type = {a["agent_type"]: a for a in data["agents"]}
    assert by_type["coder"]["model"] == "gemini/gemini-2.5-flash"
    assert by_type["tester"]["model"] == "gemini/gemini-2.5-flash"
    assert by_type["coder"]["estimated_cost_usd"] > 0
    total = sum(a["estimated_cost_usd"] for a in data["agents"])
    assert data["total_estimated_usd"] == pytest.approx(total)


async def test_estimate_default_plan_when_no_agent_types(api, make_user):
    _, _, headers = await make_user("cost2@acme.com")
    r = api.post("/api/v1/cost/estimate", json={}, headers=headers)
    assert r.status_code == 200
    agent_types = [a["agent_type"] for a in r.json()["agents"]]
    assert agent_types == ["planner", "coder", "tester", "validator"]


async def test_estimate_non_llm_agent_is_zero_cost(api, make_user):
    _, _, headers = await make_user("cost3@acme.com")
    r = api.post(
        "/api/v1/cost/estimate",
        json={"agent_types": ["hitl_controller"]},
        headers=headers,
    )
    assert r.status_code == 200
    item = r.json()["agents"][0]
    assert item["agent_type"] == "hitl_controller"
    assert item["estimated_cost_usd"] == 0.0
    assert item["model"] == "none"


async def test_budget_returns_position(api, make_user):
    _, _, headers = await make_user(
        "cost4@acme.com",
        tenant_kwargs={"monthly_budget_usd": 100.0, "current_month_spend_usd": 40.0},
    )
    r = api.get("/api/v1/cost/budget", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["monthly_budget_usd"] == 100.0
    assert data["current_month_spend_usd"] == 40.0
    assert data["remaining_usd"] == pytest.approx(60.0)
    assert data["exceeded"] is False


async def test_budget_exceeded_flag(api, make_user):
    _, _, headers = await make_user(
        "cost5@acme.com",
        tenant_kwargs={"monthly_budget_usd": 100.0, "current_month_spend_usd": 120.0},
    )
    r = api.get("/api/v1/cost/budget", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["exceeded"] is True
    assert data["remaining_usd"] == 0.0


async def test_history_empty_for_tenant_without_records(api, make_user):
    _, _, headers = await make_user("cost6@acme.com")
    r = api.get("/api/v1/cost/history", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_history_groups_cost_records_by_day(api, make_user, db_session):
    tenant, user, headers = await make_user("cost7@acme.com")
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="cost history task")
    db_session.add(task)
    await db_session.flush()

    day1 = datetime.now(timezone.utc) - timedelta(days=2)
    day2 = datetime.now(timezone.utc) - timedelta(days=1)

    db_session.add_all([
        CostRecord(task_id=task.id, user_id=user.id, tenant_id=tenant.id,
                   llm_model="openai/gpt-4o", input_tokens=1000, output_tokens=500,
                   cost_usd=0.01, recorded_at=day1),
        CostRecord(task_id=task.id, user_id=user.id, tenant_id=tenant.id,
                   llm_model="openai/gpt-4o", input_tokens=1000, output_tokens=500,
                   cost_usd=0.02, recorded_at=day1),
        CostRecord(task_id=task.id, user_id=user.id, tenant_id=tenant.id,
                   llm_model="anthropic/claude-sonnet-4-6", input_tokens=1000, output_tokens=500,
                   cost_usd=0.03, recorded_at=day2),
    ])
    await db_session.commit()

    r = api.get("/api/v1/cost/history", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    by_day = {d["date"]: d for d in data}
    assert by_day[str(day1.date())]["cost_usd"] == pytest.approx(0.03)
    assert by_day[str(day1.date())]["task_count"] == 1
    assert by_day[str(day2.date())]["cost_usd"] == pytest.approx(0.03)


async def test_history_is_tenant_isolated(api, make_user, db_session):
    tenant_a, user_a, headers_a = await make_user("cost8a@acme.com")
    _, _, headers_b = await make_user("cost8b@acme.com")

    task = Task(user_id=user_a.id, tenant_id=tenant_a.id, goal="tenant a task")
    db_session.add(task)
    await db_session.flush()
    db_session.add(CostRecord(
        task_id=task.id, user_id=user_a.id, tenant_id=tenant_a.id,
        llm_model="openai/gpt-4o", input_tokens=100, output_tokens=50, cost_usd=0.005,
    ))
    await db_session.commit()

    r_a = api.get("/api/v1/cost/history", headers=headers_a)
    assert len(r_a.json()) == 1

    r_b = api.get("/api/v1/cost/history", headers=headers_b)
    assert r_b.json() == []

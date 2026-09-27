"""Unit tests for Orchestrator (Step 1.11)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
import pytest

from app.core.orchestrator import Orchestrator
from app.core.router import RoutingPlan
from app.agents.base import AgentResult
from app.db.models import Task, TaskStatus, Tenant, User, AgentRun, CostRecord


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeRouter:
    def __init__(self, plan_data=None):
        self.plan_data = plan_data or RoutingPlan(
            agents=["coder", "tester"],
            sequential=["coder"],
            parallel_groups=[["tester"]],
            reasoning="Test reasoning",
            confidence=0.9,
            estimated_tokens={"coder": 1000, "tester": 500}
        )
        self.called = 0

    async def plan(self, goal, context, failure_patterns):
        self.called += 1
        self.last_goal = goal
        self.last_context = context
        self.last_failures = failure_patterns
        return self.plan_data


class FakeBroadcaster:
    def __init__(self):
        self.emitted = []

    async def emit(self, task_id, event_type, data):
        self.emitted.append((event_type, data))


class FakeShortMemory:
    def __init__(self):
        self.store = {}

    async def set_value(self, task_id, field, value):
        self.store[(str(task_id), field)] = value

    async def get_value(self, task_id, field):
        return self.store.get((str(task_id), field))


class FakeLongMemory:
    def __init__(self, failures=None):
        self.failures = failures or []
        self.stored_tasks = []
        self.stored_failures = []

    async def search_similar_failures(self, query, n_results=3):
        class FakeFailure:
            def __init__(self, content, failed_agent):
                self.content = content
                self.metadata = {"failed_agent": failed_agent}
        return [FakeFailure(f["error"], f["failed_agent"]) for f in self.failures]

    async def store_task_result(self, task_id, goal, result_summary, agent_types_used, cost_usd, quality_score):
        self.stored_tasks.append({
            "task_id": task_id,
            "goal": goal,
            "result_summary": result_summary,
            "agent_types_used": agent_types_used,
            "cost_usd": cost_usd,
            "quality_score": quality_score
        })

    async def store_failure(self, task_id, goal, error_summary, failed_agent):
        self.stored_failures.append({
            "task_id": task_id,
            "goal": goal,
            "error_summary": error_summary,
            "failed_agent": failed_agent
        })


class MockAgent:
    def __init__(self, agent_type, result_content="code output", cost=0.01, confidence=0.9, should_raise=False):
        self.agent_type = agent_type
        self.result_content = result_content
        self.cost = cost
        self.confidence = confidence
        self.should_raise = should_raise
        self.execute_calls = []

    async def execute(self, goal, context, task_id):
        self.execute_calls.append((goal, context, task_id))
        if self.should_raise:
            raise ValueError(f"Agent {self.agent_type} failure")
        return AgentResult(
            agent_type=self.agent_type,
            agent_id=f"{self.agent_type}-1",
            provider="mock",
            model="mock-model",
            system_prompt="system",
            user_prompt="user",
            content=self.result_content,
            parsed={"code": self.result_content, "explanation": "explanation text"},
            reasoning="agent reasoning",
            cost_usd=self.cost,
            confidence_score=self.confidence,
            input_tokens=100,
            output_tokens=200,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_seconds=0.1,
            success=True,
            error=None
        )


async def _make_tenant_and_user(session):
    tenant = Tenant(name="Acme", slug="acme", chroma_collection_prefix="acme")
    session.add(tenant)
    await session.flush()
    user = User(email="dev@acme.test", hashed_password="not-a-real-hash", full_name="Dev User", tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    return tenant, user


# ── Tests ────────────────────────────────────────────────────────────────────

async def test_execute_calls_router_once(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="write a script")
    db_session.add(task)
    await db_session.commit()

    router = FakeRouter()
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()
    agent = MockAgent("coder")

    def agent_factory(agent_type):
        return agent

    orchestrator = Orchestrator(
        router=router,
        agent_factory=agent_factory,
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)
    assert router.called == 1
    assert router.last_goal == "write a script"


async def test_sequential_agents_run_in_order(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="chain of agents")
    db_session.add(task)
    await db_session.commit()

    plan = RoutingPlan(
        agents=["coder", "tester"],
        sequential=["coder", "tester"],
        parallel_groups=[],
        reasoning="sequential only",
        confidence=0.8,
        estimated_tokens={}
    )
    router = FakeRouter(plan)
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()

    run_order = []

    class TrackedAgent:
        def __init__(self, name):
            self.name = name

        async def execute(self, goal, context, task_id):
            run_order.append(self.name)
            return AgentResult(
                agent_type=self.name,
                agent_id="id",
                provider="mock",
                model="mock",
                system_prompt="s",
                user_prompt="u",
                content="done",
                parsed={"explanation": "done"},
                confidence_score=0.9
            )

    agents = {"coder": TrackedAgent("coder"), "tester": TrackedAgent("tester")}
    orchestrator = Orchestrator(
        router=router,
        agent_factory=lambda name: agents[name],
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)
    assert run_order == ["coder", "tester"]


async def test_parallel_group_agents_run_in_parallel(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="run concurrent agents")
    db_session.add(task)
    await db_session.commit()

    plan = RoutingPlan(
        agents=["coder", "tester", "security"],
        sequential=["coder"],
        parallel_groups=[["tester", "security"]],
        reasoning="parallel tester and security",
        confidence=0.8,
        estimated_tokens={}
    )
    router = FakeRouter(plan)
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()

    execution_timestamps = {}

    class TimingAgent:
        def __init__(self, name):
            self.name = name

        async def execute(self, goal, context, task_id):
            execution_timestamps[self.name] = time.perf_counter()
            await asyncio.sleep(0.05)
            return AgentResult(
                agent_type=self.name,
                agent_id="id",
                provider="mock",
                model="mock",
                system_prompt="s",
                user_prompt="u",
                content="done",
                parsed={"explanation": "done"},
                confidence_score=0.9
            )

    agents = {
        "coder": TimingAgent("coder"),
        "tester": TimingAgent("tester"),
        "security": TimingAgent("security")
    }

    orchestrator = Orchestrator(
        router=router,
        agent_factory=lambda name: agents[name],
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)
    
    # tester and security ran basically simultaneously after coder
    assert execution_timestamps["coder"] < execution_timestamps["tester"]
    assert execution_timestamps["coder"] < execution_timestamps["security"]
    # difference between tester and security start is extremely small (concurrent)
    assert abs(execution_timestamps["tester"] - execution_timestamps["security"]) < 0.02


async def test_db_task_status_updates(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="status updates test")
    db_session.add(task)
    await db_session.commit()

    router = FakeRouter()
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()
    agent = MockAgent("coder")

    orchestrator = Orchestrator(
        router=router,
        agent_factory=lambda n: agent,
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)

    # Re-fetch task
    await db_session.refresh(task)
    assert task.status == TaskStatus.COMPLETED
    assert task.agents_spawned == ["coder", "tester"]
    assert task.estimated_cost_usd > 0
    assert task.actual_cost_usd == 0.02  # coder (0.01) + tester (0.01)
    assert task.quality_score == pytest.approx(0.9)


async def test_websocket_events_emitted_in_order(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="stream events")
    db_session.add(task)
    await db_session.commit()

    router = FakeRouter()
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()
    agent = MockAgent("coder")

    orchestrator = Orchestrator(
        router=router,
        agent_factory=lambda n: agent,
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)

    events = [e[0] for e in broadcaster.emitted]
    expected = [
        "task_started",
        "failure_patterns_checked",
        "routing_complete",
        "cost_estimated",
        "agent_spawned",      # sequential coder
        "agent_completed",
        "agent_spawned",      # parallel tester
        "agent_completed",
        "quality_check",
        "hallucination_check",
        "learning_stored",
        "task_completed"
    ]
    assert events == expected


async def test_agent_run_rows_created(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="agent runs verification")
    db_session.add(task)
    await db_session.commit()

    router = FakeRouter()
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()

    orchestrator = Orchestrator(
        router=router,
        agent_factory=lambda n: MockAgent(n),
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)

    # Check AgentRun records
    from sqlalchemy import select
    result = await db_session.execute(select(AgentRun).where(AgentRun.task_id == task.id))
    runs = result.scalars().all()
    assert len(runs) == 2
    assert {r.agent_type for r in runs} == {"coder", "tester"}
    for r in runs:
        assert r.status == "completed"


async def test_cost_record_rows_created_per_agent_run(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="cost record verification")
    db_session.add(task)
    await db_session.commit()

    orchestrator = Orchestrator(
        router=FakeRouter(),
        agent_factory=lambda n: MockAgent(n),
        short_memory=FakeShortMemory(),
        long_memory=FakeLongMemory(),
        broadcaster=FakeBroadcaster(),
        db_session=db_session,
    )

    # Pass string ids (as the Celery worker does) to exercise UUID coercion
    await orchestrator.execute_task(
        str(task.id), task.goal, {}, str(tenant.id), str(user.id)
    )

    from sqlalchemy import select
    result = await db_session.execute(
        select(CostRecord).where(CostRecord.task_id == task.id)
    )
    records = result.scalars().all()
    # One CostRecord per agent run (sequential coder + parallel tester)
    assert len(records) == 2
    for rec in records:
        assert rec.tenant_id == tenant.id
        assert rec.user_id == user.id
        assert rec.agent_run_id is not None
        assert rec.llm_model == "mock-model"
        assert rec.input_tokens == 100
        assert rec.output_tokens == 200
        assert rec.cost_usd == pytest.approx(0.01)


async def test_on_agent_exception_failure_stored_in_ltm(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="exceptional task")
    db_session.add(task)
    await db_session.commit()

    router = FakeRouter()
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()
    agent = MockAgent("coder", should_raise=True)

    orchestrator = Orchestrator(
        router=router,
        agent_factory=lambda n: agent,
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    with pytest.raises(ValueError, match="Agent coder failure"):
        await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)

    await db_session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert "Agent coder failure" in task.result["error"]
    
    assert len(long_mem.stored_failures) == 1
    assert long_mem.stored_failures[0]["failed_agent"] == "orchestrator"
    assert "Agent coder failure" in long_mem.stored_failures[0]["error_summary"]


async def test_final_result_stored_on_success(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="success storage test")
    db_session.add(task)
    await db_session.commit()

    router = FakeRouter()
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()
    agent = MockAgent("coder", result_content="successful code output")

    orchestrator = Orchestrator(
        router=router,
        agent_factory=lambda n: agent,
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)

    assert len(long_mem.stored_tasks) == 1
    assert long_mem.stored_tasks[0]["task_id"] == task.id
    assert long_mem.stored_tasks[0]["result_summary"] == "successful code output"


async def test_total_cost_rollup(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="cost rollup task")
    db_session.add(task)
    await db_session.commit()

    router = FakeRouter()
    broadcaster = FakeBroadcaster()
    short_mem = FakeShortMemory()
    long_mem = FakeLongMemory()
    
    # coder costs 0.05, tester costs 0.02
    agent_coder = MockAgent("coder", cost=0.05)
    agent_tester = MockAgent("tester", cost=0.02)
    agents = {"coder": agent_coder, "tester": agent_tester}

    orchestrator = Orchestrator(
        router=router,
        agent_factory=lambda name: agents[name],
        short_memory=short_mem,
        long_memory=long_mem,
        broadcaster=broadcaster,
        db_session=db_session
    )

    await orchestrator.execute_task(task.id, task.goal, {}, tenant.id, user.id)

    await db_session.refresh(task)
    assert task.actual_cost_usd == pytest.approx(0.07)

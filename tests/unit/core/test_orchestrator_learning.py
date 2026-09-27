"""Orchestrator self-learning wiring: real hallucination score + 3 learning levels.

Phase 3, Step 3.2.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agents.base import AgentResult
from app.core.orchestrator import Orchestrator
from app.core.router import RoutingPlan
from app.db.models import Task, Tenant, User


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeRouter:
    """Router that records whether tenant context was forwarded."""

    def __init__(self, plan_data: RoutingPlan, accept_tenant=True):
        self.plan_data = plan_data
        self.accept_tenant = accept_tenant
        self.last_tenant = "<never called>"

    async def plan(self, goal, context, failure_patterns):
        self.last_tenant = None
        return self.plan_data


class FakeTenantAwareRouter(FakeRouter):
    async def plan(self, goal, context, failure_patterns, tenant_id=""):
        self.last_tenant = tenant_id
        return self.plan_data


class FakeBroadcaster:
    def __init__(self):
        self.emitted = []

    async def emit(self, task_id, event_type, data):
        self.emitted.append((event_type, data))

    def events(self):
        return [e[0] for e in self.emitted]

    def data_for(self, event_type):
        return [d for t, d in self.emitted if t == event_type]


class FakeShortMemory:
    def __init__(self):
        self.store = {}

    async def set_value(self, task_id, field, value):
        self.store[(str(task_id), field)] = value


class FakeLongMemory:
    def __init__(self):
        self.stored_tasks = []
        self.stored_failures = []

    async def search_similar_failures(self, query, n_results=3):
        return []

    async def store_task_result(
        self, task_id, goal, result_summary, agent_types_used,
        cost_usd, quality_score, extra_metadata=None,
    ):
        self.stored_tasks.append({"extra_metadata": extra_metadata})

    async def store_failure(
        self, task_id, goal, error_summary, failed_agent, extra_metadata=None,
    ):
        self.stored_failures.append({"failed_agent": failed_agent})


class FakeLearningEngine:
    def __init__(self, fail_store_success=False):
        self.fail_store_success = fail_store_success
        self.success_calls = []
        self.causal_calls = []
        self.confidence_calls = []
        self.failure_calls = []

    async def store_success(self, task_id, goal, results, plan, cost, quality, tenant_id):
        self.success_calls.append(
            {"task_id": task_id, "plan": plan, "cost": cost,
             "quality": quality, "tenant_id": tenant_id}
        )
        if self.fail_store_success:
            raise RuntimeError("vector store down")

    async def analyze_why(self, task_id, goal, results, tenant_id=""):
        self.causal_calls.append({"task_id": task_id, "tenant_id": tenant_id})
        return "why it worked"

    async def update_routing_confidence(self, goal, agent_types, quality, tenant_id):
        self.confidence_calls.append(
            {"goal": goal, "agents": list(agent_types),
             "quality": quality, "tenant_id": tenant_id}
        )

    async def learn_from_failure(self, task_id, goal, error, failed_agent, tenant_id=""):
        self.failure_calls.append({"error": error, "failed_agent": failed_agent})


class StubAgent:
    """Deterministic agent returning a caller-controlled AgentResult."""

    def __init__(self, agent_type, content="out", confidence=0.9,
                 parsed=None, success=True):
        self.agent_type = agent_type
        self.content = content
        self.confidence = confidence
        self.parsed = parsed or {"code": content, "explanation": content}
        self.success = success
        self.calls = 0

    async def execute(self, goal, context, task_id):
        self.calls += 1
        return AgentResult(
            agent_type=self.agent_type,
            agent_id=f"{self.agent_type}-1",
            provider="mock",
            model="mock-model",
            system_prompt="s",
            user_prompt="u",
            content=self.content,
            parsed=self.parsed,
            reasoning="reasoning",
            cost_usd=0.01,
            confidence_score=self.confidence,
            input_tokens=10,
            output_tokens=20,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_seconds=0.01,
            success=self.success,
            error=None if self.success else "boom",
        )


async def _make_tenant_and_user(session):
    tenant = Tenant(name="Acme", slug="acme", chroma_collection_prefix="acme")
    session.add(tenant)
    await session.flush()
    user = User(email="dev@acme.test", hashed_password="h", full_name="Dev", tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    return tenant, user


async def _new_task(session, tenant, user, goal="learn from me"):
    task = Task(user_id=user.id, tenant_id=tenant.id, goal=goal)
    session.add(task)
    await session.commit()
    return task


def _plan(agents, sequential=None, parallel=None):
    sequential = sequential if sequential is not None else list(agents)
    return RoutingPlan(
        agents=list(agents),
        sequential=list(sequential),
        parallel_groups=list(parallel or []),
        reasoning="r",
        confidence=0.9,
        estimated_tokens={},
    )


def _build(router, agents, learning_engine=None, inline=True, long_mem=None,
           db_session=None):
    return Orchestrator(
        router=router,
        agent_factory=lambda name: agents[name],
        short_memory=FakeShortMemory(),
        long_memory=long_mem or FakeLongMemory(),
        broadcaster=FakeBroadcaster(),
        db_session=db_session,
        learning_engine=learning_engine,
        learning_causal_inline=inline,
    )


# ── Learning wiring ──────────────────────────────────────────────────────────

async def test_success_runs_all_three_learning_levels(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    engine = FakeLearningEngine()
    router = FakeTenantAwareRouter(_plan(["coder"]))
    agents = {"coder": StubAgent("coder")}
    orch = _build(router, agents, engine)

    await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    assert len(engine.success_calls) == 1
    assert engine.success_calls[0]["tenant_id"] == str(tenant.id)
    assert engine.success_calls[0]["quality"] == pytest.approx(0.9)
    assert len(engine.causal_calls) == 1          # Level 2 (inline)
    assert len(engine.confidence_calls) == 1      # Level 3
    assert engine.confidence_calls[0]["agents"] == ["coder"]

    stored = orch.broadcaster.data_for("learning_stored")
    assert stored[0]["levels"] == ["storage", "causal", "routing_confidence"]


async def test_tenant_id_is_forwarded_to_tenant_aware_router(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    router = FakeTenantAwareRouter(_plan(["coder"]))
    orch = _build(router, {"coder": StubAgent("coder")}, FakeLearningEngine())

    await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    assert router.last_tenant == str(tenant.id)


async def test_legacy_router_without_tenant_kwarg_still_works(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    router = FakeRouter(_plan(["coder"]))
    orch = _build(router, {"coder": StubAgent("coder")}, FakeLearningEngine())

    await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    assert router.last_tenant is None  # never passed, never crashed


async def test_broken_learning_engine_does_not_fail_the_task(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    engine = FakeLearningEngine(fail_store_success=True)
    orch = _build(
        FakeRouter(_plan(["coder"])), {"coder": StubAgent("coder")}, engine,
        db_session=db_session,
    )

    result = await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    await db_session.refresh(task)
    assert task.status.value == "completed"
    assert result["summary"]
    assert engine.confidence_calls  # Level 3 still attempted after Level 1 blew up


async def test_failure_path_calls_learn_from_failure(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user, goal="explode")

    class Exploding(StubAgent):
        async def execute(self, goal, context, task_id):
            raise ValueError("agent blew up")

    engine = FakeLearningEngine()
    orch = _build(FakeRouter(_plan(["coder"])), {"coder": Exploding("coder")}, engine)

    with pytest.raises(ValueError, match="agent blew up"):
        await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    assert len(engine.failure_calls) == 1
    assert engine.failure_calls[0]["failed_agent"] == "orchestrator"
    assert "agent blew up" in engine.failure_calls[0]["error"]


# ── Real hallucination score ─────────────────────────────────────────────────

async def test_hallucination_check_uses_detector_score(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    detector = StubAgent(
        "hallucination_detector", content="0.2", parsed={"score": 0.2}, confidence=0.2
    )
    plan = _plan(["coder", "hallucination_detector"])
    orch = _build(FakeRouter(plan), {"coder": StubAgent("coder"),
                                     "hallucination_detector": detector})

    await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    check = orch.broadcaster.data_for("hallucination_check")[0]
    assert check["score"] == pytest.approx(0.2)
    assert check["passed"] is False


async def test_hallucination_check_passes_when_detector_is_happy(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    detector = StubAgent(
        "hallucination_detector", content="0.95", parsed={"score": 0.95}, confidence=0.95
    )
    plan = _plan(["coder", "hallucination_detector"])
    orch = _build(FakeRouter(plan), {"coder": StubAgent("coder"),
                                     "hallucination_detector": detector})

    await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    assert orch.broadcaster.data_for("hallucination_check")[0]["passed"] is True
    assert "hallucination_retry" not in orch.broadcaster.events()


async def test_no_detector_means_neutral_passing_check(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    orch = _build(FakeRouter(_plan(["coder"])), {"coder": StubAgent("coder")})

    await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    check = orch.broadcaster.data_for("hallucination_check")[0]
    assert (check["score"], check["passed"]) == (1.0, True)


# ── Hallucination retry sweep ────────────────────────────────────────────────

async def test_low_score_retries_failed_content_agent(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    class FailsOnce(StubAgent):
        """Fails its first execute, succeeds on the retry."""

        async def execute(self, goal, context, task_id):
            self.calls += 1
            ok = self.calls > 1
            return AgentResult(
                agent_type="coder", agent_id="c-1", provider="mock", model="mock-model",
                system_prompt="s", user_prompt="u", content="c", parsed={"code": "c"},
                confidence_score=0.9, success=ok, error=None if ok else "bad output",
            )

    coder = FailsOnce("coder")
    detector = StubAgent("hallucination_detector", parsed={"score": 0.1}, confidence=0.1)
    plan = _plan(["coder", "hallucination_detector"])
    orch = _build(FakeRouter(plan), {"coder": coder, "hallucination_detector": detector})

    await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    retries = orch.broadcaster.data_for("hallucination_retry")
    assert retries and retries[0]["agents"] == ["coder"]
    assert coder.calls == 2  # original + one retry


async def test_validators_are_never_retried(db_session):
    tenant, user = await _make_tenant_and_user(db_session)
    task = await _new_task(db_session, tenant, user)

    validator = StubAgent("validator", success=False, content="rejected")
    detector = StubAgent("hallucination_detector", parsed={"score": 0.1}, confidence=0.1)
    plan = _plan(["validator", "hallucination_detector"])
    orch = _build(FakeRouter(plan), {"validator": validator,
                                     "hallucination_detector": detector})

    await orch.execute_task(str(task.id), task.goal, {}, str(tenant.id), str(user.id))

    assert "hallucination_retry" not in orch.broadcaster.events()
    assert validator.calls == 1

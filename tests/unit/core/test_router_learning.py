"""Router self-correction via learned routing confidence (Phase 3, Step 3.2)."""
from __future__ import annotations

import json

from app.core.router import DEFAULT_PLAN, RoutingPlan, TaskRouter
from app.llm import LLMProvider


class FakeLearningEngine:
    """Minimal stand-in: records the hint lookup, returns canned hints."""

    def __init__(self, hints=None, raises=False):
        self.hints = hints or []
        self.raises = raises
        self.calls = []

    async def get_routing_hints(self, goal, candidate_agents=None, tenant_id="", limit=5):
        self.calls.append({"goal": goal, "tenant_id": tenant_id})
        if self.raises:
            raise RuntimeError("redis exploded")
        return list(self.hints)


def _capturing_router(payload, engine=None):
    captured: dict = {}

    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        captured["prompt"] = messages[-1]["content"]
        return {"content": json.dumps(payload), "input_tokens": 1, "output_tokens": 1}

    router = TaskRouter(
        llm_provider=LLMProvider(complete_fn=_fn), learning_engine=engine
    )
    return router, captured


PLAN_WITHOUT_DOCS = {
    "agents": ["planner", "coder", "validator"],
    "sequential": ["planner", "coder", "validator"],
    "parallel_groups": [],
    "reasoning": "code task",
    "confidence": 0.9,
    "estimated_tokens": {"coder": 1000},
}


async def test_learned_hints_are_injected_into_the_prompt():
    engine = FakeLearningEngine(hints=[("login", "security", 3)])
    router, captured = _capturing_router(PLAN_WITHOUT_DOCS, engine)

    await router.plan("implement login", tenant_id="t1")

    assert "login->security(3)" in captured["prompt"]
    assert engine.calls[0]["tenant_id"] == "t1"


async def test_prompt_says_none_learned_when_engine_has_no_history():
    engine = FakeLearningEngine(hints=[])
    router, captured = _capturing_router(PLAN_WITHOUT_DOCS, engine)

    await router.plan("implement login")

    assert "(none learned yet)" in captured["prompt"]


async def test_strong_learned_agent_is_readded_before_validator():
    engine = FakeLearningEngine(hints=[("login", "security", 3)])
    router, _ = _capturing_router(PLAN_WITHOUT_DOCS, engine)

    plan = await router.plan("implement login")

    assert "security" in plan.agents
    assert plan.agents[-1] == "validator"  # validator invariant preserved
    assert "security" in plan.sequential
    assert plan.sequential[-1] == "validator"
    assert "Learned routing" in plan.reasoning


async def test_weak_learned_agent_is_not_readded():
    engine = FakeLearningEngine(hints=[("login", "security", 1)])
    router, _ = _capturing_router(PLAN_WITHOUT_DOCS, engine)

    plan = await router.plan("implement login")

    assert plan.agents == ["planner", "coder", "validator"]


async def test_learned_agent_already_in_plan_is_not_duplicated():
    engine = FakeLearningEngine(hints=[("code", "coder", 5)])
    router, _ = _capturing_router(PLAN_WITHOUT_DOCS, engine)

    plan = await router.plan("write code")

    assert plan.agents.count("coder") == 1
    assert "Learned routing" not in plan.reasoning


async def test_hint_lookup_failure_does_not_break_routing():
    engine = FakeLearningEngine(raises=True)
    router, _ = _capturing_router(PLAN_WITHOUT_DOCS, engine)

    plan = await router.plan("implement login")

    assert plan.agents == ["planner", "coder", "validator"]


async def test_no_engine_leaves_phase2_plan_unchanged():
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        return {"content": json.dumps(PLAN_WITHOUT_DOCS), "input_tokens": 1, "output_tokens": 1}

    router = TaskRouter(llm_provider=LLMProvider(complete_fn=_fn))
    plan = await router.plan("write code", tenant_id="t1")

    assert plan.agents == ["planner", "coder", "validator"]
    assert plan.reasoning == "code task"


async def test_broken_llm_with_engine_still_returns_default_plan():
    engine = FakeLearningEngine(hints=[("login", "security", 3)])

    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        return {"content": "not json at all {{{", "input_tokens": 1, "output_tokens": 1}

    router = TaskRouter(llm_provider=LLMProvider(complete_fn=_fn), learning_engine=engine)
    plan = await router.plan("implement login")

    assert plan == DEFAULT_PLAN


def test_apply_learned_hints_preserves_other_plan_fields():
    plan = RoutingPlan(
        agents=["coder", "validator"],
        sequential=["coder", "validator"],
        parallel_groups=[["tester"]],
        reasoning="r",
        confidence=0.75,
        estimated_tokens={"coder": 900},
    )

    out = TaskRouter._apply_learned_hints(plan, [("docs", "docs", 4)])

    assert out.parallel_groups == [["tester"]]
    assert out.confidence == 0.75
    assert out.estimated_tokens == {"coder": 900}
    assert out.agents == ["coder", "docs", "validator"]

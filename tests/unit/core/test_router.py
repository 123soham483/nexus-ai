"""Unit tests for TaskRouter (Step 1.10)."""
from __future__ import annotations

import json

import pytest

from app.core.router import DEFAULT_PLAN, RoutingPlan, TaskRouter
from app.llm import LLMProvider


def _router_with_json(payload: dict) -> TaskRouter:
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        return {"content": json.dumps(payload), "input_tokens": 10, "output_tokens": 50}

    return TaskRouter(llm_provider=LLMProvider(complete_fn=_fn))


def _router_broken() -> TaskRouter:
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        return {"content": "not valid json {{{", "input_tokens": 1, "output_tokens": 1}

    return TaskRouter(llm_provider=LLMProvider(complete_fn=_fn))


AUTH_PLAN = {
    "agents": ["planner", "coder", "security", "tester", "validator"],
    "sequential": ["planner", "coder", "validator"],
    "parallel_groups": [["security", "tester"]],
    "reasoning": "Auth task needs security review",
    "confidence": 0.9,
    "estimated_tokens": {"planner": 800, "coder": 2500, "security": 1200},
}

BUILD_PLAN = {
    "agents": ["planner", "coder", "tester", "validator"],
    "sequential": ["planner", "coder", "tester", "validator"],
    "parallel_groups": [],
    "reasoning": "Code build task",
    "confidence": 0.88,
    "estimated_tokens": {"coder": 3000, "tester": 1500},
}


async def test_plan_returns_routing_plan_dataclass():
    router = _router_with_json(BUILD_PLAN)
    plan = await router.plan("build a REST API")
    assert isinstance(plan, RoutingPlan)
    assert "coder" in plan.agents


async def test_auth_goal_includes_security_agent():
    router = _router_with_json(AUTH_PLAN)
    plan = await router.plan("implement JWT auth login")
    assert "security" in plan.agents


async def test_build_goal_includes_coder_and_tester():
    router = _router_with_json(BUILD_PLAN)
    plan = await router.plan("build a parser module")
    assert "coder" in plan.agents
    assert "tester" in plan.agents


async def test_validator_always_last_in_agents_list():
    router = _router_with_json(AUTH_PLAN)
    plan = await router.plan("implement oauth login flow")
    assert plan.agents[-1] == "validator"


async def test_planner_first_when_present():
    router = _router_with_json(BUILD_PLAN)
    plan = await router.plan("multi-step build task")
    assert plan.agents[0] == "planner"


async def test_json_parse_failure_returns_default_plan():
    router = _router_broken()
    plan = await router.plan("anything")
    assert plan == DEFAULT_PLAN


async def test_failure_patterns_passed_to_llm_prompt():
    captured: dict = {}

    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        captured["prompt"] = messages[-1]["content"]
        return {"content": json.dumps(BUILD_PLAN), "input_tokens": 1, "output_tokens": 1}

    router = TaskRouter(llm_provider=LLMProvider(complete_fn=_fn))
    patterns = [{"error": "timeout", "agent": "coder"}]
    await router.plan("build api", failure_patterns=patterns)
    assert "timeout" in captured["prompt"]


def test_parse_llm_json_handles_code_blocks():
    router = TaskRouter()
    
    # Test Markdown code block wrapping
    raw_block = "```json\n{\"agents\": [\"coder\"]}\n```"
    parsed = router._parse_llm_json(raw_block)
    assert parsed == {"agents": ["coder"]}

    # Test raw text prefix/suffix
    embedded = "Here is the plan:\n{\"agents\": [\"validator\"]}\nHope it helps!"
    parsed_embedded = router._parse_llm_json(embedded)
    assert parsed_embedded == {"agents": ["validator"]}


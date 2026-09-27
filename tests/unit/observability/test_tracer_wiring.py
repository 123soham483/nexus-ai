"""Tracing through the *real* orchestrator, agent and provider (Step 4.1).

These tests do not test NexusTracer in isolation — they run the actual pipeline
with a shared fake tracer to prove the wiring produces the promised hierarchy:
one task span, one agent span under it, one llm span under that.
"""
from __future__ import annotations

import pytest

from app.agents.base import AgentResult
from app.agents.development.coder_agent import CoderAgent
from app.core.orchestrator import Orchestrator
from app.core.router import RoutingPlan
from app.llm import AllProvidersFailedError, LLMMessage, LLMProvider
from app.observability.tracer import (
    COST_USD,
    FALLBACK_USED,
    INPUT_TOKENS,
    LATENCY_MS,
    LLM_ATTEMPTS,
    LLM_ERROR,
    OUTPUT_TOKENS,
    TASK_ID,
    TOOL_NAME,
    TOOL_SUCCESS,
    NexusTracer,
)
from app.security.sandbox import SandboxResult

# ``TesterAgent`` starts with "Test" → keep pytest from collecting the class.
from app.agents.quality.tester_agent import TesterAgent as TesterAgentCls

TesterAgentCls.__test__ = False
from tests.unit.observability.test_tracer import FakeTracer

TASK = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"


# ── fakes ────────────────────────────────────────────────────────────────────

class FakeRouter:
    def __init__(self, plan: RoutingPlan):
        self.plan_data = plan

    async def plan(self, goal, context, failure_patterns):
        return self.plan_data


class FakeShortMemory:
    async def set_value(self, task_id, field, value):
        return None


class FakeLongMemory:
    async def search_similar_failures(self, query, n_results=3):
        return []

    async def store_task_result(self, *a, **k):
        return None

    async def store_failure(self, *a, **k):
        return None


class FakeSandbox:
    def __init__(self, result=None):
        self.result = result or SandboxResult(exit_code=0, stdout="2 passed")
        self.executed = []

    async def run_python(self, code, **kwargs):
        self.executed.append(code)
        return self.result


#: A realistic coder response, so the agent's confidence (and therefore the
#: task's aggregate quality score) is actually non-zero.
CODER_RESPONSE = (
    "REASONING:\nUse a module-level function.\n\n"
    "CODE:\n" + "\n".join(
        "def placeholder_%d(x):" % i for i in range(6)
    ) + "\n    return x\n\n"
    "EXPLANATION:\nA tiny helper module."
)


def _completion(content=CODER_RESPONSE, input_tokens=100, output_tokens=50):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        return {
            "content": content,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    return _fn


def _plan(agents=("coder",)) -> RoutingPlan:
    return RoutingPlan(
        agents=list(agents),
        sequential=list(agents),
        parallel_groups=[],
        reasoning="single agent",
        confidence=0.9,
        estimated_tokens={a: 100 for a in agents},
    )


def _orchestrator(tracer, agents, plan=None) -> Orchestrator:
    return Orchestrator(
        router=FakeRouter(plan or _plan()),
        agent_factory=lambda agent_type: agents[agent_type],
        short_memory=FakeShortMemory(),
        long_memory=FakeLongMemory(),
        broadcaster=None,
        tracer=tracer,
    )


# ── the full pipeline ────────────────────────────────────────────────────────

async def test_pipeline_emits_one_nested_task_agent_llm_span_chain():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    llm = LLMProvider(complete_fn=_completion(), tracer=tracer)
    agent = CoderAgent(llm=llm, tracer=tracer)

    await _orchestrator(tracer, {"coder": agent}).execute_task(
        TASK, "write a script", {}, TENANT, USER
    )

    task_spans = fake.by_kind("task")
    agent_spans = fake.by_kind("agent")
    llm_spans = fake.by_kind("llm")

    assert len(task_spans) == 1
    assert len(agent_spans) == 1
    assert len(llm_spans) == 1
    # The hierarchy the spec promises: task → agent → llm.
    assert agent_spans[0].parent is task_spans[0]
    assert llm_spans[0].parent is agent_spans[0]
    assert task_spans[0].parent is None


async def test_llm_span_records_the_real_token_and_cost_facts():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    llm = LLMProvider(
        complete_fn=_completion(input_tokens=120, output_tokens=340), tracer=tracer
    )
    agent = CoderAgent(llm=llm, tracer=tracer)

    await _orchestrator(tracer, {"coder": agent}).execute_task(
        TASK, "write a script", {}, TENANT, USER
    )

    attrs = fake.by_kind("llm")[0].attributes
    assert attrs[INPUT_TOKENS] == 120
    assert attrs[OUTPUT_TOKENS] == 340
    assert attrs[COST_USD] > 0                      # gemini pricing applied
    assert attrs["gen_ai.system"] == "gemini"
    assert attrs[LATENCY_MS] >= 0


async def test_agent_span_records_confidence_and_success_facts():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    llm = LLMProvider(complete_fn=_completion(), tracer=tracer)
    agent = CoderAgent(llm=llm, tracer=tracer)

    await _orchestrator(tracer, {"coder": agent}).execute_task(
        TASK, "write a script", {}, TENANT, USER
    )

    attrs = fake.by_kind("agent")[0].attributes
    assert attrs["nexus.agent.type"] == "coder"
    assert attrs[TASK_ID] == TASK
    assert 0.0 <= attrs["nexus.agent.confidence"] <= 1.0
    assert attrs["nexus.agent.id"]


async def test_task_span_records_routing_and_outcome():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    llm = LLMProvider(complete_fn=_completion(), tracer=tracer)
    agent = CoderAgent(llm=llm, tracer=tracer)

    await _orchestrator(tracer, {"coder": agent}).execute_task(
        TASK, "write a script", {}, TENANT, USER
    )

    attrs = fake.by_kind("task")[0].attributes
    assert attrs["nexus.routing.agents"] == "coder"
    assert attrs["nexus.routing.confidence"] == 0.9
    assert attrs["nexus.task.status"] == "completed"
    assert attrs["nexus.task.actual_cost_usd"] > 0
    assert attrs["nexus.quality.score"] > 0
    assert attrs["nexus.hallucination.passed"] is True


async def test_failed_task_marks_the_root_span_failed():
    class Exploding(CoderAgent):
        async def execute(self, task, context=None, task_id=None):
            raise ValueError("agent blew up")

    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    agent = Exploding(llm=LLMProvider(complete_fn=_completion(), tracer=tracer),
                      tracer=tracer)

    with pytest.raises(ValueError, match="agent blew up"):
        await _orchestrator(tracer, {"coder": agent}).execute_task(
            TASK, "write a script", {}, TENANT, USER
        )

    assert fake.by_kind("task")[0].attributes["nexus.task.status"] == "failed"


# ── provider-level fallback visibility ───────────────────────────────────────

async def test_llm_span_records_which_provider_fell_back():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    calls = {"n": 0}

    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("claude is down")
        return {"content": "ok", "input_tokens": 5, "output_tokens": 7}

    llm = LLMProvider(
        complete_fn=_fn,
        providers=["claude", "gemini"],
        max_retries=1,
        retry_backoff_base=0,
        tracer=tracer,
    )

    result = await llm.complete([LLMMessage("user", "hi")], agent_type="coder")

    assert result.fallback_used is True
    span = fake.by_kind("llm")[0]
    assert span.attributes[LLM_ATTEMPTS] == 2
    assert span.attributes[FALLBACK_USED] is True
    assert span.attributes["gen_ai.system"] == "claude"   # the fallback that answered (primary is gemini per AGENT_LLM_MAP)
    assert any(name == "llm.provider_failed" for name, _ in span.events)


async def test_llm_span_records_a_total_provider_outage():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)

    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        raise RuntimeError("everything is down")

    llm = LLMProvider(
        complete_fn=_fn,
        providers=["claude"],
        max_retries=1,
        retry_backoff_base=0,
        tracer=tracer,
    )

    with pytest.raises(AllProvidersFailedError):
        await llm.complete([LLMMessage("user", "hi")], agent_type="coder")

    span = fake.by_kind("llm")[0]
    assert "claude" in span.attributes[LLM_ERROR]
    assert any(name == "llm.provider_failed" for name, _ in span.events)


# ── tool span ────────────────────────────────────────────────────────────────

async def test_tester_agent_records_a_tool_span_for_sandbox_execution():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    llm = LLMProvider(
        complete_fn=_completion(
            "TEST_PLAN:\ncover it\n\nTEST_CODE:\nprint('hi')\n\nEXPECTED_RESULTS:\npass"
        ),
        tracer=tracer,
    )
    agent = TesterAgentCls(llm=llm, sandbox=FakeSandbox(), tracer=tracer)

    await agent.execute("write tests for the parser", {}, TASK)

    tool = fake.by_kind("tool")[0]
    assert tool.attributes[TOOL_NAME] == "docker_sandbox"
    assert tool.attributes[TOOL_SUCCESS] is True
    assert tool.attributes["nexus.tool.exit_code"] == 0
    # The sandbox call is nested inside the tester's own agent span.
    assert tool.parent is fake.by_kind("agent")[0]


async def test_failing_sandbox_run_is_visible_on_the_tool_span():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    llm = LLMProvider(
        complete_fn=_completion(
            "TEST_PLAN:\nplan\n\nTEST_CODE:\nassert False\n\nEXPECTED_RESULTS:\npass"
        ),
        tracer=tracer,
    )
    failing = FakeSandbox(SandboxResult(exit_code=1, stderr="AssertionError"))
    agent = TesterAgentCls(llm=llm, sandbox=failing, tracer=tracer)

    await agent.execute("write tests", {}, TASK)

    tool = fake.by_kind("tool")[0]
    assert tool.attributes[TOOL_SUCCESS] is False
    assert tool.attributes["nexus.tool.exit_code"] == 1

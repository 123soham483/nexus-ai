"""Unit tests for BaseAgent (Step 1.6).

The LLM provider and both memories are injected as fakes, so the full agent
lifecycle is exercised without Redis, Chroma, network, or a database.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents import AgentResult, BaseAgent
from app.llm import LLMProvider


# ── fakes ────────────────────────────────────────────────────────────────────
def make_llm(content="result text", *, input_tokens=12, output_tokens=8, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["model"] = model
        return {"content": content, "input_tokens": input_tokens, "output_tokens": output_tokens}

    return LLMProvider(complete_fn=_fn)


class FakeShortTerm:
    def __init__(self):
        self.store: dict = {}

    async def get_messages(self, task_id, limit=None):
        return list(self.store.get(str(task_id), []))

    async def add_message(self, task_id, role, content):
        self.store.setdefault(str(task_id), []).append({"role": role, "content": content})


class _Hit:
    def __init__(self, document):
        self.document = document


class FakeLongTerm:
    def __init__(self, docs):
        self._docs = docs
        self.queries = []

    async def search(self, query, n_results=5, where=None):
        self.queries.append(query)
        return [_Hit(d) for d in self._docs[:n_results]]


class EchoAgent(BaseAgent):
    agent_type = "coder"  # maps to "gemini" in AGENT_LLM_MAP
    system_prompt = "You are Echo."

    def parse_response(self, content):
        return {"echo": content.strip()}


# ── tests ────────────────────────────────────────────────────────────────────
async def test_run_returns_agent_result():
    agent = EchoAgent(llm=make_llm("hello world"))
    result = await agent.run("do a thing")

    assert isinstance(result, AgentResult)
    assert result.agent_type == "coder"
    assert result.provider == "gemini"  # routed via AGENT_LLM_MAP
    assert result.model == "gemini/gemini-2.5-flash"
    assert result.content == "hello world"
    assert result.parsed == {"echo": "hello world"}
    assert result.input_tokens == 12 and result.output_tokens == 8
    assert result.cost_usd > 0
    assert result.duration_seconds is not None
    assert result.started_at is not None and result.completed_at is not None


async def test_system_and_user_prompt_sent():
    capture: dict = {}
    agent = EchoAgent(llm=make_llm(capture=capture))
    await agent.run("build a parser", context={"lang": "python"})

    msgs = capture["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "You are Echo."
    assert msgs[-1]["role"] == "user"
    assert "build a parser" in msgs[-1]["content"]
    assert "python" in msgs[-1]["content"]  # context serialized in


async def test_long_term_memory_injected_into_prompt():
    capture: dict = {}
    ltm = FakeLongTerm(["prior insight A", "prior insight B"])
    agent = EchoAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.run("solve it")

    assert ltm.queries == ["solve it"]  # searched with the goal by default
    assert result.memory_retrieved == ["prior insight A", "prior insight B"]
    assert "prior insight A" in capture["messages"][-1]["content"]


async def test_short_term_history_loaded_and_turn_stored():
    task_id = uuid.uuid4()
    stm = FakeShortTerm()
    await stm.add_message(task_id, "user", "earlier question")
    await stm.add_message(task_id, "assistant", "earlier answer")

    capture: dict = {}
    agent = EchoAgent(llm=make_llm("fresh answer", capture=capture), short_term=stm)
    await agent.run("new question", task_id=task_id)

    roles = [m["role"] for m in capture["messages"]]
    # system, prior user, prior assistant, current user
    assert roles == ["system", "user", "assistant", "user"]

    # The new turn was appended (2 prior + 2 new = 4).
    stored = await stm.get_messages(task_id)
    assert len(stored) == 4
    assert stored[-1] == {"role": "assistant", "content": "fresh answer"}


async def test_store_false_skips_persistence():
    task_id = uuid.uuid4()
    stm = FakeShortTerm()
    agent = EchoAgent(llm=make_llm(), short_term=stm)
    await agent.run("q", task_id=task_id, store=False)
    assert await stm.get_messages(task_id) == []


async def test_provider_override_beats_agent_map():
    agent = EchoAgent(llm=make_llm(), provider="gemini")
    result = await agent.run("x")
    assert result.provider == "gemini"


async def test_to_agent_run_builds_orm_row():
    agent = EchoAgent(llm=make_llm("code here"))
    result = await agent.run("write code")
    task_id = uuid.uuid4()

    run = result.to_agent_run(task_id)
    assert run.task_id == task_id
    assert run.agent_type == "coder"
    assert run.llm_provider == "gemini"
    assert run.llm_model == "gemini/gemini-2.5-flash"
    assert run.llm_response == "code here"
    assert run.input_tokens == 12
    assert run.cost_usd > 0
    assert run.status == "completed"

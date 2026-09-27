"""Unit tests for DebuggerAgent (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.development.debugger_agent import DebuggerAgent
from app.llm import LLMProvider


COMPLETE_RESPONSE = """SYMPTOM:
The API returns 500 on empty payloads for /users.

ROOT_CAUSE:
The handler indexes into body['name'] without a guard, so an empty dict raises KeyError.

FIX:
def create_user(body: dict) -> User:
    name = (body or {}).get("name")
    if not name:
        raise ValueError("name is required")
    return User(name=name)

VERIFICATION:
Run pytest tests/test_users.py -k create_user_empty and confirm the ValueError path.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["called"] = True
        return {"content": content, "input_tokens": 120, "output_tokens": 240}

    return LLMProvider(complete_fn=_fn)


class FakeLongTerm:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.searched = False
        self.stored = False
        self.last_store_args = None

    async def search_similar_failures(self, query, n_results=3):
        self.searched = True
        self.last_query = query
        return self.hits

    async def store_task_result(self, task_id, goal, result_summary, agent_types, cost, quality):
        self.stored = True
        self.last_store_args = {
            "task_id": task_id,
            "goal": goal,
            "result_summary": result_summary,
            "agent_types": agent_types,
            "cost": cost,
            "quality": quality,
        }


class _Hit:
    def __init__(self, content):
        self.content = content


async def test_execute_returns_agent_result_with_debugger_type():
    agent = DebuggerAgent(llm=make_llm())
    result = await agent.execute("fix the /users 500 bug", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "debugger"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_parse_response_extracts_sections():
    agent = DebuggerAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "empty payloads" in parsed["symptom"]
    assert "KeyError" in parsed["root_cause"]
    assert "def create_user" in parsed["fix"]
    assert "pytest tests" in parsed["verification"]


async def test_parse_response_handles_missing_sections():
    agent = DebuggerAgent()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["symptom"] == ""
    assert parsed["root_cause"] == ""
    assert parsed["fix"] == ""
    assert parsed["verification"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = DebuggerAgent()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["fix"] == ""


async def test_confidence_full_response_is_1():
    agent = DebuggerAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_fix():
    agent = DebuggerAgent()
    partial = {"symptom": "x", "root_cause": "", "fix": "", "verification": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.1)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = DebuggerAgent(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("fix the bug", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["debugger"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior failure: KeyError on empty body")])
    capture: dict = {}
    agent = DebuggerAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("fix the bug", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior failure: KeyError on empty body" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior failure: KeyError on empty body"]

"""Unit tests for TesterAgent (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
# ``TesterAgent`` starts with "Test" and would be collected as a pytest test
# class (it has an __init__) — opt it out and alias the binding for clarity.
from app.agents.quality.tester_agent import TesterAgent as TesterAgentCls

TesterAgentCls.__test__ = False  # not a pytest test class
from app.llm import LLMProvider


COMPLETE_RESPONSE = """TEST_PLAN:
Cover the factorial edge cases: n<0 raises, n=0 and n=1 return 1, plus a large value for performance.

TEST_CODE:
def test_factorial_negative_raises():
    with pytest.raises(ValueError):
        factorial(-1)

def test_factorial_zero_and_one():
    assert factorial(0) == 1
    assert factorial(1) == 1

def test_factorial_large():
    assert factorial(10) == 3628800

EXPECTED_RESULTS:
Run pytest tests/test_factorial.py -v — all three tests pass.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["temperature"] = temperature
            capture["called"] = True
        return {"content": content, "input_tokens": 100, "output_tokens": 200}

    return LLMProvider(complete_fn=_fn)


class FakeLongTerm:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.searched = False
        self.stored = False
        self.last_store_args = None

    async def search_similar_tasks(self, query, n_results=5, min_quality_score=0.7):
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


async def test_execute_returns_agent_result_with_tester_type():
    agent = TesterAgentCls(llm=make_llm())
    result = await agent.execute("test the factorial function", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "tester"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_parse_response_extracts_sections():
    agent = TesterAgentCls()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "edge cases" in parsed["test_plan"]
    assert "def test_factorial_negative_raises" in parsed["test_code"]
    assert "pytest tests" in parsed["expected_results"]


async def test_parse_response_handles_missing_sections():
    agent = TesterAgentCls()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["test_plan"] == ""
    assert parsed["test_code"] == ""
    assert parsed["expected_results"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = TesterAgentCls()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["test_code"] == ""


async def test_confidence_full_response_is_1():
    agent = TesterAgentCls()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_test_code():
    agent = TesterAgentCls()
    partial = {"test_plan": "x", "test_code": "", "expected_results": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = TesterAgentCls(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("test it", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["tester"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)
    assert "def test_factorial" in ltm.last_store_args["result_summary"]


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior tests: use parametrize for edge cases")])
    capture: dict = {}
    agent = TesterAgentCls(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("test it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior tests: use parametrize" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior tests: use parametrize for edge cases"]

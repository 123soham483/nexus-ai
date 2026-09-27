"""Unit tests for PlannerAgent (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.coordination.planner_agent import PlannerAgent
from app.llm import LLMProvider


COMPLETE_RESPONSE = """ANALYSIS:
The goal decomposes into three sequential phases with a shared data dependency between phases two and three.

PLAN:
1. Scaffold the project structure and interfaces (`def scaffold()`).
2. Implement the core pipeline with tests.
3. Wire the API layer and run the validator.

SUCCESS_CRITERIA:
All tests pass, the API responds within budget, and the validator approves the output.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["called"] = True
        return {"content": content, "input_tokens": 150, "output_tokens": 300}

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


async def test_execute_returns_agent_result_with_planner_type():
    agent = PlannerAgent(llm=make_llm())
    result = await agent.execute("plan the new auth module", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "planner"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_parse_response_extracts_sections():
    agent = PlannerAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "sequential phases" in parsed["analysis"]
    assert "Scaffold the project" in parsed["plan"]
    assert "validator approves" in parsed["success_criteria"]


async def test_parse_response_handles_missing_sections():
    agent = PlannerAgent()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["analysis"] == ""
    assert parsed["plan"] == ""
    assert parsed["success_criteria"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = PlannerAgent()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["plan"] == ""


async def test_confidence_full_response_is_1():
    agent = PlannerAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_plan():
    agent = PlannerAgent()
    partial = {"analysis": "x", "plan": "", "success_criteria": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = PlannerAgent(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("plan it", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["planner"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)
    assert "Scaffold" in ltm.last_store_args["result_summary"]


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior plan: order phases by dependency")])
    capture: dict = {}
    agent = PlannerAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("plan it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior plan: order phases by dependency" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior plan: order phases by dependency"]

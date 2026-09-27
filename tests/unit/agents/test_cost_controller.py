"""Unit tests for CostController (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.coordination.cost_controller import CostController
from app.llm import LLMProvider


COMPLETE_RESPONSE = """COST_ANALYSIS:
Most spend comes from the coder agent's long outputs and the token-heavy estimator path.

ESTIMATE:
Planned run: planner 1k + coder 3k (each `def generate()` call averages 3k output tokens) + tester 1.5k + validator 0.5k → ~$0.06 per task.

RECOMMENDATIONS:
1. Route tester to gemini-flash (already done).
2. Cap coder output_tokens at 2k.
3. Batch parallel agents to share context.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["called"] = True
        return {"content": content, "input_tokens": 180, "output_tokens": 360}

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


async def test_execute_returns_agent_result_with_cost_controller_type():
    agent = CostController(llm=make_llm())
    result = await agent.execute("estimate the run cost", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "cost_controller"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_parse_response_extracts_sections():
    agent = CostController()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "coder agent" in parsed["cost_analysis"]
    assert "0.06" in parsed["estimate"]
    assert "gemini-flash" in parsed["recommendations"]


async def test_parse_response_handles_missing_sections():
    agent = CostController()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["cost_analysis"] == ""
    assert parsed["estimate"] == ""
    assert parsed["recommendations"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = CostController()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["estimate"] == ""


async def test_confidence_full_response_is_1():
    agent = CostController()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_estimate():
    agent = CostController()
    partial = {"cost_analysis": "x", "estimate": "", "recommendations": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = CostController(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("estimate it", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["cost_controller"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)
    assert "0.06" in ltm.last_store_args["result_summary"]


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior cost: cap output tokens")])
    capture: dict = {}
    agent = CostController(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("estimate it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior cost: cap output tokens" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior cost: cap output tokens"]

"""Unit tests for OptimizerAgent (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.development.optimizer_agent import OptimizerAgent
from app.llm import LLMProvider


COMPLETE_RESPONSE = """ANALYSIS:
The loop rebuilds the result list from scratch on every iteration, making this O(n^2).

CODE:
def dedupe(items: list) -> list:
    seen: set = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

RESULTS:
Worst case drops from O(n^2) to O(n); benchmark with pytest-benchmark.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["called"] = True
        return {"content": content, "input_tokens": 110, "output_tokens": 220}

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


async def test_execute_returns_agent_result_with_optimizer_type():
    agent = OptimizerAgent(llm=make_llm())
    result = await agent.execute("optimize the dedupe loop", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "optimizer"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_parse_response_extracts_sections():
    agent = OptimizerAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "O(n^2)" in parsed["analysis"]
    assert "def dedupe" in parsed["code"]
    assert "O(n)" in parsed["results"]


async def test_parse_response_handles_missing_sections():
    agent = OptimizerAgent()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["analysis"] == ""
    assert parsed["code"] == ""
    assert parsed["results"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = OptimizerAgent()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["code"] == ""


async def test_confidence_full_response_is_1():
    agent = OptimizerAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_code():
    agent = OptimizerAgent()
    partial = {"analysis": "x", "code": "", "results": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = OptimizerAgent(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("optimize it", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["optimizer"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior optimization: use a set for dedupe")])
    capture: dict = {}
    agent = OptimizerAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("optimize it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior optimization: use a set for dedupe" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior optimization: use a set for dedupe"]

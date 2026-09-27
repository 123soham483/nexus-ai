"""Unit tests for CoderAgent (Step 1.9).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.development.coder_agent import CoderAgent
from app.agents.base import AgentResult
from app.llm import LLMProvider


# ── fakes ────────────────────────────────────────────────────────────────────
COMPLETE_RESPONSE = """REASONING:
I will implement a factorial function using recursion with a base case.

CODE:
def factorial(n: int) -> int:
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return 1
    return n * factorial(n - 1)

EXPLANATION:
Computes n! recursively. Handles n=0/1 as base cases and rejects negatives.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
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


# ── tests ────────────────────────────────────────────────────────────────────
async def test_execute_returns_agent_result_with_coder_type():
    agent = CoderAgent(llm=make_llm())
    result = await agent.execute("write factorial in python", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "coder"
    assert result.provider == "gemini"


async def test_parse_response_extracts_sections():
    agent = CoderAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "recursion" in parsed["reasoning"].lower()
    assert "def factorial" in parsed["code"]
    assert "Computes n!" in parsed["explanation"]


async def test_parse_response_handles_missing_sections():
    agent = CoderAgent()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["reasoning"] == ""
    assert parsed["code"] == ""
    assert parsed["explanation"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_confidence_high_for_complete_response():
    agent = CoderAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_incomplete_response():
    agent = CoderAgent()
    assert agent._calculate_confidence({"reasoning": "", "code": "", "explanation": ""}) == 0.0
    assert agent._calculate_confidence({"reasoning": "hi", "code": "x", "explanation": ""}) == 0.3


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = CoderAgent(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("write factorial", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior: use type hints")])
    capture: dict = {}
    agent = CoderAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("write a parser", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior: use type hints" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior: use type hints"]

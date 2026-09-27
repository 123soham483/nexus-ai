"""Unit tests for ValidatorAgent (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.coordination.validator_agent import ValidatorAgent
from app.llm import LLMProvider


COMPLETE_RESPONSE = """REQUIREMENTS:
The handler must return 200 with valid JSON, reject malformed input with 400, and stay under 200ms p95.

VALIDATION:
1. PASS — `def handle_request()` returns 200 for a valid payload (test 12).
2. FAIL — empty payload raises KeyError instead of returning 400 (test 13).
3. PASS — p95 latency 120ms under load (k6 run 4).

VERDICT:
FAIL — requirement 2 is not met; fix the empty-payload path before merge.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["temperature"] = temperature
            capture["called"] = True
        return {"content": content, "input_tokens": 160, "output_tokens": 320}

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


async def test_execute_returns_agent_result_with_validator_type():
    agent = ValidatorAgent(llm=make_llm())
    result = await agent.execute("validate the handler", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "validator"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_execute_uses_deterministic_temperature():
    capture: dict = {}
    agent = ValidatorAgent(llm=make_llm(capture=capture))
    await agent.execute("validate the handler", {}, task_id=uuid.uuid4())
    assert capture["temperature"] == 0.0


async def test_parse_response_extracts_sections():
    agent = ValidatorAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "200ms p95" in parsed["requirements"]
    assert "KeyError" in parsed["validation"]
    assert "FAIL" in parsed["verdict"]


async def test_parse_response_handles_missing_sections():
    agent = ValidatorAgent()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["requirements"] == ""
    assert parsed["validation"] == ""
    assert parsed["verdict"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = ValidatorAgent()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["validation"] == ""


async def test_confidence_full_response_is_1():
    agent = ValidatorAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_validation():
    agent = ValidatorAgent()
    partial = {"requirements": "x", "validation": "", "verdict": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = ValidatorAgent(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("validate it", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["validator"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)
    assert "KeyError" in ltm.last_store_args["result_summary"]


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior validation: check empty payloads")])
    capture: dict = {}
    agent = ValidatorAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("validate it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior validation: check empty payloads" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior validation: check empty payloads"]

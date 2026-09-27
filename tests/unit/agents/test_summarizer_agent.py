"""Unit tests for SummarizerAgent (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.knowledge.summarizer_agent import SummarizerAgent
from app.llm import LLMProvider


COMPLETE_RESPONSE = """SUMMARY:
The design doc proposes a three-stage pipeline with explicit error boundaries.

KEY_POINTS:
- Stage 1 validates input; the `class Validator` handles schema errors.
- Stage 2 runs the work; retries are bounded to three attempts.
- Stage 3 persists results transactionally; rollback on failure.
- Observability: every stage emits a structured log line.

CONCLUSION:
The pipeline is sound for production if error boundaries stay explicit.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["called"] = True
        return {"content": content, "input_tokens": 60, "output_tokens": 120}

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


async def test_execute_returns_agent_result_with_summarizer_type():
    agent = SummarizerAgent(llm=make_llm())
    result = await agent.execute("summarize the pipeline design", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "summarizer"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_parse_response_extracts_sections():
    agent = SummarizerAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "three-stage pipeline" in parsed["summary"]
    assert "Stage 1 validates" in parsed["key_points"]
    assert "sound for production" in parsed["conclusion"]


async def test_parse_response_handles_missing_sections():
    agent = SummarizerAgent()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["summary"] == ""
    assert parsed["key_points"] == ""
    assert parsed["conclusion"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = SummarizerAgent()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["key_points"] == ""


async def test_confidence_full_response_is_1():
    agent = SummarizerAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_key_points():
    agent = SummarizerAgent()
    partial = {"summary": "x", "key_points": "", "conclusion": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = SummarizerAgent(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("summarize it", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["summarizer"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)
    assert "three-stage pipeline" in ltm.last_store_args["result_summary"]


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior summary: keep caveats intact")])
    capture: dict = {}
    agent = SummarizerAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("summarize it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior summary: keep caveats intact" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior summary: keep caveats intact"]

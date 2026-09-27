"""Unit tests for ResearchAgent (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.knowledge.research_agent import ResearchAgent
from app.llm import LLMProvider


COMPLETE_RESPONSE = """SUMMARY:
Exponential backoff with jitter is the recommended retry strategy for transient failures.

FINDINGS:
1. The reference implementation `def retry()` shows linear backoff — the most common mistake.
2. AWS SDKs default to exponential backoff with full jitter; both reduce thundering-herd risk.
3. Fixed retry counts without backoff amplify cascading failures under load.

SOURCES:
- AWS Architecture Blog: Timeout, retry, and backoff
- Stripe: Error handling — retry with exponential backoff
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["called"] = True
        return {"content": content, "input_tokens": 70, "output_tokens": 140}

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


async def test_execute_returns_agent_result_with_research_type():
    agent = ResearchAgent(llm=make_llm())
    result = await agent.execute("research retry strategies", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "research"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_parse_response_extracts_sections():
    agent = ResearchAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "Exponential backoff" in parsed["summary"]
    assert "thundering-herd" in parsed["findings"]
    assert "AWS Architecture Blog" in parsed["sources"]


async def test_parse_response_handles_missing_sections():
    agent = ResearchAgent()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["summary"] == ""
    assert parsed["findings"] == ""
    assert parsed["sources"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = ResearchAgent()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["findings"] == ""


async def test_confidence_full_response_is_1():
    agent = ResearchAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_findings():
    agent = ResearchAgent()
    partial = {"summary": "x", "findings": "", "sources": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = ResearchAgent(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("research it", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["research"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)
    assert "Exponential backoff" in ltm.last_store_args["result_summary"]


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior research: cite primary sources")])
    capture: dict = {}
    agent = ResearchAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("research it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior research: cite primary sources" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior research: cite primary sources"]

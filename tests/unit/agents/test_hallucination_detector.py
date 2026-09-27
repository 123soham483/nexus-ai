"""Unit tests for HallucinationDetector (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.coordination.hallucination_detector import HallucinationDetector
from app.llm import LLMProvider


COMPLETE_RESPONSE = """CLAIMS:
1. \"The system supports 10k concurrent users.\"
2. \"The `def retry()` helper handles all transient failures.\"

EVIDENCE:
1. UNSUPPORTED — no load test above 1k users exists in the repo.
2. PARTIAL — `def retry()` handles 3 retries but raises on rate-limit errors.

VERDICT:
HALLUCINATION — claim 1 is unsupported; flag for revision.
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["temperature"] = temperature
            capture["called"] = True
        return {"content": content, "input_tokens": 170, "output_tokens": 340}

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


async def test_execute_returns_agent_result_with_detector_type():
    agent = HallucinationDetector(llm=make_llm())
    result = await agent.execute("check the summary for hallucinations", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "hallucination_detector"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_execute_uses_deterministic_temperature():
    capture: dict = {}
    agent = HallucinationDetector(llm=make_llm(capture=capture))
    await agent.execute("check the summary", {}, task_id=uuid.uuid4())
    assert capture["temperature"] == 0.0


async def test_parse_response_extracts_sections():
    agent = HallucinationDetector()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "10k concurrent" in parsed["claims"]
    assert "UNSUPPORTED" in parsed["evidence"]
    assert "HALLUCINATION" in parsed["verdict"]


async def test_parse_response_handles_missing_sections():
    agent = HallucinationDetector()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["claims"] == ""
    assert parsed["evidence"] == ""
    assert parsed["verdict"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = HallucinationDetector()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["evidence"] == ""


async def test_confidence_full_response_is_1():
    agent = HallucinationDetector()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_evidence():
    agent = HallucinationDetector()
    partial = {"claims": "x", "evidence": "", "verdict": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_stores_in_long_term_memory():
    ltm = FakeLongTerm()
    agent = HallucinationDetector(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("check it", {}, task_id=task_id)
    assert ltm.stored is True
    assert ltm.last_store_args["task_id"] == task_id
    assert ltm.last_store_args["agent_types"] == ["hallucination_detector"]
    assert ltm.last_store_args["quality"] == pytest.approx(1.0)
    assert "UNSUPPORTED" in ltm.last_store_args["result_summary"]


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior audit: unsupported load claims")])
    capture: dict = {}
    agent = HallucinationDetector(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("check it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior audit: unsupported load claims" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior audit: unsupported load claims"]

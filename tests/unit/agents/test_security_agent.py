"""Unit tests for SecurityAgent (Phase 2).

All dependencies are injected fakes — no Redis, Chroma, network, or DB.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.base import AgentResult
from app.agents.quality.security_agent import SecurityAgent
from app.llm import LLMProvider


COMPLETE_RESPONSE = """THREAT_MODEL:
The auth handler is internet-facing; trust boundary is the HTTP layer. Threat surface: injection, auth bypass, secret leakage.

VULNERABILITIES:
1. [CWE-89 / CRITICAL] Raw SQL interpolation in `def login()` — the username parameter is concatenated into the query (line 14).
2. [CWE-798 / HIGH] Hardcoded API key in settings.py.
3. [CWE-287 / MED] Password comparison uses plain == instead of a constant-time check.

REMEDIATION:
1. Parameterize the query with bound parameters.
2. Move the key to an env var and rotate it.
3. Use bcrypt.checkpw (already used elsewhere in the codebase).
"""


def make_llm(content=COMPLETE_RESPONSE, *, capture=None):
    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        if capture is not None:
            capture["messages"] = messages
            capture["temperature"] = temperature
            capture["called"] = True
        return {"content": content, "input_tokens": 90, "output_tokens": 180}

    return LLMProvider(complete_fn=_fn)


class FakeLongTerm:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.searched = False
        self.stored = False
        self.last_store_args = None
        self.failure_stored = False
        self.last_failure_args = None

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

    async def store_failure(self, task_id, goal, error_summary, failed_agent):
        self.failure_stored = True
        self.last_failure_args = {
            "task_id": task_id,
            "goal": goal,
            "error_summary": error_summary,
            "failed_agent": failed_agent,
        }


class _Hit:
    def __init__(self, content):
        self.content = content


async def test_execute_returns_agent_result_with_security_type():
    agent = SecurityAgent(llm=make_llm())
    result = await agent.execute("audit the auth handler", {}, task_id=uuid.uuid4())
    assert isinstance(result, AgentResult)
    assert result.agent_type == "security"
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"


async def test_execute_uses_deterministic_temperature():
    capture: dict = {}
    agent = SecurityAgent(llm=make_llm(capture=capture))
    await agent.execute("audit the auth handler", {}, task_id=uuid.uuid4())
    assert capture["temperature"] == 0.0


async def test_parse_response_extracts_sections():
    agent = SecurityAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert "internet-facing" in parsed["threat_model"]
    assert "CWE-89" in parsed["vulnerabilities"]
    assert "bcrypt.checkpw" in parsed["remediation"]


async def test_parse_response_handles_missing_sections():
    agent = SecurityAgent()
    parsed = agent.parse_response("just some unstructured text")
    assert parsed["threat_model"] == ""
    assert parsed["vulnerabilities"] == ""
    assert parsed["remediation"] == ""
    assert parsed["raw"] == "just some unstructured text"


async def test_parse_response_puts_everything_in_raw_when_no_headers():
    agent = SecurityAgent()
    parsed = agent.parse_response("no headers here at all")
    assert parsed["raw"] == "no headers here at all"
    assert parsed["vulnerabilities"] == ""


async def test_confidence_full_response_is_1():
    agent = SecurityAgent()
    parsed = agent.parse_response(COMPLETE_RESPONSE)
    assert agent._calculate_confidence(parsed) == pytest.approx(1.0)


async def test_confidence_low_for_missing_vulnerabilities():
    agent = SecurityAgent()
    partial = {"threat_model": "x", "vulnerabilities": "", "remediation": ""}
    assert agent._calculate_confidence(partial) == pytest.approx(0.3)
    assert agent._calculate_confidence({}) == 0.0


async def test_high_confidence_findings_store_to_failures():
    ltm = FakeLongTerm()
    agent = SecurityAgent(llm=make_llm(), long_term=ltm)
    task_id = uuid.uuid4()
    await agent.execute("audit it", {}, task_id=task_id)
    # High-confidence findings are learned from as FAILURES, not task successes
    assert ltm.failure_stored is True
    assert ltm.stored is False
    args = ltm.last_failure_args
    assert args["task_id"] == task_id
    assert args["failed_agent"] == "security"
    assert "CWE-89" in args["error_summary"]
    assert "Parameterize" in args["error_summary"]


async def test_clean_audit_falls_back_to_task_result_store():
    from types import SimpleNamespace

    ltm = FakeLongTerm()
    agent = SecurityAgent(llm=make_llm(), long_term=ltm)
    await agent._store_success_memory(
        "audit it",
        {"threat_model": "x", "vulnerabilities": "", "remediation": "all clear"},
        SimpleNamespace(content="raw", cost_usd=0.0),
        0.9,
        None,
    )
    assert ltm.stored is True
    assert ltm.failure_stored is False
    assert ltm.last_store_args["result_summary"] == "all clear"


async def test_memory_retrieval_called_before_llm():
    ltm = FakeLongTerm(hits=[_Hit("prior audit: SQL injection via f-strings")])
    capture: dict = {}
    agent = SecurityAgent(llm=make_llm(capture=capture), long_term=ltm)
    result = await agent.execute("audit it", {}, task_id=uuid.uuid4())
    assert ltm.searched is True
    assert capture.get("called") is True
    assert "prior audit: SQL injection via f-strings" in capture["messages"][-1]["content"]
    assert result.memory_retrieved == ["prior audit: SQL injection via f-strings"]

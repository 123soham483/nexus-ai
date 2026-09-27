"""Integration tests for the learned-memory endpoints (Phase 3, Step 3.3)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.memory.long_term import MemoryResult

pytestmark = pytest.mark.integration


class FakeMemory:
    """Drop-in LongTermMemory: canned patterns/tasks/failures, records calls."""

    def __init__(self, patterns=None, tasks=None, failures=None):
        self.patterns = patterns if patterns is not None else []
        self.tasks = tasks if tasks is not None else []
        self.failures = failures if failures is not None else []
        self.calls = []

    async def list_patterns(self, pattern_type=None, limit=20):
        self.calls.append(("list_patterns", pattern_type, limit))
        hits = self.patterns
        if pattern_type:
            hits = [h for h in hits if h.metadata.get("pattern_type") == pattern_type]
        return hits[:limit]

    async def search_similar_tasks(self, query, n_results=5, min_quality_score=0.7):
        self.calls.append(("tasks", query, n_results))
        return self.tasks

    async def search_similar_failures(self, query, n_results=3):
        self.calls.append(("failures", query, n_results))
        return self.failures


class FakeLearningEngine:
    def __init__(self, hints=None, raises=False):
        self.hints = hints or []
        self.raises = raises
        self.calls = []

    async def get_routing_hints(self, goal, candidate_agents=None, tenant_id="", limit=5):
        self.calls.append({"goal": goal, "tenant_id": tenant_id})
        if self.raises:
            raise RuntimeError("redis down")
        return list(self.hints)


def _patch(memory, engine=None):
    """Patch the module-level builders so no Chroma/Redis is touched."""
    return (
        patch("app.api.v1.memory._build_memory", return_value=memory),
        patch(
            "app.api.v1.memory._build_learning_engine",
            return_value=engine or FakeLearningEngine(),
        ),
    )


def _hit(content, **meta):
    return MemoryResult(content=content, metadata=meta, similarity_score=0.25)


# ── GET /memory/patterns ─────────────────────────────────────────────────────

def test_patterns_requires_auth(api):
    assert api.get("/api/v1/memory/patterns").status_code == 401


async def test_patterns_lists_learned_patterns(api, make_user):
    _, _, headers = await make_user("pat1@acme.com")
    memory = FakeMemory(
        patterns=[
            _hit(
                "Causal analysis for: build api",
                pattern_type="causal",
                pattern_data={"why_it_worked": "planner first"},
                timestamp="2026-09-23T10:00:00+00:00",
            ),
        ]
    )
    patched_mem, patched_engine = _patch(memory)
    with patched_mem, patched_engine:
        r = api.get("/api/v1/memory/patterns", headers=headers)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1
    assert data["patterns"][0]["pattern_type"] == "causal"
    assert data["patterns"][0]["pattern_data"] == {"why_it_worked": "planner first"}
    assert data["patterns"][0]["content"].startswith("Causal analysis")


async def test_patterns_normalises_json_string_pattern_data(api, make_user):
    _, _, headers = await make_user("pat2@acme.com")
    memory = FakeMemory(
        patterns=[_hit("p", pattern_type="causal", pattern_data='{"a": 1}')]
    )
    patched_mem, patched_engine = _patch(memory)
    with patched_mem, patched_engine:
        r = api.get("/api/v1/memory/patterns", headers=headers)

    assert r.json()["patterns"][0]["pattern_data"] == {"a": 1}


async def test_patterns_survives_unparseable_pattern_data(api, make_user):
    _, _, headers = await make_user("pat3@acme.com")
    memory = FakeMemory(patterns=[_hit("p", pattern_data="not json at all")])
    patched_mem, patched_engine = _patch(memory)
    with patched_mem, patched_engine:
        r = api.get("/api/v1/memory/patterns", headers=headers)

    assert r.status_code == 200
    assert r.json()["patterns"][0]["pattern_data"] == {}


async def test_patterns_forwards_filter_and_limit(api, make_user):
    _, _, headers = await make_user("pat4@acme.com")
    memory = FakeMemory()
    patched_mem, patched_engine = _patch(memory)
    with patched_mem, patched_engine:
        r = api.get(
            "/api/v1/memory/patterns",
            params={"pattern_type": "causal", "limit": 3},
            headers=headers,
        )

    assert r.status_code == 200
    assert memory.calls == [("list_patterns", "causal", 3)]


async def test_patterns_rejects_out_of_range_limit(api, make_user):
    _, _, headers = await make_user("pat5@acme.com")
    memory = FakeMemory()
    patched_mem, patched_engine = _patch(memory)
    with patched_mem, patched_engine:
        r = api.get("/api/v1/memory/patterns", params={"limit": 500}, headers=headers)

    assert r.status_code == 422


# ── GET /memory/suggestions ──────────────────────────────────────────────────

def test_suggestions_requires_auth(api):
    assert api.get("/api/v1/memory/suggestions", params={"goal": "x"}).status_code == 401


async def test_suggestions_groups_hints_into_agent_ranking(api, make_user):
    _, _, headers = await make_user("sug1@acme.com")
    memory = FakeMemory()
    engine = FakeLearningEngine(
        hints=[("login", "security", 3), ("jwt", "security", 2), ("login", "coder", 1)]
    )
    patched_mem, patched_engine = _patch(memory, engine)
    with patched_mem, patched_engine:
        r = api.get(
            "/api/v1/memory/suggestions",
            params={"goal": "implement JWT login"},
            headers=headers,
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["goal"] == "implement JWT login"
    assert "login" in data["keywords"] and "jwt" in data["keywords"]
    assert [s["agent"] for s in data["suggested_agents"]] == ["security", "coder"]
    assert data["suggested_agents"][0]["score"] == 5
    assert set(data["suggested_agents"][0]["matched_keywords"]) == {"login", "jwt"}
    assert data["notes"] is None


async def test_suggestions_includes_similar_tasks_and_risk_patterns(api, make_user):
    _, _, headers = await make_user("sug2@acme.com")
    memory = FakeMemory(
        tasks=[_hit("used FastAPI", task_id="t1", quality_score=0.9)],
        failures=[_hit("timeout on build", failed_agent="tester")],
    )
    patched_mem, patched_engine = _patch(memory)
    with patched_mem, patched_engine:
        r = api.get(
            "/api/v1/memory/suggestions",
            params={"goal": "build a REST API", "limit": 2},
            headers=headers,
        )

    data = r.json()
    assert data["similar_tasks"][0]["content"] == "used FastAPI"
    assert data["risk_patterns"][0]["metadata"]["failed_agent"] == "tester"
    assert ("tasks", "build a REST API", 2) in memory.calls
    assert ("failures", "build a REST API", 2) in memory.calls


async def test_suggestions_explains_empty_learned_history(api, make_user):
    _, _, headers = await make_user("sug3@acme.com")
    patched_mem, patched_engine = _patch(FakeMemory())
    with patched_mem, patched_engine:
        r = api.get(
            "/api/v1/memory/suggestions", params={"goal": "brand new thing"}, headers=headers
        )

    data = r.json()
    assert data["suggested_agents"] == []
    assert "No learned routing history" in data["notes"]


async def test_suggestions_hint_lookup_failure_degrades_gracefully(api, make_user):
    _, _, headers = await make_user("sug4@acme.com")
    engine = FakeLearningEngine(raises=True)
    patched_mem, patched_engine = _patch(FakeMemory(), engine)
    with patched_mem, patched_engine:
        r = api.get(
            "/api/v1/memory/suggestions", params={"goal": "anything"}, headers=headers
        )

    assert r.status_code == 200
    assert r.json()["suggested_agents"] == []


async def test_suggestions_requires_a_goal(api, make_user):
    _, _, headers = await make_user("sug5@acme.com")
    patched_mem, patched_engine = _patch(FakeMemory())
    with patched_mem, patched_engine:
        r = api.get("/api/v1/memory/suggestions", headers=headers)

    assert r.status_code == 422

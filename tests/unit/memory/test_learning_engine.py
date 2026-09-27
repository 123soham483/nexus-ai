"""Unit tests for LearningEngine (Phase 3, Step 3.1).

Everything is faked: a deterministic hash embedder + in-memory Chroma stand-in
for long-term memory, an injectable LLM stub for causal analysis, and fakeredis
for the routing-confidence counters. No network, DB, or real Redis required.
"""
from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace

import pytest

from app.memory.learning_engine import (
    CONFIDENCE_KEY_TEMPLATE,
    LearningEngine,
    extract_keywords,
)
from app.memory.long_term import LongTermMemory


# ── fakes ────────────────────────────────────────────────────────────────────
def fake_embedder(text: str) -> list[float]:
    h = int(hashlib.md5(text.encode()).hexdigest(), 16)
    return [(h >> i & 0xFF) / 255.0 for i in range(384)]


class FakeCollection:
    def __init__(self):
        self.ids: list[str] = []
        self.embeddings: list[list[float]] = []
        self.documents: list[str] = []
        self.metadatas: list[dict] = []

    def add(self, ids, embeddings, documents, metadatas=None):
        self.ids += list(ids)
        self.embeddings += [list(e) for e in embeddings]
        self.documents += list(documents)
        self.metadatas += list(metadatas) if metadatas is not None else [{}] * len(ids)

    def query(self, query_embeddings, n_results=5, where=None):
        return {
            "ids": [[self.ids[i] for i in range(min(n_results, len(self.ids)))]],
            "documents": [[self.documents[i] for i in range(min(n_results, len(self.documents)))]],
            "metadatas": [[self.metadatas[i] for i in range(min(n_results, len(self.metadatas)))]],
            "distances": [[0.0] * min(n_results, len(self.ids))],
        }

    def count(self):
        return len(self.ids)


class FakeChromaClient:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def get_or_create_collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


class FakeLLM:
    """Records calls; returns a canned analysis JSON or raises."""

    def __init__(self, content: str = "", raises: bool = False):
        self.content = content
        self.raises = raises
        self.calls: list[dict] = []

    async def complete(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self.raises:
            raise RuntimeError("llm down")
        return SimpleNamespace(content=self.content)


def make_result(agent_type: str, confidence: float = 0.9, content: str = "did work"):
    return SimpleNamespace(
        agent_type=agent_type,
        confidence_score=confidence,
        content=content,
        reasoning="reasoning text",
    )


_ANALYSIS_JSON = (
    '{"why_it_worked": "security agent matched auth keywords", '
    '"goal_pattern": "auth + token goals", '
    '"risk_factors": ["missing tests", "no docs"]}'
)


@pytest.fixture
def ltm():
    return LongTermMemory(client=FakeChromaClient(), embedder=fake_embedder, tenant_prefix="acme")


@pytest.fixture
def engine(ltm, fake_redis):
    return LearningEngine(long_memory=ltm, llm_provider=FakeLLM(_ANALYSIS_JSON), redis_client=fake_redis)


# ── keyword extraction ───────────────────────────────────────────────────────
async def test_extract_keywords_drops_stopwords_and_short_tokens():
    assert extract_keywords("build an API for the auth token flow") == [
        "api", "auth", "token", "flow",
    ]


# ── Level 1 ──────────────────────────────────────────────────────────────────
async def test_store_success_stores_rich_metadata(engine, ltm):
    plan = SimpleNamespace(agents=["planner", "coder"], parallel_groups=[["tester", "docs"]], confidence=0.91)
    await engine.store_success(
        uuid.uuid4(), "build a python api", [make_result("coder"), make_result("tester")],
        plan, cost=0.07, quality=0.88, tenant_id="acme",
    )
    col = ltm.client.get_or_create_collection("acme_tasks")
    assert col.count() == 1
    meta = col.metadatas[0]
    assert meta["agent_types_used"] == "coder,tester"
    assert meta["routing_confidence"] == 0.91
    assert meta["parallel_groups"] == "tester+docs"
    assert meta["total_cost_usd"] == 0.07
    assert meta["tenant_id"] == "acme"


# ── Level 2 ──────────────────────────────────────────────────────────────────
async def test_analyze_why_calls_llm_and_stores_causal_pattern(ltm, fake_redis):
    llm = FakeLLM(_ANALYSIS_JSON)
    engine = LearningEngine(long_memory=ltm, llm_provider=llm, redis_client=fake_redis)
    result = await engine.analyze_why(uuid.uuid4(), "build auth flow", [make_result("security")], "acme")

    assert result == "security agent matched auth keywords"
    assert len(llm.calls) == 1
    col = ltm.client.get_or_create_collection("acme_patterns")
    assert col.count() == 1
    assert col.metadatas[0]["pattern_type"] == "causal"
    data = col.metadatas[0]["pattern_data"]
    assert data["type"] == "causal"
    assert data["goal_pattern"] == "auth + token goals"
    assert data["risk_factors"] == "missing tests,no docs"


async def test_analyze_why_returns_empty_on_llm_failure(ltm, fake_redis):
    engine = LearningEngine(long_memory=ltm, llm_provider=FakeLLM(raises=True), redis_client=fake_redis)
    result = await engine.analyze_why(uuid.uuid4(), "build auth flow", [make_result("security")], "acme")
    assert result == ""
    assert ltm.client.get_or_create_collection("acme_patterns").count() == 0


# ── Level 3 ──────────────────────────────────────────────────────────────────
async def test_update_routing_confidence_increments_each_pair(engine, fake_redis):
    await engine.update_routing_confidence("build python api", ["coder"], 0.7, "acme")
    keywords = extract_keywords("build python api")
    assert keywords == ["python", "api"]
    for keyword in keywords:
        key = CONFIDENCE_KEY_TEMPLATE.format(tenant="acme", keyword=keyword, agent="coder")
        assert await fake_redis.get(key) == "1"


async def test_update_routing_confidence_strong_signal_increments_by_two(engine, fake_redis):
    await engine.update_routing_confidence("build python api", ["coder"], 0.95, "acme")
    key = CONFIDENCE_KEY_TEMPLATE.format(tenant="acme", keyword="python", agent="coder")
    assert await fake_redis.get(key) == "2"


async def test_update_routing_confidence_weak_signal_decrements(engine, fake_redis):
    key = CONFIDENCE_KEY_TEMPLATE.format(tenant="acme", keyword="python", agent="coder")
    await fake_redis.set(key, 5)
    await engine.update_routing_confidence("build python api", ["coder"], 0.2, "acme")
    assert await fake_redis.get(key) == "4"


async def test_update_routing_confidence_survives_redis_errors(ltm):
    class BrokenRedis:
        async def incrby(self, *a, **k):
            raise ConnectionError("redis down")

    engine = LearningEngine(long_memory=ltm, llm_provider=FakeLLM(), redis_client=BrokenRedis())
    # Must not raise — learning degrades gracefully.
    await engine.update_routing_confidence("build python api", ["coder"], 0.9, "acme")


# ── failure learning ─────────────────────────────────────────────────────────
async def test_learn_from_failure_stores_failure_with_causal_analysis(ltm, fake_redis):
    llm = FakeLLM('{"why_it_failed": "no db credentials", "goal_pattern": "db goals", "risk_factors": ["env"]}')
    engine = LearningEngine(long_memory=ltm, llm_provider=llm, redis_client=fake_redis)

    why = await engine.learn_from_failure(uuid.uuid4(), "connect postgres", "timeout", "coder", "acme")

    assert why == "no db credentials"
    col = ltm.client.get_or_create_collection("acme_failures")
    assert col.count() == 1
    assert col.metadatas[0]["failed_agent"] == "coder"
    assert col.metadatas[0]["causal"] == "no db credentials"


async def test_learn_from_failure_decrements_failed_agent_confidence(engine, fake_redis):
    key = CONFIDENCE_KEY_TEMPLATE.format(tenant="acme", keyword="postgres", agent="coder")
    await fake_redis.set(key, 3)
    await engine.learn_from_failure(uuid.uuid4(), "connect postgres", "timeout", "coder", "acme")
    assert await fake_redis.get(key) == "2"


# ── hints (consumed by the router in Step 3.2) ───────────────────────────────
async def test_get_routing_hints_returns_top_positive_scores(engine, fake_redis):
    await fake_redis.set(
        CONFIDENCE_KEY_TEMPLATE.format(tenant="acme", keyword="python", agent="coder"), 4
    )
    await fake_redis.set(
        CONFIDENCE_KEY_TEMPLATE.format(tenant="acme", keyword="python", agent="tester"), 2
    )
    hints = await engine.get_routing_hints("build python api", ["coder", "tester"], "acme")
    assert hints[0] == ("python", "coder", 4)
    assert ("python", "tester", 2) in hints


async def test_get_routing_hints_empty_without_redis(ltm):
    engine = LearningEngine(long_memory=ltm, llm_provider=FakeLLM(), redis_client=None)
    engine._redis = None
    # Force the lazy resolver to fail so it returns no client.
    import app.security.redis_client as rc

    original = rc.get_redis
    rc.get_redis = lambda: (_ for _ in ()).throw(RuntimeError("no redis"))
    try:
        assert await engine.get_routing_hints("build python api", ["coder"], "acme") == []
    finally:
        rc.get_redis = original

"""Unit tests for LongTermMemory (Step 1.8).

Uses a deterministic hash embedder and an in-memory fake Chroma client so
no sentence-transformers or Chroma server is required.
"""
from __future__ import annotations

import hashlib
import uuid

import pytest

from app.memory.long_term import LongTermMemory, MemoryResult


# ── fakes ────────────────────────────────────────────────────────────────────
def fake_embedder(text: str) -> list[float]:
    """Deterministic 384-d vector from text hash (per spec)."""
    h = int(hashlib.md5(text.encode()).hexdigest(), 16)
    return [(h >> i & 0xFF) / 255.0 for i in range(384)]


class FakeCollection:
    """Minimal in-memory Chroma collection stand-in."""

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

    def _dist(self, a: list[float], b: list[float]) -> float:
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    def query(self, query_embeddings, n_results=5, where=None):
        q = query_embeddings[0]
        order = sorted(range(len(self.ids)), key=lambda i: self._dist(q, self.embeddings[i]))
        order = order[:n_results]
        return {
            "ids": [[self.ids[i] for i in order]],
            "documents": [[self.documents[i] for i in order]],
            "metadatas": [[self.metadatas[i] for i in order]],
            "distances": [[self._dist(q, self.embeddings[i]) for i in order]],
        }

    def get(self, where=None, limit=None):
        rows = list(range(len(self.ids)))
        if where:
            rows = [
                i
                for i in rows
                if all(self.metadatas[i].get(k) == v for k, v in where.items())
            ]
        if limit is not None:
            rows = rows[:limit]
        return {
            "ids": [self.ids[i] for i in rows],
            "documents": [self.documents[i] for i in rows],
            "metadatas": [self.metadatas[i] for i in rows],
        }

    def count(self):
        return len(self.ids)


class FakeChromaClient:
    """Stand-in for chromadb.EphemeralClient()."""

    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def get_or_create_collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


@pytest.fixture
def ltm():
    return LongTermMemory(client=FakeChromaClient(), embedder=fake_embedder, tenant_prefix="acme")


# ── tests (minimum 8 per spec) ───────────────────────────────────────────────
async def test_store_task_result_stores_in_tasks_collection(ltm):
    task_id = uuid.uuid4()
    await ltm.store_task_result(
        task_id,
        goal="build a REST API in Python",
        result_summary="Used FastAPI with pydantic models",
        agent_types_used=["planner", "coder"],
        cost_usd=0.05,
        quality_score=0.9,
    )
    col = ltm.client.get_or_create_collection("acme_tasks")
    assert col.count() == 1
    assert col.documents[0] == "Used FastAPI with pydantic models"
    assert col.metadatas[0]["task_id"] == str(task_id)
    assert col.metadatas[0]["agent_types"] == "planner,coder"


async def test_search_similar_tasks_returns_above_quality_threshold(ltm):
    await ltm.store_task_result(
        uuid.uuid4(),
        goal="write python unit tests",
        result_summary="pytest fixtures work well",
        agent_types_used=["coder"],
        cost_usd=0.01,
        quality_score=0.95,
    )
    hits = await ltm.search_similar_tasks("python testing", min_quality_score=0.7)
    assert len(hits) == 1
    assert isinstance(hits[0], MemoryResult)
    assert hits[0].content == "pytest fixtures work well"
    assert hits[0].metadata["quality_score"] == 0.95


async def test_search_similar_tasks_filters_below_quality_threshold(ltm):
    await ltm.store_task_result(
        uuid.uuid4(),
        goal="write python unit tests",
        result_summary="low quality attempt",
        agent_types_used=["coder"],
        cost_usd=0.01,
        quality_score=0.4,
    )
    await ltm.store_task_result(
        uuid.uuid4(),
        goal="write python unit tests",
        result_summary="high quality attempt",
        agent_types_used=["coder"],
        cost_usd=0.02,
        quality_score=0.9,
    )
    hits = await ltm.search_similar_tasks("python testing", min_quality_score=0.7)
    assert len(hits) == 1
    assert hits[0].content == "high quality attempt"


async def test_store_failure_stores_in_failures_collection(ltm):
    task_id = uuid.uuid4()
    await ltm.store_failure(
        task_id,
        goal="deploy to production",
        error_summary="Connection timeout to database",
        failed_agent="coder",
    )
    col = ltm.client.get_or_create_collection("acme_failures")
    assert col.count() == 1
    assert col.documents[0] == "Connection timeout to database"
    assert col.metadatas[0]["failed_agent"] == "coder"


async def test_search_similar_failures_returns_relevant(ltm):
    await ltm.store_failure(
        uuid.uuid4(),
        goal="connect to postgres database",
        error_summary="auth failed: invalid password",
        failed_agent="coder",
    )
    hits = await ltm.search_similar_failures("postgres connection error")
    assert len(hits) == 1
    assert "auth failed" in hits[0].content


async def test_store_pattern_stores_in_patterns_collection(ltm):
    await ltm.store_pattern(
        "routing",
        "auth tasks need security agent first",
        {"agents": ["security", "coder"]},
    )
    col = ltm.client.get_or_create_collection("acme_patterns")
    assert col.count() == 1
    assert col.metadatas[0]["pattern_type"] == "routing"
    assert col.metadatas[0]["pattern_data"] == {"agents": ["security", "coder"]}


async def test_search_patterns_filters_by_pattern_type(ltm):
    await ltm.store_pattern("routing", "route auth to security", {"k": 1})
    await ltm.store_pattern("cost", "expensive tasks use gpt-3.5", {"k": 2})
    hits = await ltm.search_patterns("auth routing", pattern_type="routing")
    assert len(hits) == 1
    assert hits[0].metadata["pattern_type"] == "routing"


async def test_tenant_isolation(ltm):
    other = LongTermMemory(
        client=FakeChromaClient(), embedder=fake_embedder, tenant_prefix="other_co"
    )
    await ltm.store_task_result(
        uuid.uuid4(),
        goal="python api",
        result_summary="acme-only result",
        agent_types_used=["coder"],
        cost_usd=0.01,
        quality_score=0.9,
    )
    hits = await other.search_similar_tasks("python api", min_quality_score=0.0)
    assert hits == []

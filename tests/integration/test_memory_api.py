"""Integration tests for the Memory search API (tenant-scoped, injectable memory)."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.memory.long_term import MemoryResult

pytestmark = pytest.mark.integration


class FakeMemory:
    """Drop-in LongTermMemory returning canned hits; records the calls."""

    def __init__(self) -> None:
        self.calls = []

    def _hits(self):
        return [
            MemoryResult(
                content="found it", metadata={"task_id": "x"}, similarity_score=0.5
            )
        ]

    async def search_similar_tasks(self, query, n_results=5, min_quality_score=0.7):
        self.calls.append(("tasks", query, n_results))
        return self._hits()

    async def search_similar_failures(self, query, n_results=3):
        self.calls.append(("failures", query, n_results))
        return self._hits()

    async def search_patterns(self, query, pattern_type=None, n_results=5):
        self.calls.append(("patterns", query, n_results))
        return self._hits()


def _patch_memory(api, fake):
    """Patch the endpoint's memory builder so no ChromaDB is touched."""
    return patch("app.api.v1.memory._build_memory", return_value=fake)


def test_search_requires_auth(api):
    r = api.post("/api/v1/memory/search", json={"query": "deploy"})
    assert r.status_code == 401


async def test_search_tasks_uses_tenant_prefix(api, make_user):
    tenant, _, headers = await make_user("mem1@acme.com")
    fake = FakeMemory()
    with patch("app.api.v1.memory._build_memory") as mock_build:
        mock_build.return_value = fake
        r = api.post(
            "/api/v1/memory/search",
            json={"query": "quicksort bug", "collection": "tasks", "n_results": 3},
            headers=headers,
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["query"] == "quicksort bug"
    assert data["collection"] == "tasks"
    assert len(data["results"]) == 1
    assert data["results"][0]["content"] == "found it"
    assert data["results"][0]["metadata"] == {"task_id": "x"}
    assert data["results"][0]["similarity_score"] == 0.5
    # The memory was built with the tenant's chroma prefix and searched.
    mock_build.assert_called_once_with(tenant.chroma_collection_prefix)
    assert fake.calls == [("tasks", "quicksort bug", 3)]


async def test_search_failures_and_patterns_route_to_methods(api, make_user):
    _, _, headers = await make_user("mem2@acme.com")
    fake = FakeMemory()
    with _patch_memory(api, fake):
        r_fail = api.post(
            "/api/v1/memory/search",
            json={"query": "timeout", "collection": "failures"},
            headers=headers,
        )
        r_pat = api.post(
            "/api/v1/memory/search",
            json={"query": "routing", "collection": "patterns"},
            headers=headers,
        )
    assert r_fail.status_code == 200
    assert r_pat.status_code == 200
    assert fake.calls == [
        ("failures", "timeout", 5),
        ("patterns", "routing", 5),
    ]


async def test_search_invalid_collection_422(api, make_user):
    _, _, headers = await make_user("mem3@acme.com")
    with _patch_memory(api, FakeMemory()):
        r = api.post(
            "/api/v1/memory/search",
            json={"query": "anything", "collection": "nonsense"},
            headers=headers,
        )
    assert r.status_code == 422


async def test_search_empty_query_422(api, make_user):
    _, _, headers = await make_user("mem4@acme.com")
    r = api.post(
        "/api/v1/memory/search",
        json={"query": "", "collection": "tasks"},
        headers=headers,
    )
    assert r.status_code == 422

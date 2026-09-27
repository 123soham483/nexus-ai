"""LongTermMemory — ChromaDB-backed permanent vector memory.

Stores task results, failure patterns, and learned routing patterns as
embeddings, searched by semantic similarity. Each tenant is isolated via a
collection name prefix (``{tenant_prefix}_tasks|failures|patterns``).

Both the Chroma client and embedder are injectable (BRAIN.md D5): tests use
``chromadb.EphemeralClient()`` (or an in-memory fake) plus a deterministic hash
embedder — no ``sentence-transformers`` or Chroma server required. Production
defaults lazily import heavy deps on first use (D3).

Chroma's client is synchronous; calls run in a thread pool so the async API
never blocks the event loop.
"""
from __future__ import annotations

import asyncio
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from app.config import settings

# Single-text embedder: text → vector. Batch embedders (texts → vectors) also work.
Embedder = Union[
    Callable[[str], List[float]],
    Callable[[Sequence[str]], List[List[float]]],
]


@dataclass
class MemoryResult:
    """One retrieved memory."""

    content: str
    metadata: dict
    similarity_score: float  # 0.0 = identical, 2.0 = completely different (cosine distance)

    @property
    def document(self) -> str:
        """Alias for :attr:`content` — satisfies BaseAgent's duck-typed memory interface."""
        return self.content


class LongTermMemory:
    """Tenant-scoped semantic memory over three Chroma collections."""

    _TASKS = "tasks"
    _FAILURES = "failures"
    _PATTERNS = "patterns"

    def __init__(
        self,
        client=None,
        embedder: Optional[Embedder] = None,
        tenant_prefix: str = "default",
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._tenant_prefix = tenant_prefix
        self._collections: Dict[str, Any] = {}

    # ── lazy defaults ────────────────────────────────────────────────────────
    @property
    def client(self):
        """The active Chroma client (lazily built from settings)."""
        if self._client is None:
            self._client = _get_default_client()
        return self._client

    @property
    def embedder(self) -> Embedder:
        """The active embedder (lazily builds SentenceTransformer default)."""
        if self._embedder is None:
            self._embedder = _get_default_embedder()
        return self._embedder

    def _collection_name(self, suffix: str) -> str:
        return f"{self._tenant_prefix}_{suffix}"

    def _get_collection(self, suffix: str):
        name = self._collection_name(suffix)
        if name not in self._collections:
            self._collections[name] = self.client.get_or_create_collection(name)
        return self._collections[name]

    async def _embed_text(self, text: str) -> List[float]:
        def _do() -> List[float]:
            # The embedder is duck-typed (single-text OR batch callable — see the
            # Embedder union). Try the single-text form, fall back to batch.
            fn: Any = self.embedder
            try:
                result = fn(text)
                if result and isinstance(result[0], (int, float)):
                    return list(result)
            except TypeError:
                pass
            batch = fn([text])
            return list(batch[0])

        return await asyncio.to_thread(_do)

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _first(res: Dict[str, Any], key: str) -> List[Any]:
        value = res.get(key)
        if not value:
            return []
        return value[0] or []

    def _to_results(self, res: Dict[str, Any]) -> List[MemoryResult]:
        docs = self._first(res, "documents")
        metas = self._first(res, "metadatas")
        dists = self._first(res, "distances")
        results: List[MemoryResult] = []
        for i, doc in enumerate(docs):
            dist = dists[i] if i < len(dists) else 0.0
            meta = (metas[i] if i < len(metas) else None) or {}
            results.append(
                MemoryResult(
                    content=doc or "",
                    metadata=meta,
                    similarity_score=float(dist) if dist is not None else 0.0,
                )
            )
        return results

    async def _query_collection(
        self,
        suffix: str,
        query: str,
        n_results: int,
        *,
        post_filter: Optional[Callable[[dict], bool]] = None,
    ) -> List[MemoryResult]:
        if not query:
            return []
        embedding = await self._embed_text(query)
        collection = self._get_collection(suffix)
        # Over-fetch when post-filtering so we still return up to n_results matches.
        fetch_n = n_results * 5 if post_filter else n_results
        res = await asyncio.to_thread(
            collection.query,
            query_embeddings=[embedding],
            n_results=max(fetch_n, n_results),
        )
        results = self._to_results(res)
        if post_filter:
            results = [r for r in results if post_filter(r.metadata)]
        return results[:n_results]

    # ── task results ─────────────────────────────────────────────────────────
    async def store_task_result(
        self,
        task_id,
        goal: str,
        result_summary: str,
        agent_types_used: List[str],
        cost_usd: float,
        quality_score: float,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Embed the goal and store the result summary in the tasks collection.

        ``extra_metadata`` (Phase 3) lets the LearningEngine attach richer
        structural fields (agent count, parallel groups, routing confidence...)
        without changing the base metadata contract. Values must be Chroma-legal
        scalars; the caller is responsible for flattening containers.
        """
        embedding = await self._embed_text(goal)
        collection = self._get_collection(self._TASKS)
        metadata: Dict[str, Any] = {
            "task_id": str(task_id),
            "agent_types": ",".join(agent_types_used),
            "cost_usd": float(cost_usd),
            "quality_score": float(quality_score),
            "timestamp": self._utcnow_iso(),
        }
        if extra_metadata:
            # Base keys stay authoritative — extras can add, never overwrite.
            metadata = {**extra_metadata, **metadata}
        await asyncio.to_thread(
            collection.add,
            ids=[_uuid.uuid4().hex],
            embeddings=[embedding],
            documents=[result_summary],
            metadatas=[metadata],
        )

    async def search_similar_tasks(
        self,
        query: str,
        n_results: int = 5,
        min_quality_score: float = 0.7,
    ) -> List[MemoryResult]:
        """Search tasks by semantic similarity, keeping only high-quality results."""

        def _quality_ok(meta: dict) -> bool:
            score = meta.get("quality_score", 0.0)
            try:
                return float(score) >= min_quality_score
            except (TypeError, ValueError):
                return False

        return await self._query_collection(
            self._TASKS,
            query,
            n_results,
            post_filter=_quality_ok,
        )

    # ── failures ─────────────────────────────────────────────────────────────
    async def store_failure(
        self,
        task_id,
        goal: str,
        error_summary: str,
        failed_agent: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Embed the goal and store a failure record.

        ``extra_metadata`` (Phase 3) carries the LearningEngine's causal
        analysis for the failure; values must be Chroma-legal scalars.
        """
        embedding = await self._embed_text(goal)
        collection = self._get_collection(self._FAILURES)
        metadata: Dict[str, Any] = {
            "task_id": str(task_id),
            "failed_agent": failed_agent,
            "timestamp": self._utcnow_iso(),
        }
        if extra_metadata:
            metadata = {**extra_metadata, **metadata}
        await asyncio.to_thread(
            collection.add,
            ids=[_uuid.uuid4().hex],
            embeddings=[embedding],
            documents=[error_summary],
            metadatas=[metadata],
        )

    async def search_similar_failures(
        self, query: str, n_results: int = 3
    ) -> List[MemoryResult]:
        """Search past failures semantically similar to ``query``."""
        return await self._query_collection(self._FAILURES, query, n_results)

    # ── patterns ─────────────────────────────────────────────────────────────
    async def store_pattern(
        self, pattern_type: str, description: str, pattern_data: dict
    ) -> None:
        """Embed the description and store a learned routing pattern."""
        embedding = await self._embed_text(description)
        collection = self._get_collection(self._PATTERNS)
        await asyncio.to_thread(
            collection.add,
            ids=[_uuid.uuid4().hex],
            embeddings=[embedding],
            documents=[description],
            metadatas=[
                {
                    "pattern_type": pattern_type,
                    "pattern_data": pattern_data,
                    "timestamp": self._utcnow_iso(),
                }
            ],
        )

    async def list_patterns(
        self, pattern_type: Optional[str] = None, limit: int = 20
    ) -> List[MemoryResult]:
        """The most recently learned patterns, newest first (Phase 3, Step 3.3).

        Unlike :meth:`search_patterns` this needs no query text — it is the
        read path behind ``GET /memory/patterns``, so it uses Chroma's
        ``get`` (metadata only, no embeddings) and sorts by the stored
        ``timestamp`` descending. ``similarity_score`` is always 0.0 because
        nothing was ranked.
        """
        collection = self._get_collection(self._PATTERNS)
        where = {"pattern_type": pattern_type} if pattern_type else None

        def _do() -> List[MemoryResult]:
            res = collection.get(where=where, limit=limit)
            # ``get`` returns flat lists, not query()'s nested-per-query shape.
            docs = res.get("documents") or []
            metas = res.get("metadatas") or []
            out: List[MemoryResult] = []
            for i, doc in enumerate(docs):
                meta = (metas[i] if i < len(metas) else None) or {}
                out.append(
                    MemoryResult(
                        content=doc or "", metadata=meta, similarity_score=0.0
                    )
                )
            return out

        results = await asyncio.to_thread(_do)
        results.sort(
            key=lambda r: str(r.metadata.get("timestamp", "")), reverse=True
        )
        return results[:limit]

    async def search_patterns(
        self,
        query: str,
        pattern_type: Optional[str] = None,
        n_results: int = 5,
    ) -> List[MemoryResult]:
        """Search learned patterns, optionally filtered by ``pattern_type``."""

        def _type_ok(meta: dict) -> bool:
            if pattern_type is None:
                return True
            return meta.get("pattern_type") == pattern_type

        return await self._query_collection(
            self._PATTERNS,
            query,
            n_results,
            post_filter=_type_ok,
        )

    # ── BaseAgent compatibility ──────────────────────────────────────────────
    async def search(
        self, query: str, n_results: int = 5, where: Optional[Dict[str, Any]] = None
    ) -> List[MemoryResult]:
        """Generic search over task results (used by :class:`BaseAgent`)."""
        min_quality = 0.0
        if where and "quality_score" in where:
            min_quality = float(where["quality_score"].get("$gte", 0.0))
        return await self.search_similar_tasks(
            query, n_results=n_results, min_quality_score=min_quality
        )


def _get_default_client():
    import chromadb  # lazy (D3)

    return chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)


def _get_default_embedder() -> Callable[[str], List[float]]:
    from sentence_transformers import SentenceTransformer  # lazy (D3)

    model = SentenceTransformer("all-MiniLM-L6-v2")
    return lambda text: model.encode(text).tolist()

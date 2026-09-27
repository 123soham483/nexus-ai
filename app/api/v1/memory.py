"""Memory API Router — tenant-scoped semantic search over long-term memory."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.dependencies import DBSession, CurrentUser
from app.db.models.tenant import Tenant
from app.memory.learning_engine import extract_keywords
from app.schemas.memory import (
    AgentSuggestion,
    MemoryPattern,
    MemoryPatternsResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemorySuggestionsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: collection name → LongTermMemory search method
_COLLECTION_METHODS = {
    "tasks": "search_similar_tasks",
    "failures": "search_similar_failures",
    "patterns": "search_patterns",
}


def _build_memory(tenant_prefix: str):
    """LongTermMemory for a tenant. Lazy import (heavy dep, D3) — tests patch
    this module-level name with a fake memory."""
    from app.memory.long_term import LongTermMemory  # lazy (D3)

    return LongTermMemory(tenant_prefix=tenant_prefix)


def _build_learning_engine(memory):
    """LearningEngine over a tenant's memory — patched in tests."""
    from app.memory.learning_engine import LearningEngine  # lazy (D3)

    return LearningEngine(memory)


async def _tenant_or_404(db, tenant_id):
    """The caller's tenant row, or a 404 (mirrors ``search_memory``)."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    return tenant


def _as_pattern_data(value: Any) -> Dict[str, object]:
    """Normalise stored ``pattern_data`` to a dict (nested dict or JSON string)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass
    return {}


def _group_hints_by_agent(
    hints: List[tuple], keywords: List[str]
) -> List[AgentSuggestion]:
    """Roll learned (keyword, agent, score) hints up into per-agent evidence."""
    scores: Dict[str, int] = {}
    matched: Dict[str, List[str]] = {}
    for keyword, agent, score in hints:
        scores[agent] = scores.get(agent, 0) + int(score)
        matched.setdefault(agent, []).append(keyword)
    ordered = sorted(scores, key=lambda a: scores[a], reverse=True)
    return [
        AgentSuggestion(
            agent=agent,
            score=scores[agent],
            matched_keywords=[
                k for k in keywords if k in matched[agent]
            ] or matched[agent],
        )
        for agent in ordered
    ]


def _to_results(hits) -> List[MemorySearchResult]:
    return [
        MemorySearchResult(
            content=h.content,
            metadata=h.metadata,
            similarity_score=h.similarity_score,
        )
        for h in hits
    ]


@router.post("/search", response_model=MemorySearchResponse)
async def search_memory(
    body: MemorySearchRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """Semantically search one of the tenant's long-term memory collections."""
    tenant = await _tenant_or_404(db, current_user.tenant_id)

    memory = _build_memory(tenant.chroma_collection_prefix)
    method = getattr(memory, _COLLECTION_METHODS[body.collection])
    hits = await method(body.query, n_results=body.n_results)

    return MemorySearchResponse(
        query=body.query,
        collection=body.collection,
        results=_to_results(hits),
    )


@router.get("/patterns", response_model=MemoryPatternsResponse)
async def list_patterns(
    current_user: CurrentUser,
    db: DBSession,
    pattern_type: Optional[str] = Query(
        None, description="Filter by pattern type, e.g. 'causal' or 'routing'"
    ),
    limit: int = Query(20, ge=1, le=100),
):
    """List the tenant's learned patterns, newest first (Phase 3, Step 3.3).

    This is the window into *why* NexusAI routes the way it does: every entry
    is a causal analysis the LearningEngine stored after a task.
    """
    tenant = await _tenant_or_404(db, current_user.tenant_id)
    memory = _build_memory(tenant.chroma_collection_prefix)
    hits = await memory.list_patterns(pattern_type=pattern_type, limit=limit)

    patterns = [
        MemoryPattern(
            content=h.content,
            pattern_type=str(h.metadata.get("pattern_type", "")),
            pattern_data=_as_pattern_data(h.metadata.get("pattern_data")),
            timestamp=str(h.metadata.get("timestamp", "")),
        )
        for h in hits
    ]
    return MemoryPatternsResponse(patterns=patterns, total=len(patterns))


@router.get("/suggestions", response_model=MemorySuggestionsResponse)
async def memory_suggestions(
    current_user: CurrentUser,
    db: DBSession,
    goal: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(5, ge=1, le=20),
):
    """Pre-flight intelligence for a goal, drawn from the tenant's own history.

    Answers three questions before the task runs: which agents has this kind of
    goal rewarded before (learned confidence), what did similar *successful*
    goals look like, and which failures should we avoid repeating.
    """
    tenant = await _tenant_or_404(db, current_user.tenant_id)
    memory = _build_memory(tenant.chroma_collection_prefix)
    engine = _build_learning_engine(memory)

    keywords = extract_keywords(goal)
    # Learning is advisory: a broken engine/Redis must degrade the endpoint to
    # "no suggestions", never a 500.
    try:
        hints = await engine.get_routing_hints(
            goal, tenant_id=str(current_user.tenant_id)
        )
    except Exception as exc:
        logger.warning("memory suggestions: hint lookup failed (%s)", exc)
        hints = []
    similar_tasks = await memory.search_similar_tasks(goal, n_results=limit)
    risk_patterns = await memory.search_similar_failures(goal, n_results=limit)

    notes = (
        None
        if hints
        else "No learned routing history for this goal yet — the first run will seed it."
    )
    return MemorySuggestionsResponse(
        goal=goal,
        keywords=keywords,
        suggested_agents=_group_hints_by_agent(hints, keywords),
        similar_tasks=_to_results(similar_tasks),
        risk_patterns=_to_results(risk_patterns),
        notes=notes,
    )

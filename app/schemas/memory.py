"""Schemas for the long-term-memory search API."""
from pydantic import BaseModel, Field
from typing import Dict, List, Literal, Optional


class MemorySearchRequest(BaseModel):
    """Semantic search over a tenant's long-term memory collections."""

    query: str = Field(..., min_length=1, max_length=500)
    collection: Literal["tasks", "failures", "patterns"] = "tasks"
    n_results: int = Field(5, ge=1, le=20)


class MemorySearchResult(BaseModel):
    content: str
    metadata: Dict[str, object] = {}
    similarity_score: float


class MemorySearchResponse(BaseModel):
    query: str
    collection: str
    results: List[MemorySearchResult]


class MemoryPattern(BaseModel):
    """One learned pattern (Phase 3, Step 3.3).

    ``pattern_data`` is free-form: older records stored a nested dict, newer
    ones may store a JSON string (Chroma metadata is scalar-only), so the
    endpoint normalises both into a dict.
    """

    content: str
    pattern_type: str = ""
    pattern_data: Dict[str, object] = {}
    timestamp: str = ""


class MemoryPatternsResponse(BaseModel):
    patterns: List[MemoryPattern]
    total: int


class AgentSuggestion(BaseModel):
    """A learned keyword→agent routing recommendation with its evidence."""

    agent: str
    score: int
    matched_keywords: List[str] = []


class MemorySuggestionsResponse(BaseModel):
    """Pre-flight routing intelligence for a goal, drawn from tenant memory."""

    goal: str
    keywords: List[str] = []
    suggested_agents: List[AgentSuggestion] = []
    similar_tasks: List[MemorySearchResult] = []
    risk_patterns: List[MemorySearchResult] = []
    notes: Optional[str] = None

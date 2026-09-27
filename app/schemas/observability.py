"""Schemas for the observability API: tenant-wide metrics."""
from pydantic import BaseModel
from typing import Dict, Optional


class HallucinationObservabilityResponse(BaseModel):
    tenant_average: float
    by_agent: dict[str, float]
    recent: list[dict]


class MetricsResponse(BaseModel):
    """Aggregate execution metrics for one tenant."""

    total_tasks: int
    tasks_by_status: Dict[str, int]
    total_agent_runs: int
    total_cost_usd: float
    total_tokens: int
    avg_quality_score: Optional[float] = None
    avg_duration_seconds: Optional[float] = None

"""Schemas for the agents API: registry listing and per-agent stats."""
from pydantic import BaseModel
from typing import List, Optional


class AgentTypeInfo(BaseModel):
    """One entry in the agent registry listing."""

    agent_type: str
    provider: str
    model: str
    implemented: bool  # has a concrete class in AGENT_CLASSES
    llm_agent: bool  # False for non-LLM agents (e.g. hitl_controller)


class AgentStats(BaseModel):
    """Aggregated execution stats for one agent type within a tenant."""

    agent_type: str
    run_count: int
    success_count: int
    success_rate: float
    total_cost_usd: float
    avg_duration_seconds: Optional[float] = None


class AgentsStatsResponse(BaseModel):
    agents: List[AgentStats]
    total_runs: int

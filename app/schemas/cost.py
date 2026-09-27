"""Schemas for the cost API: estimate, history, and budget."""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import date


class CostEstimateRequest(BaseModel):
    """Ask for a cost estimate for a set of agent types (or the default plan)."""

    goal: Optional[str] = Field(default=None, max_length=2000, description="Optional goal (informational)")
    agent_types: List[str] = Field(
        default_factory=list,
        description="Agent types to estimate. Empty → the default routing plan.",
    )


class CostEstimateItem(BaseModel):
    agent_type: str
    model: str
    estimated_tokens: int
    estimated_cost_usd: float


class CostEstimateResponse(BaseModel):
    agents: List[CostEstimateItem]
    total_estimated_usd: float


class BudgetResponse(BaseModel):
    monthly_budget_usd: float
    current_month_spend_usd: float
    remaining_usd: float
    exceeded: bool


class CostHistoryItem(BaseModel):
    """One day's aggregated spend for the tenant."""

    date: date
    cost_usd: float
    task_count: int

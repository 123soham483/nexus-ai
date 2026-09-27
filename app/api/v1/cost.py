"""Cost API Router — estimates, per-day history, and tenant budget (tenant-scoped)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.dependencies import DBSession, CurrentUser
from app.db.models.tenant import Tenant
from app.db.models.task import Task
from app.db.models.cost_record import CostRecord
from app.llm.routing import (
    NON_LLM_AGENTS,
    estimate_agent_cost,
    resolve_model,
    provider_for_agent,
)
from app.schemas.cost import (
    BudgetResponse,
    CostEstimateItem,
    CostEstimateRequest,
    CostEstimateResponse,
    CostHistoryItem,
)

router = APIRouter()

#: Used when the request carries no explicit agent types (mirrors TaskRouter's
#: DEFAULT_PLAN — the orchestrator's fallback routing).
_DEFAULT_PLAN_AGENTS = ["planner", "coder", "tester", "validator"]
_HISTORY_DAYS = 90


@router.post("/estimate", response_model=CostEstimateResponse)
async def estimate_cost_endpoint(
    body: CostEstimateRequest,
    current_user: CurrentUser,
):
    """Estimate LLM cost for a set of agent types (or the default plan).

    Pure computation over the pricing tables — no LLM call, no DB read. Uses
    the same 70/30 input/output split as the orchestrator's cost estimation.
    """
    agent_types = body.agent_types or list(_DEFAULT_PLAN_AGENTS)
    items: list[CostEstimateItem] = []
    for agent_type in agent_types:
        provider = provider_for_agent(agent_type)
        try:
            model = resolve_model(provider)
        except Exception:
            model = provider
        if agent_type in NON_LLM_AGENTS:
            model = "none"  # no LLM call — nothing to route or bill
        estimated = estimate_agent_cost(agent_type)
        items.append(
            CostEstimateItem(
                agent_type=agent_type,
                model=model,
                estimated_tokens=1000,
                estimated_cost_usd=round(estimated, 6),
            )
        )
    total = round(sum(i.estimated_cost_usd for i in items), 6)
    return CostEstimateResponse(agents=items, total_estimated_usd=total)


@router.get("/budget", response_model=BudgetResponse)
async def get_budget(
    current_user: CurrentUser,
    db: DBSession,
):
    """Current monthly budget position for the tenant."""
    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    remaining = tenant.monthly_budget_usd - tenant.current_month_spend_usd
    return BudgetResponse(
        monthly_budget_usd=tenant.monthly_budget_usd,
        current_month_spend_usd=tenant.current_month_spend_usd,
        remaining_usd=round(max(remaining, 0.0), 6),
        exceeded=remaining <= 0,
    )


@router.get("/history", response_model=list[CostHistoryItem])
async def get_cost_history(
    current_user: CurrentUser,
    db: DBSession,
):
    """Per-day aggregated spend for the tenant over the last 90 days.

    Grouping happens in Python (not SQL date functions) so the query stays
    portable across SQLite and Postgres (D2). Empty days are omitted.
    """
    since = datetime.now(timezone.utc) - timedelta(days=_HISTORY_DAYS)
    result = await db.execute(
        select(CostRecord)
        .join(Task, Task.id == CostRecord.task_id)
        .where(Task.tenant_id == current_user.tenant_id, CostRecord.recorded_at >= since)
        .order_by(CostRecord.recorded_at.asc())
    )
    records = result.scalars().all()

    by_day: dict = {}
    for record in records:
        day = record.recorded_at.date() if record.recorded_at else since.date()
        entry = by_day.setdefault(day, {"cost": 0.0, "tasks": set()})
        entry["cost"] += record.cost_usd
        entry["tasks"].add(record.task_id)

    history = [
        CostHistoryItem(
            date=day,
            cost_usd=round(entry["cost"], 6),
            task_count=len(entry["tasks"]),
        )
        for day, entry in sorted(by_day.items())
    ]
    return history

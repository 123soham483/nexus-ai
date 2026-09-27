"""Agents API Router — registry listing and tenant-scoped agent stats."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.dependencies import DBSession, CurrentUser
from app.db.models.task import Task
from app.db.models.agent_run import AgentRun
from app.schemas.agents import AgentStats, AgentTypeInfo, AgentsStatsResponse

router = APIRouter()

#: AgentRun statuses that count as a failure for success-rate stats.
_FAILED_STATUSES = ("failed", "rejected", "timed_out")


@router.get("/", response_model=List[AgentTypeInfo])
async def list_agents(
    current_user: CurrentUser,
):
    """List every known agent type with its routing model.

    Read of the shared registries — no DB access, auth required.
    """
    from app.agents.factory import AGENT_CLASSES
    from app.llm.routing import AGENT_LLM_MAP, provider_for_agent, resolve_model

    agent_types = sorted(set(AGENT_CLASSES) | set(AGENT_LLM_MAP))
    agents: List[AgentTypeInfo] = []
    for agent_type in agent_types:
        provider = provider_for_agent(agent_type)
        try:
            model = resolve_model(provider)
        except Exception:
            model = provider
        agents.append(
            AgentTypeInfo(
                agent_type=agent_type,
                provider=provider,
                model=model,
                implemented=agent_type in AGENT_CLASSES,
                llm_agent=agent_type != "hitl_controller",
            )
        )
    return agents


@router.get("/stats", response_model=AgentsStatsResponse)
async def get_agent_stats(
    current_user: CurrentUser,
    db: DBSession,
    limit: int = Query(50, ge=1, le=200),
):
    """Per-agent-type aggregate stats for the tenant (runs, success, cost)."""
    result = await db.execute(
        select(
            AgentRun.agent_type,
            func.count(),
            func.count().filter(AgentRun.status.notin_(_FAILED_STATUSES)),
            func.coalesce(func.sum(AgentRun.cost_usd), 0.0),
            func.avg(AgentRun.duration_seconds),
        )
        .join(Task, Task.id == AgentRun.task_id)
        .where(Task.tenant_id == current_user.tenant_id)
        .group_by(AgentRun.agent_type)
        .order_by(func.count().desc())
        .limit(limit)
    )
    rows = result.all()

    agents: List[AgentStats] = []
    total_runs = 0
    for agent_type, run_count, success_count, total_cost, avg_duration in rows:
        run_count = int(run_count)
        success_count = int(success_count)
        total_runs += run_count
        agents.append(
            AgentStats(
                agent_type=agent_type,
                run_count=run_count,
                success_count=success_count,
                success_rate=round(success_count / run_count, 4) if run_count else 0.0,
                total_cost_usd=round(float(total_cost or 0.0), 6),
                avg_duration_seconds=(
                    round(float(avg_duration), 2) if avg_duration is not None else None
                ),
            )
        )
    return AgentsStatsResponse(agents=agents, total_runs=total_runs)

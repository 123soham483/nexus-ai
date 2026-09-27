"""Observability API Router — tenant-wide metrics and trace events."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
import uuid

from app.dependencies import DBSession, CurrentUser
from app.db.models.task import Task
from app.db.models.agent_run import AgentRun
from app.db.models.trace import Trace
from app.db.models.enums import TaskStatus
from app.observability.hallucination_scorer import HallucinationScorer
from app.schemas.observability import HallucinationObservabilityResponse, MetricsResponse
from app.schemas.task import TraceResponse

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    current_user: CurrentUser,
    db: DBSession,
):
    """Aggregate execution metrics for the tenant across all tasks."""
    tenant_id = current_user.tenant_id

    total_tasks = (
        await db.execute(
            select(func.count()).select_from(Task).where(Task.tenant_id == tenant_id)
        )
    ).scalar_one()

    status_rows = (
        await db.execute(
            select(Task.status, func.count())
            .where(Task.tenant_id == tenant_id)
            .group_by(Task.status)
        )
    ).all()
    tasks_by_status = {
        (s.value if isinstance(s, TaskStatus) else str(s)): int(n)
        for s, n in status_rows
    }

    total_agent_runs = (
        await db.execute(
            select(func.count())
            .select_from(AgentRun)
            .join(Task, Task.id == AgentRun.task_id)
            .where(Task.tenant_id == tenant_id)
        )
    ).scalar_one()

    total_cost = (
        await db.execute(
            select(func.coalesce(func.sum(Task.actual_cost_usd), 0.0))
            .where(Task.tenant_id == tenant_id)
        )
    ).scalar_one()

    total_tokens = (
        await db.execute(
            select(func.coalesce(func.sum(Task.tokens_used), 0))
            .where(Task.tenant_id == tenant_id)
        )
    ).scalar_one()

    avg_quality = (
        await db.execute(
            select(func.avg(Task.quality_score)).where(Task.tenant_id == tenant_id)
        )
    ).scalar_one()

    avg_duration = (
        await db.execute(
            select(func.avg(Task.duration_seconds)).where(Task.tenant_id == tenant_id)
        )
    ).scalar_one()

    return MetricsResponse(
        total_tasks=int(total_tasks),
        tasks_by_status=tasks_by_status,
        total_agent_runs=int(total_agent_runs),
        total_cost_usd=round(float(total_cost or 0.0), 6),
        total_tokens=int(total_tokens or 0),
        avg_quality_score=(
            round(float(avg_quality), 4) if avg_quality is not None else None
        ),
        avg_duration_seconds=(
            round(float(avg_duration), 2) if avg_duration is not None else None
        ),
    )


@router.get("/hallucination", response_model=HallucinationObservabilityResponse)
async def get_hallucination_metrics(
    current_user: CurrentUser,
    db: DBSession,
    days: int = Query(30, ge=1, le=90),
):
    """Tenant hallucination averages, per-agent breakdown, and recent history."""
    scorer = HallucinationScorer(db_session=db)
    data = await scorer.get_tenant_breakdown(str(current_user.tenant_id), days=days)
    return HallucinationObservabilityResponse(**data)


@router.get("/traces", response_model=List[TraceResponse])
async def get_traces(
    current_user: CurrentUser,
    db: DBSession,
    task_id: Optional[uuid.UUID] = Query(default=None, description="Filter by task"),
    event_type: Optional[str] = Query(default=None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Tenant-scoped execution trace events, newest first."""
    stmt = (
        select(Trace)
        .join(Task, Task.id == Trace.task_id)
        .where(Task.tenant_id == current_user.tenant_id)
        .order_by(Trace.timestamp.desc(), Trace.sequence_number.desc())
        .limit(limit)
        .offset(offset)
    )
    if task_id is not None:
        stmt = stmt.where(Trace.task_id == task_id)
    if event_type is not None:
        stmt = stmt.where(Trace.event_type == event_type)

    result = await db.execute(stmt)
    traces = result.scalars().all()
    return list(traces)

"""Tasks API Router — authenticated and tenant-isolated endpoints for managing tasks."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional, List, cast
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, update

from app.config import settings
from app.dependencies import DBSession, CurrentUser
from app.db.models.task import Task
from app.db.models.enums import TaskStatus
from app.db.models.tenant import Tenant
from app.db.models.trace import Trace
from app.db.models.cost_record import CostRecord
from app.schemas.task import (
    TaskCreate,
    TaskResponse,
    TaskDetailResponse,
    TaskListResponse,
    TraceResponse,
    CostRecordResponse,
)
from app.schemas.hitl import HitlResolveRequest, HitlRequestResponse
from app.security.injection_scanner import InjectionScanner
from app.hitl import default_store

router = APIRouter()
logger = logging.getLogger(__name__)

#: A task PENDING longer than this was almost certainly dispatched to a worker
#: that died before executing it (acks_late redelivery lost, process killed).
#: Well below the Celery soft time limit, far above any normal queue wait.
ORPHANED_PENDING_TIMEOUT_SECONDS = 600


async def _reap_orphaned_pending(db) -> int:
    """Mark long-orphaned PENDING tasks as FAILED (never freshly queued ones).

    Runs opportunistically on each task creation: a PENDING row older than
    ORPHANED_PENDING_TIMEOUT_SECONDS with no started_at has no worker working
    on it (a live worker commits ROUTING within seconds of pickup), so it can
    only be a lost dispatch. Cheap: one indexed UPDATE per create.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=ORPHANED_PENDING_TIMEOUT_SECONDS
    )
    result = await db.execute(
        update(Task)
        .where(
            Task.status == TaskStatus.PENDING,
            Task.created_at < cutoff,
            Task.started_at.is_(None),
        )
        .values(
            status=TaskStatus.FAILED,
            result={"error": "Task could not be dispatched to the worker "
                             "(orphaned pending beyond the dispatch timeout)."},
            completed_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount:
        logger.warning("Reaped %s orphaned PENDING tasks", result.rowcount)
    return result.rowcount


def schedule_task_execution(
    task_id: str,
    goal: str,
    context: dict,
    tenant_id: str,
    user_id: str,
) -> None:
    """Queue a task on Celery, or run it in this process when ``TASK_DISPATCH=inline``.

    Inline mode is for local Windows without a Redis broker / Celery worker —
    otherwise ``delay()`` succeeds (or is stubbed) and the row stays ``pending``.
    """
    if settings.TASK_DISPATCH == "inline":
        asyncio.create_task(
            _run_task_inline(task_id, goal, context, tenant_id, user_id)
        )
        return
    from app.workers.task_worker import execute_task_worker

    logger.info("Dispatching task %s to Celery broker %s", task_id, settings.CELERY_BROKER_URL)
    async_result = execute_task_worker.delay(task_id, goal, context, tenant_id, user_id)
    logger.info("Celery dispatch returned celery_id=%s for task %s", async_result.id, task_id)


async def _run_task_inline(
    task_id: str,
    goal: str,
    context: dict,
    tenant_id: str,
    user_id: str,
) -> None:
    from app.workers.task_worker import _async_execute, _mark_task_failed

    try:
        await _async_execute(task_id, goal, context, tenant_id, user_id)
    except Exception as exc:
        logger.exception("Inline execution failed for task %s", task_id)
        await _mark_task_failed(task_id, str(exc))


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    current_user: CurrentUser,
    db: DBSession,
):
    """Create and immediately dispatch a task for asynchronous execution."""
    # 1. Scan goal for prompt injection (two-layer scanner; honours
    #    ENABLE_PROMPT_INJECTION_SCAN if the operator disabled scanning).
    scanner = InjectionScanner()
    scan_result = await scanner.scan(body.goal)
    if not scan_result.safe:
        # Surface *why* it was blocked (rule ids / categories) so a legitimate
        # goal that trips a rule can be triaged, without echoing an attacker's
        # payload back to them.
        detail = "Request blocked: potential prompt injection detected"
        if scan_result.reason:
            detail = f"{detail} ({scan_result.reason})"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )

    # 2. Load tenant, check monthly budget
    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    if tenant.current_month_spend_usd >= tenant.monthly_budget_usd:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Monthly budget exceeded. Update your budget in settings.",
        )

    # 3. Create Task row (+ reclaim long-orphaned PENDING rows from dead
    #    dispatches so they can't sit pending forever — T9).
    task = Task(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        goal=body.goal,
        context=body.context,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    await _reap_orphaned_pending(db)
    await db.commit()
    await db.refresh(task)

    # 4. Dispatch. Celery is the production path. ``TASK_DISPATCH=inline`` runs
    #    the orchestrator in this process so a missing worker cannot leave the
    #    row ``pending`` forever. A broker outage on the celery path must NOT
    #    leave an orphaned pending row while answering 201.
    try:
        schedule_task_execution(
            str(task.id),
            body.goal,
            body.context,
            str(current_user.tenant_id),
            str(current_user.id),
        )
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.result = {
            "error": f"Task could not be queued for execution: {type(exc).__name__}"
        }
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task accepted but the execution queue is unavailable. "
            "Please retry in a moment.",
        )

    return task


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    current_user: CurrentUser,
    db: DBSession,
    status: Optional[TaskStatus] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all tasks belonging to the current user's tenant, with optional status filter."""
    # Build query
    query = select(Task).where(Task.tenant_id == current_user.tenant_id)
    if status is not None:
        query = query.where(Task.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Apply pagination and fetch
    query = query.order_by(Task.created_at.desc()).limit(limit).offset(offset)
    results = await db.execute(query)
    tasks = results.scalars().all()

    # ORM rows are converted to TaskResponse by pydantic (from_attributes) during
    # response serialization — cast silences the static type mismatch.
    return TaskListResponse(
        tasks=cast(List[TaskResponse], list(tasks)),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
):
    """Get full details of a task by ID. Enforces tenant boundary."""
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == current_user.tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    return task


@router.delete("/{task_id}")
async def cancel_task(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
):
    """Best-effort cancellation of a pending/running task."""
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == current_user.tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.ROUTING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task in {task.status.value} state",
        )

    task.status = TaskStatus.CANCELLED
    await db.commit()

    return {"message": "Task cancelled", "task_id": str(task_id)}


@router.get("/{task_id}/trace", response_model=List[TraceResponse])
async def get_task_trace(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
):
    """Get ordered list of execution trace events for a task."""
    # Enforce tenant check on Task first
    task_result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == current_user.tenant_id)
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Fetch traces
    result = await db.execute(
        select(Trace)
        .where(Trace.task_id == task_id)
        .order_by(Trace.sequence_number.asc())
    )
    traces = result.scalars().all()
    return list(traces)


@router.get("/{task_id}/cost", response_model=List[CostRecordResponse])
async def get_task_cost(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
):
    """Get all billable LLM cost records for a task."""
    # Enforce tenant check on Task first
    task_result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == current_user.tenant_id)
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Fetch cost records
    result = await db.execute(
        select(CostRecord)
        .where(CostRecord.task_id == task_id)
        .order_by(CostRecord.recorded_at.asc())
    )
    costs = result.scalars().all()
    return list(costs)


async def _get_tenant_task(task_id: uuid.UUID, current_user, db) -> Task:
    """Fetch a task enforcing the tenant boundary (404 for cross-tenant)."""
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == current_user.tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    return task


@router.get("/{task_id}/hitl/pending", response_model=List[HitlRequestResponse])
async def list_pending_hitl_requests(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
):
    """List all pending HITL approval requests for a task (tenant-scoped)."""
    await _get_tenant_task(task_id, current_user, db)
    requests = await default_store.list_pending(task_id=str(task_id))
    return list(requests)


@router.get("/{task_id}/hitl/history", response_model=List[HitlRequestResponse])
async def list_hitl_history(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
):
    """All HITL requests for a task — pending and resolved (newest first)."""
    await _get_tenant_task(task_id, current_user, db)
    requests = await default_store.list_requests(task_id=str(task_id))
    return list(requests)


@router.post("/{task_id}/hitl/resolve", response_model=HitlRequestResponse)
async def resolve_hitl_request(
    task_id: uuid.UUID,
    body: HitlResolveRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    """Approve or reject a pending HITL request for a task.

    The decision wakes the waiting HitlController (via the store), which emits
    ``hitl_resolved`` and completes with the human's verdict.
    """
    await _get_tenant_task(task_id, current_user, db)

    request = await default_store.get(str(body.request_id))
    if request is None or request.task_id != str(task_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="HITL request not found",
        )
    if request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"HITL request already resolved ({request.status})",
        )

    resolved = await default_store.resolve(
        request.id,
        approved=body.approved,
        resolved_by=str(current_user.id),
        note=body.note,
    )
    return resolved

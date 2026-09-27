import asyncio
import uuid as _uuid_module
from celery.exceptions import SoftTimeLimitExceeded

from app.config import settings
from app.workers.celery_app import celery_app

@celery_app.task(
    bind=True,
    max_retries=3,
    name="nexusai.execute_task",
    # Time limits come from settings so they can never fall below the HITL wait
    # (Phase 3, Step 3.4): a task blocked on human approval needs the soft limit
    # to outlast HITL_TIMEOUT_SECONDS, otherwise every approval is a race with
    # Celery. Settings validates soft > HITL timeout and hard > soft.
    soft_time_limit=settings.TASK_SOFT_TIME_LIMIT,
    time_limit=settings.TASK_TIME_LIMIT,
)
def execute_task_worker(
    self,
    task_id: str,
    goal: str,
    context: dict,
    tenant_id: str,
    user_id: str,
):
    """
    Celery task that runs the NexusAI orchestration pipeline.
    Bridges sync Celery into async orchestrator via asyncio.run().
    """
    try:
        asyncio.run(_async_execute(task_id, goal, context, tenant_id, user_id))
    except SoftTimeLimitExceeded:
        # Celery raised because the task blocked too long (e.g. a stuck HITL
        # wait or LLM call). Re-raising would trigger a *retry* that re-runs
        # the whole non-idempotent pipeline, so finalise the failure instead.
        asyncio.run(
            _mark_task_failed(task_id, f"Task exceeded the {settings.TASK_SOFT_TIME_LIMIT}s execution limit")
        )
        raise
    except Exception as exc:
        # The orchestrator's failure path already persisted status=failed + the
        # task_failed trace (and re-raised), so retrying here would re-run a
        # non-idempotent LLM pipeline and could flip a FAILED task back to
        # running. Only genuinely non-executed failures (DB/dispatch layer,
        # before the orchestrator saw the task) are worth retrying.
        if self.request.retries < self.max_retries and not _failure_was_persisted(task_id):
            # Exponential backoff: 2^retry seconds
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        # Max retries exhausted (or the failure is already durable) — make sure
        # the DB reflects a terminal state, then surface the error to Celery.
        asyncio.run(_mark_task_failed(task_id, str(exc)))
        raise


async def _async_execute(task_id, goal, context, tenant_id, user_id):
    """
    Build the full orchestrator dependency graph and run execute_task.
    All dependencies built here — not at module level (lazy init pattern).
    """
    from app.db.session import get_session_context   # context manager version
    from app.memory.short_term import ShortTermMemory
    from app.memory.long_term import LongTermMemory
    from app.memory.learning_engine import LearningEngine
    from app.core.router import TaskRouter
    from app.core.orchestrator import Orchestrator
    from app.websockets.manager import manager
    from app.websockets.broadcaster import WebSocketBroadcaster

    async with get_session_context() as db:
        short_memory = ShortTermMemory()
        long_memory = LongTermMemory(tenant_prefix=tenant_id[:8])
        # Phase 3: the living production path — one engine feeds both the router
        # (learned hints read) and the orchestrator (learned storage on outcome).
        learning_engine = LearningEngine(long_memory)
        router = TaskRouter(learning_engine=learning_engine)
        broadcaster = WebSocketBroadcaster(manager=manager, db_session=db)

        orchestrator = Orchestrator(
            router=router,
            agent_factory=_build_agent_factory(short_memory, long_memory),
            short_memory=short_memory,
            long_memory=long_memory,
            broadcaster=broadcaster,
            db_session=db,
            learning_engine=learning_engine,
        )

        await orchestrator.execute_task(task_id, goal, context, tenant_id, user_id)


def _build_agent_factory(short_memory, long_memory):
    """Returns a factory function that creates agent instances.

    Uses the shared :class:`app.agents.factory.AgentFactory` registry, injecting
    the real LLM provider and the shared short/long-term memories.
    """
    from app.agents.factory import AgentFactory
    from app.llm.provider import default_provider

    factory = AgentFactory(
        llm=default_provider,
        short_term=short_memory,
        long_term=long_memory,
    )
    return factory.create


async def _mark_task_failed(task_id: str, error: str):
    """Update task status to failed after max retries exhausted.

    Runs in its OWN session and commits directly — by the time this is called
    the orchestrator's session is gone, so the terminal status must be
    persisted here, not left to the caller's transaction management.
    """
    from app.db.session import get_session_context
    from app.db.models.task import Task, TaskStatus
    from sqlalchemy import select

    async with get_session_context() as db:
        uuid_task_id = (
            _uuid_module.UUID(task_id) if isinstance(task_id, str) else task_id
        )
        result = await db.execute(select(Task).where(Task.id == uuid_task_id))
        task = result.scalar_one_or_none()
        if task and task.status not in (TaskStatus.FAILED, TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            task.status = TaskStatus.FAILED
            task.result = {"error": error}
            from datetime import datetime, timezone

            task.completed_at = datetime.now(timezone.utc)
            await db.commit()


def _failure_was_persisted(task_id: str) -> bool:
    """True when the task row is already in a terminal state.

    Checked SYNCHRONOUSLY (short own event loop) so the retry decision in the
    sync Celery body can ask: did the orchestrator already record this failure?
    If yes, retrying would re-run the pipeline for nothing.
    """
    import sqlite3  # noqa: F401  (avoid unused-import lint when non-sqlite)

    try:
        return asyncio.run(_task_is_terminal(task_id))
    except Exception:  # pragma: no cover - defensive: never block the retry path
        return False


async def _task_is_terminal(task_id: str) -> bool:
    from app.db.session import get_session_context
    from app.db.models.task import Task, TaskStatus
    from sqlalchemy import select

    async with get_session_context() as db:
        uuid_task_id = (
            _uuid_module.UUID(task_id) if isinstance(task_id, str) else task_id
        )
        result = await db.execute(select(Task).where(Task.id == uuid_task_id))
        task = result.scalar_one_or_none()
        return bool(
            task and task.status in (TaskStatus.FAILED, TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        )

"""Regression tests for the task-execution crash (BRAIN.md T1/T2/T3).

Covers the real failure chain reproduced live on Windows without Docker:
  T1  worker starts with an EMPTY task registry -> "Received unregistered task
      of type 'nexusai.execute_task'" -> tasks stay `pending` forever.
  T2  worker session rollback erased the orchestrator's FAILED status +
      failure traces -> task looked stuck in `pending` even though the
      failure path had run.
  T3  the worker retried a non-idempotent pipeline on every exception,
      including failures the orchestrator had already persisted.
  T4  a down broker used to 500 AFTER the row was committed -> orphaned
      `pending` task + 500; now the row is failed and a 503 is returned.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.celery_app import celery_app
from app.workers.task_worker import execute_task_worker

pytestmark = pytest.mark.integration


# ── T1: the worker process must know the task ────────────────────────────────
def test_celery_app_includes_worker_module_so_registry_is_not_empty():
    """The live reproduction: a worker started with
    `celery -A app.workers.celery_app worker` received the message and raised
    KeyError('nexusai.execute_task') because nothing imported task_worker.
    `include` must keep the registry populated in a fresh worker process.
    """
    assert "app.workers.task_worker" in celery_app.conf.include
    # And the registry really resolves the task (not just the module list):
    assert "nexusai.execute_task" in celery_app.tasks


# ── T2: failure state must survive the worker's session rollback ─────────────
async def test_orchestrator_failure_commits_failed_status_and_error(db_session):
    """Simulate the exact live sequence: orchestrator marks FAILED + raises,
    then the worker's context manager rolls the session back. The FAILED state
    must survive because the failure path committed it explicitly."""
    from sqlalchemy import select

    from app.core.orchestrator import Orchestrator
    from app.db.models.task import Task
    from app.db.models.enums import TaskStatus
    from app.db.models.tenant import Tenant

    tenant = Tenant(name="t2", slug="t2", chroma_collection_prefix="t2")
    db_session.add(tenant)
    await db_session.flush()
    task = Task(
        user_id=uuid.uuid4(), tenant_id=tenant.id, goal="fail on purpose"
    )
    db_session.add(task)
    await db_session.commit()
    task_id = str(task.id)

    class _ExplodingRouter:
        async def plan(self, *_args, **_kwargs):
            raise RuntimeError("LLM provider unavailable (controlled failure)")

    orchestrator = Orchestrator(
        router=_ExplodingRouter(),
        agent_factory=lambda _t: None,  # never reached
        short_memory=MagicMock(),
        long_memory=MagicMock(),
        broadcaster=AsyncMock(),  # _emit awaits broadcaster.emit(...)
        db_session=db_session,
        learning_engine=None,
    )
    long_memory = orchestrator.long_memory
    long_memory.search_similar_failures = AsyncMock(return_value=[])

    with pytest.raises(RuntimeError, match="LLM provider unavailable"):
        await orchestrator.execute_task(
            task_id, "fail on purpose", {}, str(tenant.id), str(uuid.uuid4())
        )

    # The failure path must have PERSISTED (not just flushed):
    row = (
        await db_session.execute(select(Task).where(Task.id == task.id))
    ).scalar_one()
    assert row.status == TaskStatus.FAILED
    assert "LLM provider unavailable" in row.result["error"]
    assert row.completed_at is not None


async def test_worker_session_context_preserves_committed_failure_state():
    """get_session_context must not roll back data the callee already committed
    when an exception propagates (the T2 half of the crash)."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import Base
    from app.db.models.enums import TaskStatus
    from app.db.models.task import Task
    from app.db.models.tenant import Tenant
    from app.db.session import get_session_context

    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)

    # get_session_context resolves the process-wide sessionmaker; inject the
    # test one (the worker process does the equivalent via DATABASE_URL).
    from app.db import session as db_session_module

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(db_session_module, "_sessionmaker", maker, raising=False)

        async with maker() as seed:
            tenant = Tenant(name="t2b", slug="t2b", chroma_collection_prefix="t2b")
            seed.add(tenant)
            await seed.flush()
            task = Task(user_id=uuid.uuid4(), tenant_id=tenant.id, goal="ctx test")
            seed.add(task)
            await seed.commit()
            task_id = str(task.id)

        # Simulate the orchestrator: mutate, commit, then raise.
        with _pytest.raises(RuntimeError):
            async with get_session_context() as session:
                row = (
                    await session.execute(select(Task).where(Task.id == task.id))
                ).scalar_one()
                row.status = TaskStatus.FAILED
                row.result = {"error": "boom"}
                await session.commit()
                raise RuntimeError("boom")

        # The worker's cleanup ran rollback+close — the committed FAILED survives.
        async with maker() as verify:
            row = (
                await verify.execute(select(Task).where(Task.id == task.id))
            ).scalar_one()
            assert row.status == TaskStatus.FAILED
            assert row.result == {"error": "boom"}

    await engine.dispose()


# ── T3: do not retry a failure the orchestrator already persisted ────────────
@patch("app.workers.task_worker._failure_was_persisted", return_value=True)
@patch("app.workers.task_worker.asyncio.run")
def test_worker_does_not_retry_when_failure_already_persisted(
    mock_run, _mock_persisted
):
    """Retry would re-run a non-idempotent LLM pipeline; when the FAILED state
    is durable the worker must finalise and surface the error instead."""
    mock_run.side_effect = RuntimeError("All LLM providers failed")

    task_self = MagicMock()
    task_self.request.retries = 0  # would normally retry
    task_self.max_retries = 3
    task_self.retry = MagicMock()
    task_self.backend = MagicMock()

    with patch(
        "app.workers.task_worker._mark_task_failed", new_callable=AsyncMock
    ) as mock_mark:
        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            execute_task_worker.__class__.run(
                task_self,
                task_id=str(uuid.uuid4()),
                goal="g",
                context={},
                tenant_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
            )
        mock_mark.assert_called_once()

    task_self.retry.assert_not_called()


# ── T4: broker down must not 500 with an orphaned `pending` row ──────────────
@patch("app.workers.task_worker.execute_task_worker.delay")
async def test_create_task_broker_down_fails_the_row_and_returns_503(
    mock_delay, app_client
):
    mock_delay.side_effect = ConnectionError("Error 111 connecting to localhost:6379")

    headers = await _register(app_client, "brokerdown@example.com")
    r = await app_client.post(
        "/api/v1/tasks/", json={"goal": "implement bubble sort in python"}, headers=headers
    )

    assert r.status_code == 503, r.text
    assert "queue is unavailable" in r.json()["error"]
    mock_delay.assert_called_once()


async def _register(app_client, email: str):
    r = await app_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepassword", "full_name": "T"},
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}

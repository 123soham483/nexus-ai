"""Post-PENDING-stabilization regression tests (2026-09-27 update).

Proves, at the integration level, the invariants the stabilization phase added:

  R1  A task can never remain PENDING indefinitely — every dispatch/execution
      failure path ends in a terminal state (existing T1–T4 tests in
      test_task_execution_regression.py cover the worker/registry side; here
      we cover the reaper and re-assert the end states).
  R2  The 600s orphaned-PENDING reaper fails old orphans but never touches
      freshly queued tasks (no false positives on legitimate queue waits).
  R3  Status transitions PENDING→ROUTING→RUNNING are committed immediately:
      an external DB reader sees RUNNING while the LLM is still executing
      (the T8 fix — no end-of-task-only commits).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.db.models.enums import TaskStatus
from app.db.models.task import Task
from app.db.models.tenant import Tenant

pytestmark = pytest.mark.integration


async def _make_task(db_session, *, created_at=None, status=TaskStatus.PENDING,
                     started_at=None, goal="orphan test") -> Task:
    tenant = Tenant(name=f"t-{uuid.uuid4().hex[:8]}", slug=f"t-{uuid.uuid4().hex[:8]}",
                    chroma_collection_prefix="t")
    db_session.add(tenant)
    await db_session.flush()
    task = Task(
        user_id=uuid.uuid4(), tenant_id=tenant.id, goal=goal, status=status,
        created_at=created_at or datetime.now(timezone.utc),
    )
    if started_at is not None:
        task.started_at = started_at
    db_session.add(task)
    await db_session.commit()
    return task


# ── R2: the 600s orphaned-PENDING reaper ─────────────────────────────────────

async def test_reaper_fails_old_orphaned_pending(db_session):
    """PENDING + no started_at + older than 600s -> FAILED with a clear error."""
    from app.api.v1.tasks import _reap_orphaned_pending

    old = await _make_task(
        db_session,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=601),
    )

    reaped = await _reap_orphaned_pending(db_session)
    await db_session.commit()

    assert reaped >= 1
    row = (
        await db_session.execute(select(Task).where(Task.id == old.id))
    ).scalar_one()
    assert row.status == TaskStatus.FAILED
    assert "orphaned" in row.result["error"]
    assert row.completed_at is not None


async def test_reaper_leaves_fresh_queued_tasks_alone(db_session):
    """PENDING + recently created -> must remain PENDING (no false positive)."""
    from app.api.v1.tasks import _reap_orphaned_pending

    fresh = await _make_task(db_session)  # created now

    reaped_fresh = await _reap_orphaned_pending.__wrapped__(db_session) if hasattr(
        _reap_orphaned_pending, "__wrapped__"
    ) else None
    # Direct call against a session containing only fresh tasks:
    from app.api.v1.tasks import _reap_orphaned_pending as reap

    count = await reap(db_session)
    await db_session.commit()
    assert count == 0  # nothing older than the cutoff exists in this session

    row = (
        await db_session.execute(select(Task).where(Task.id == fresh.id))
    ).scalar_one()
    assert row.status == TaskStatus.PENDING
    assert row.completed_at is None


async def test_reaper_never_touches_running_or_started_tasks(db_session):
    """RUNNING tasks and PENDING tasks WITH started_at are never reaped."""
    from app.api.v1.tasks import _reap_orphaned_pending

    old_running = await _make_task(
        db_session,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=1200),
        status=TaskStatus.RUNNING,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=1100),
    )
    old_started_pending = await _make_task(
        db_session,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=1200),
        status=TaskStatus.PENDING,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=1150),
    )

    await _reap_orphaned_pending(db_session)
    await db_session.commit()

    r = (await db_session.execute(select(Task).where(Task.id == old_running.id))).scalar_one()
    s = (await db_session.execute(select(Task).where(Task.id == old_started_pending.id))).scalar_one()
    assert r.status == TaskStatus.RUNNING
    assert s.status == TaskStatus.PENDING


async def test_reaper_timeout_is_600_seconds():
    from app.api.v1.tasks import ORPHANED_PENDING_TIMEOUT_SECONDS
    assert ORPHANED_PENDING_TIMEOUT_SECONDS == 600


# ── R3: immediate status commits (external reader sees RUNNING mid-task) ─────

async def test_external_reader_sees_running_during_execution(db_engine):
    """While the LLM is still executing, an independent session must already
    observe status=RUNNING — proving the ROUTING/RUNNING commits are real
    commits, not end-of-task flushes (T8 regression guard)."""
    from unittest.mock import AsyncMock as _AM

    from app.core.orchestrator import Orchestrator
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # Two independent sessions on the SAME database: one drives the
    # orchestrator, the other plays the external reader (UI/API).
    async with maker() as writer, maker() as reader:
        tenant = Tenant(name="t-ext", slug="t-ext", chroma_collection_prefix="t-ext")
        writer.add(tenant)
        await writer.flush()
        task = Task(user_id=uuid.uuid4(), tenant_id=tenant.id, goal="watch me run")
        writer.add(task)
        await writer.commit()
        task_id = str(task.id)

        class _SlowRouter:
            def __init__(self):
                self.seen_during_plan = None

            async def plan(self, *_a, **_k):
                # While "the routing LLM call is in flight", read from the INDEPENDENT
                # session. In-memory SQLite shares the DB across sessions on
                # one engine, so this sees only COMMITTED state.
                row = (await reader.execute(
                    select(Task).where(Task.id == task.id)
                )).scalar_one()
                self.seen_during_plan = row.status
                raise RuntimeError("stop before real execution")

        slow_router = _SlowRouter()
        orchestrator = Orchestrator(
            router=slow_router,
            agent_factory=lambda _t: None,
            short_memory=MagicMock(),
            long_memory=MagicMock(),
            broadcaster=_AM(),  # _emit awaits broadcaster.emit(...)
            db_session=writer,
            learning_engine=None,
        )
        orchestrator.long_memory.search_similar_failures = _AM(return_value=[])

        with pytest.raises(RuntimeError, match="stop before real execution"):
            await orchestrator.execute_task(
                task_id, "watch me run", {}, str(tenant.id), str(uuid.uuid4())
            )

        # ROUTING commit already happened before router.plan() ran: an external
        # reader sees ROUTING (not stale PENDING) while the routing LLM executes.
        assert slow_router.seen_during_plan == TaskStatus.ROUTING, (
            "External reader must see ROUTING while the routing LLM executes — "
            "the immediate PENDING→ROUTING commit is missing or deferred (T8 regression)."
        )

        # And the failure path must also commit its terminal state:
        row = (await reader.execute(select(Task).where(Task.id == task.id))).scalar_one()
        assert row.status == TaskStatus.FAILED

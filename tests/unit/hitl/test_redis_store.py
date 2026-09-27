"""Tests for the cross-process HITL store (Phase 3, Step 3.4).

Uses fakeredis (including its pub/sub) so the whole worker-creates /
API-resolves dance runs with no real Redis.
"""
from __future__ import annotations

import asyncio

import pytest

from app.hitl import build_store, default_store
from app.hitl.redis_store import RedisHitlStore
from app.hitl.store import APPROVED, PENDING, REJECTED, TIMED_OUT, HitlStore


# ── factory ──────────────────────────────────────────────────────────────────

def test_build_store_defaults_to_in_memory():
    assert isinstance(build_store("memory"), HitlStore)
    assert isinstance(build_store(None), HitlStore)


def test_build_store_redis_backend():
    assert isinstance(build_store("redis"), RedisHitlStore)


def test_shared_default_store_is_in_memory_for_dev():
    assert isinstance(default_store, HitlStore)


# ── CRUD over fakeredis ──────────────────────────────────────────────────────

async def test_create_and_get_round_trip(fake_redis):
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="deploy", reason="risky"
    )

    fetched = await store.get(request.id)
    assert fetched is not None
    assert fetched.task_id == "t1"
    assert fetched.goal == "deploy"
    assert fetched.reason == "risky"
    assert fetched.status == PENDING
    assert fetched.resolved_at is None


async def test_get_unknown_returns_none(fake_redis):
    assert await RedisHitlStore(fake_redis).get("nope") is None


async def test_dashed_and_undashed_ids_are_the_same_record(fake_redis):
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r",
        request_id="ABCDEF01-2345-6789-ABCD-EF0123456789",
    )
    assert request.id == "abcdef0123456789abcdef0123456789"
    assert (await store.get("ABCDEF01-2345-6789-ABCD-EF0123456789")) is not None
    assert (await store.get("abcdef0123456789abcdef0123456789")) is not None


async def test_create_writes_a_ttl(fake_redis):
    """Abandoned approvals must not leak in Redis forever."""
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )
    assert await fake_redis.ttl(f"hitl:request:{request.id}") > 0


async def test_resolve_marks_approved_and_records_who(fake_redis):
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )

    resolved = await store.resolve(request.id, True, resolved_by="alice", note="lgtm")

    assert resolved.status == APPROVED
    assert resolved.resolved_by == "alice"
    assert resolved.note == "lgtm"
    assert resolved.resolved_at is not None
    # Persisted, not just returned.
    stored = await store.get(request.id)
    assert stored.status == APPROVED
    assert stored.resolved_by == "alice"


async def test_resolve_rejects(fake_redis):
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )
    assert (await store.resolve(request.id, False)).status == REJECTED


async def test_resolve_unknown_returns_none(fake_redis):
    assert await RedisHitlStore(fake_redis).resolve("ghost", True) is None


async def test_first_decision_wins(fake_redis):
    """Two API replicas racing must not flip the verdict."""
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )

    await store.resolve(request.id, True, resolved_by="alice")
    second = await store.resolve(request.id, False, resolved_by="bob")

    assert second.status == APPROVED
    assert (await store.get(request.id)).resolved_by == "alice"


# ── listing ──────────────────────────────────────────────────────────────────

async def test_list_pending_is_task_scoped(fake_redis):
    store = RedisHitlStore(fake_redis)
    a = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )
    await store.create(task_id="t2", agent_type="hitl_controller", goal="g", reason="r")

    pending = await store.list_pending(task_id="t1")

    assert [r.id for r in pending] == [a.id]


async def test_list_pending_excludes_resolved(fake_redis):
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )
    await store.resolve(request.id, True)

    assert await store.list_pending(task_id="t1") == []
    history = await store.list_requests(task_id="t1")
    assert [r.status for r in history] == [APPROVED]


async def test_list_requests_across_all_tasks_is_newest_first(fake_redis):
    store = RedisHitlStore(fake_redis)
    first = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )
    second = await store.create(
        task_id="t2", agent_type="hitl_controller", goal="g", reason="r"
    )
    # Force a deterministic ordering (both created in the same microsecond).
    second.created_at = first.created_at.replace(microsecond=first.created_at.microsecond + 1)
    await fake_redis.hset(
        f"hitl:request:{second.id}", mapping={"created_at": second.created_at.isoformat()}
    )

    all_requests = await store.list_requests()

    assert [r.id for r in all_requests] == [second.id, first.id]


# ── cross-process wait / resolve ─────────────────────────────────────────────

async def test_wait_for_returns_immediately_when_already_resolved(fake_redis):
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )
    await store.resolve(request.id, True, resolved_by="alice")

    assert (await store.wait_for(request.id, timeout=1)).status == APPROVED


async def test_wait_for_unknown_raises_key_error(fake_redis):
    with pytest.raises(KeyError):
        await RedisHitlStore(fake_redis).wait_for("ghost", timeout=1)


async def test_wait_is_woken_by_a_resolution_from_another_store(fake_redis):
    """The real bug: worker waits, API process (separate store) resolves."""
    worker_store = RedisHitlStore(fake_redis)   # Celery process
    api_store = RedisHitlStore(fake_redis)      # API process
    request = await worker_store.create(
        task_id="t1", agent_type="hitl_controller", goal="deploy", reason="risky"
    )

    waiter = asyncio.create_task(worker_store.wait_for(request.id, timeout=5))
    await asyncio.sleep(0.05)  # let the waiter subscribe
    assert not waiter.done()

    await api_store.resolve(request.id, True, resolved_by="alice")

    resolved = await asyncio.wait_for(waiter, timeout=5)
    assert resolved.status == APPROVED
    assert resolved.resolved_by == "alice"


async def test_wait_times_out_and_stamps_the_record(fake_redis):
    store = RedisHitlStore(fake_redis)
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="g", reason="r"
    )

    resolved = await store.wait_for(request.id, timeout=0.05)

    assert resolved.status == TIMED_OUT
    # The API reads the same verdict, not just the waiting worker.
    assert (await store.get(request.id)).status == TIMED_OUT


async def test_hitl_controller_resolves_across_processes(fake_redis):
    """The production path: worker-created request, API-resolved decision."""
    from app.agents.coordination.hitl_controller import HitlController

    controller = HitlController(
        store=RedisHitlStore(fake_redis), timeout_seconds=5
    )
    api_store = RedisHitlStore(fake_redis)  # a different process, same Redis

    running = asyncio.create_task(controller.execute("deploy to prod", {}, "t1"))
    await asyncio.sleep(0.05)

    pending = await api_store.list_pending(task_id="t1")
    assert len(pending) == 1
    await api_store.resolve(pending[0].id, True, resolved_by="alice", note="lgtm")

    result = await asyncio.wait_for(running, timeout=5)
    assert result.success is True
    assert result.parsed["approved"] is True
    assert result.parsed["resolved_by"] == "alice"


async def test_clear_drops_everything(fake_redis):
    store = RedisHitlStore(fake_redis)
    await store.create(task_id="t1", agent_type="hitl_controller", goal="g", reason="r")

    await store.clear()

    assert await store.list_requests() == []

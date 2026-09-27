"""Unit tests for the HITL request store (Phase 2.14)."""
from __future__ import annotations

import asyncio

import pytest

from app.hitl.store import HitlStore


@pytest.fixture
def store() -> HitlStore:
    return HitlStore()


async def test_create_stores_pending_request(store):
    request = await store.create(
        task_id="t1", agent_type="hitl_controller", goal="deploy", reason="needs approval"
    )
    assert request.status == "pending"
    assert request.id
    assert request.task_id == "t1"
    assert request.goal == "deploy"
    assert (await store.get(request.id)) is request


async def test_get_returns_none_for_unknown(store):
    assert await store.get("nope") is None


async def test_list_pending_filters_by_task(store):
    req1 = await store.create(task_id="t1", agent_type="hitl_controller", goal="g1", reason="r")
    req2 = await store.create(task_id="t2", agent_type="hitl_controller", goal="g2", reason="r")
    req3 = await store.create(task_id="t2", agent_type="hitl_controller", goal="g3", reason="r")
    await store.resolve(req2.id, approved=True)

    pending_t2 = await store.list_pending(task_id="t2")
    assert [r.id for r in pending_t2] == [req3.id]

    # Without a filter, resolved requests are excluded too.
    all_pending = await store.list_pending()
    assert {r.id for r in all_pending} == {req1.id, req3.id}


async def test_resolve_approve_sets_status_and_stamps(store):
    request = await store.create(task_id="t1", agent_type="hitl_controller", goal="g", reason="r")
    resolved = await store.resolve(request.id, approved=True, resolved_by="user-1", note="go ahead")
    assert resolved.status == "approved"
    assert resolved.resolved_by == "user-1"
    assert resolved.note == "go ahead"
    assert resolved.resolved_at is not None
    assert (await store.get(request.id)).status == "approved"


async def test_resolve_reject_sets_status_rejected(store):
    request = await store.create(task_id="t1", agent_type="hitl_controller", goal="g", reason="r")
    resolved = await store.resolve(request.id, approved=False, resolved_by="user-1")
    assert resolved.status == "rejected"


async def test_resolve_is_idempotent_first_decision_wins(store):
    request = await store.create(task_id="t1", agent_type="hitl_controller", goal="g", reason="r")
    first = await store.resolve(request.id, approved=True, resolved_by="alice")
    second = await store.resolve(request.id, approved=False, resolved_by="bob")
    assert second is first
    assert second.status == "approved"
    assert second.resolved_by == "alice"


async def test_resolve_unknown_returns_none(store):
    assert await store.resolve("nope", approved=True) is None


async def test_wait_for_returns_immediately_when_already_resolved(store):
    request = await store.create(task_id="t1", agent_type="hitl_controller", goal="g", reason="r")
    await store.resolve(request.id, approved=True)
    result = await store.wait_for(request.id, timeout=0.5)
    assert result.status == "approved"


async def test_wait_for_wakes_when_resolved(store):
    request = await store.create(task_id="t1", agent_type="hitl_controller", goal="g", reason="r")

    async def _resolve_later():
        await asyncio.sleep(0.01)
        await store.resolve(request.id, approved=True, resolved_by="user-1")

    resolver = asyncio.create_task(_resolve_later())
    result = await store.wait_for(request.id, timeout=5)
    await resolver
    assert result.status == "approved"
    assert result.resolved_by == "user-1"


async def test_wait_for_times_out_and_marks_timed_out(store):
    request = await store.create(task_id="t1", agent_type="hitl_controller", goal="g", reason="r")
    result = await store.wait_for(request.id, timeout=0.01)
    assert result.status == "timed_out"
    assert (await store.get(request.id)).status == "timed_out"


async def test_wait_for_unknown_request_raises(store):
    with pytest.raises(KeyError):
        await store.wait_for("nope", timeout=0.01)


async def test_list_requests_returns_pending_and_resolved(store):
    r1 = await store.create(task_id="t1", agent_type="hitl_controller", goal="g1", reason="r1")
    r2 = await store.create(task_id="t1", agent_type="hitl_controller", goal="g2", reason="r2")
    await store.resolve(r1.id, approved=True)

    all_for_task = await store.list_requests(task_id="t1")
    assert {r.id for r in all_for_task} == {r1.id, r2.id}
    assert {r.status for r in all_for_task} == {"pending", "approved"}

    # Without a filter, requests for other tasks appear too.
    other = await store.create(task_id="t2", agent_type="hitl_controller", goal="g3", reason="r3")
    everything = await store.list_requests()
    assert {r.id for r in everything} == {r1.id, r2.id, other.id}


async def test_clear_drops_all_requests(store):
    await store.create(task_id="t1", agent_type="hitl_controller", goal="g", reason="r")
    await store.clear()
    assert await store.list_pending() == []

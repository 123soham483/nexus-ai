"""Unit tests for the non-LLM HitlController (Phase 2.14).

Zero real services: a fresh in-memory HitlStore, a fake broadcaster, and a
poisoned LLM (the controller must never call it). The wait-for-resolution path
is exercised by running ``execute`` as a task and resolving from the test.
"""
from __future__ import annotations

import asyncio

from app.hitl.store import HitlStore
from app.agents.coordination.hitl_controller import HitlController
from app.websockets.events import HITL_REQUIRED, HITL_RESOLVED

TASK_ID = "11111111-2222-3333-4444-555555555555"


class FakeBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, task_id, event_type, data) -> None:
        self.events.append((task_id, event_type, data))


class ExplodingLLM:
    async def complete(self, *args, **kwargs):
        raise AssertionError("hitl_controller must never call the LLM")


def _controller(store=None, broadcaster=None, **kwargs) -> HitlController:
    return HitlController(
        store=store or HitlStore(),
        broadcaster=broadcaster,
        timeout_seconds=5,
        **kwargs,
    )


async def test_execute_creates_pending_request_and_returns_agent_result():
    store = HitlStore()
    controller = _controller(store=store)

    exec_task = asyncio.create_task(controller.execute("deploy the service", task_id=TASK_ID))
    await asyncio.sleep(0.01)

    pending = await store.list_pending()
    assert len(pending) == 1
    assert pending[0].goal == "deploy the service"
    assert pending[0].task_id == TASK_ID
    assert pending[0].status == "pending"

    await store.resolve(pending[0].id, approved=True, resolved_by="human-1", note="ship it")
    result = await exec_task

    assert result.agent_type == "hitl_controller"
    assert result.success is True
    assert result.parsed["decision"] == "approved"
    assert result.parsed["request_id"] == pending[0].id
    assert result.parsed["resolved_by"] == "human-1"
    assert result.parsed["note"] == "ship it"


async def test_emits_hitl_required_with_request_details():
    store = HitlStore()
    broadcaster = FakeBroadcaster()
    controller = _controller(store=store, broadcaster=broadcaster)

    exec_task = asyncio.create_task(controller.execute("deploy", task_id=TASK_ID))
    await asyncio.sleep(0.01)
    pending = await store.list_pending()
    await store.resolve(pending[0].id, approved=True)
    await exec_task

    required = [e for e in broadcaster.events if e[1] == HITL_REQUIRED]
    assert len(required) == 1
    task_id, event_type, data = required[0]
    assert task_id == TASK_ID
    assert data["request_id"] == pending[0].id
    assert data["task_id"] == TASK_ID
    assert data["status"] == "pending"
    assert data["goal"] == "deploy"
    assert data["reason"]


async def test_rejected_approval_returns_failed_result():
    store = HitlStore()
    controller = _controller(store=store)

    exec_task = asyncio.create_task(controller.execute("deploy", task_id=TASK_ID))
    await asyncio.sleep(0.01)
    pending = await store.list_pending()
    await store.resolve(pending[0].id, approved=False, resolved_by="human-1", note="not now")
    result = await exec_task

    assert result.success is False
    assert result.status == "rejected"
    assert "rejected" in (result.error or "")
    assert result.parsed["approved"] is False
    assert result.parsed["resolved_by"] == "human-1"
    assert result.parsed["note"] == "not now"


async def test_timeout_returns_failed_result():
    store = HitlStore()
    controller = HitlController(store=store, timeout_seconds=0.01)
    result = await controller.execute("deploy", task_id=TASK_ID)
    assert result.success is False
    assert result.status == "timed_out"
    assert "timed out" in (result.error or "")
    assert (await store.list_pending()) == []


async def test_emits_hitl_resolved_with_decision():
    store = HitlStore()
    broadcaster = FakeBroadcaster()
    controller = _controller(store=store, broadcaster=broadcaster)

    exec_task = asyncio.create_task(controller.execute("deploy", task_id=TASK_ID))
    await asyncio.sleep(0.01)
    pending = await store.list_pending()
    await store.resolve(pending[0].id, approved=True, resolved_by="human-1")
    await exec_task

    resolved = [e for e in broadcaster.events if e[1] == HITL_RESOLVED]
    assert len(resolved) == 1
    data = resolved[0][2]
    assert data["status"] == "approved"
    assert data["resolved_by"] == "human-1"
    assert data["request_id"] == pending[0].id


async def test_no_llm_call_and_zero_cost():
    controller = _controller()
    controller.llm = ExplodingLLM()  # would raise if execute touched the LLM

    exec_task = asyncio.create_task(controller.execute("deploy", task_id=TASK_ID))
    await asyncio.sleep(0.01)
    pending = await controller.store.list_pending()
    await controller.store.resolve(pending[0].id, approved=True)
    result = await exec_task

    assert result.cost_usd == 0.0
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.provider == "human"
    assert result.model == "human-in-the-loop"


async def test_reason_comes_from_context():
    store = HitlStore()
    controller = _controller(store=store)

    exec_task = asyncio.create_task(
        controller.execute(
            "deploy", context={"approval_reason": "Deploying to production"}, task_id=TASK_ID
        )
    )
    await asyncio.sleep(0.01)
    pending = await store.list_pending()
    assert pending[0].reason == "Deploying to production"
    await store.resolve(pending[0].id, approved=True)
    await exec_task


async def test_result_converts_to_agent_run():
    store = HitlStore()
    controller = _controller(store=store)

    exec_task = asyncio.create_task(controller.execute("deploy", task_id=TASK_ID))
    await asyncio.sleep(0.01)
    pending = await store.list_pending()
    await store.resolve(pending[0].id, approved=True)
    result = await exec_task

    run = result.to_agent_run(TASK_ID)
    assert run.agent_type == "hitl_controller"
    assert run.status == "approved"
    assert run.cost_usd == 0.0
    assert run.llm_provider == "human"
    assert run.llm_model == "human-in-the-loop"


def test_agent_factory_constructor_compatibility():
    # AgentFactory.create passes llm/short_term/long_term — the controller must
    # accept them (and ignore them) so the shared registry can build it.
    agent = HitlController(llm=object(), short_term=object(), long_term=object())
    assert agent.agent_type == "hitl_controller"
    assert agent.timeout_seconds > 0

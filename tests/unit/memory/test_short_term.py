"""Unit tests for ShortTermMemory (Step 1.7), backed by fakeredis."""
from __future__ import annotations

import uuid

import pytest

from app.memory.short_term import ShortTermMemory


@pytest.fixture
def task_id():
    return uuid.uuid4()


async def test_add_and_get_messages_in_order(fake_redis, task_id):
    stm = ShortTermMemory(fake_redis)
    await stm.add_message(task_id, "user", "hello")
    await stm.add_message(task_id, "assistant", "hi there")

    msgs = await stm.get_messages(task_id)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert [m["content"] for m in msgs] == ["hello", "hi there"]
    assert all("ts" in m for m in msgs)  # timestamp recorded


async def test_get_messages_limit_returns_last_n(fake_redis, task_id):
    stm = ShortTermMemory(fake_redis)
    for i in range(5):
        await stm.add_message(task_id, "user", f"m{i}")
    last_two = await stm.get_messages(task_id, limit=2)
    assert [m["content"] for m in last_two] == ["m3", "m4"]


async def test_messages_capped_at_max(fake_redis, task_id):
    stm = ShortTermMemory(fake_redis, max_messages=3)
    for i in range(6):
        await stm.add_message(task_id, "user", f"m{i}")
    msgs = await stm.get_messages(task_id)
    assert [m["content"] for m in msgs] == ["m3", "m4", "m5"]  # oldest evicted


async def test_scratch_set_get_roundtrip(fake_redis, task_id):
    stm = ShortTermMemory(fake_redis)
    await stm.set_value(task_id, "plan", {"steps": [1, 2, 3]})
    assert await stm.get_value(task_id, "plan") == {"steps": [1, 2, 3]}
    assert await stm.get_value(task_id, "missing", default="x") == "x"


async def test_get_all_values(fake_redis, task_id):
    stm = ShortTermMemory(fake_redis)
    await stm.set_value(task_id, "a", 1)
    await stm.set_value(task_id, "b", "two")
    assert await stm.get_all_values(task_id) == {"a": 1, "b": "two"}


async def test_ttl_applied_to_keys(fake_redis, task_id):
    stm = ShortTermMemory(fake_redis, ttl_seconds=123)
    await stm.add_message(task_id, "user", "x")
    await stm.set_value(task_id, "k", "v")
    assert 0 < await fake_redis.ttl(stm._messages_key(task_id)) <= 123
    assert 0 < await fake_redis.ttl(stm._scratch_key(task_id)) <= 123


async def test_clear_removes_everything(fake_redis, task_id):
    stm = ShortTermMemory(fake_redis)
    await stm.add_message(task_id, "user", "x")
    await stm.set_value(task_id, "k", "v")
    await stm.clear(task_id)
    assert await stm.get_messages(task_id) == []
    assert await stm.get_all_values(task_id) == {}


async def test_isolation_between_tasks(fake_redis):
    stm = ShortTermMemory(fake_redis)
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    await stm.add_message(t1, "user", "for-t1")
    assert await stm.get_messages(t2) == []


async def test_works_as_base_agent_memory(fake_redis, task_id):
    """ShortTermMemory satisfies the interface BaseAgent calls (get/add)."""
    from app.agents import BaseAgent
    from app.llm import LLMProvider

    async def fn(*, model, messages, max_tokens, temperature, timeout):
        return {"content": "answer", "input_tokens": 1, "output_tokens": 1}

    stm = ShortTermMemory(fake_redis)
    agent = BaseAgent(llm=LLMProvider(complete_fn=fn), short_term=stm)
    await agent.run("first", task_id=task_id)
    await agent.run("second", task_id=task_id)

    msgs = await stm.get_messages(task_id)
    # two runs × (user + assistant) = 4 messages
    assert len(msgs) == 4
    assert msgs[0]["content"].endswith("first")

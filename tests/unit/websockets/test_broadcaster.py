"""Unit tests for ConnectionManager and WebSocketBroadcaster (Step 1.12)."""
from __future__ import annotations

import pytest
import uuid
from sqlalchemy import select

from app.websockets.manager import ConnectionManager
from app.websockets.broadcaster import WebSocketBroadcaster
from app.db.models.trace import Trace
from app.db.models import Tenant, User, Task


class MockWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent = []
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        if self.closed:
            raise RuntimeError("WebSocket closed")
        self.sent.append(message)


async def _make_tenant_user_task(session):
    tenant = Tenant(name="Acme", slug="acme", chroma_collection_prefix="acme")
    session.add(tenant)
    await session.flush()
    user = User(email="dev@acme.test", hashed_password="not-a-real-hash", full_name="Dev User", tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    task = Task(user_id=user.id, tenant_id=tenant.id, goal="broadcasting test")
    session.add(task)
    await session.flush()
    return tenant, user, task


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_emit_sends_correct_structure_to_manager():
    manager = ConnectionManager()
    ws = MockWebSocket()
    task_id = str(uuid.uuid4())

    await manager.connect(ws, task_id)
    assert ws.accepted is True
    assert manager.connection_count(task_id) == 1

    broadcaster = WebSocketBroadcaster(manager=manager)
    await broadcaster.emit(task_id, "task_started", {"some": "data"})

    assert len(ws.sent) == 1
    msg = ws.sent[0]
    assert msg["event"] == "task_started"
    assert msg["data"] == {"some": "data"}
    assert "timestamp" in msg


async def test_emit_creates_trace_in_db(db_session):
    tenant, user, task = await _make_tenant_user_task(db_session)
    await db_session.commit()

    manager = ConnectionManager()
    broadcaster = WebSocketBroadcaster(manager=manager, db_session=db_session)

    await broadcaster.emit(str(task.id), "agent_spawned", {"agent_type": "coder"})
    await db_session.commit()

    # Query Trace rows
    result = await db_session.execute(select(Trace).where(Trace.task_id == task.id))
    traces = result.scalars().all()
    assert len(traces) == 1
    assert traces[0].event_type == "agent_spawned"
    assert traces[0].event_data == {"agent_type": "coder"}
    assert traces[0].agent_type == "coder"
    assert traces[0].sequence_number == 1


@pytest.mark.anyio
async def test_emit_does_not_crash_when_no_clients():
    manager = ConnectionManager()
    broadcaster = WebSocketBroadcaster(manager=manager)
    # Silently skip, no crash
    await broadcaster.emit(str(uuid.uuid4()), "task_started", {})


@pytest.mark.anyio
async def test_emit_does_not_crash_when_db_session_is_none():
    manager = ConnectionManager()
    ws = MockWebSocket()
    task_id = str(uuid.uuid4())

    await manager.connect(ws, task_id)
    broadcaster = WebSocketBroadcaster(manager=manager, db_session=None)
    await broadcaster.emit(task_id, "task_started", {})
    assert len(ws.sent) == 1


@pytest.mark.anyio
async def test_send_to_task_sends_to_all_connections():
    manager = ConnectionManager()
    ws1 = MockWebSocket()
    ws2 = MockWebSocket()
    task_id = str(uuid.uuid4())

    await manager.connect(ws1, task_id)
    await manager.connect(ws2, task_id)
    assert manager.connection_count(task_id) == 2

    await manager.send_to_task(task_id, {"msg": "hello"})
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    assert ws1.sent[0] == {"msg": "hello"}
    assert ws2.sent[0] == {"msg": "hello"}


@pytest.mark.anyio
async def test_send_to_task_skips_when_no_connections():
    manager = ConnectionManager()
    # No connections, no crash
    await manager.send_to_task(str(uuid.uuid4()), {"msg": "hello"})


@pytest.mark.anyio
async def test_sequence_numbers_increment_correctly():
    manager = ConnectionManager()
    broadcaster = WebSocketBroadcaster(manager=manager)
    task_id = str(uuid.uuid4())

    assert broadcaster._next_sequence(task_id) == 1
    assert broadcaster._next_sequence(task_id) == 2
    
    other_task = str(uuid.uuid4())
    assert broadcaster._next_sequence(other_task) == 1
    assert broadcaster._next_sequence(task_id) == 3

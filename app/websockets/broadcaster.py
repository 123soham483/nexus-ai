from datetime import datetime, timezone
import uuid as _uuid_module
from app.websockets.manager import ConnectionManager
from app.db.models.trace import Trace

class WebSocketBroadcaster:
    """
    Emits structured events to WebSocket clients AND persists them as Trace rows.
    Injectable: tests can pass a mock manager and None for db_session.
    """
    def __init__(self, manager: ConnectionManager, db_session=None):
        self.manager = manager
        self.db_session = db_session
        self._sequence_counters: dict = {}

    async def emit(self, task_id: str, event_type: str, data: dict) -> None:
        """
        1. Build message: {event, data, timestamp}
        2. Send to all WebSocket clients for this task_id
        3. Persist as Trace row if db_session available
        """
        message = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Send to WebSocket clients (silently skip if none connected)
        await self.manager.send_to_task(task_id, message)

        # Persist to DB
        if self.db_session:
            seq = self._next_sequence(task_id)

            db_task_id = (
                _uuid_module.UUID(task_id) if isinstance(task_id, str) else task_id
            )

            trace = Trace(
                task_id=db_task_id,
                event_type=event_type,
                event_data=data,
                agent_type=data.get("agent_type"),
                sequence_number=seq,
            )
            self.db_session.add(trace)
            # Don't commit here — let the caller manage transactions

    def _next_sequence(self, task_id: str) -> int:
        self._sequence_counters[task_id] = self._sequence_counters.get(task_id, 0) + 1
        return self._sequence_counters[task_id]

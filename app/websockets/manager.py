from fastapi import WebSocket
from typing import Dict, List

class ConnectionManager:
    """
    Manages active WebSocket connections indexed by task_id.
    Multiple clients can connect to the same task_id (multiple browser tabs).
    """
    def __init__(self):
        self.active: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str) -> None:
        await websocket.accept()
        self.active.setdefault(task_id, []).append(websocket)

    async def disconnect(self, websocket: WebSocket, task_id: str) -> None:
        connections = self.active.get(task_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self.active.pop(task_id, None)

    async def send_to_task(self, task_id: str, message: dict) -> None:
        """Send JSON message to ALL clients connected to this task_id."""
        connections = self.active.get(task_id, [])
        dead = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws, task_id)

    def connection_count(self, task_id: str) -> int:
        return len(self.active.get(task_id, []))

# Shared singleton — imported by main.py and broadcaster
manager = ConnectionManager()

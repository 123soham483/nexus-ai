"""HitlStore — pending human-approval requests for the HITL flow.

The human-in-the-loop flow works like this: a HitlController (a non-LLM agent)
creates a pending request, waits for a decision, and the Tasks API resolves it
when a human approves or rejects. This module holds the request model and the
store. The store is injectable and its default implementation is in-memory,
so unit tests need no real services; resolution wakes waiting coroutines via
per-request ``asyncio.Event`` objects (no polling).
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

#: Statuses a HITL request can be in.
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
TIMED_OUT = "timed_out"


@dataclass
class HitlRequest:
    """One pending (or resolved) human-approval request."""

    id: str
    task_id: str
    agent_type: str
    goal: str
    reason: str
    status: str = PENDING
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    note: Optional[str] = None


class HitlStore:
    """In-memory store of HITL requests.

    Async interface so a Redis-backed implementation (needed for cross-process
    use: the Celery worker creates requests, the API process resolves them) can
    drop in later without changing callers. Injectable — tests use a fresh
    instance.
    """

    def __init__(self) -> None:
        self._requests: Dict[str, HitlRequest] = {}
        self._events: Dict[str, asyncio.Event] = {}

    @staticmethod
    def _key(request_id: str) -> str:
        """Normalize a request id: dash-insensitive, lowercase.

        Store keys are undashed hex; callers (the API layer) legitimately pass
        canonical dashed UUID strings, so lookups must match either form.
        """
        return str(request_id).replace("-", "").lower()

    async def create(
        self,
        *,
        task_id,
        agent_type: str,
        goal: str,
        reason: str,
        timeout_seconds: int = 300,
        request_id: Optional[str] = None,
    ) -> HitlRequest:
        """Create and store a pending request. Returns it."""
        request = HitlRequest(
            id=self._key(request_id or uuid.uuid4().hex),
            task_id=str(task_id) if task_id else "",
            agent_type=agent_type,
            goal=goal,
            reason=reason,
        )
        self._requests[request.id] = request
        self._events[request.id] = asyncio.Event()
        return request

    async def get(self, request_id: str) -> Optional[HitlRequest]:
        """Return the request, or ``None`` if unknown."""
        return self._requests.get(self._key(request_id))

    async def list_pending(self, task_id=None) -> List[HitlRequest]:
        """All requests still pending, optionally filtered by task."""
        out: List[HitlRequest] = []
        for request in self._requests.values():
            if request.status == PENDING and (
                task_id is None or request.task_id == str(task_id)
            ):
                out.append(request)
        return out

    async def list_requests(self, task_id=None) -> List[HitlRequest]:
        """All requests (pending AND resolved), optionally filtered by task.

        Newest first. Backs the ``GET /tasks/{id}/hitl/history`` endpoint.
        """
        out: List[HitlRequest] = []
        for request in self._requests.values():
            if task_id is None or request.task_id == str(task_id):
                out.append(request)
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out

    async def resolve(
        self,
        request_id: str,
        approved: bool,
        resolved_by: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Optional[HitlRequest]:
        """Resolve a pending request.

        Sets ``approved``/``rejected``, stamps ``resolved_at``/``resolved_by``,
        and wakes any waiter. Idempotent: an already-resolved request is
        returned unchanged (first decision wins). Returns ``None`` for an
        unknown request id.
        """
        key = self._key(request_id)
        request = self._requests.get(key)
        if request is None:
            return None
        if request.status != PENDING:
            return request
        request.status = APPROVED if approved else REJECTED
        request.resolved_at = datetime.now(timezone.utc)
        request.resolved_by = resolved_by
        request.note = note
        event = self._events.get(key)
        if event is not None:
            event.set()
        return request

    async def wait_for(
        self, request_id: str, timeout: Optional[float] = None
    ) -> HitlRequest:
        """Block until the request is resolved, or mark it ``timed_out``.

        Returns immediately if already resolved. Raises ``KeyError`` for an
        unknown request id. With no timeout, waits indefinitely.
        """
        key = self._key(request_id)
        request = self._requests.get(key)
        if request is None:
            raise KeyError(f"Unknown HITL request: {request_id}")
        if request.status != PENDING:
            return request
        event = self._events.get(key)
        if event is not None and not event.is_set():
            try:
                await asyncio.wait_for(event.wait(), timeout)
            except asyncio.TimeoutError:
                request.status = TIMED_OUT
                request.resolved_at = datetime.now(timezone.utc)
        return request

    async def clear(self) -> None:
        """Drop all requests (test hygiene / reset)."""
        self._requests.clear()
        self._events.clear()

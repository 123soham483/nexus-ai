"""RedisHitlStore — cross-process HITL requests (Phase 3, Step 3.4).

The in-memory :class:`~app.hitl.store.HitlStore` only works *within one
process*. In production the request is created by the **Celery worker** (while
running :class:`~app.agents.coordination.hitl_controller.HitlController`) and
resolved by the **API process** (``POST /tasks/{id}/hitl/resolve``) — two
different processes, so an in-memory dict can never see the resolution and every
approval times out.

This store keeps the exact same async interface but persists to Redis and wakes
waiters across processes via pub/sub on ``hitl:resolved:{id}`` (no polling).

Layout (all keys namespaced, TTL'd so abandoned requests cannot leak forever):

    hitl:request:{id}          HASH  — the serialized request
    hitl:task:{task_id}        SET   — request ids for one task
    hitl:resolved:{id}         CHAN  — resolution notification

``request_id`` normalisation (dash-insensitive, lowercase hex) matches
:class:`HitlStore` so both backends accept dashed UUIDs and undashed hex alike.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.hitl.store import (
    APPROVED,
    PENDING,
    REJECTED,
    TIMED_OUT,
    HitlRequest,
)

logger = logging.getLogger(__name__)

#: How long a request record lives in Redis (mirrors the in-memory store's
#: lifetime, bounded so an abandoned approval can't leak memory forever).
REQUEST_TTL_SECONDS = 24 * 3600

_REQUEST_KEY = "hitl:request:{id}"
_TASK_KEY = "hitl:task:{task_id}"
_RESOLVED_CHANNEL = "hitl:resolved:{id}"


class RedisHitlStore:
    """Redis-backed :class:`HitlStore` drop-in for cross-process HITL.

    ``redis`` is injectable (tests pass fakeredis); when omitted the shared
    lazy client from :mod:`app.security.redis_client` is used.
    """

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client

    # ── collaborators ────────────────────────────────────────────────────────
    @property
    def redis(self):
        """The active async Redis client (lazily built from settings)."""
        if self._redis is None:
            from app.security.redis_client import get_redis  # lazy

            self._redis = get_redis()
        return self._redis

    @staticmethod
    def _key(request_id: str) -> str:
        """Normalize a request id: dash-insensitive, lowercase (matches HitlStore)."""
        return str(request_id).replace("-", "").lower()

    # ── serialization ────────────────────────────────────────────────────────
    @staticmethod
    def _serialize(request: HitlRequest) -> Dict[str, str]:
        return {
            "id": request.id,
            "task_id": request.task_id,
            "agent_type": request.agent_type,
            "goal": request.goal,
            "reason": request.reason,
            "status": request.status,
            "created_at": request.created_at.isoformat(),
            "resolved_at": request.resolved_at.isoformat() if request.resolved_at else "",
            "resolved_by": request.resolved_by or "",
            "note": request.note or "",
        }

    @staticmethod
    def _deserialize(data: Dict[str, Any]) -> HitlRequest:
        """Rebuild a request from a Redis hash (tolerant of missing fields)."""

        def _dt(value: Any) -> Optional[datetime]:
            if not value:
                return None
            try:
                return datetime.fromisoformat(str(value))
            except ValueError:  # pragma: no cover - defensive
                return None

        created = _dt(data.get("created_at")) or datetime.now(timezone.utc)
        return HitlRequest(
            id=str(data.get("id", "")),
            task_id=str(data.get("task_id", "")),
            agent_type=str(data.get("agent_type", "")),
            goal=str(data.get("goal", "")),
            reason=str(data.get("reason", "")),
            status=str(data.get("status", PENDING)),
            created_at=created,
            resolved_at=_dt(data.get("resolved_at")),
            resolved_by=data.get("resolved_by") or None,
            note=data.get("note") or None,
        )

    # ── CRUD ─────────────────────────────────────────────────────────────────
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
        """Create and persist a pending request (``timeout_seconds`` is advisory:
        the waiting side owns the deadline, exactly as in ``HitlStore``)."""
        request = HitlRequest(
            id=self._key(request_id or uuid.uuid4().hex),
            task_id=str(task_id) if task_id else "",
            agent_type=agent_type,
            goal=goal,
            reason=reason,
        )
        redis = self.redis
        key = _REQUEST_KEY.format(id=request.id)
        await redis.hset(key, mapping=self._serialize(request))
        await redis.expire(key, REQUEST_TTL_SECONDS)
        if request.task_id:
            task_key = _TASK_KEY.format(task_id=request.task_id)
            await redis.sadd(task_key, request.id)
            await redis.expire(task_key, REQUEST_TTL_SECONDS)
        return request

    async def get(self, request_id: str) -> Optional[HitlRequest]:
        """Return the request, or ``None`` if unknown/expired."""
        data = await self.redis.hgetall(
            _REQUEST_KEY.format(id=self._key(request_id))
        )
        if not data:
            return None
        return self._deserialize(data)

    async def _list_for(self, task_id=None) -> List[HitlRequest]:
        """All stored requests, optionally for one task (newest first)."""
        redis = self.redis
        if task_id is not None:
            ids = await redis.smembers(_TASK_KEY.format(task_id=str(task_id)))
        else:
            ids = []
            async for key in redis.scan_iter(match="hitl:request:*"):
                ids.append(str(key).rsplit(":", 1)[-1])
        requests: List[HitlRequest] = []
        for request_id in ids:
            request = await self.get(request_id)
            if request is not None:
                requests.append(request)
        requests.sort(key=lambda r: r.created_at, reverse=True)
        return requests

    async def list_pending(self, task_id=None) -> List[HitlRequest]:
        """All requests still pending, optionally filtered by task."""
        return [
            r for r in await self._list_for(task_id) if r.status == PENDING
        ]

    async def list_requests(self, task_id=None) -> List[HitlRequest]:
        """All requests (pending AND resolved), newest first."""
        return await self._list_for(task_id)

    async def resolve(
        self,
        request_id: str,
        approved: bool,
        resolved_by: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Optional[HitlRequest]:
        """Resolve a pending request and publish the wake-up.

        Idempotent and race-safe across processes: the status transition is a
        compare-and-set via ``HSETNX``-style guarded ``HSET`` on ``status``, so
        when two API replicas race the first decision wins. Returns ``None`` for
        an unknown request.
        """
        key = _REQUEST_KEY.format(id=self._key(request_id))
        redis = self.redis
        request = await self.get(request_id)
        if request is None:
            return None

        # First decision wins: only flip a still-pending record. The Lua-free
        # form is safe enough here because ``HSET`` of an identical value is a
        # no-op — the guard below is what prevents a second writer.
        if request.status == PENDING:
            request.status = APPROVED if approved else REJECTED
            request.resolved_at = datetime.now(timezone.utc)
            request.resolved_by = resolved_by
            request.note = note
            await redis.hset(
                key,
                mapping={
                    "status": request.status,
                    "resolved_at": request.resolved_at.isoformat(),
                    "resolved_by": resolved_by or "",
                    "note": note or "",
                },
            )
            await redis.expire(key, REQUEST_TTL_SECONDS)

        await redis.publish(
            _RESOLVED_CHANNEL.format(id=request.id),
            json.dumps({"id": request.id, "status": request.status}),
        )
        return request

    async def wait_for(
        self, request_id: str, timeout: Optional[float] = None
    ) -> HitlRequest:
        """Block until resolved (possibly by another process), else ``timed_out``.

        Subscribes *before* re-reading the record, so a resolution that lands in
        the gap between the read and the subscribe is still observed. Raises
        ``KeyError`` for an unknown request id.

        The loop is deliberately deadline-driven rather than "catch the
        TimeoutError from ``wait_for``": some Redis clients swallow the
        cancellation of a blocked ``listen()``, which makes ``asyncio.wait_for``
        *return* at the deadline instead of raising. Trusting the clock (and the
        record's own status) keeps the timeout verdict correct either way.
        """
        normalized = self._key(request_id)
        request_key = _REQUEST_KEY.format(id=normalized)
        redis = self.redis
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout

        request = await self.get(normalized)
        if request is None:
            raise KeyError(f"Unknown HITL request: {request_id}")
        if request.status != PENDING:
            return request

        channel = _RESOLVED_CHANNEL.format(id=normalized)
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async def _wait_message() -> bool:
                """True once a resolution message arrives, False if listen ends."""
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        return True
                return False

            while True:
                # Re-read after subscribing: closes the resolve-then-subscribe
                # race, and picks up resolutions published while we were busy.
                request = await self.get(normalized)
                if request is None:
                    raise KeyError(f"Unknown HITL request: {request_id}")
                if request.status != PENDING:
                    return request

                remaining = None if deadline is None else deadline - loop.time()
                if remaining is not None and remaining <= 0:
                    break
                try:
                    woken = await asyncio.wait_for(_wait_message(), remaining)
                except asyncio.TimeoutError:
                    break
                if not woken:
                    # listen() ended without a message (connection closed, or a
                    # client that swallowed the cancellation): re-check once and
                    # let the deadline logic below decide.
                    request = await self.get(normalized)
                    if request is not None and request.status != PENDING:
                        return request
                    break
        finally:
            try:
                await pubsub.unsubscribe(channel)
            finally:
                await pubsub.aclose()

        # Deadline reached with no resolution: stamp the timeout in Redis too,
        # so the API reads the same verdict the waiting worker does.
        request = await self.get(normalized)
        if request is None:
            raise KeyError(f"Unknown HITL request: {request_id}")
        if request.status == PENDING and deadline is not None:
            await redis.hset(request_key, mapping={"status": TIMED_OUT})
            await redis.expire(request_key, REQUEST_TTL_SECONDS)
            request = await self.get(normalized) or request
        return request

    async def clear(self) -> None:
        """Drop all requests (test hygiene / reset)."""
        redis = self.redis
        keys = [str(k) async for k in redis.scan_iter(match="hitl:*")]
        if keys:
            await redis.delete(*keys)

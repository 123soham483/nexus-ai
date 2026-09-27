"""ShortTermMemory — per-task working memory backed by Redis.

Holds the rolling conversation (a capped Redis list) plus a small key/value
scratchpad (a Redis hash) for each task, both auto-expiring after
``REDIS_CACHE_TTL``. This is the fast, ephemeral context an agent needs *within*
a task; durable, cross-task knowledge lives in :class:`LongTermMemory`.

The Redis client is injected (defaulting to the shared lazy client) so tests use
``fakeredis`` with no server running. Values are JSON-encoded; the client is
expected to be ``decode_responses=True`` (as the shared client is).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings


class ShortTermMemory:
    """Redis-backed conversation buffer + scratchpad, scoped per task."""

    def __init__(
        self,
        redis=None,
        *,
        ttl_seconds: Optional[int] = None,
        max_messages: int = 50,
    ) -> None:
        self._redis = redis  # injected; resolved lazily so import needs no server
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.REDIS_CACHE_TTL
        self._max_messages = max_messages

    # ── key helpers ──────────────────────────────────────────────────────────
    @property
    def redis(self):
        """The active async Redis client (shared lazy client unless injected)."""
        if self._redis is None:
            from app.security.redis_client import get_redis

            self._redis = get_redis()
        return self._redis

    @staticmethod
    def _messages_key(task_id) -> str:
        return f"stm:{task_id}:messages"

    @staticmethod
    def _scratch_key(task_id) -> str:
        return f"stm:{task_id}:scratch"

    # ── conversation ─────────────────────────────────────────────────────────
    async def add_message(self, task_id, role: str, content: str) -> None:
        """Append a message, trim to the last ``max_messages``, refresh TTL."""
        key = self._messages_key(task_id)
        payload = json.dumps(
            {
                "role": role,
                "content": content,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        await self.redis.rpush(key, payload)
        # Keep only the most recent N (negative indices count from the end).
        await self.redis.ltrim(key, -self._max_messages, -1)
        await self.redis.expire(key, self._ttl)

    async def get_messages(self, task_id, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return stored messages oldest→newest (optionally just the last N)."""
        key = self._messages_key(task_id)
        start = -limit if limit else 0
        raw = await self.redis.lrange(key, start, -1)
        return [json.loads(item) for item in raw]

    # ── scratchpad ───────────────────────────────────────────────────────────
    async def set_value(self, task_id, field: str, value: Any) -> None:
        """Store an arbitrary JSON-serializable value under ``field``."""
        key = self._scratch_key(task_id)
        await self.redis.hset(key, field, json.dumps(value))
        await self.redis.expire(key, self._ttl)

    async def get_value(self, task_id, field: str, default: Any = None) -> Any:
        """Read a scratchpad value, returning ``default`` if absent."""
        raw = await self.redis.hget(self._scratch_key(task_id), field)
        return json.loads(raw) if raw is not None else default

    async def get_all_values(self, task_id) -> Dict[str, Any]:
        """Return the whole scratchpad as a decoded dict."""
        raw = await self.redis.hgetall(self._scratch_key(task_id))
        return {k: json.loads(v) for k, v in raw.items()}

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def clear(self, task_id) -> None:
        """Drop all short-term state for a task."""
        await self.redis.delete(self._messages_key(task_id), self._scratch_key(task_id))

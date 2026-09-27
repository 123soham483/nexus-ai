"""Lazy async Redis client shared across the app.

Kept separate from business logic so tests can override ``get_redis`` with a
fakeredis instance. Import is lazy: no connection is made until first use.
"""
from __future__ import annotations

from typing import Any, Optional

from app.config import settings

#: Shared client, lazily created on first ``get_redis`` call.
_redis: Optional[Any] = None


def get_redis():
    """Return a process-wide async Redis client, created on first call."""
    global _redis
    if _redis is None:
        # Imported lazily so importing this module never requires redis running.
        from redis import asyncio as aioredis

        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close the shared client on shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def set_redis(client) -> None:
    """Override the shared client (used by tests to inject fakeredis)."""
    global _redis
    _redis = client

"""Human-in-the-loop (HITL) approval flow: request store + shared instance.

Two interchangeable stores implement the same async interface:

    HitlStore       in-process dict + asyncio.Event  (tests, dev, single process)
    RedisHitlStore  Redis hash + pub/sub             (prod, cross-process)

Pick one with ``HITL_STORE_BACKEND=memory|redis``. Production needs ``redis``
because the Celery worker creates the approval request and the API process
resolves it — an in-memory store would never see the resolution and every
approval would time out.
"""
from __future__ import annotations

from app.config import settings
from app.hitl.store import HitlRequest, HitlStore


def build_store(backend: str | None = None):
    """Construct the configured HITL store (heavy import is lazy)."""
    chosen = (backend or settings.HITL_STORE_BACKEND or "memory").strip().lower()
    if chosen == "redis":
        from app.hitl.redis_store import RedisHitlStore  # lazy

        return RedisHitlStore()
    return HitlStore()


#: Shared store used by the HitlController and the Tasks API. Selected once at
#: import from settings so both sides always agree on the same backend.
default_store = build_store()

__all__ = ["HitlRequest", "HitlStore", "build_store", "default_store"]

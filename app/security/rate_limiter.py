"""Redis-backed per-endpoint rate limiting (Phase 4, Step 4.5.2)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

#: (method, normalized path) → max requests per 60s window
ENDPOINT_LIMITS: Dict[Tuple[str, str], int] = {
    ("POST", "/api/v1/tasks/"): 10,
    ("POST", "/api/v1/tasks"): 10,
    ("POST", "/api/v1/auth/login"): 5,
    ("POST", "/api/v1/memory/search"): 30,
}

WINDOW_SECONDS = 60


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


def _normalize_path(path: str) -> str:
    if path != "/" and path.endswith("/"):
        return path
    if path.endswith("/") and path.count("/") > 2:
        return path
    return path if path.endswith("/") or path.count("/") <= 3 else path + "/"


async def check_rate_limit(
    redis,
    *,
    key: str,
    limit: int,
    window: int = WINDOW_SECONDS,
) -> RateLimitResult:
    now = int(time.time())
    bucket = f"ratelimit:{key}:{now // window}"
    try:
        count = await redis.incr(bucket)
        if count == 1:
            await redis.expire(bucket, window + 1)
    except Exception:
        return RateLimitResult(allowed=True, remaining=limit, retry_after=0)

    remaining = max(0, limit - int(count))
    if int(count) > limit:
        retry_after = window - (now % window)
        return RateLimitResult(allowed=False, remaining=0, retry_after=retry_after)
    return RateLimitResult(allowed=True, remaining=remaining, retry_after=0)


def rate_limit_key(request: Request) -> str:
    client = request.client.host if request.client else "unknown"
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return f"user:{auth[-16:]}"
    return f"ip:{client}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies endpoint-specific limits and sets ``X-RateLimit-Remaining``."""

    def __init__(
        self,
        app,
        redis_getter: Optional[Callable] = None,
        limits: Optional[Dict[Tuple[str, str], int]] = None,
    ) -> None:
        super().__init__(app)
        self._redis_getter = redis_getter
        self._limits = limits or ENDPOINT_LIMITS

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = _normalize_path(request.url.path)
        limit = self._limits.get((request.method.upper(), path))
        if limit is None:
            # Also try with trailing slash variant
            alt = path.rstrip("/") if path.endswith("/") else path + "/"
            limit = self._limits.get((request.method.upper(), alt))

        remaining_header = str(limit) if limit is not None else "999"

        if limit is not None:
            redis = None
            if self._redis_getter is not None:
                redis = self._redis_getter()
            else:
                try:
                    from app.security.redis_client import get_redis

                    redis = get_redis()
                except Exception:
                    redis = None

            if redis is not None:
                rl_key = f"{request.method}:{path}:{rate_limit_key(request)}"
                result = await check_rate_limit(redis, key=rl_key, limit=limit)
                remaining_header = str(result.remaining)
                if not result.allowed:
                    import uuid as _uuid

                    request_id = request.headers.get("X-Request-ID") or str(
                        _uuid.uuid4()
                    )
                    body = (
                        '{"error":"Rate limit exceeded","code":"RATE_LIMITED",'
                        f'"request_id":"{request_id}"}}'
                    )
                    return Response(
                        content=body,
                        status_code=429,
                        media_type="application/json",
                        headers={
                            "Retry-After": str(result.retry_after),
                            "X-RateLimit-Remaining": "0",
                            "X-Request-ID": request_id,
                        },
                    )

        response = await call_next(request)
        response.headers.setdefault("X-RateLimit-Remaining", remaining_header)
        return response

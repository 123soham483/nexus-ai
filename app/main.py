"""FastAPI application entry point.

Assembles the ASGI app: mounts the versioned API router, exposes health checks,
manages startup/shutdown lifecycle, and defines the WebSocket endpoint for streaming traces.
"""
from __future__ import annotations

import structlog
import uuid as _uuid_module
from contextlib import asynccontextmanager
from typing import Union
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db.session import dispose_engine, get_session
from app.security.redis_client import close_redis
from app.security.rate_limiter import RateLimitMiddleware
from app.middleware.request_context import RequestIdMiddleware, register_exception_handlers
from app.observability.metrics import generate_metrics_output
from app.api.v1.router import api_router
from app.websockets.manager import manager
from app.websockets.broadcaster import WebSocketBroadcaster
from app.db.models.trace import Trace

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(
        "nexusai_starting",
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
    )
    yield
    # Shutdown
    await dispose_engine()
    try:
        await close_redis()
    except Exception:
        pass
    logger.info("nexusai_stopped")


app = FastAPI(
    title="NexusAI API",
    version=settings.APP_VERSION,
    description="Multi-Agent AI Orchestration Platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

register_exception_handlers(app)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(api_router, prefix="/api/v1")


@app.get(settings.PROMETHEUS_METRICS_PATH, tags=["observability"])
async def prometheus_metrics():
    """Prometheus scrape endpoint (Step 4.2)."""
    return Response(generate_metrics_output(), media_type="text/plain; version=0.0.4; charset=utf-8")

# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    task_id: str,
    db: AsyncSession = Depends(get_session),
):
    await manager.connect(websocket, task_id)
    try:
        # Convert task_id string to UUID object for database query. If it is not
        # a valid UUID the raw string is kept and the query simply matches nothing.
        uuid_task_id: Union[str, _uuid_module.UUID]
        try:
            uuid_task_id = _uuid_module.UUID(task_id)
        except ValueError:
            uuid_task_id = task_id

        # Send historical traces immediately on connect
        result = await db.execute(
            select(Trace)
            .where(Trace.task_id == uuid_task_id)
            .order_by(Trace.sequence_number.asc())
        )
        traces = result.scalars().all()
        for trace in traces:
            await websocket.send_json({
                "event": trace.event_type,
                "data": trace.event_data,
                "timestamp": trace.timestamp.isoformat(),
                "sequence": trace.sequence_number,
            })

        # Keep connection alive until client disconnects
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        await manager.disconnect(websocket, task_id)
    except Exception:
        await manager.disconnect(websocket, task_id)

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": settings.APP_VERSION, "env": settings.APP_ENV}

@app.get("/health/db", tags=["health"])
async def health_db(db: AsyncSession = Depends(get_session)):
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "postgresql"}

@app.get("/health/redis", tags=["health"])
async def health_redis():
    from app.security.redis_client import get_redis
    client = await get_redis()
    await client.ping()
    return {"status": "ok", "service": "redis"}

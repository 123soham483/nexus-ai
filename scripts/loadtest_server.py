"""Run a real NexusAI API for load testing without Postgres/Redis/Docker.

The production stack needs Postgres, Redis and a Docker daemon. When those are
not available we can still exercise the *HTTP request path* (auth, validation,
prompt-injection scan, DB write, serialization, middleware) by running the app
on SQLite with an in-process fakeredis and Celery dispatch stubbed out.

What is faithful here:
  - the ASGI app and all middleware (request-id, rate limit, structured errors)
  - JWT auth, tenant provisioning, task creation and listing
  - real persistence of users/tenants/tasks

What is NOT faithful (and why load-test numbers are caveated):
  - Celery dispatch is a no-op (no broker), so no agent pipeline runs
  - Redis is fakeredis (in-process), so it is faster than a real Redis round trip
  - SQLite, not Postgres

Run:
    .venv/Scripts/python.exe scripts/loadtest_server.py
    locust -f tests/load/locustfile.py --host=http://localhost:8020 \\
        --users 100 --spawn-rate 20 --run-time 45s --headless
"""
from __future__ import annotations

import os

# Environment MUST be set before app.config is imported (settings read once).
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.loadtest.db")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "loadtest-secret")
os.environ.setdefault("ENABLE_OPENTELEMETRY", "false")
os.environ.setdefault("SANDBOX_ENABLED", "false")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

LOADTEST_SYNC_DB = "./.loadtest.db"


def _create_tables_sync() -> None:
    """Create the schema with a synchronous engine (no event loop needed).

    Using the sync driver avoids binding the async engine to a throwaway event
    loop that uvicorn will not reuse.
    """
    from sqlalchemy import create_engine

    from app.db.models import Base

    engine = create_engine(f"sqlite:///{LOADTEST_SYNC_DB}")
    Base.metadata.create_all(engine)
    engine.dispose()


def _enable_sqlite_concurrency() -> None:
    """Make SQLite tolerate 100 concurrent writers (WAL + busy timeout).

    Without this, concurrent registrations collide with "database is locked"
    and the load run reports spurious 500s that are an artefact of using SQLite
    instead of Postgres.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def _pragmas(dbapi_connection, _record):  # noqa: ANN001
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass


def _install_substitutes() -> None:
    import fakeredis.aioredis

    from app.security import rate_limiter
    from app.security.redis_client import set_redis
    from app.workers import task_worker

    # In-process Redis substitute: token blacklist, rate limiting, short-term memory.
    set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))

    # Relax endpoint limits for the latency run. All 100 virtual users share one
    # source IP, so the production 5/min login limit would rate-limit the very
    # first wave and leave every subsequent authenticated request unauthenticated.
    # Rate-limit *correctness* is covered by tests/integration/test_security.py;
    # here we only want unthrottled latency numbers. Mutating the dict in place is
    # enough because RateLimitMiddleware holds a reference to it.
    for key in list(rate_limiter.ENDPOINT_LIMITS):
        rate_limiter.ENDPOINT_LIMITS[key] = 1_000_000

    # Stub Celery dispatch: no broker, and we must not run real agent pipelines
    # (which would call live LLMs) during a load test.
    class _NoopDispatch:
        def delay(self, *args, **kwargs):
            return None

    task_worker.execute_task_worker = _NoopDispatch()  # type: ignore[assignment]


def main() -> None:
    _enable_sqlite_concurrency()
    _create_tables_sync()
    _install_substitutes()

    import uvicorn

    from app.main import app

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("LOADTEST_PORT", "8020")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()

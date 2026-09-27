"""Application settings loaded from environment / .env via pydantic-settings.

This is the single source of configuration for the entire backend. Every other
module imports the shared ``settings`` instance from here rather than reading
``os.environ`` directly, so configuration is typed, validated once at import,
and trivially overridable in tests.
"""
from __future__ import annotations

from functools import cached_property
from typing import List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings.

    Values are sourced (in order of precedence) from real environment variables,
    then the ``.env`` file, then the defaults declared here. Field names are
    case-insensitive against env var names.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # tolerate unrelated env vars in the shell
    )

    # ── App ─────────────────────────────────────────────────────────────────
    APP_NAME: str = "NexusAI"
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-in-production"

    # ── PostgreSQL ──────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://nexusai:nexusai_password@localhost:5432/nexusai_db"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_ECHO: bool = False

    # ── Redis ───────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── ChromaDB ────────────────────────────────────────────────────────────
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    CHROMA_COLLECTION_TASKS: str = "nexusai_tasks"
    CHROMA_COLLECTION_FAILURES: str = "nexusai_failures"
    CHROMA_COLLECTION_PATTERNS: str = "nexusai_patterns"

    # ── LLM Providers ───────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"

    # ── LLM Behaviour ───────────────────────────────────────────────────────
    DEFAULT_LLM_PROVIDER: str = "gemini"
    FALLBACK_ORDER: str = "gemini,claude,gpt4,ollama"
    LLM_MAX_RETRIES: int = 3
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_MAX_TOKENS: int = 4096
    #: When True, every LLM completion returns a deterministic, goal-derived
    #: canned response instead of calling a real provider. DEV/TEST ONLY —
    #: the provider refuses to enable itself in production so a misconfigured
    #: deployment can never silently serve fake model output.
    LLM_FAKE_MODE: bool = False
    #: ``celery`` (production: Redis broker + worker) or ``inline`` (API
    #: process runs the orchestrator — local Windows without a worker).
    TASK_DISPATCH: str = "celery"

    # ── JWT Auth ────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Rate Limiting ───────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    # ── Cost Controls ───────────────────────────────────────────────────────
    ENABLE_COST_ESTIMATION: bool = True
    COST_ALERT_THRESHOLD_USD: float = 10.0
    COST_HARD_LIMIT_USD: float = 50.0
    DEFAULT_MONTHLY_BUDGET_USD: float = 100.0

    # ── HITL Controls ───────────────────────────────────────────────────────
    HITL_ENABLED: bool = True
    HITL_TIMEOUT_SECONDS: int = 300
    HITL_HIGH_RISK_TOOLS: str = "execute_code,write_file,delete_file,call_api,run_sql"
    #: ``memory`` (in-process, tests/dev) or ``redis`` (cross-process, prod):
    #: a Celery worker creates approval requests the API process must resolve.
    HITL_STORE_BACKEND: str = "memory"

    # ── Celery task time limits (Phase 3, Step 3.4) ─────────────────────────
    #: Soft limit MUST exceed HITL_TIMEOUT_SECONDS — a task can legitimately
    #: block on human approval, and killing it at exactly the HITL timeout
    #: would make every approval a race (validated below).
    TASK_SOFT_TIME_LIMIT: int = 360
    TASK_TIME_LIMIT: int = 420

    # ── Security ────────────────────────────────────────────────────────────
    ENABLE_PROMPT_INJECTION_SCAN: bool = True
    INJECTION_BLOCK_THRESHOLD: float = 0.85

    # ── Docker Sandbox ──────────────────────────────────────────────────────
    #: When False, generated code is never executed (agents keep writing tests
    #: and code, they just don't run them).
    SANDBOX_ENABLED: bool = True
    SANDBOX_IMAGE: str = "python:3.11-slim"
    SANDBOX_CPU_LIMIT: float = 0.5
    SANDBOX_MEMORY_LIMIT: str = "256m"
    SANDBOX_TIMEOUT_SECONDS: int = 30
    SANDBOX_NETWORK_DISABLED: bool = True

    # ── Observability ───────────────────────────────────────────────────────
    ENABLE_OPENTELEMETRY: bool = True
    OTEL_EXPORTER_ENDPOINT: str = "http://localhost:4317"
    #: service.name resource attribute on every emitted span.
    OTEL_SERVICE_NAME: str = "nexusai"
    #: Prometheus scrape path (the root-level ``/metrics`` endpoint).
    PROMETHEUS_METRICS_PATH: str = "/metrics"
    LOG_LEVEL: str = "INFO"
    ENABLE_HALLUCINATION_DETECTION: bool = True
    HALLUCINATION_SCORE_THRESHOLD: float = 0.70

    # ── Multi-Tenancy ───────────────────────────────────────────────────────
    ENABLE_MULTI_TENANCY: bool = True
    DEFAULT_TENANT_RATE_LIMIT: int = 100

    # ── Validators / derived helpers ─────────────────────────────────────────
    @field_validator("SECRET_KEY")
    @classmethod
    def _secret_key_not_empty(cls, v: str) -> str:
        """A blank secret key would silently produce forgeable JWTs."""
        if not v or not v.strip():
            raise ValueError("SECRET_KEY must not be empty")
        return v

    @field_validator("HITL_STORE_BACKEND")
    @classmethod
    def _known_hitl_backend(cls, v: str) -> str:
        """Reject a typo'd backend instead of silently falling back to memory."""
        backend = (v or "memory").strip().lower()
        if backend not in {"memory", "redis"}:
            raise ValueError(
                f"HITL_STORE_BACKEND must be 'memory' or 'redis', got {v!r}"
            )
        return backend

    @field_validator("TASK_DISPATCH")
    @classmethod
    def _known_task_dispatch(cls, v: str) -> str:
        mode = (v or "celery").strip().lower()
        if mode not in {"celery", "inline"}:
            raise ValueError(
                f"TASK_DISPATCH must be 'celery' or 'inline', got {v!r}"
            )
        return mode

    @model_validator(mode="after")
    def _task_limits_outlast_hitl(self) -> "Settings":
        """A task waiting on a human must not be killed by its own time limit.

        Celery's soft limit must leave room for the HITL wait *plus* the rest of
        the pipeline, so the hard limit has to be larger again.
        """
        if self.HITL_ENABLED:
            if self.TASK_SOFT_TIME_LIMIT <= self.HITL_TIMEOUT_SECONDS:
                raise ValueError(
                    "TASK_SOFT_TIME_LIMIT must exceed HITL_TIMEOUT_SECONDS "
                    f"({self.TASK_SOFT_TIME_LIMIT} <= {self.HITL_TIMEOUT_SECONDS})"
                )
            if self.TASK_TIME_LIMIT <= self.TASK_SOFT_TIME_LIMIT:
                raise ValueError(
                    "TASK_TIME_LIMIT must exceed TASK_SOFT_TIME_LIMIT "
                    f"({self.TASK_TIME_LIMIT} <= {self.TASK_SOFT_TIME_LIMIT})"
                )
        return self

    @property
    def fallback_order_list(self) -> List[str]:
        """FALLBACK_ORDER as a cleaned list of provider names."""
        return [p.strip() for p in self.FALLBACK_ORDER.split(",") if p.strip()]

    @property
    def hitl_high_risk_tools_list(self) -> List[str]:
        """HITL_HIGH_RISK_TOOLS as a cleaned list of tool names."""
        return [t.strip() for t in self.HITL_HIGH_RISK_TOOLS.split(",") if t.strip()]

    @cached_property
    def sync_database_url(self) -> str:
        """Sync form of DATABASE_URL for Alembic / non-async contexts.

        Converts the asyncpg driver to psycopg2 and aiosqlite to plain sqlite.
        """
        url = self.DATABASE_URL
        return (
            url.replace("+asyncpg", "")
            .replace("+aiosqlite", "")
        )

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _forbid_fake_llm_in_production(self) -> "Settings":
        """Hard safety rail: fake LLM output must never serve real traffic."""
        if self.LLM_FAKE_MODE and self.is_production:
            raise ValueError(
                "LLM_FAKE_MODE=true is not allowed when APP_ENV is production — "
                "fake model output must never serve real traffic"
            )
        return self


# Shared, import-once settings instance used across the app.
settings = Settings()
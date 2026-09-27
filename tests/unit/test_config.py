"""Tests for app.config.Settings."""
import pytest
from pydantic import ValidationError

from app.config import Settings, settings


def test_settings_loads_without_error():
    """The shared settings instance imports and has expected defaults."""
    assert settings.APP_NAME == "NexusAI"
    assert settings.APP_PORT == 8000
    assert isinstance(settings.DEBUG, bool)


def test_types_are_coerced():
    """Numeric/bool env-style strings are coerced to the annotated types."""
    s = Settings(APP_PORT="9001", DEBUG="false", COST_HARD_LIMIT_USD="42.5")
    assert s.APP_PORT == 9001
    assert s.DEBUG is False
    assert s.COST_HARD_LIMIT_USD == 42.5


def test_empty_secret_key_raises():
    """A blank SECRET_KEY must fail validation (forgeable-JWT guard)."""
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY="   ")


def test_fallback_order_list_parses():
    s = Settings(FALLBACK_ORDER="claude, gemini ,gpt4")
    assert s.fallback_order_list == ["claude", "gemini", "gpt4"]


def test_hitl_high_risk_tools_list_parses():
    s = Settings(HITL_HIGH_RISK_TOOLS="execute_code, write_file")
    assert s.hitl_high_risk_tools_list == ["execute_code", "write_file"]


def test_sync_database_url_strips_async_driver():
    s = Settings(DATABASE_URL="postgresql+asyncpg://u:p@h:5432/db")
    assert s.sync_database_url == "postgresql://u:p@h:5432/db"

    s2 = Settings(DATABASE_URL="sqlite+aiosqlite:///./test.db")
    assert s2.sync_database_url == "sqlite:///./test.db"


def test_is_production_flag():
    assert Settings(APP_ENV="production").is_production is True
    assert Settings(APP_ENV="development").is_production is False


# ── HITL store backend + task time limits (Phase 3, Step 3.4) ────────────────

def test_hitl_store_backend_defaults_to_memory():
    """Dev/test must not require Redis just to run an approval flow."""
    assert Settings().HITL_STORE_BACKEND == "memory"


def test_hitl_store_backend_accepts_redis_case_insensitively():
    assert Settings(HITL_STORE_BACKEND=" Redis ").HITL_STORE_BACKEND == "redis"


def test_unknown_hitl_store_backend_is_rejected():
    """A typo must fail loudly, not silently fall back to the memory store."""
    with pytest.raises(ValidationError):
        Settings(HITL_STORE_BACKEND="postgres")


def test_task_soft_limit_must_outlast_hitl_timeout():
    """Otherwise every approval race with Celery's soft limit."""
    with pytest.raises(ValidationError):
        Settings(HITL_TIMEOUT_SECONDS=300, TASK_SOFT_TIME_LIMIT=300)


def test_task_hard_limit_must_exceed_soft_limit():
    with pytest.raises(ValidationError):
        Settings(TASK_SOFT_TIME_LIMIT=400, TASK_TIME_LIMIT=400)


def test_task_limits_may_be_short_when_hitl_is_disabled():
    """With no human in the loop there is nothing to wait for."""
    s = Settings(HITL_ENABLED=False, TASK_SOFT_TIME_LIMIT=30, TASK_TIME_LIMIT=30)
    assert s.TASK_SOFT_TIME_LIMIT == 30

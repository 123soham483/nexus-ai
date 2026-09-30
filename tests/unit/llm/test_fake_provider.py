"""LLM_FAKE_MODE: deterministic fake provider for keyless E2E verification.

Covers the completion contract, determinism, and the production safety rail.
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.llm.provider import AllProvidersFailedError, LLMMessage, LLMProvider, _fake_complete


def _provider() -> LLMProvider:
    return LLMProvider(complete_fn=_fake_complete)


@pytest.mark.asyncio
async def test_fake_complete_returns_normalized_payload():
    raw = await _fake_complete(
        model="anthropic/claude-sonnet-4-6",
        messages=[{"role": "user", "content": "make a factorial"}],
        max_tokens=512,
        temperature=0.7,
        timeout=30,
    )
    assert raw["content"]
    assert raw["input_tokens"] > 0
    assert raw["output_tokens"] > 0
    assert raw["raw"]["fake"] is True


@pytest.mark.asyncio
async def test_fake_provider_is_deterministic():
    p = _provider()
    msgs = [LLMMessage(role="user", content="factorial please")]
    r1 = await p.complete(msgs, agent_type="coder")
    r2 = await p.complete(msgs, agent_type="coder")
    assert r1.content == r2.content
    assert (r1.input_tokens, r1.output_tokens) == (r2.input_tokens, r2.output_tokens)


@pytest.mark.asyncio
async def test_fake_provider_success_has_no_fallback():
    r = await _provider().complete(
        [LLMMessage(role="user", content="hello")], agent_type="planner"
    )
    assert r.attempts == [r.provider]
    assert not r.fallback_used


@pytest.mark.asyncio
async def test_real_provider_without_fake_mode_still_fails_without_keys(monkeypatch):
    """Default path (litellm, no keys) still raises the controlled error.

    Clears every cloud credential on the already-imported settings singleton —
    chdir alone cannot help because Settings() loads the developer .env at
    import time. Otherwise a real Gemini key makes the call SUCCEED, which is
    an environment property, not a code property.
    """
    from app.llm import routing as routing_module

    for field in routing_module._CLOUD_KEY_FIELDS.values():
        monkeypatch.setattr(routing_module.settings, field, "", raising=False)
    p = LLMProvider(max_retries=1, retry_backoff_base=0)  # real path, no keys
    with pytest.raises(AllProvidersFailedError):
        await p.complete([LLMMessage(role="user", content="hi")])


def test_fake_mode_refused_in_production(monkeypatch, tmp_path):
    # isolate from any developer .env
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="LLM_FAKE_MODE"):
        Settings(APP_ENV="production", LLM_FAKE_MODE=True, _env_file=None)


def test_fake_mode_allowed_in_development(tmp_path):
    s = Settings(APP_ENV="development", LLM_FAKE_MODE=True, _env_file=None)
    assert s.LLM_FAKE_MODE is True


@pytest.mark.asyncio
async def test_daily_quota_429_fails_fast_without_retries():
    """A PerDay-quota 429 must NOT be retried — it pins the solo worker for minutes."""
    calls = {"n": 0}

    async def daily_429(**kwargs):
        calls["n"] += 1
        raise RuntimeError(
            '429 "You exceeded your current quota ... quotaId: '
            'GenerateRequestsPerDayPerProjectPerModel-FreeTier ... retry in 30.0s"'
        )

    p = LLMProvider(complete_fn=daily_429, max_retries=6, retry_backoff_base=0)
    with pytest.raises((RuntimeError, AllProvidersFailedError)) as ei:
        await p.complete([LLMMessage(role="user", content="hi")], fallback=False)
    # failed fast: exactly ONE underlying attempt, no retry sleeps
    assert calls["n"] == 1
    assert "PerDay" in str(ei.value)


@pytest.mark.asyncio
async def test_minute_quota_429_is_retried():
    """Transient (non-daily) 429s should still be retried."""
    calls = {"n": 0}

    async def minute_429_then_ok(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError('429 ... "retry in 2.0s"')
        return {"content": "ok", "input_tokens": 1, "output_tokens": 1}

    p = LLMProvider(complete_fn=minute_429_then_ok, max_retries=3, retry_backoff_base=0)
    r = await p.complete([LLMMessage(role="user", content="hi")], fallback=False)
    assert r.content == "ok"
    assert calls["n"] == 2

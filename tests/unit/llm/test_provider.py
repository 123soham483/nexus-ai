"""Unit tests for the LLM provider layer (Step 1.5).

All tests inject a deterministic fake completion coroutine, so no LiteLLM
install, network, or API keys are required (BRAIN.md D3/D5).
"""
from __future__ import annotations

import pytest

from app.llm import (
    AllProvidersFailedError,
    CompletionResult,
    LLMMessage,
    LLMProvider,
    estimate_agent_cost,
    estimate_cost,
    provider_for_agent,
    resolve_model,
)

MESSAGES = [LLMMessage(role="user", content="hello")]


def _fake(content="hi", *, input_tokens=10, output_tokens=5):
    """Build a completion coroutine that always succeeds with fixed usage."""

    async def _fn(*, model, messages, max_tokens, temperature, timeout):
        return {
            "content": content,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "raw": {"model": model},
        }

    return _fn


def _failing(exc=RuntimeError("boom")):
    async def _fn(**_kwargs):
        raise exc

    return _fn


# ── routing ──────────────────────────────────────────────────────────────────
def test_resolve_model_known_provider():
    assert resolve_model("claude") == "anthropic/claude-sonnet-4-6"


def test_resolve_model_unknown_raises():
    with pytest.raises(KeyError):
        resolve_model("nope")


def test_provider_for_agent_uses_map_then_default():
    assert provider_for_agent("coder") == "gemini"
    assert provider_for_agent("research") == "gemini"
    # Unknown agent falls back to the configured default provider.
    from app.config import settings

    assert provider_for_agent("unknown-agent") == settings.DEFAULT_LLM_PROVIDER
    assert provider_for_agent(None) == settings.DEFAULT_LLM_PROVIDER


def test_estimate_cost_matches_pricing_table():
    # claude: (0.003 in, 0.015 out) per 1K tokens.
    cost = estimate_cost("anthropic/claude-sonnet-4-6", 1000, 1000)
    assert cost == pytest.approx(0.003 + 0.015)


def test_estimate_cost_local_model_is_free():
    from app.config import settings

    assert estimate_cost(f"ollama/{settings.OLLAMA_MODEL}", 5000, 5000) == 0.0


def test_estimate_agent_cost_uses_pricing_and_split():
    # coder → gemini; 1000 tokens at 70/30 split.
    cost = estimate_agent_cost("coder")
    expected = estimate_cost(
        "gemini/gemini-2.5-flash", int(1000 * 0.7), int(1000 * 0.3)
    )
    assert cost == pytest.approx(expected)


def test_estimate_agent_cost_non_llm_agent_is_zero():
    from app.llm.routing import NON_LLM_AGENTS

    assert "hitl_controller" in NON_LLM_AGENTS
    assert estimate_agent_cost("hitl_controller") == 0.0


# ── complete: happy path ─────────────────────────────────────────────────────
async def test_complete_returns_normalized_result():
    p = LLMProvider(complete_fn=_fake("answer", input_tokens=100, output_tokens=20))
    result = await p.complete(MESSAGES, provider="claude")

    assert isinstance(result, CompletionResult)
    assert result.content == "answer"
    assert result.provider == "claude"
    assert result.model == "anthropic/claude-sonnet-4-6"
    assert result.input_tokens == 100
    assert result.output_tokens == 20
    assert result.cost_usd == pytest.approx(estimate_cost(result.model, 100, 20))
    assert result.attempts == ["claude"]


async def test_complete_accepts_dict_messages():
    p = LLMProvider(complete_fn=_fake("ok"))
    result = await p.complete([{"role": "user", "content": "hi"}], provider="gpt4")
    assert result.content == "ok"
    assert result.provider == "gpt4"


async def test_agent_type_selects_provider():
    p = LLMProvider(complete_fn=_fake())
    result = await p.complete(MESSAGES, agent_type="research", fallback=False)
    assert result.provider == "gemini"


async def test_empty_messages_rejected():
    p = LLMProvider(complete_fn=_fake())
    with pytest.raises(ValueError):
        await p.complete([], provider="claude")


# ── retries ──────────────────────────────────────────────────────────────────
async def test_retries_then_succeeds():
    calls = {"n": 0}

    async def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {"content": "recovered", "input_tokens": 1, "output_tokens": 1}

    p = LLMProvider(complete_fn=flaky, max_retries=3, retry_backoff_base=0)
    result = await p.complete(MESSAGES, provider="claude", fallback=False)
    assert result.content == "recovered"
    assert calls["n"] == 3


async def test_no_fallback_single_provider_failure_raises():
    p = LLMProvider(complete_fn=_failing(), max_retries=2, retry_backoff_base=0)
    with pytest.raises(AllProvidersFailedError) as ei:
        await p.complete(MESSAGES, provider="claude", fallback=False)
    assert "claude" in ei.value.errors


# ── fallback across providers ────────────────────────────────────────────────
async def test_fallback_moves_to_next_provider():
    async def only_gemini(*, model, **kwargs):
        if model == resolve_model("gemini"):
            return {"content": "from-gemini", "input_tokens": 2, "output_tokens": 2}
        raise RuntimeError("provider down")

    p = LLMProvider(
        complete_fn=only_gemini,
        providers=["claude", "gemini", "gpt4", "ollama"],
        max_retries=1,
        retry_backoff_base=0,
    )
    result = await p.complete(MESSAGES, provider="claude")
    assert result.provider == "gemini"
    assert result.content == "from-gemini"
    assert result.attempts == ["claude", "gemini"]


async def test_all_providers_fail_reports_each():
    p = LLMProvider(
        complete_fn=_failing(ValueError("nope")),
        providers=["claude", "gemini"],
        max_retries=1,
        retry_backoff_base=0,
    )
    with pytest.raises(AllProvidersFailedError) as ei:
        await p.complete(MESSAGES, provider="claude")
    assert set(ei.value.errors) == {"claude", "gemini"}


async def test_primary_not_duplicated_in_fallback_order():
    seen = []

    async def track(*, model, **kwargs):
        seen.append(model)
        raise RuntimeError("down")

    p = LLMProvider(
        complete_fn=track,
        providers=["claude", "gemini"],  # claude also the primary
        max_retries=1,
        retry_backoff_base=0,
    )
    with pytest.raises(AllProvidersFailedError):
        await p.complete(MESSAGES, provider="claude")
    # claude attempted exactly once despite appearing in both primary + fallback.
    assert seen == [resolve_model("claude"), resolve_model("gemini")]


def test_provider_credentials_configured_respects_keys(monkeypatch):
    from app.config import settings
    from app.llm.routing import provider_credentials_configured

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "gk")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert provider_credentials_configured("claude") is False
    assert provider_credentials_configured("gemini") is True
    assert provider_credentials_configured("gpt4") is False
    assert provider_credentials_configured("ollama") is True


def test_real_path_skips_providers_without_cloud_keys(monkeypatch):
    from app.config import settings
    from app.llm.provider import LLMProvider, _litellm_complete

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "gk")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    p = LLMProvider(providers=["claude", "gemini", "gpt4", "ollama"])
    p._complete_fn = _litellm_complete
    assert p._candidate_providers("claude", None, True) == ["gemini", "ollama"]


def test_injected_complete_fn_does_not_skip_empty_keys(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "")
    p = LLMProvider(complete_fn=_failing(), providers=["claude", "gemini"])
    assert p._candidate_providers("claude", None, True) == ["claude", "gemini"]

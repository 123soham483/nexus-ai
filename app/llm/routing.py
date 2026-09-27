"""LLM routing tables: provider → model, agent → provider, and pricing.

Everything that is "which model string do we actually send" lives here so a
single edit swaps placeholder model IDs for real ones (BRAIN.md D6). The rest of
the app refers to *providers* by their short names (``claude``, ``gemini``,
``gpt4``, ``ollama``) — matching ``settings.FALLBACK_ORDER`` — and lets this
module resolve the concrete, LiteLLM-qualified model string.
"""
from __future__ import annotations

from typing import Dict, Tuple

from app.config import settings

# Live Gemini model for this project's Google API key. gemini-2.5-pro 404s for
# new API users; gemini-2.5-flash is the verified production model.
_GEMINI_LIVE = "gemini/gemini-2.5-flash"

# ── Provider → concrete model string ─────────────────────────────────────────
# Values are LiteLLM-qualified model identifiers (``<provider>/<model>``). These
# are the spec's placeholder IDs kept verbatim (D6); edit only here to go live.
PROVIDER_MODELS: Dict[str, str] = {
    "claude": "anthropic/claude-sonnet-4-6",
    "gemini": _GEMINI_LIVE,
    "gemini-flash": _GEMINI_LIVE,
    "gemini-pro": _GEMINI_LIVE,  # alias onto flash — 2.5-pro 404s for new keys
    "gpt4": "openai/gpt-4o",
    "gpt35": "openai/gpt-3.5-turbo",
    "ollama": f"ollama/{settings.OLLAMA_MODEL}",
}

# ── Agent type → preferred provider ──────────────────────────────────────────
# Gemini is the project's sole live provider (GOOGLE_API_KEY). Every LLM agent
# maps here so a missing Anthropic/OpenAI key cannot stall the first hop.
AGENT_LLM_MAP: Dict[str, str] = {
    "coder": "gemini",
    "debugger": "gemini",
    "optimizer": "gemini",
    "refactor": "gemini",
    "tester": "gemini",
    "reviewer": "gemini",
    "security": "gemini",
    "planner": "gemini",
    "docs": "gemini",
    "research": "gemini",
    "summarizer": "gemini",
    "validator": "gemini",
    "hallucination_detector": "gemini",
    "cost_controller": "gemini",
}

# Cloud providers that need an env key. Ollama (and unknown names) are treated
# as always-configured so a local fallback still runs.
_CLOUD_KEY_FIELDS: Dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "gemini-flash": "GOOGLE_API_KEY",
    "gemini-pro": "GOOGLE_API_KEY",
    "gpt4": "OPENAI_API_KEY",
    "gpt35": "OPENAI_API_KEY",
}

# ── Non-LLM agents ───────────────────────────────────────────────────────────
# Agent types that make NO LLM calls (estimate as zero cost). Kept here (not in
# the factory) so routing/cost logic has one source of truth without importing
# the agent layer. Add any future non-LLM agent here.
NON_LLM_AGENTS = frozenset({"hitl_controller"})

# ── Pricing: USD per 1K tokens, keyed by concrete model string ───────────────
# (input_per_1k, output_per_1k). Local models are free. A conservative default
# is used for any model missing from the table so cost is never silently zero.
MODEL_PRICING: Dict[str, Tuple[float, float]] = {
    "anthropic/claude-sonnet-4-6": (0.003, 0.015),
    "gemini/gemini-2.5-flash": (0.0003, 0.0025),
    "gemini/gemini-2.5-pro": (0.00125, 0.005),  # unused while aliased to flash
    "openai/gpt-4o": (0.005, 0.015),
    "openai/gpt-3.5-turbo": (0.0005, 0.0015),
    f"ollama/{settings.OLLAMA_MODEL}": (0.0, 0.0),
}

_DEFAULT_PRICING: Tuple[float, float] = (0.003, 0.015)


def resolve_model(provider: str) -> str:
    """Return the concrete model string for a provider short-name.

    Raises ``KeyError`` (via ``UnknownProviderError`` at the call site) so a typo
    in FALLBACK_ORDER or an agent map fails loudly rather than silently.
    """
    try:
        return PROVIDER_MODELS[provider]
    except KeyError as exc:
        raise KeyError(
            f"Unknown LLM provider {provider!r}; known: {sorted(PROVIDER_MODELS)}"
        ) from exc


def provider_for_agent(agent_type: str | None) -> str:
    """Provider a given agent type should use, defaulting to the configured one."""
    if agent_type and agent_type in AGENT_LLM_MAP:
        return AGENT_LLM_MAP[agent_type]
    return settings.DEFAULT_LLM_PROVIDER


def provider_credentials_configured(provider: str) -> bool:
    """True when this provider can be called without a missing-key timeout.

    Empty ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` used to make every agent
    burn ``LLM_MAX_RETRIES`` × ``LLM_TIMEOUT_SECONDS`` on Claude/GPT before
    Gemini — tasks looked stuck in ``pending`` / ``running``. The real LiteLLM
    path skips those providers; injected fakes never consult this.
    """
    field = _CLOUD_KEY_FIELDS.get(provider)
    if field is None:
        return True
    return bool((getattr(settings, field, "") or "").strip())


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost in USD for a call, from the pricing table (default price if unknown)."""
    in_rate, out_rate = MODEL_PRICING.get(model, _DEFAULT_PRICING)
    return (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate


def estimate_agent_cost(agent_type: str, estimated_tokens: int = 1000) -> float:
    """Estimated USD for one agent type at the default 70/30 input/output split.

    Shared by the orchestrator's ``cost_estimated`` step and the
    ``POST /api/v1/cost/estimate`` endpoint. Unknown or unroutable agent types
    (e.g. the non-LLM ``hitl_controller``) fall back to a conservative $0.02 so
    estimation never crashes a plan.
    """
    if agent_type in NON_LLM_AGENTS:
        return 0.0
    try:
        provider = provider_for_agent(agent_type)
        model = resolve_model(provider)
    except Exception:
        return 0.02
    return estimate_cost(model, int(estimated_tokens * 0.7), int(estimated_tokens * 0.3))

"""LLM provider layer: resilient, testable access to language models.

Public surface:
    - LLMProvider / default_provider — the front door agents call
    - LLMMessage, CompletionResult — request/response value types
    - LLMError, AllProvidersFailedError — failure signalling
    - routing helpers (resolve_model, provider_for_agent, estimate_cost)
"""
from __future__ import annotations

from app.llm.provider import (
    AllProvidersFailedError,
    CompletionResult,
    LLMError,
    LLMMessage,
    LLMProvider,
    default_provider,
)
from app.llm.routing import (
    AGENT_LLM_MAP,
    MODEL_PRICING,
    NON_LLM_AGENTS,
    PROVIDER_MODELS,
    estimate_agent_cost,
    estimate_cost,
    provider_credentials_configured,
    provider_for_agent,
    resolve_model,
)

__all__ = [
    "LLMProvider",
    "default_provider",
    "LLMMessage",
    "CompletionResult",
    "LLMError",
    "AllProvidersFailedError",
    "AGENT_LLM_MAP",
    "PROVIDER_MODELS",
    "MODEL_PRICING",
    "NON_LLM_AGENTS",
    "resolve_model",
    "provider_for_agent",
    "provider_credentials_configured",
    "estimate_cost",
    "estimate_agent_cost",
]

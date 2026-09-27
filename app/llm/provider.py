"""LiteLLM-backed provider with multi-provider fallback and retries.

``LLMProvider.complete`` is the single entry point every agent uses to talk to a
model. It tries providers in order (the requested/agent-preferred one first,
then ``settings.FALLBACK_ORDER``), retrying each up to ``LLM_MAX_RETRIES`` times
before moving on, and returns a normalized :class:`CompletionResult` carrying
token counts and computed cost.

The actual network call is a single injectable coroutine (``complete_fn``). In
production it lazily imports ``litellm`` (BRAIN.md D3) so importing this module
never drags in the SDK; in tests a deterministic fake is injected (D5) so the
suite needs no network, keys, or LiteLLM install.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Union

from app.config import settings
from app.llm.routing import (
    estimate_cost,
    provider_credentials_configured,
    provider_for_agent,
    resolve_model,
)
from app.observability.metrics import record_llm_call
from app.observability.tracer import (
    LLM_ATTEMPTS,
    LLM_ERROR,
    NexusTracer,
    get_tracer,
)


# ── Data types ───────────────────────────────────────────────────────────────
@dataclass
class LLMMessage:
    """A single chat message. ``role`` is one of system/user/assistant."""

    role: str
    content: str


MessageLike = Union[LLMMessage, Dict[str, str]]


@dataclass
class CompletionResult:
    """Normalized result of a successful completion, ready for persistence."""

    content: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    attempts: List[str] = field(default_factory=list)  # providers tried, in order
    raw: Any = None

    @property
    def fallback_used(self) -> bool:
        return len(self.attempts) > 1

    @property
    def model_used(self) -> str:
        return self.model


# ── Errors ───────────────────────────────────────────────────────────────────
class LLMError(Exception):
    """Base class for provider-layer failures."""


class AllProvidersFailedError(LLMError):
    """Every candidate provider failed. Carries the per-provider error map."""

    def __init__(self, errors: Dict[str, str]):
        self.errors = errors
        detail = "; ".join(f"{p}: {e}" for p, e in errors.items())
        super().__init__(f"All LLM providers failed ({detail})")


# The completion callable contract: given a concrete model + normalized messages,
# return a dict with content and (optionally) token usage / raw response.
CompleteFn = Callable[..., Awaitable[Dict[str, Any]]]


def _normalize_messages(messages: Sequence[MessageLike]) -> List[Dict[str, str]]:
    """Coerce LLMMessage / dict inputs into the ``[{role, content}]`` wire form."""
    out: List[Dict[str, str]] = []
    for m in messages:
        if isinstance(m, LLMMessage):
            out.append({"role": m.role, "content": m.content})
        elif isinstance(m, dict) and "role" in m and "content" in m:
            out.append({"role": str(m["role"]), "content": str(m["content"])})
        else:  # pragma: no cover - guardrail for misuse
            raise TypeError(f"Unsupported message: {m!r}")
    if not out:
        raise ValueError("messages must be a non-empty sequence")
    return out


async def _litellm_complete(
    *, model: str, messages: List[Dict[str, str]], max_tokens: int,
    temperature: float, timeout: int,
) -> Dict[str, Any]:
    """Default completion path: call LiteLLM (imported lazily) and normalize."""
    import litellm  # lazy: never imported at module load (D3)

    resp = await litellm.acompletion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    return {
        "content": choice.message.content or "",
        "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
        "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
        "raw": resp,
    }


async def _fake_complete(
    *, model: str, messages: List[Dict[str, str]], max_tokens: int,
    temperature: float, timeout: int,
) -> Dict[str, Any]:
    """Deterministic DEV/TEST completion: canned, goal-derived output, no network.

    Enabled via ``settings.LLM_FAKE_MODE`` (refused in production). Output is a
    pure function of the last user message so the whole pipeline (agents →
    orchestrator → DB) can be exercised end-to-end without keys or network.
    Token counts are derived deterministically from the prompt so cost math and
    hallucination scoring have realistic non-zero inputs.
    """
    user_msg = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    content = (
        "```python\n"
        "def solve(x):\n"
        f"    # deterministic fake-LLM response for: {user_msg[:80]!r}\n"
        "    return x\n"
        "```\n"
        "Analysis: completed by the deterministic fake provider "
        "(LLM_FAKE_MODE=true). This is canned output for development testing "
        "and must never be used in production."
    )
    in_tok = sum(len(m["content"].split()) for m in messages) + 7
    out_tok = len(content.split())
    return {
        "content": content,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "raw": {"fake": True, "model": model},
    }


class LLMProvider:
    """Resilient front door to the LLMs used by every agent."""

    def __init__(
        self,
        complete_fn: Optional[CompleteFn] = None,
        providers: Optional[Sequence[str]] = None,
        *,
        max_retries: Optional[int] = None,
        retry_backoff_base: float = 0.5,
        tracer: Optional[NexusTracer] = None,
    ) -> None:
        # Injecting complete_fn is how tests avoid LiteLLM/network entirely (D5).
        # LLM_FAKE_MODE swaps the real path for the deterministic fake so a live
        # stack (uvicorn + celery worker + broker) can run to COMPLETED without
        # keys or network. Refused in production at settings load time.
        if complete_fn is not None:
            self._complete_fn = complete_fn
        elif settings.LLM_FAKE_MODE:
            self._complete_fn = _fake_complete
        else:
            self._complete_fn = _litellm_complete
        #: Phase 4 tracing: one llm span per completion request, nested inside
        #: the calling agent's span (no-op without OpenTelemetry installed).
        self.tracer = tracer if tracer is not None else get_tracer()
        self._fallback = list(providers) if providers is not None else settings.fallback_order_list
        self._max_retries = max_retries if max_retries is not None else settings.LLM_MAX_RETRIES
        self._backoff_base = retry_backoff_base

    def _candidate_providers(
        self, provider: Optional[str], agent_type: Optional[str], fallback: bool
    ) -> List[str]:
        """Ordered, de-duplicated provider list to attempt."""
        primary = provider or provider_for_agent(agent_type)
        if not fallback:
            return [primary]
        ordered = [primary, *self._fallback]
        seen: set[str] = set()
        result: List[str] = []
        for p in ordered:
            if p and p not in seen:
                seen.add(p)
                result.append(p)
        # Real LiteLLM calls: skip providers whose cloud key is empty so we do
        # not sit on Claude/OpenAI timeouts (30s × retries) before Gemini.
        # Injected/fake complete_fn keeps the full list so unit tests still
        # exercise fallback without keys.
        if self._complete_fn is _litellm_complete:
            keyed = [p for p in result if provider_credentials_configured(p)]
            if keyed:
                return keyed
        return result

    async def _call_one(
        self, provider: str, messages: List[Dict[str, str]], max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        """Call a single provider, retrying transient failures with backoff."""
        model = resolve_model(provider)
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                raw = await self._complete_fn(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=settings.LLM_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 - any provider error is retryable
                last_exc = exc
                text = str(exc)
                # A DAILY-quota 429 (e.g. Gemini "GenerateRequestsPerDay…") will
                # not free up within any sane retry window — retrying just pins
                # the solo worker for minutes and makes every task read as
                # "stuck on pending". Fail fast; the caller records FAILED.
                if "PerDay" in text or "PerDayPerProject" in text:
                    raise
                if attempt < self._max_retries:
                    # Rate limits (429) and transient 5xx need a real wait, not
                    # 0.5s. Honor a provider-provided retry delay when present,
                    # otherwise use exponential backoff with a 5s floor.
                    delay = self._backoff_base * attempt
                    import re as _re
                    m = _re.search(r"retry in ([0-9.]+)s", text, _re.IGNORECASE)
                    if m:
                        delay = max(delay, min(float(m.group(1)) + 1.0, 70.0))
                    elif "RateLimit" in type(exc).__name__ or "429" in text:
                        delay = max(delay, 5.0 * attempt)
                    await asyncio.sleep(delay)
                continue

            in_tok = int(raw.get("input_tokens") or 0)
            out_tok = int(raw.get("output_tokens") or 0)
            cost = (
                estimate_cost(model, in_tok, out_tok)
                if settings.ENABLE_COST_ESTIMATION
                else 0.0
            )
            return CompletionResult(
                content=raw.get("content", ""),
                provider=provider,
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
                raw=raw.get("raw"),
            )
        raise last_exc if last_exc else LLMError(f"{provider} failed with no exception")

    async def complete(
        self,
        messages: Sequence[MessageLike],
        *,
        provider: Optional[str] = None,
        agent_type: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        fallback: bool = True,
    ) -> CompletionResult:
        """Complete a chat request, falling back across providers on failure.

        ``provider`` forces a starting provider; otherwise ``agent_type`` selects
        one via :func:`provider_for_agent`. With ``fallback`` (default) the
        remaining ``FALLBACK_ORDER`` providers are tried in turn. Raises
        :class:`AllProvidersFailedError` if none succeed.
        """
        norm = _normalize_messages(messages)
        max_tok = max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS
        candidates = self._candidate_providers(provider, agent_type, fallback)
        primary = candidates[0] if candidates else "unknown"

        # One llm span per completion request, nested inside the agent span that
        # is current when ``complete`` is awaited (Step 4.1).
        with self.tracer.llm_span(
            agent_type=agent_type or "", provider=primary
        ) as span:
            errors: Dict[str, str] = {}
            tried: List[str] = []
            for p in candidates:
                tried.append(p)
                try:
                    result = await self._call_one(p, norm, max_tok, temperature)
                    result.attempts = tried
                    span.record_llm_usage(
                        provider=result.provider,
                        model=result.model,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        cost_usd=result.cost_usd,
                        agent_type=agent_type or "",
                        fallback_used=result.fallback_used,
                    )
                    record_llm_call(
                        result.model,
                        agent_type or "",
                        result.input_tokens,
                        result.output_tokens,
                        result.cost_usd,
                    )
                    span.set_attribute(LLM_ATTEMPTS, len(tried))
                    return result
                except Exception as exc:  # noqa: BLE001 - record and try next
                    errors[p] = f"{type(exc).__name__}: {exc}"
                    span.add_event(
                        "llm.provider_failed",
                        {"provider": p, "error": errors[p][:200]},
                    )
            span.set_attribute(
                LLM_ERROR,
                "; ".join(f"{p}: {e}" for p, e in errors.items())[:500],
            )
            raise AllProvidersFailedError(errors)


# Process-wide default instance (uses the real LiteLLM path). Agents may inject
# their own for testing or specialized routing.
default_provider = LLMProvider()

"""NexusTracer — OpenTelemetry spans for the orchestration pipeline (Step 4.1).

One tracer, four span kinds, nested so a single trace explains *why* a task cost
what it cost:

    task_span    root    one task execution (the orchestrator's pipeline)
      agent_span child   one agent turn (BaseAgent.execute)
        llm_span nested  one completion request (LLMProvider.complete)
      tool_span  nested  one side-effecting tool call (e.g. the code sandbox)

Nesting is *automatic*: each span is opened with ``start_as_current_span``, so
whatever is opened inside the ``with`` block becomes its child. Callers do not
pass parent spans around.

Design rules (BRAIN.md): OpenTelemetry is a heavy optional dependency, so it is
imported lazily — when it is missing (the local dev venv and the whole test
suite) the tracer degrades to a no-op and every span call stays safe. The real
OTel tracer is injectable, so unit tests assert parenting and attributes with a
fake instead of mocking the SDK internals.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping, Optional

from app.config import settings

logger = logging.getLogger(__name__)

#: Goals can be long (and are user data) — spans keep a bounded excerpt.
GOAL_MAX_CHARS = 200

# ── Attribute keys: one source of truth so callers and dashboards agree ───────
SPAN_KIND = "nexus.span.kind"
TASK_ID = "nexus.task.id"
TASK_GOAL = "nexus.task.goal"
TASK_STATUS = "nexus.task.status"
TENANT_ID = "nexus.tenant.id"
AGENT_TYPE = "nexus.agent.type"
AGENT_ID = "nexus.agent.id"
AGENT_CONFIDENCE = "nexus.agent.confidence"
AGENT_SUCCESS = "nexus.agent.success"
#: GenAI semantic conventions for the model-facing attributes.
PROVIDER = "gen_ai.system"
MODEL = "gen_ai.request.model"
INPUT_TOKENS = "gen_ai.usage.input_tokens"
OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
COST_USD = "nexus.llm.cost_usd"
FALLBACK_USED = "nexus.llm.fallback_used"
LLM_ATTEMPTS = "nexus.llm.attempts"
LLM_ERROR = "nexus.llm.error"
LATENCY_MS = "nexus.latency_ms"
TOOL_NAME = "nexus.tool.name"
TOOL_SUCCESS = "nexus.tool.success"

#: Span names, greppable and stable.
TASK_SPAN_NAME = "task"
AGENT_SPAN_NAME = "agent"
LLM_SPAN_NAME = "llm"
TOOL_SPAN_NAME = "tool"


def _excerpt(text: Any, limit: int = GOAL_MAX_CHARS) -> str:
    """A bounded, single-line view of potentially long user text."""
    if text is None:
        return ""
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


class SpanHandle:
    """Thin wrapper over a real OTel span that is always safe to call.

    When tracing is disabled the handle wraps ``None`` and every method is a
    no-op, so instrumented code needs no ``if tracing`` branches. It also owns
    the attribute vocabulary, so a caller records a *fact* (``record_llm_usage``)
    rather than guessing attribute names.
    """

    __slots__ = ("_span", "_started")

    def __init__(self, span: Any = None) -> None:
        # Guarded so a caller creating a handle directly is harmless.
        object.__setattr__(self, "_span", span)
        object.__setattr__(self, "_started", time.perf_counter())

    # ── introspection ────────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        """True when a real span is attached (tracing is on)."""
        return object.__getattribute__(self, "_span") is not None

    @property
    def span(self) -> Any:
        """The underlying span, or ``None`` (for tests/advanced callers)."""
        return object.__getattribute__(self, "_span")

    # ── recording ────────────────────────────────────────────────────────────
    def set_attribute(self, key: str, value: Any) -> None:
        span = object.__getattribute__(self, "_span")
        if span is None:
            return
        try:
            span.set_attribute(key, value)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("tracer: set_attribute(%s) failed: %s", key, exc)

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        for key, value in attributes.items():
            self.set_attribute(key, value)

    def add_event(self, name: str, attributes: Optional[Mapping[str, Any]] = None) -> None:
        span = object.__getattribute__(self, "_span")
        if span is None:
            return
        try:
            span.add_event(name, dict(attributes or {}))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("tracer: add_event(%s) failed: %s", name, exc)

    def record_exception(self, exc: BaseException) -> None:
        span = object.__getattribute__(self, "_span")
        if span is None:
            return
        try:
            span.record_exception(exc)
        except Exception:  # pragma: no cover - defensive
            pass

    def record_llm_usage(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        agent_type: Optional[str] = None,
        fallback_used: Optional[bool] = None,
    ) -> None:
        """Record the token/cost facts of a completion on this span."""
        if provider is not None:
            self.set_attribute(PROVIDER, provider)
        if model is not None:
            self.set_attribute(MODEL, model)
        if agent_type is not None:
            self.set_attribute(AGENT_TYPE, agent_type)
        if input_tokens is not None:
            self.set_attribute(INPUT_TOKENS, int(input_tokens))
        if output_tokens is not None:
            self.set_attribute(OUTPUT_TOKENS, int(output_tokens))
        if cost_usd is not None:
            self.set_attribute(COST_USD, float(cost_usd))
        if fallback_used is not None:
            self.set_attribute(FALLBACK_USED, bool(fallback_used))

    def record_latency(self, seconds: Optional[float] = None) -> float:
        """Stamp the span's elapsed time (called automatically on span exit)."""
        elapsed = (
            time.perf_counter() - object.__getattribute__(self, "_started")
            if seconds is None
            else seconds
        )
        self.set_attribute(LATENCY_MS, round(elapsed * 1000, 3))
        return elapsed

    def __getattr__(self, item: str) -> Any:
        """Pass through anything else (``is_recording``, ``set_status``…)."""
        span = object.__getattribute__(self, "_span")
        if span is None:
            raise AttributeError(item)
        return getattr(span, item)


class NexusTracer:
    """Creates the task/agent/llm/tool spans; no-op when tracing is off.

    ``enabled`` and ``endpoint`` default to settings. The OTel tracer and
    provider are injectable: tests pass a fake tracer implementing
    ``start_as_current_span``, so parenting is asserted without the SDK.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        endpoint: Optional[str] = None,
        service_name: Optional[str] = None,
        tracer: Any = None,
        provider: Any = None,
    ) -> None:
        self.enabled: bool = (
            bool(settings.ENABLE_OPENTELEMETRY) if enabled is None else bool(enabled)
        )
        self.endpoint: str = (
            settings.OTEL_EXPORTER_ENDPOINT if endpoint is None else endpoint
        )
        self.service_name: str = (
            settings.OTEL_SERVICE_NAME if service_name is None else service_name
        )
        self._tracer = tracer
        self._provider = provider

    # ── lazy construction ────────────────────────────────────────────────────
    def _resolve_tracer(self) -> Any:
        """The OTel tracer, or ``None`` when tracing is off/unavailable.

        A failed build disables the tracer *permanently* (one log line, not one
        per span) — a missing optional dependency must cost nothing per call.
        """
        if not self.enabled:
            return None
        if self._tracer is not None:
            return self._tracer
        try:
            self._tracer = self._build_tracer()
        except Exception as exc:
            logger.warning(
                "NexusTracer disabled: OpenTelemetry unavailable (%s)", exc
            )
            self.enabled = False
            self._tracer = None
        return self._tracer

    def _build_tracer(self) -> Any:
        """Build a real OTLP-exporting tracer (imports OTel lazily)."""
        from opentelemetry import trace  # lazy (heavy optional dep)
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": self.service_name})
        provider = TracerProvider(resource=resource)
        if self.endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=self.endpoint, insecure=True)
                )
            )
        else:  # pragma: no cover - configuration dependent
            logger.info(
                "NexusTracer: no OTEL_EXPORTER_ENDPOINT set; spans stay in-process"
            )
        # Register globally so other instrumented libraries join our traces.
        try:
            trace.set_tracer_provider(provider)
        except Exception:  # pragma: no cover - already set by another component
            pass
        self._provider = provider
        return provider.get_tracer(self.service_name)

    def is_active(self) -> bool:
        """Whether spans will actually be produced."""
        return self._resolve_tracer() is not None

    def flush(self) -> None:
        """Force-export pending spans (best effort; used on shutdown)."""
        provider = self._provider
        if provider is None:
            return
        try:
            provider.force_flush()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("NexusTracer flush failed: %s", exc)

    def shutdown(self) -> None:
        """Shut the provider down, flushing what is left."""
        provider = self._provider
        if provider is None:
            return
        try:
            provider.shutdown()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("NexusTracer shutdown failed: %s", exc)

    # ── span creation ────────────────────────────────────────────────────────
    @contextmanager
    def _span(self, name: str, attributes: Mapping[str, Any]) -> Iterator[SpanHandle]:
        """Open a span (or a no-op handle) and stamp its latency on exit."""
        tracer = self._resolve_tracer()
        if tracer is None:
            yield SpanHandle(None)
            return

        with tracer.start_as_current_span(name) as span:
            handle = SpanHandle(span)
            handle.set_attributes(attributes)
            try:
                yield handle
            finally:
                handle.record_latency()

    def task_span(
        self, task_id: str = "", goal: str = "", tenant_id: str = ""
    ) -> Any:
        """Root span for one task execution."""
        return self._span(
            TASK_SPAN_NAME,
            {
                SPAN_KIND: "task",
                TASK_ID: str(task_id),
                TASK_GOAL: _excerpt(goal),
                TENANT_ID: str(tenant_id),
            },
        )

    def agent_span(
        self,
        task_id: str = "",
        agent_type: str = "",
        model: str = "",
        agent_id: str = "",
    ) -> Any:
        """Child span for one agent turn (nested under the task span)."""
        return self._span(
            f"{AGENT_SPAN_NAME}.{agent_type or 'unknown'}",
            {
                SPAN_KIND: "agent",
                TASK_ID: str(task_id),
                AGENT_TYPE: agent_type or "",
                AGENT_ID: agent_id or "",
                MODEL: model or "",
            },
        )

    def llm_span(
        self, agent_type: str = "", model: str = "", provider: str = ""
    ) -> Any:
        """Nested span for one completion request."""
        return self._span(
            f"{LLM_SPAN_NAME}.{provider or 'unknown'}",
            {
                SPAN_KIND: "llm",
                AGENT_TYPE: agent_type or "",
                MODEL: model or "",
                PROVIDER: provider or "",
            },
        )

    def tool_span(self, agent_type: str = "", tool_name: str = "") -> Any:
        """Nested span for one tool call (sandbox execution, external API…)."""
        return self._span(
            f"{TOOL_SPAN_NAME}.{tool_name or 'unknown'}",
            {
                SPAN_KIND: "tool",
                AGENT_TYPE: agent_type or "",
                TOOL_NAME: tool_name or "",
            },
        )


#: Shared tracer used by the orchestrator, agents and the LLM provider.
default_tracer = NexusTracer()


def get_tracer() -> NexusTracer:
    """The process-wide tracer (exported for callers; replaceable in tests)."""
    return default_tracer


def set_tracer(tracer: NexusTracer) -> None:
    """Swap the shared tracer (tests, or a pre-wired application instance)."""
    global default_tracer
    default_tracer = tracer

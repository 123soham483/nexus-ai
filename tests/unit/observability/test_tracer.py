"""Tests for NexusTracer (Phase 4, Step 4.1).

OpenTelemetry is not installed in the dev venv, so these tests inject a fake
tracer implementing the one contract the instrumented code relies on:
``start_as_current_span`` as a context manager that makes the opened span
*current*. The fake keeps a real contextvar stack, so nesting is asserted the
way OTel actually propagates context — not by inspecting our own bookkeeping.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager

from app.config import settings
from app.observability.tracer import (
    AGENT_CONFIDENCE,
    COST_USD,
    FALLBACK_USED,
    GOAL_MAX_CHARS,
    INPUT_TOKENS,
    LATENCY_MS,
    OUTPUT_TOKENS,
    SpanHandle,
    NexusTracer,
    SPAN_KIND,
    TASK_GOAL,
    TASK_ID,
    TOOL_NAME,
    TOOL_SUCCESS,
)


# ── fake OpenTelemetry ───────────────────────────────────────────────────────

class FakeSpan:
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.attributes = {}
        self.events = []
        self.exceptions = []

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def add_event(self, name, attributes=None):
        self.events.append((name, attributes or {}))

    def record_exception(self, exc):
        self.exceptions.append(exc)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<FakeSpan {self.name}>"


class FakeTracer:
    """Minimal OTel-compatible tracer: nesting via a contextvar stack."""

    def __init__(self):
        self.spans = []
        self._current = contextvars.ContextVar("fake_otel_current", default=None)

    @contextmanager
    def start_as_current_span(self, name):
        span = FakeSpan(name, parent=self._current.get())
        self.spans.append(span)
        token = self._current.set(span)
        try:
            yield span
        finally:
            self._current.reset(token)

    @property
    def current(self):
        return self._current.get()

    def named(self, name):
        return [s for s in self.spans if s.name == name]

    def by_kind(self, kind):
        return [s for s in self.spans if s.attributes.get(SPAN_KIND) == kind]


class FakeProvider:
    def __init__(self):
        self.flushes = 0
        self.shutdowns = 0

    def force_flush(self):
        self.flushes += 1

    def shutdown(self):
        self.shutdowns += 1


def _tracer(**kwargs) -> tuple[NexusTracer, FakeTracer]:
    fake = FakeTracer()
    return NexusTracer(tracer=fake, enabled=True, **kwargs), fake


# ── span creation & attributes ───────────────────────────────────────────────

def test_task_span_records_identity_goal_and_kind():
    tracer, fake = _tracer()

    with tracer.task_span(task_id="t-1", goal="build an api", tenant_id="ten-1") as span:
        assert span.active is True

    task = fake.named("task")[0]
    assert task.attributes[TASK_ID] == "t-1"
    assert task.attributes[TASK_GOAL] == "build an api"
    assert task.attributes[SPAN_KIND] == "task"
    assert task.attributes["nexus.tenant.id"] == "ten-1"


def test_task_goal_is_truncated_to_a_bounded_excerpt():
    tracer, fake = _tracer()
    long_goal = "x" * (GOAL_MAX_CHARS + 500)

    with tracer.task_span(task_id="t", goal=long_goal):
        pass

    stored = fake.named("task")[0].attributes[TASK_GOAL]
    assert len(stored) == GOAL_MAX_CHARS + 1  # excerpt + ellipsis
    assert stored.endswith("…")


def test_goal_newlines_are_collapsed_into_one_line():
    tracer, fake = _tracer()

    with tracer.task_span(task_id="t", goal="line one\n\n  line two"):
        pass

    assert fake.named("task")[0].attributes[TASK_GOAL] == "line one line two"


def test_agent_span_is_a_child_of_the_task_span():
    tracer, fake = _tracer()

    with tracer.task_span(task_id="t-1", goal="goal"):
        with tracer.agent_span(task_id="t-1", agent_type="coder", agent_id="a-1"):
            pass

    task = fake.named("task")[0]
    agent = fake.named("agent.coder")[0]
    assert agent.parent is task


def test_llm_span_nests_inside_the_agent_span():
    tracer, fake = _tracer()

    with tracer.task_span(task_id="t-1", goal="goal"):
        with tracer.agent_span(task_id="t-1", agent_type="coder"):
            with tracer.llm_span(agent_type="coder", provider="claude", model="m"):
                pass

    task, agent, llm = (
        fake.named("task")[0],
        fake.named("agent.coder")[0],
        fake.named("llm.claude")[0],
    )
    assert agent.parent is task
    assert llm.parent is agent
    assert llm.attributes["gen_ai.system"] == "claude"


def test_tool_span_nests_and_records_the_tool_name():
    tracer, fake = _tracer()

    with tracer.agent_span(agent_type="tester"):
        with tracer.tool_span("tester", "docker_sandbox") as span:
            span.set_attribute(TOOL_SUCCESS, True)

    tool = fake.named("tool.docker_sandbox")[0]
    assert tool.parent is fake.named("agent.tester")[0]
    assert tool.attributes[TOOL_NAME] == "docker_sandbox"
    assert tool.attributes[TOOL_SUCCESS] is True


def test_spans_without_a_parent_are_roots():
    tracer, fake = _tracer()
    with tracer.task_span(task_id="t", goal="g"):
        pass
    with tracer.task_span(task_id="t2", goal="g"):
        pass

    assert all(s.parent is None for s in fake.named("task"))


def test_span_latency_is_recorded_on_exit():
    tracer, fake = _tracer()

    with tracer.task_span(task_id="t", goal="g"):
        pass

    latency = fake.named("task")[0].attributes[LATENCY_MS]
    assert isinstance(latency, float)
    assert latency >= 0


def test_span_kinds_are_tagged_for_filtering():
    tracer, fake = _tracer()

    with tracer.task_span(task_id="t", goal="g"):
        with tracer.agent_span(agent_type="coder"):
            with tracer.llm_span(provider="claude"):
                pass
            with tracer.tool_span("coder", "shell"):
                pass

    assert len(fake.by_kind("task")) == 1
    assert len(fake.by_kind("agent")) == 1
    assert len(fake.by_kind("llm")) == 1
    assert len(fake.by_kind("tool")) == 1


# ── usage recording ──────────────────────────────────────────────────────────

def test_record_llm_usage_writes_tokens_cost_and_model():
    tracer, fake = _tracer()

    with tracer.llm_span(agent_type="coder", provider="claude", model="m") as span:
        span.record_llm_usage(
            provider="claude",
            model="anthropic/claude-sonnet-4-6",
            input_tokens=120,
            output_tokens=340,
            cost_usd=0.0042,
            agent_type="coder",
            fallback_used=True,
        )

    attrs = fake.named("llm.claude")[0].attributes
    assert attrs[INPUT_TOKENS] == 120
    assert attrs[OUTPUT_TOKENS] == 340
    assert attrs[COST_USD] == 0.0042
    assert attrs[FALLBACK_USED] is True
    assert attrs["gen_ai.request.model"] == "anthropic/claude-sonnet-4-6"


def test_record_llm_usage_skips_unset_fields():
    tracer, fake = _tracer()
    with tracer.llm_span(provider="claude") as span:
        span.record_llm_usage(input_tokens=1)
    attrs = fake.named("llm.claude")[0].attributes
    assert attrs[INPUT_TOKENS] == 1
    assert OUTPUT_TOKENS not in attrs


# ── disabled / unavailable ───────────────────────────────────────────────────

def test_disabled_tracer_is_a_no_op():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=False)

    with tracer.task_span(task_id="t", goal="g") as span:
        span.set_attribute("x", 1)
        span.add_event("e")
        span.record_llm_usage(input_tokens=5)

    assert tracer.is_active() is False
    assert fake.spans == []
    assert span.active is False


def test_missing_opentelemetry_disables_the_tracer_permanently():
    tracer = NexusTracer(enabled=True)
    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        raise ImportError("No module named 'opentelemetry'")

    tracer._build_tracer = _boom  # type: ignore[method-assign]

    with tracer.task_span(task_id="t", goal="g"):
        pass
    with tracer.task_span(task_id="t2", goal="g"):
        pass

    assert calls["n"] == 1          # tried once, not per span
    assert tracer.enabled is False
    assert tracer.is_active() is False


def test_span_handle_without_a_span_is_safe():
    handle = SpanHandle(None)
    assert handle.active is False
    handle.set_attribute("a", 1)
    handle.set_attributes({"b": 2})
    handle.add_event("c")
    handle.record_exception(ValueError("x"))
    assert handle.record_latency() >= 0


def test_broken_span_methods_never_raise():
    class Exploding:
        def set_attribute(self, *a, **k):
            raise RuntimeError("span is gone")

        def add_event(self, *a, **k):
            raise RuntimeError("span is gone")

        def record_exception(self, *a, **k):
            raise RuntimeError("span is gone")

    handle = SpanHandle(Exploding())
    handle.set_attribute("a", 1)
    handle.add_event("b")
    handle.record_exception(ValueError("x"))


def test_span_handle_passes_through_unknown_attributes():
    class WithExtras:
        def is_recording(self):
            return True

    assert SpanHandle(WithExtras()).is_recording() is True
    try:
        SpanHandle(None).is_recording()
    except AttributeError:
        pass
    else:  # pragma: no cover - the guard must hold
        raise AssertionError("SpanHandle(None) must not invent attributes")


# ── configuration & lifecycle ────────────────────────────────────────────────

def test_enabled_defaults_to_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_OPENTELEMETRY", True, raising=False)
    assert NexusTracer(tracer=FakeTracer()).enabled is True
    monkeypatch.setattr(settings, "ENABLE_OPENTELEMETRY", False, raising=False)
    assert NexusTracer(tracer=FakeTracer()).enabled is False


def test_endpoint_and_service_name_default_to_settings():
    tracer = NexusTracer(tracer=FakeTracer())
    assert tracer.endpoint == settings.OTEL_EXPORTER_ENDPOINT
    assert tracer.service_name == settings.OTEL_SERVICE_NAME


def test_flush_and_shutdown_delegate_to_the_provider():
    provider = FakeProvider()
    tracer = NexusTracer(tracer=FakeTracer(), enabled=True, provider=provider)

    tracer.flush()
    tracer.shutdown()

    assert provider.flushes == 1
    assert provider.shutdowns == 1


def test_flush_and_shutdown_are_no_ops_without_a_provider():
    tracer = NexusTracer(tracer=FakeTracer(), enabled=True)
    tracer.flush()
    tracer.shutdown()


def test_injected_tracer_is_used_verbatim():
    fake = FakeTracer()
    tracer = NexusTracer(tracer=fake, enabled=True)
    assert tracer.is_active() is True
    with tracer.task_span(task_id="t", goal="g"):
        pass
    assert len(fake.spans) == 1


def test_set_and_get_tracer_swap_the_shared_instance():
    from app.observability import tracer as tracer_module

    original = tracer_module.get_tracer()
    replacement = NexusTracer(tracer=FakeTracer(), enabled=True)
    try:
        tracer_module.set_tracer(replacement)
        assert tracer_module.get_tracer() is replacement
    finally:
        tracer_module.set_tracer(original)
    assert tracer_module.get_tracer() is original

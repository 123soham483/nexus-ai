"""Prometheus metrics for NexusAI (Phase 4, Step 4.2).

Uses a dedicated :class:`CollectorRegistry` so tests can swap registries without
colliding with the global default. Production and ``GET /metrics`` read from the
active registry via :func:`generate_metrics_output`.
"""
from __future__ import annotations

from typing import Optional

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

#: Application metrics live on this registry (not duplicated on REGISTRY).
_metrics_registry: CollectorRegistry = CollectorRegistry()

TASKS_TOTAL: Counter
TASK_DURATION: Histogram
AGENT_RUNS_TOTAL: Counter
LLM_COST_TOTAL: Counter
LLM_TOKENS_TOTAL: Counter
ACTIVE_TASKS: Gauge
HITL_PENDING: Gauge
HALLUCINATION_SCORE: Histogram


def get_metrics_registry() -> CollectorRegistry:
    return _metrics_registry


def set_metrics_registry(registry: Optional[CollectorRegistry]) -> None:
    """Replace the active registry (tests only — recreates metric collectors)."""
    global _metrics_registry, TASKS_TOTAL, TASK_DURATION, AGENT_RUNS_TOTAL
    global LLM_COST_TOTAL, LLM_TOKENS_TOTAL, ACTIVE_TASKS, HITL_PENDING
    global HALLUCINATION_SCORE
    _metrics_registry = registry or CollectorRegistry()
    _init_metrics()


def _init_metrics() -> None:
    global TASKS_TOTAL, TASK_DURATION, AGENT_RUNS_TOTAL, LLM_COST_TOTAL
    global LLM_TOKENS_TOTAL, ACTIVE_TASKS, HITL_PENDING, HALLUCINATION_SCORE
    reg = _metrics_registry
    TASKS_TOTAL = Counter(
        "nexusai_tasks_total",
        "Total tasks created",
        ["tenant_id", "status"],
        registry=reg,
    )
    TASK_DURATION = Histogram(
        "nexusai_task_duration_seconds",
        "Task execution duration",
        ["tenant_id", "status"],
        buckets=[5, 10, 30, 60, 120, 300],
        registry=reg,
    )
    AGENT_RUNS_TOTAL = Counter(
        "nexusai_agent_runs_total",
        "Total agent runs",
        ["agent_type", "model", "success"],
        registry=reg,
    )
    LLM_COST_TOTAL = Counter(
        "nexusai_llm_cost_usd_total",
        "Total LLM cost in USD",
        ["model", "agent_type"],
        registry=reg,
    )
    LLM_TOKENS_TOTAL = Counter(
        "nexusai_llm_tokens_total",
        "Total LLM tokens used",
        ["model", "direction"],
        registry=reg,
    )
    ACTIVE_TASKS = Gauge(
        "nexusai_active_tasks",
        "Currently running tasks",
        registry=reg,
    )
    HITL_PENDING = Gauge(
        "nexusai_hitl_pending_total",
        "Pending HITL approvals",
        registry=reg,
    )
    HALLUCINATION_SCORE = Histogram(
        "nexusai_hallucination_score",
        "Hallucination detection scores",
        buckets=[0.1, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0],
        registry=reg,
    )


_init_metrics()


def record_task_started(tenant_id: str) -> None:
    ACTIVE_TASKS.inc()
    TASKS_TOTAL.labels(tenant_id=tenant_id, status="started").inc()


def record_task_completed(
    tenant_id: str, duration: float, status: str = "completed"
) -> None:
    ACTIVE_TASKS.dec()
    TASKS_TOTAL.labels(tenant_id=tenant_id, status=status).inc()
    TASK_DURATION.labels(tenant_id=tenant_id, status=status).observe(max(duration, 0.0))


def record_agent_run(
    agent_type: str,
    model: str,
    success: bool,
    cost: float = 0.0,
    tokens: int = 0,
) -> None:
    AGENT_RUNS_TOTAL.labels(
        agent_type=agent_type or "unknown",
        model=model or "unknown",
        success=str(success).lower(),
    ).inc()
    if cost > 0 and model:
        LLM_COST_TOTAL.labels(model=model, agent_type=agent_type or "unknown").inc(cost)
    if tokens > 0 and model:
        LLM_TOKENS_TOTAL.labels(model=model, direction="total").inc(tokens)


def record_llm_call(
    model: str,
    agent_type: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
) -> None:
    if model:
        LLM_COST_TOTAL.labels(model=model, agent_type=agent_type or "unknown").inc(
            max(cost, 0.0)
        )
        if input_tokens:
            LLM_TOKENS_TOTAL.labels(model=model, direction="input").inc(input_tokens)
        if output_tokens:
            LLM_TOKENS_TOTAL.labels(model=model, direction="output").inc(output_tokens)


def record_hallucination_score(score: float) -> None:
    HALLUCINATION_SCORE.observe(max(0.0, min(float(score), 1.0)))


def set_hitl_pending(count: int) -> None:
    HITL_PENDING.set(max(0, int(count)))


def generate_metrics_output() -> bytes:
    return generate_latest(_metrics_registry)

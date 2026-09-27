"""Prometheus metrics (Step 4.2)."""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry
from httpx import ASGITransport, AsyncClient

from app.observability import metrics as metrics_module
from app.observability.metrics import (
    generate_metrics_output,
    record_agent_run,
    record_llm_call,
    record_task_completed,
    set_metrics_registry,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    reg = CollectorRegistry()
    set_metrics_registry(reg)
    yield
    set_metrics_registry(CollectorRegistry())


def test_record_task_completed_increments_counter():
    record_task_completed("tenant-a", 1.5, "completed")
    body = generate_metrics_output().decode()
    assert "nexusai_tasks_total" in body
    assert 'tenant_id="tenant-a"' in body
    assert 'status="completed"' in body


def test_record_agent_run_increments_agent_counter():
    record_agent_run("coder", "claude-sonnet", True, cost=0.01, tokens=100)
    body = generate_metrics_output().decode()
    assert "nexusai_agent_runs_total" in body
    assert 'agent_type="coder"' in body


def test_record_llm_call_increments_cost_and_tokens():
    record_llm_call("claude-sonnet", "coder", 50, 80, 0.002)
    body = generate_metrics_output().decode()
    assert "nexusai_llm_cost_usd_total" in body
    assert "nexusai_llm_tokens_total" in body
    assert 'direction="input"' in body
    assert 'direction="output"' in body


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/metrics")
    assert r.status_code == 200
    assert "nexusai_tasks_total" in r.text

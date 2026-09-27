"""Observability layer: distributed tracing, Prometheus metrics, quality scores.

Every collaborator here is injectable and every heavy dependency (the
OpenTelemetry SDK, ``prometheus_client``) is imported lazily, so importing this
package never requires them and the unit suite runs with fakes.
"""
from __future__ import annotations

from app.observability.tracer import (
    NexusTracer,
    SpanHandle,
    get_tracer,
    set_tracer,
)

__all__ = [
    "NexusTracer",
    "SpanHandle",
    "get_tracer",
    "set_tracer",
]

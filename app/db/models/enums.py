"""Shared enums used by DB models and schemas."""
from __future__ import annotations

import enum


class TaskStatus(str, enum.Enum):
    """Lifecycle states of a task as it moves through the orchestrator."""

    PENDING = "pending"
    ROUTING = "routing"
    RUNNING = "running"
    HITL_WAITING = "hitl_waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

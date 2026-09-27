"""Task model — a single user goal executed by the orchestrator."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.db.models.enums import TaskStatus

if TYPE_CHECKING:
    from app.db.models.user import User
    from app.db.models.tenant import Tenant
    from app.db.models.agent_run import AgentRun
    from app.db.models.trace import Trace


class Task(UUIDPrimaryKeyMixin, Base):
    """The central unit of work.

    Captures the user's goal, the routing decision, execution results, and all
    the observability numbers (cost, tokens, quality, hallucination score).
    """

    __tablename__ = "tasks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    goal: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    routing_decision: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    estimated_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=False, length=32),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
    )

    agents_spawned: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    llm_calls_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    result: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hallucination_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="tasks")
    tenant: Mapped["Tenant"] = relationship(back_populates="tasks")
    agent_runs: Mapped[List["AgentRun"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    traces: Mapped[List["Trace"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Task id={self.id} status={self.status.value}>"

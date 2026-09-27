"""AgentRun model — one execution of one agent within a task."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.task import Task


class AgentRun(UUIDPrimaryKeyMixin, Base):
    """A detailed record of a single agent invocation.

    Stores the exact prompts, the model that actually answered, the agent's
    reasoning, tool calls, token counts and cost — everything needed to replay
    or audit why an agent produced its output.
    """

    __tablename__ = "agent_runs"

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    agent_type: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)  # per-run instance id
    llm_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)

    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    llm_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tools_called: Mapped[List[Any]] = mapped_column(JSON, default=list, nullable=False)
    memory_retrieved: Mapped[List[Any]] = mapped_column(JSON, default=list, nullable=False)

    output_quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hallucination_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship(back_populates="agent_runs")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<AgentRun agent={self.agent_type!r} model={self.llm_model!r}>"

"""Trace model — an ordered event in a task's execution timeline."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow

if TYPE_CHECKING:
    from app.db.models.task import Task


class Trace(UUIDPrimaryKeyMixin, Base):
    """A single observable event emitted during task execution.

    Traces are the durable backing store behind the WebSocket event stream:
    even if no client is connected, every event is persisted here and can be
    replayed in order via ``sequence_number``.
    """

    __tablename__ = "traces"

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    agent_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    task: Mapped["Task"] = relationship(back_populates="traces")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Trace seq={self.sequence_number} event={self.event_type!r}>"

"""CostRecord model — a single billable LLM call, for cost analytics."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow

if TYPE_CHECKING:
    from app.db.models.user import User


class CostRecord(UUIDPrimaryKeyMixin, Base):
    """One row per LLM call, enabling per-task / per-agent / per-tenant rollups."""

    __tablename__ = "cost_records"

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="cost_records")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<CostRecord model={self.llm_model!r} cost=${self.cost_usd:.4f}>"

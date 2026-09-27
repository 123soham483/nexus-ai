"""Persisted hallucination score history (Phase 4, Step 4.3)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow


class HallucinationScoreRecord(UUIDPrimaryKeyMixin, Base):
    """One hallucination check outcome for trend and per-agent breakdown."""

    __tablename__ = "hallucination_scores"

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

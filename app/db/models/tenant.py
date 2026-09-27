"""Tenant model — the top-level isolation boundary for multi-tenancy."""
from __future__ import annotations

import uuid
from typing import List, TYPE_CHECKING

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # avoid runtime circular imports; only needed for typing
    from app.db.models.user import User
    from app.db.models.task import Task


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An isolated customer workspace.

    Every user, task, memory collection and cost record is scoped to a tenant.
    ``chroma_collection_prefix`` namespaces the tenant's vector collections;
    ``current_month_spend_usd`` is compared against ``monthly_budget_usd`` before
    accepting new tasks.
    """

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    current_month_spend_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    chroma_collection_prefix: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    users: Mapped[List["User"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    tasks: Mapped[List["Task"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Tenant slug={self.slug!r} active={self.is_active}>"

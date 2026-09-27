"""User model — an authenticated principal belonging to exactly one tenant."""
from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.tenant import Tenant
    from app.db.models.task import Task
    from app.db.models.cost_record import CostRecord


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A platform user. Passwords are always stored bcrypt-hashed."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="users")
    tasks: Mapped[List["Task"]] = relationship(back_populates="user")
    cost_records: Mapped[List["CostRecord"]] = relationship(back_populates="user")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User email={self.email!r} tenant={self.tenant_id}>"

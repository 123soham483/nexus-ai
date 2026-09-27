"""Multi-tenant DB session context (Phase 4, Step 4.4).

Binds ``tenant_id`` onto ``session.info`` for observability and optional
enforcement helpers. Does **not** install a global SQLAlchemy listener — that
would break migrations, system queries, and many existing explicit filters.
"""
from __future__ import annotations

from typing import Any, Optional

TENANT_INFO_KEY = "tenant_id"


class TenantIsolationMiddleware:
    @staticmethod
    def apply(session: Any, tenant_id: str) -> None:
        """Attach tenant context to a session (call after auth resolves tenant)."""
        session.info[TENANT_INFO_KEY] = str(tenant_id)

    @staticmethod
    def get_tenant_id(session: Any) -> Optional[str]:
        value = session.info.get(TENANT_INFO_KEY)
        return str(value) if value is not None else None

    @staticmethod
    def require_tenant_id(session: Any) -> str:
        tenant_id = TenantIsolationMiddleware.get_tenant_id(session)
        if not tenant_id:
            raise RuntimeError("tenant context missing on database session")
        return tenant_id

    @staticmethod
    def verify_query(query: Any, tenant_id: str) -> bool:
        """Return True if the SELECT includes a tenant_id predicate."""
        where = getattr(query, "whereclause", None)
        if where is None:
            return False
        text = str(where).lower()
        if "tenant_id" not in text:
            return False
        tid = str(tenant_id).lower()
        if tid in text or tid.replace("-", "") in text.replace("-", ""):
            return True
        # Bound parameters (e.g. :tenant_id_1) still prove the query is scoped.
        return ":tenant" in text or "tenant_id_" in text

"""Schemas for the HITL (human-in-the-loop) approval API."""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class HitlResolveRequest(BaseModel):
    """A human's decision on one pending HITL request."""

    request_id: UUID = Field(..., description="Id of the pending request to resolve")
    approved: bool = Field(..., description="True to approve, False to reject")
    note: Optional[str] = Field(default=None, max_length=500, description="Optional decision note")


class HitlRequestResponse(BaseModel):
    """Serialized view of a HITL request (pending or resolved)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    agent_type: str
    goal: str
    reason: str
    status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    note: Optional[str] = None

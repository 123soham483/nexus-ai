"""Pydantic request/response schemas for authentication."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=255)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    """Public representation of a user (never includes the password hash).

    ``email`` is a plain ``str``: response models only serialise, they don't
    re-validate. EmailStr here made GET /auth/me 500 whenever the stored email
    was not deliverable-style (e.g. the dev-only ``demo@nexusai.local`` seed,
    which email-validator rejects as a special-use domain).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    tenant_id: uuid.UUID
    created_at: datetime


class MessageResponse(BaseModel):
    message: str

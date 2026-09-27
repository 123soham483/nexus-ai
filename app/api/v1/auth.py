"""Authentication endpoints: register, login, refresh, logout, me."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.dependencies import CurrentUser, blacklist_key, oauth2_scheme
from app.schemas.auth import (
    AccessToken,
    MessageResponse,
    RefreshRequest,
    Token,
    UserOut,
    UserRegister,
)
from app.security.auth import (
    TokenError,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.security.redis_client import get_redis

router = APIRouter()


def _slugify(value: str) -> str:
    """Turn an arbitrary string into a URL-safe tenant slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "tenant"


async def _unique_tenant_slug(db: AsyncSession, base: str) -> str:
    """Return a slug based on ``base`` that is not already taken."""
    slug = _slugify(base)
    candidate = slug
    suffix = 1
    while True:
        exists = (
            await db.execute(select(Tenant).where(Tenant.slug == candidate))
        ).scalar_one_or_none()
        if exists is None:
            return candidate
        suffix += 1
        candidate = f"{slug}-{suffix}"


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegister,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Token:
    """Register a new user, creating a fresh tenant to own them.

    Each self-service registration provisions its own single-user tenant so the
    multi-tenant isolation model holds from the very first request.
    """
    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    # Derive a tenant name/slug from the email local-part.
    local_part = payload.email.split("@", 1)[0]
    slug = await _unique_tenant_slug(db, local_part)
    tenant = Tenant(
        name=f"{local_part}'s workspace",
        slug=slug,
        chroma_collection_prefix=slug,
    )
    db.add(tenant)
    await db.flush()  # assign tenant.id

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        tenant_id=tenant.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return Token(
        access_token=create_access_token(str(user.id), str(user.tenant_id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/login", response_model=Token)
async def login(
    db: Annotated[AsyncSession, Depends(get_session)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Token:
    """OAuth2-password-flow login.

    Accepts form fields ``username`` (the email) and ``password`` so the tokens
    are compatible with FastAPI's docs "Authorize" dialog and standard clients.
    """
    user = (
        await db.execute(select(User).where(User.email == username))
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive"
        )

    return Token(
        access_token=create_access_token(str(user.id), str(user.tenant_id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=AccessToken)
async def refresh(
    payload: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AccessToken:
    """Exchange a valid refresh token for a new access token."""
    try:
        token_data = verify_token(payload.refresh_token, expected_type="refresh")
        user_id = uuid.UUID(token_data.sub)
    except (TokenError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    return AccessToken(access_token=create_access_token(str(user.id), str(user.tenant_id)))


@router.post("/logout", response_model=MessageResponse)
async def logout(
    current_user: CurrentUser,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> MessageResponse:
    """Revoke the presented access token by blacklisting it until its expiry."""
    redis = get_redis()
    try:
        token_data = verify_token(token, expected_type="access")
        ttl = max(1, token_data.exp - int(datetime.now(timezone.utc).timestamp()))
    except TokenError:
        ttl = 60  # token already invalid; blacklist briefly and move on
    await redis.set(blacklist_key(token), "1", ex=ttl)
    return MessageResponse(message="logged out")


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> User:
    """Return the currently authenticated user."""
    return current_user

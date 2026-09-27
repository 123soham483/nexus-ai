"""FastAPI dependency-injection functions.

Central place for the reusable dependencies routers declare via ``Depends``:
DB session, the authenticated user, superuser gating, and the Redis client.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_session
from app.db.tenant_isolation import TenantIsolationMiddleware
from app.security.auth import TokenError, verify_token
from app.security.redis_client import get_redis

# tokenUrl is only used by the OpenAPI docs "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=True)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def blacklist_key(token: str) -> str:
    """Redis key under which a revoked (logged-out) token is stored."""
    return f"blacklist:token:{token}"


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Resolve and return the authenticated, active user for a bearer token.

    Verifies signature/expiry/type, rejects blacklisted (logged-out) tokens, and
    loads the user row. Raises 401 on any failure.
    """
    # Reject explicitly revoked tokens.
    redis = get_redis()
    if await redis.get(blacklist_key(token)):
        raise _CREDENTIALS_EXC

    try:
        payload = verify_token(token, expected_type="access")
    except TokenError:
        raise _CREDENTIALS_EXC

    if not payload.sub:
        raise _CREDENTIALS_EXC

    # The JWT subject is a string; the PK column is a UUID type whose bind
    # processor expects a uuid.UUID. Coerce, treating a malformed id as 401.
    try:
        user_id = uuid.UUID(payload.sub)
    except (ValueError, TypeError):
        raise _CREDENTIALS_EXC

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    TenantIsolationMiddleware.apply(db, str(user.tenant_id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_superuser(current_user: CurrentUser) -> User:
    """Gate an endpoint to superusers only."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return current_user


CurrentSuperuser = Annotated[User, Depends(get_current_superuser)]
DBSession = Annotated[AsyncSession, Depends(get_session)]

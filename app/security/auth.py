"""Authentication primitives: password hashing and JWT create/verify.

Password hashing uses the ``bcrypt`` package directly (not passlib) because
passlib 1.7.4 is incompatible with bcrypt 5.x (see BRAIN.md Problem P1).

JWTs are signed with ``settings.SECRET_KEY`` using ``settings.JWT_ALGORITHM``.
Two token types are issued: short-lived ``access`` tokens and longer-lived
``refresh`` tokens; ``verify_token`` enforces the expected type.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings

# bcrypt hard-limits passwords to 72 bytes; longer inputs must be truncated
# consistently on both hash and verify or verification will silently fail.
_BCRYPT_MAX_BYTES = 72


class TokenPayload(BaseModel):
    """Decoded JWT claims we care about."""

    sub: str  # user id
    exp: int
    type: str
    tenant_id: Optional[str] = None


# ── Password hashing ─────────────────────────────────────────────────────────
def _to_bcrypt_bytes(plain: str) -> bytes:
    """UTF-8 encode and truncate to bcrypt's 72-byte limit."""
    return plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of ``plain``. A fresh salt is used each call."""
    hashed = bcrypt.hashpw(_to_bcrypt_bytes(plain), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff ``plain`` matches the stored bcrypt ``hashed``."""
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash in the DB — treat as non-matching rather than crash.
        return False


# ── JWT ──────────────────────────────────────────────────────────────────────
def _create_token(claims: dict, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    to_encode = {
        **claims,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "type": token_type,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, tenant_id: str) -> str:
    """Create a signed access token carrying the user's id and tenant."""
    return _create_token(
        {"sub": str(user_id), "tenant_id": str(tenant_id)},
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )


def create_refresh_token(user_id: str) -> str:
    """Create a signed refresh token (no tenant claim; used only to re-mint access)."""
    return _create_token(
        {"sub": str(user_id)},
        timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        "refresh",
    )


class TokenError(Exception):
    """Raised when a token is invalid, expired, or of the wrong type."""


def verify_token(token: str, expected_type: str = "access") -> TokenPayload:
    """Decode and validate a JWT.

    Raises ``TokenError`` if the signature/expiry is invalid or the token type
    does not match ``expected_type``. The API layer translates this into HTTP 401.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise TokenError(f"Invalid or expired token: {exc}") from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        raise TokenError(
            f"Wrong token type: expected {expected_type!r}, got {token_type!r}"
        )

    return TokenPayload(
        sub=payload.get("sub"),
        exp=payload.get("exp"),
        type=token_type,
        tenant_id=payload.get("tenant_id"),
    )

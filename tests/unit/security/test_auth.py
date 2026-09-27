"""Unit tests for app.security.auth (hashing + JWT)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.security import auth
from app.security.auth import (
    TokenError,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)


def test_hash_password_is_salted():
    """Two hashes of the same password differ (random salt)."""
    h1 = hash_password("hunter2")
    h2 = hash_password("hunter2")
    assert h1 != h2
    assert h1.startswith("$2")  # bcrypt marker


def test_verify_password_correct():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_password_wrong():
    h = hash_password("s3cret")
    assert verify_password("wrong", h) is False


def test_verify_password_handles_long_input():
    """Passwords longer than 72 bytes still hash/verify consistently."""
    long_pw = "a" * 200
    h = hash_password(long_pw)
    assert verify_password(long_pw, h) is True


def test_verify_password_malformed_hash_returns_false():
    assert verify_password("x", "not-a-bcrypt-hash") is False


def test_access_token_roundtrip():
    token = create_access_token("user-123", "tenant-abc")
    payload = verify_token(token, expected_type="access")
    assert payload.sub == "user-123"
    assert payload.tenant_id == "tenant-abc"
    assert payload.type == "access"


def test_refresh_token_roundtrip():
    token = create_refresh_token("user-123")
    payload = verify_token(token, expected_type="refresh")
    assert payload.sub == "user-123"
    assert payload.type == "refresh"


def test_wrong_token_type_rejected():
    access = create_access_token("u", "t")
    with pytest.raises(TokenError):
        verify_token(access, expected_type="refresh")


def test_tampered_token_rejected():
    token = create_access_token("u", "t")
    tampered = token[:-3] + ("abc" if not token.endswith("abc") else "xyz")
    with pytest.raises(TokenError):
        verify_token(tampered, expected_type="access")


def test_expired_token_rejected(monkeypatch):
    """A token minted already-expired must be rejected."""
    # Build a token whose expiry is in the past by patching the helper.
    token = auth._create_token(
        {"sub": "u", "tenant_id": "t"},
        timedelta(seconds=-10),
        "access",
    )
    with pytest.raises(TokenError):
        verify_token(token, expected_type="access")

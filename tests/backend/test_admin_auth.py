"""Tests for admin authentication (bcrypt, rate limiting, JWT cookies)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import jwt
import pytest

from core.admin.dependencies import (
    _check_admin_rate_limit,
    _validate_password,
    _validate_jwt_cookie,
)


# -- Password validation -----------------------------------------------


class TestValidatePassword:
    def test_bcrypt_hash_valid(self) -> None:
        password = "my-secret-password"
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": hashed, "ADMIN_PASSWORD": ""}):
            assert _validate_password(password) is True

    def test_bcrypt_hash_invalid(self) -> None:
        hashed = bcrypt.hashpw(b"correct-password", bcrypt.gensalt()).decode()
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": hashed, "ADMIN_PASSWORD": ""}):
            assert _validate_password("wrong-password") is False

    def test_plaintext_fallback_valid(self) -> None:
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": "", "ADMIN_PASSWORD": "test123"}):
            assert _validate_password("test123") is True

    def test_plaintext_fallback_invalid(self) -> None:
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": "", "ADMIN_PASSWORD": "test123"}):
            assert _validate_password("wrong") is False

    def test_no_password_configured(self) -> None:
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": "", "ADMIN_PASSWORD": ""}):
            assert _validate_password("anything") is False


# -- JWT cookie validation ---------------------------------------------


class TestJWTCookie:
    def test_valid_jwt(self) -> None:
        secret = "test-jwt-secret"
        from datetime import UTC, datetime, timedelta
        token = jwt.encode(
            {"sub": "admin", "exp": datetime.now(UTC) + timedelta(hours=1)},
            secret, algorithm="HS256",
        )
        with patch.dict(os.environ, {"ADMIN_JWT_SECRET": secret}):
            assert _validate_jwt_cookie(token) is True

    def test_expired_jwt(self) -> None:
        secret = "test-jwt-secret"
        from datetime import UTC, datetime, timedelta
        token = jwt.encode(
            {"sub": "admin", "exp": datetime.now(UTC) - timedelta(hours=1)},
            secret, algorithm="HS256",
        )
        with patch.dict(os.environ, {"ADMIN_JWT_SECRET": secret}):
            assert _validate_jwt_cookie(token) is False

    def test_invalid_jwt(self) -> None:
        with patch.dict(os.environ, {"ADMIN_JWT_SECRET": "real-secret"}):
            assert _validate_jwt_cookie("not-a-jwt") is False

    def test_no_secret_configured(self) -> None:
        with patch.dict(os.environ, {"ADMIN_JWT_SECRET": ""}):
            assert _validate_jwt_cookie("any-token") is False


# -- Rate limiting -----------------------------------------------------


class TestAdminRateLimit:
    async def test_allows_within_limit(self) -> None:
        mock_redis = MagicMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.app.state.services.redis = mock_redis

        # Should not raise
        await _check_admin_rate_limit(mock_request)

    async def test_blocks_over_limit(self) -> None:
        mock_redis = MagicMock()
        mock_redis.incr = AsyncMock(return_value=6)  # Over the limit of 5
        mock_redis.expire = AsyncMock()

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.app.state.services.redis = mock_redis

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await _check_admin_rate_limit(mock_request)
        assert exc_info.value.status_code == 429

    async def test_graceful_without_redis(self) -> None:
        mock_request = MagicMock()
        mock_request.app.state.services.redis = None

        # Should not raise
        await _check_admin_rate_limit(mock_request)

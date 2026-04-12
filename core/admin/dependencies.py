"""Shared dependencies for admin sub-routers.

Replaces the old service-locator pattern (_get_db, _get_llm, etc.)
that used circular imports from core.main. These dependency functions
use request.app.state instead.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

ADMIN_RATE_LIMIT_MAX = 5
ADMIN_RATE_LIMIT_WINDOW = 60  # seconds


async def _check_admin_rate_limit(request: Request) -> None:
    """Rate-limit admin auth attempts: 5 per minute per IP."""
    redis = getattr(getattr(request.app, "state", None), "services", None)
    if redis is not None:
        redis = redis.redis
    if redis is None:
        return

    ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:admin:{ip}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, ADMIN_RATE_LIMIT_WINDOW)
    if current > ADMIN_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Too many auth attempts ({ADMIN_RATE_LIMIT_MAX}/{ADMIN_RATE_LIMIT_WINDOW}s)",
        )


def _validate_password(provided: str) -> bool:
    """Validate admin password against hash or plaintext fallback."""
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
    if password_hash:
        return bcrypt.checkpw(provided.encode(), password_hash.encode())

    # Fallback: plaintext comparison (deprecated)
    plaintext = os.environ.get("ADMIN_PASSWORD", "")
    if not plaintext:
        return False
    logger.warning(
        "Using plaintext ADMIN_PASSWORD — set ADMIN_PASSWORD_HASH (bcrypt) instead"
    )
    return hmac.compare_digest(provided, plaintext)


def _validate_jwt_cookie(token: str) -> bool:
    """Validate a JWT admin session cookie."""
    secret = os.environ.get("ADMIN_JWT_SECRET", "")
    if not secret:
        return False
    try:
        jwt.decode(token, secret, algorithms=["HS256"])
        return True
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return False


async def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    admin_session: str | None = Cookie(default=None),
) -> None:
    """Validate admin auth via JWT cookie, Bearer token, or password."""
    # Try JWT cookie first (set by /api/admin/login) — no rate limit needed
    if admin_session and _validate_jwt_cookie(admin_session):
        return

    # Fall back to Bearer token (password)
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Rate-limit only actual password validation attempts
    await _check_admin_rate_limit(request)

    has_hash = bool(os.environ.get("ADMIN_PASSWORD_HASH", ""))
    has_plain = bool(os.environ.get("ADMIN_PASSWORD", ""))
    if not has_hash and not has_plain:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_PASSWORD not configured on server",
        )

    if not _validate_password(credentials.credentials):
        raise HTTPException(status_code=401, detail="Invalid admin password")


def get_db(request: Request) -> Any:
    """Get database connection from app state."""
    return request.app.state.services.db


def get_llm(request: Request) -> Any:
    """Get LLM client from app state."""
    return request.app.state.services.llm_client


def get_registry(request: Request) -> Any:
    """Get agent registry from app state."""
    return request.app.state.services.agent_registry


def get_redis(request: Request) -> Any:
    """Get Redis client from app state."""
    return request.app.state.services.redis


def get_config_version_repo(request: Request) -> Any:
    """Get config version repo from app state."""
    return request.app.state.services.config_version_repo

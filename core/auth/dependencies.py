"""Public-user auth dependencies (magic-link cookie session)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import jwt
from fastapi import Cookie, HTTPException, Request

from core.auth.jwt_secrets import get_hs256_secret

if TYPE_CHECKING:
    from core.models import User

# RFC 5322 is wildly more permissive than this; tighter regex is fine here
# since this address must also be deliverable via SMTP and we'd rather
# reject obvious junk early.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

USER_RATE_LIMIT_MAX = 5
USER_RATE_LIMIT_WINDOW = 3600  # 1 hour
USER_SESSION_COOKIE = "user_session"
USER_JWT_TTL_DAYS = 30


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


def _get_redis(request: Request):
    services = getattr(getattr(request.app, "state", None), "services", None)
    return services.redis if services is not None else None


def _get_db(request: Request):
    services = getattr(getattr(request.app, "state", None), "services", None)
    return services.db if services is not None else None


async def _check_email_rate_limit(request: Request, email: str) -> None:
    """Enforce max 5 magic-link requests per email per hour."""
    redis = _get_redis(request)
    if redis is None:
        return
    key = f"ratelimit:magic_link:{email.lower()}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, USER_RATE_LIMIT_WINDOW)
    if current > USER_RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many magic-link requests "
                f"({USER_RATE_LIMIT_MAX}/{USER_RATE_LIMIT_WINDOW // 60}min)"
            ),
        )


def _validate_user_jwt(token: str) -> str | None:
    """Return the user_id string from a valid JWT, or None if invalid."""
    secret = get_hs256_secret("AUTH_JWT_SECRET")
    if not secret:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None


async def get_current_user(
    request: Request,
    user_session: str | None = Cookie(default=None),
) -> User:
    """Resolve the authenticated user via the user_session JWT cookie.

    Raises 401 if the cookie is missing, the JWT is invalid, or the user
    no longer exists.
    """
    if not user_session:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id_str = _validate_user_jwt(user_session)
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    import uuid

    from core.repos.user_repo import UserRepo

    db = _get_db(request)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc

    repo = UserRepo(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


async def get_optional_user(
    request: Request,
    user_session: str | None = Cookie(default=None),
) -> User | None:
    """Like get_current_user but returns None instead of raising 401."""
    if not user_session:
        return None
    try:
        return await get_current_user(request, user_session)
    except HTTPException:
        return None

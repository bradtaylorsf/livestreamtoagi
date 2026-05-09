"""Public user auth: magic-link request, verify, logout, /me."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from core.auth.dependencies import (
    USER_JWT_TTL_DAYS,
    USER_SESSION_COOKIE,
    _check_email_rate_limit,
    get_current_user,
    is_valid_email,
)
from core.auth.email import EmailSendError, send_email
from core.models import User
from core.repos.user_repo import MagicLinkTokenRepo, UserRepo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user-auth"])

MAGIC_LINK_TTL_MINUTES = 15


class MagicLinkRequest(BaseModel):
    email: str
    next: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    simulations_submitted: int
    total_cost_spent: str
    created_at: str | None = None
    last_login_at: str | None = None


def _user_to_response(u: User) -> UserResponse:
    return UserResponse(
        id=str(u.id),
        email=u.email,
        simulations_submitted=u.simulations_submitted,
        total_cost_spent=str(u.total_cost_spent),
        created_at=u.created_at.isoformat() if u.created_at else None,
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _safe_relative_redirect(raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    path = raw_path.strip()
    if not path or not path.startswith("/") or path.startswith("//"):
        return None
    if "\\" in path or any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        return None

    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc:
        return None
    return parsed.geturl()


@router.post("/magic-link")
async def request_magic_link(
    body: MagicLinkRequest,
    request: Request,
) -> dict[str, str]:
    """Email a single-use sign-in link to ``body.email``.

    Always returns 200 to avoid leaking whether an account exists. Rate
    limited to 5/hr per email.
    """
    email = (body.email or "").strip().lower()
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Invalid email address")

    await _check_email_rate_limit(request, email)

    services = request.app.state.services
    db = services.db
    repo = MagicLinkTokenRepo(db)

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)
    await repo.create(token_hash, email, expires_at=expires_at)

    base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    link_params = {"token": raw_token}
    next_path = _safe_relative_redirect(body.next)
    if next_path:
        link_params["next"] = next_path
    link = f"{base_url}/api/auth/verify?{urlencode(link_params)}"

    subject = "Your sign-in link for Livestream to AGI"
    body_text = (
        f"Click this link to sign in:\n\n{link}\n\n"
        f"It expires in {MAGIC_LINK_TTL_MINUTES} minutes and can only be used once.\n"
        "If you didn't request this, you can safely ignore the email."
    )

    try:
        await send_email(to=email, subject=subject, body_text=body_text)
    except (EmailSendError, NotImplementedError):
        logger.exception("Failed to send magic-link email to %s", email)
        # Fail closed: signaling the user that delivery succeeded would be
        # misleading. Generic 503 is fine here.
        raise HTTPException(status_code=503, detail="Email delivery failed")  # noqa: B904

    return {"status": "ok"}


@router.get("/verify")
async def verify_magic_link(
    token: str,
    request: Request,
    response: Response,
    next_path: str | None = Query(default=None, alias="next"),
) -> RedirectResponse:
    """Consume a magic-link token, set the session cookie, redirect."""
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    # Check signing secret BEFORE consuming the token. Otherwise a
    # misconfigured deploy burns the user's magic link on every click.
    secret = os.environ.get("AUTH_JWT_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="AUTH_JWT_SECRET not configured — cannot issue session cookie",
        )

    services = request.app.state.services
    db = services.db
    token_repo = MagicLinkTokenRepo(db)
    user_repo = UserRepo(db)

    token_hash = _hash_token(token)
    email = await token_repo.consume(token_hash)
    if email is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    now = datetime.now(UTC)
    user = await user_repo.upsert_on_login(email, login_at=now)

    jwt_token = jwt.encode(
        {"sub": str(user.id), "exp": now + timedelta(days=USER_JWT_TTL_DAYS)},
        secret,
        algorithm="HS256",
    )

    redirect = RedirectResponse(
        url=_safe_relative_redirect(next_path) or "/simulations",
        status_code=303,
    )
    redirect.set_cookie(
        key=USER_SESSION_COOKIE,
        value=jwt_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=USER_JWT_TTL_DAYS * 24 * 3600,
    )
    return redirect


@router.post("/logout")
async def user_logout(response: Response) -> dict[str, str]:
    """Clear the user_session cookie."""
    response.delete_cookie(
        key=USER_SESSION_COOKIE,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"status": "logged_out"}


@router.get("/me")
async def whoami(user: User = Depends(get_current_user)) -> UserResponse:
    """Return the currently-authenticated user (or 401)."""
    return _user_to_response(user)

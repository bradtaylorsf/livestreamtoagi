"""Admin authentication routes (login/logout with JWT cookie)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from core.admin.dependencies import (
    _check_admin_rate_limit,
    _record_failed_auth,
    _validate_password,
)

router = APIRouter(tags=["auth"])

JWT_EXPIRY_HOURS = 24


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def admin_login(
    body: LoginRequest, request: Request, response: Response,
) -> dict[str, str]:
    """Validate password and set an httpOnly JWT session cookie."""
    await _check_admin_rate_limit(request)

    if not _validate_password(body.password):
        await _record_failed_auth(request)
        raise HTTPException(status_code=401, detail="Invalid admin password")

    secret = os.environ.get("ADMIN_JWT_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_JWT_SECRET not configured — cannot issue session cookie",
        )

    token = jwt.encode(
        {"sub": "admin", "exp": datetime.now(UTC) + timedelta(hours=JWT_EXPIRY_HOURS)},
        secret,
        algorithm="HS256",
    )

    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=JWT_EXPIRY_HOURS * 3600,
    )
    return {"status": "authenticated"}


@router.post("/logout")
async def admin_logout(response: Response) -> dict[str, str]:
    """Clear the admin session cookie."""
    response.delete_cookie(
        key="admin_session",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return {"status": "logged_out"}

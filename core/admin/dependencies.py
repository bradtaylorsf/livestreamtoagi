"""Shared dependencies for admin sub-routers.

Replaces the old service-locator pattern (_get_db, _get_llm, etc.)
that used circular imports from core.main. These dependency functions
use request.app.state instead.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer()


async def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> None:
    """Validate the admin password from the Authorization header."""
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_PASSWORD not configured on server",
        )
    if credentials.credentials != password:
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

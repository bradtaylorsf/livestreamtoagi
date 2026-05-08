"""Public user authentication (magic-link email flow).

Mounted at /api/auth — separate from the admin auth namespace
(/api/admin/login, /api/admin/logout) which uses a password + JWT.
"""

from __future__ import annotations

from fastapi import APIRouter

from core.auth.auth_routes import router as _auth_routes

user_auth_api = APIRouter(prefix="/api/auth")
user_auth_api.include_router(_auth_routes)

__all__ = ["user_auth_api"]

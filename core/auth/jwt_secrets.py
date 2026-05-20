"""JWT signing-secret helpers shared by admin and public auth."""

from __future__ import annotations

import os

JWT_HS256_MIN_SECRET_BYTES = 32


def get_hs256_secret(env_name: str) -> str | None:
    """Return a configured HS256 secret only when it meets the minimum strength."""
    secret = os.environ.get(env_name, "")
    if len(secret.encode("utf-8")) < JWT_HS256_MIN_SECRET_BYTES:
        return None
    return secret


def hs256_secret_error(env_name: str) -> str:
    return f"{env_name} must be configured with at least {JWT_HS256_MIN_SECRET_BYTES} bytes"

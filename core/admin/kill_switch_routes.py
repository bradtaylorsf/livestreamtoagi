"""Kill switch admin endpoints.

Provides authenticated endpoints to activate/deactivate the kill switch
via a dedicated API key (KILL_SWITCH_API_KEY), separate from general
admin auth.
"""

from __future__ import annotations

import hmac
import os
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, HTTPException

from core.admin.dependencies import get_redis
from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY

if TYPE_CHECKING:
    from core.redis_client import RedisClient

router = APIRouter(tags=["kill-switch"])

DEFAULT_KILL_SWITCH_TTL = 14400  # 4 hours


def _validate_kill_switch_key(x_kill_switch_key: str = Header(...)) -> str:
    """Validate the kill switch API key from the X-Kill-Switch-Key header."""
    expected = os.environ.get("KILL_SWITCH_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="KILL_SWITCH_API_KEY not configured on server",
        )
    if not hmac.compare_digest(x_kill_switch_key, expected):
        raise HTTPException(status_code=403, detail="Invalid kill switch key")
    return x_kill_switch_key


@router.post("/kill")
async def activate_kill_switch(
    redis: RedisClient = Depends(get_redis),
    _key: str = Depends(_validate_kill_switch_key),
    ttl: int = DEFAULT_KILL_SWITCH_TTL,
) -> dict[str, str | int]:
    """Activate the kill switch with a configurable TTL (default 4 hours)."""
    await redis.set(KILL_SWITCH_KEY, KILL_SWITCH_ACTIVE_VALUE, ex=ttl)
    return {"status": "active", "ttl_seconds": ttl}


@router.delete("/kill")
async def deactivate_kill_switch(
    redis: RedisClient = Depends(get_redis),
    _key: str = Depends(_validate_kill_switch_key),
) -> dict[str, str]:
    """Deactivate the kill switch."""
    await redis.delete(KILL_SWITCH_KEY)
    return {"status": "deactivated"}

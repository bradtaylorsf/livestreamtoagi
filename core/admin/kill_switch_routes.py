"""Kill switch admin endpoints.

Provides authenticated endpoints to activate/deactivate the kill switch
via a dedicated API key (KILL_SWITCH_API_KEY), separate from general
admin auth.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException

from core.admin.dependencies import get_redis

if TYPE_CHECKING:
    from core.redis_client import RedisClient

router = APIRouter(tags=["kill-switch"])
logger = logging.getLogger(__name__)

DEFAULT_KILL_SWITCH_TTL = 14400  # 4 hours


async def _send_activation_alert(ttl: int) -> None:
    try:
        from core.notifications.spend_kill_alerts import send_kill_switch_alert

        await send_kill_switch_alert(
            source="api",
            ttl_seconds=ttl,
            actor="kill_switch_api_key",
        )
    except Exception:
        logger.exception("Kill switch activated, but notification alert failed")


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
    background_tasks: BackgroundTasks,
    redis: RedisClient = Depends(get_redis),
    _key: str = Depends(_validate_kill_switch_key),
    ttl: int = DEFAULT_KILL_SWITCH_TTL,
) -> dict[str, str | int]:
    """Activate the kill switch with a configurable TTL (default 4 hours)."""
    await redis.set("kill_switch", "active", ex=ttl)
    background_tasks.add_task(_send_activation_alert, ttl)
    return {"status": "active", "ttl_seconds": ttl}


@router.delete("/kill")
async def deactivate_kill_switch(
    redis: RedisClient = Depends(get_redis),
    _key: str = Depends(_validate_kill_switch_key),
) -> dict[str, str]:
    """Deactivate the kill switch."""
    await redis.delete("kill_switch")
    return {"status": "deactivated"}

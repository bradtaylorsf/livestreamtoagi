"""get_audience_status tool — viewer count, chat, polls from cached Twitch data."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from .base import BaseTool

if TYPE_CHECKING:
    from core.redis_client import RedisClient

logger = logging.getLogger(__name__)


class GetAudienceStatusTool(BaseTool):
    """Get current viewer count, recent chat highlights, active polls."""

    name = "get_audience_status"
    description = "Get current viewer count, recent chat highlights, active polls"
    parameters = {}

    def __init__(self, redis_client: RedisClient) -> None:
        self._redis = redis_client

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        viewer_count_raw = await self._redis.get("audience:viewer_count")
        chat_raw = await self._redis.get("audience:recent_chat")
        polls_raw = await self._redis.get("audience:active_polls")

        return {
            "viewer_count": _parse_int(viewer_count_raw, 0),
            "recent_chat_messages": _parse_json(chat_raw, []),
            "active_polls": _parse_json(polls_raw, []),
        }


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _parse_json(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse Redis value as JSON: %s", raw[:100] if raw else raw)
        return default

"""Base tool interface for CrewAI-compatible agent tools."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class that all agent tools must implement.

    Follows the CrewAI tool interface pattern: name, description,
    parameters dict, and async execute() method.
    """

    name: str
    description: str
    parameters: dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool with the given parameters and return a result dict."""


def parse_json(raw: str | None, default: Any) -> Any:
    """Parse a JSON string, returning default on failure."""
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse Redis value as JSON: %s", raw[:100] if raw else raw)
        return default

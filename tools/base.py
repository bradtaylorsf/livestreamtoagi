"""Base tool interface for CrewAI-compatible agent tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


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

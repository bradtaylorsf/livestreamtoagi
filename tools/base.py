"""Base tool interface for CrewAI-compatible agent tools."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from core.event_bus import EventBus
    from core.repos.artifact_repo import ArtifactRepo

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class that all agent tools must implement.

    Follows the CrewAI tool interface pattern: name, description,
    parameters dict, and async execute() method.
    """

    name: str
    description: str
    parameters: dict[str, Any]

    artifact_repo: ArtifactRepo | None = None
    event_bus: EventBus | None = None

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool with the given parameters and return a result dict."""

    async def run(
        self,
        *,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the tool and persist the result as an artifact (async, non-blocking)."""
        from core.models import ARTIFACT_TYPE_MAP, PENDING_APPROVAL_TOOLS, ArtifactCreate

        start = time.monotonic()
        status = "executed"
        _error_msg: str | None = None
        try:
            result = await self.execute(**kwargs)
        except Exception as exc:
            status = "failed"
            _error_msg = str(exc)
            raise
        else:
            if self.name in PENDING_APPROVAL_TOOLS:
                status = "pending_approval"
            elif isinstance(result, dict) and result.get("simulated"):
                status = "simulated"
            return result
        finally:
            if self.artifact_repo is not None:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                artifact_type = ARTIFACT_TYPE_MAP.get(self.name, self.name)
                meta: dict[str, Any] = {"execution_time_ms": elapsed_ms}

                tool_output: dict[str, Any] | None
                if status == "failed":
                    tool_output = {"error": _error_msg} if _error_msg else None
                else:
                    tool_output = result  # type: ignore[possibly-undefined]
                    # Enrich metadata for code execution
                    if self.name == "execute_code" and tool_output is not None:
                        for key in ("stdout", "stderr", "exit_code"):
                            if key in tool_output:
                                meta[key] = tool_output[key]

                artifact = ArtifactCreate(
                    simulation_id=simulation_id,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    tool_name=self.name,
                    tool_input=kwargs if kwargs else None,
                    tool_output=tool_output,
                    artifact_type=artifact_type,
                    status=status,
                    metadata=meta,
                )
                asyncio.create_task(_save_artifact(self.artifact_repo, artifact))

                if self.event_bus is not None:
                    from core.event_bus import EventType

                    asyncio.create_task(
                        self.event_bus.emit(
                            EventType.ARTIFACT_CREATED,
                            {
                                "agent_id": agent_id,
                                "tool_name": self.name,
                                "simulation_id": str(simulation_id) if simulation_id else None,
                            },
                        )
                    )


async def _save_artifact(repo: ArtifactRepo, artifact: Any) -> None:
    """Fire-and-forget artifact persistence."""
    try:
        await repo.save_artifact(artifact)
    except Exception:
        logger.exception(
            "Failed to persist artifact for tool=%s agent=%s",
            artifact.tool_name,
            artifact.agent_id,
        )


def parse_json(raw: str | None, default: Any) -> Any:
    """Parse a JSON string, returning default on failure."""
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse Redis value as JSON: %s", raw[:100] if raw else raw)
        return default

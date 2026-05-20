"""Bridge handler for code execution.

The bridge does not introduce a second sandbox. ``code.execute`` is a thin
adapter over :class:`tools.code_execution.ExecuteCodeTool`, which owns agent
authorization, Docker/gVisor sandbox configuration, timeout clamping, cleanup,
and event emission.
"""

from __future__ import annotations

import logging
from typing import Any

from core.bridge.contract import BridgeRequest, CodeExecuteRequest
from core.llm_client import agent_cost_context
from tools.code_execution import ExecuteCodeTool

logger = logging.getLogger(__name__)


async def handle_code_execute(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Run code through the existing sandbox-backed tool.

    ``ExecuteCodeTool`` returns a contract-valid ``{"status": "error", ...}``
    dict for sandbox failures it can observe, but it acquires its Docker client
    *outside* that internal guard: when no client is injected and the daemon is
    unreachable, ``docker.from_env()`` raises. Every other bridge dispatch path
    degrades to an ``ok=false``/error payload rather than an uncaught exception
    that would crash the shared WebSocket loop (which only catches
    ``WebSocketDisconnect``), so this adapter must do the same — it converts any
    infrastructure failure into the same error shape the tool already uses.
    """
    payload = CodeExecuteRequest.model_validate(env.payload)
    kwargs: dict[str, Any] = {"language": payload.language, "code": payload.code}
    if payload.timeout is not None:
        kwargs["timeout"] = payload.timeout
    try:
        tool = ExecuteCodeTool(
            event_bus=services.event_bus,
            agent_id=env.agent_id,
            docker_client=getattr(services, "docker_client", None),
        )
        with agent_cost_context(env.agent_id):
            return await tool.execute(**kwargs)
    except Exception as exc:  # noqa: BLE001 — fail-closed to a contract-valid frame
        logger.warning(
            "code.execute failed for agent %s: %s: %s",
            env.agent_id,
            type(exc).__name__,
            exc,
        )
        return {
            "status": "error",
            "reason": f"sandbox unavailable: {type(exc).__name__}",
        }

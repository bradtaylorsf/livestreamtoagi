"""Bridge handler for code execution.

The bridge does not introduce a second sandbox. ``code.execute`` is a thin
adapter over :class:`tools.code_execution.ExecuteCodeTool`, which owns agent
authorization, Docker/gVisor sandbox configuration, timeout clamping, cleanup,
and event emission.
"""

from __future__ import annotations

from typing import Any

from core.bridge.contract import BridgeRequest, CodeExecuteRequest
from tools.code_execution import ExecuteCodeTool


async def handle_code_execute(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Run code through the existing sandbox-backed tool."""
    payload = CodeExecuteRequest.model_validate(env.payload)
    tool = ExecuteCodeTool(
        event_bus=services.event_bus,
        agent_id=env.agent_id,
        docker_client=getattr(services, "docker_client", None),
    )
    kwargs: dict[str, Any] = {"language": payload.language, "code": payload.code}
    if payload.timeout is not None:
        kwargs["timeout"] = payload.timeout
    return await tool.execute(**kwargs)

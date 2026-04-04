"""Shared tool registration and execution for ConversationEngine and CLI scripts.

Extracts tool schema conversion and execution logic so both
ConversationEngine and test_agent.py share the same code paths.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from core.bootstrap import Services
    from tools.base import BaseTool

logger = logging.getLogger(__name__)

# Maximum tool-call rounds before forcing a text response
MAX_TOOL_ROUNDS = 5


def build_agent_tools(agent_id: str, services: Services) -> dict[str, BaseTool]:
    """Build a tool registry for a specific agent, returning {name: tool_instance}.

    Uses the shared tool factories from tools/__init__.py so both
    ConversationEngine and interactive scripts get identical tool sets.
    """
    from tools import ToolRegistry, get_core_tools, get_memory_tools

    registry = ToolRegistry()

    core_tools = get_core_tools(
        event_bus=services.event_bus,
        redis_client=services.redis,
        agent_id=agent_id,
        overseer=services.overseer,
        world_repo=services.world_repo,
        cost_repo=services.cost_repo,
        llm_client=services.llm_client,
        memory_repo=services.memory_repo,
        artifact_repo=services.artifact_repo,
    )
    for tool in core_tools:
        registry.register(tool)

    core_memory = services.core_memory
    recall_memory = services.recall_memory
    archival_memory = services.archival_memory
    if all([core_memory, recall_memory, archival_memory]):
        mem_tools = get_memory_tools(
            recall_manager=recall_memory,
            archival_manager=archival_memory,
            core_manager=core_memory,
            agent_id=agent_id,
            artifact_repo=services.artifact_repo,
        )
        for tool in mem_tools:
            registry.register(tool)

    return registry.all()


def tools_to_openai_schema(tools: dict[str, BaseTool]) -> list[dict[str, Any]]:
    """Convert BaseTool instances to OpenAI function-calling tool definitions."""
    schemas: list[dict[str, Any]] = []
    for name, tool in tools.items():
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param_name, param_def in tool.parameters.items():
            prop: dict[str, Any] = {"type": param_def.get("type", "string")}
            if "description" in param_def:
                prop["description"] = param_def["description"]
            if "items" in param_def:
                prop["items"] = param_def["items"]
            if "enum" in param_def:
                prop["enum"] = param_def["enum"]
            properties[param_name] = prop
            # Treat all params as required unless marked optional
            if not param_def.get("optional", False):
                required.append(param_name)

        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
    return schemas


async def execute_tool_calls(
    tool_calls: list,
    tools: dict[str, BaseTool],
    agent_id: str,
    *,
    simulation_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> list[dict[str, str]]:
    """Execute tool calls and return tool result messages for the LLM."""
    results: list[dict[str, str]] = []
    for tc in tool_calls:
        tool = tools.get(tc.name)
        if tool is None:
            result_content = json.dumps(
                {"status": "error", "reason": f"Unknown tool: {tc.name}"}
            )
        else:
            try:
                logger.debug("Executing tool %s for %s", tc.name, agent_id)
                result = await tool.run(
                    agent_id=agent_id,
                    simulation_id=simulation_id,
                    conversation_id=conversation_id,
                    **tc.arguments,
                )
                result_content = json.dumps(result, default=str)
            except Exception as exc:
                logger.warning("Tool %s failed for %s: %s", tc.name, agent_id, exc)
                result_content = json.dumps(
                    {"status": "error", "reason": str(exc)}
                )

        results.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result_content,
        })
    return results

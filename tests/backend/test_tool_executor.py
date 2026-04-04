"""Tests for core.tool_executor — shared tool registration and execution."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from core.models import ToolCall
from core.tool_executor import (
    build_agent_tools,
    execute_tool_calls,
    tools_to_openai_schema,
)

# ── Helpers ───────────────────────────────────────────────────────


def _make_tool(name: str = "test_tool", description: str = "A test tool") -> MagicMock:
    """Create a mock BaseTool instance."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.parameters = {
        "query": {"type": "string", "description": "Search query"},
        "limit": {"type": "integer", "description": "Max results", "optional": True},
    }
    tool.run = AsyncMock(return_value={"status": "ok", "data": "result"})
    return tool


def _make_tool_call(
    name: str = "test_tool",
    arguments: dict | None = None,
    tc_id: str | None = None,
) -> ToolCall:
    return ToolCall(
        id=tc_id or f"call_{uuid.uuid4().hex[:8]}",
        name=name,
        arguments=arguments or {"query": "hello"},
    )


# ── Test: tools_to_openai_schema ──────────────────────────────────


class TestToolsToOpenaiSchema:
    def test_converts_single_tool(self) -> None:
        tool = _make_tool()
        schemas = tools_to_openai_schema({"test_tool": tool})

        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test_tool"
        assert schema["function"]["description"] == "A test tool"
        assert "query" in schema["function"]["parameters"]["properties"]

    def test_required_vs_optional_params(self) -> None:
        tool = _make_tool()
        schemas = tools_to_openai_schema({"test_tool": tool})

        required = schemas[0]["function"]["parameters"]["required"]
        assert "query" in required
        assert "limit" not in required  # marked optional

    def test_empty_tools_returns_empty_list(self) -> None:
        assert tools_to_openai_schema({}) == []

    def test_multiple_tools(self) -> None:
        tools = {
            "tool_a": _make_tool("tool_a", "Tool A"),
            "tool_b": _make_tool("tool_b", "Tool B"),
        }
        schemas = tools_to_openai_schema(tools)
        assert len(schemas) == 2
        names = {s["function"]["name"] for s in schemas}
        assert names == {"tool_a", "tool_b"}

    def test_enum_and_items_propagated(self) -> None:
        tool = _make_tool()
        tool.parameters = {
            "lang": {
                "type": "string",
                "description": "Language",
                "enum": ["python", "javascript"],
            },
            "tags": {
                "type": "array",
                "description": "Tags",
                "items": {"type": "string"},
            },
        }
        schemas = tools_to_openai_schema({"tool": tool})
        props = schemas[0]["function"]["parameters"]["properties"]
        assert props["lang"]["enum"] == ["python", "javascript"]
        assert props["tags"]["items"] == {"type": "string"}


# ── Test: execute_tool_calls ──────────────────────────────────────


class TestExecuteToolCalls:
    async def test_executes_known_tool(self) -> None:
        tool = _make_tool()
        tc = _make_tool_call()
        results = await execute_tool_calls([tc], {"test_tool": tool}, "rex")

        assert len(results) == 1
        assert results[0]["role"] == "tool"
        assert results[0]["tool_call_id"] == tc.id
        data = json.loads(results[0]["content"])
        assert data["status"] == "ok"
        tool.run.assert_awaited_once()

    async def test_unknown_tool_returns_error(self) -> None:
        tc = _make_tool_call(name="nonexistent")
        results = await execute_tool_calls([tc], {}, "rex")

        data = json.loads(results[0]["content"])
        assert data["status"] == "error"
        assert "Unknown tool" in data["reason"]

    async def test_tool_exception_returns_error(self) -> None:
        tool = _make_tool()
        tool.run = AsyncMock(side_effect=RuntimeError("Tool broke"))
        tc = _make_tool_call()
        results = await execute_tool_calls([tc], {"test_tool": tool}, "rex")

        data = json.loads(results[0]["content"])
        assert data["status"] == "error"
        assert "Tool broke" in data["reason"]

    async def test_passes_simulation_and_conversation_ids(self) -> None:
        tool = _make_tool()
        tc = _make_tool_call()
        sim_id = uuid.uuid4()
        conv_id = uuid.uuid4()

        await execute_tool_calls(
            [tc],
            {"test_tool": tool},
            "rex",
            simulation_id=sim_id,
            conversation_id=conv_id,
        )

        call_kwargs = tool.run.call_args[1]
        assert call_kwargs["simulation_id"] == sim_id
        assert call_kwargs["conversation_id"] == conv_id

    async def test_multiple_tool_calls(self) -> None:
        tool_a = _make_tool("tool_a")
        tool_b = _make_tool("tool_b")
        tc_a = _make_tool_call("tool_a")
        tc_b = _make_tool_call("tool_b")

        results = await execute_tool_calls(
            [tc_a, tc_b],
            {"tool_a": tool_a, "tool_b": tool_b},
            "rex",
        )

        assert len(results) == 2
        tool_a.run.assert_awaited_once()
        tool_b.run.assert_awaited_once()


# ── Test: build_agent_tools ───────────────────────────────────────


class TestBuildAgentTools:
    def test_builds_tools_with_services(self) -> None:
        """build_agent_tools calls get_core_tools and get_memory_tools."""
        mock_services = MagicMock()
        mock_services.core_memory = MagicMock()
        mock_services.recall_memory = MagicMock()
        mock_services.archival_memory = MagicMock()

        mock_tool = _make_tool("send_message")

        with (
            patch("tools.get_core_tools", return_value=[mock_tool]) as mock_core,
            patch("tools.get_memory_tools", return_value=[]) as mock_mem,
        ):
            tools = build_agent_tools("rex", mock_services)

        mock_core.assert_called_once()
        mock_mem.assert_called_once()
        assert "send_message" in tools

    def test_skips_memory_tools_when_missing(self) -> None:
        """If core_memory/recall/archival are None, memory tools are skipped."""
        mock_services = MagicMock()
        mock_services.core_memory = None
        mock_services.recall_memory = None
        mock_services.archival_memory = None

        mock_tool = _make_tool("send_message")

        with (
            patch("tools.get_core_tools", return_value=[mock_tool]),
            patch("tools.get_memory_tools") as mock_mem,
        ):
            tools = build_agent_tools("rex", mock_services)

        mock_mem.assert_not_called()
        assert "send_message" in tools

"""Tests for simulation-mode tool stubs (Issue #214)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.stubs import StubExecuteCodeTool, StubGenerateTilemapTool


# ── StubExecuteCodeTool ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_stub_execute_code_returns_ok():
    """Stub should return a successful result with simulated flag."""
    tool = StubExecuteCodeTool(agent_id="rex")
    result = await tool.execute(language="python", code="print('hello')")
    assert result["status"] == "ok"
    assert result["simulated"] is True
    assert "stdout" in result
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_stub_execute_code_rejects_unauthorized():
    """Stub should reject agents not in ALLOWED_AGENTS."""
    tool = StubExecuteCodeTool(agent_id="pixel")
    result = await tool.execute(language="python", code="print('hello')")
    assert result["status"] == "rejected"
    assert "not authorized" in result["reason"]


@pytest.mark.asyncio
async def test_stub_execute_code_rejects_bad_language():
    """Stub should reject unsupported languages."""
    tool = StubExecuteCodeTool(agent_id="rex")
    result = await tool.execute(language="rust", code="fn main() {}")
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_stub_execute_code_varies_responses():
    """Stub should rotate through different response fixtures."""
    tool = StubExecuteCodeTool(agent_id="rex")
    # Reset class counter
    StubExecuteCodeTool._call_index = 0
    results = []
    for _ in range(3):
        r = await tool.execute(language="python", code="x")
        results.append(r["stdout"])
    # At least 2 unique outputs from 3 calls
    assert len(set(results)) >= 2


# ���─ StubGenerateTilemapTool ─────────────────────────────────────


@pytest.mark.asyncio
async def test_stub_tilemap_returns_ok():
    """Stub should return a successful result with simulated flag."""
    tool = StubGenerateTilemapTool(agent_id="rex")
    result = await tool.execute(name="library", code="x", description="test")
    assert result["status"] == "ok"
    assert result["simulated"] is True
    assert "chunk_id" in result
    assert "preview" in result
    assert result["preview"]["name"] == "library"


@pytest.mark.asyncio
async def test_stub_tilemap_rejects_unauthorized():
    """Stub should reject agents not in ALLOWED_AGENTS."""
    tool = StubGenerateTilemapTool(agent_id="grok")
    result = await tool.execute(name="park", code="x", description="test")
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_stub_tilemap_requires_name():
    """Stub should reject empty name."""
    tool = StubGenerateTilemapTool(agent_id="rex")
    result = await tool.execute(name="", code="x", description="test")
    assert result["status"] == "rejected"


# ── get_core_tools integration ──────────────────────────────────


def test_get_core_tools_simulation_mode():
    """simulation_mode=True should use stub tools instead of real ones."""
    from tools import get_core_tools

    event_bus = AsyncMock()
    redis_client = AsyncMock()

    tools = get_core_tools(
        event_bus=event_bus,
        redis_client=redis_client,
        agent_id="rex",
        simulation_mode=True,
    )
    tool_names = [t.name for t in tools]
    assert "execute_code" in tool_names
    assert "generate_tilemap" in tool_names

    exec_tool = next(t for t in tools if t.name == "execute_code")
    assert isinstance(exec_tool, StubExecuteCodeTool)


def test_get_core_tools_production_mode():
    """simulation_mode=False should use real tools."""
    from tools import get_core_tools
    from tools.code_execution import ExecuteCodeTool

    event_bus = AsyncMock()
    redis_client = AsyncMock()

    tools = get_core_tools(
        event_bus=event_bus,
        redis_client=redis_client,
        agent_id="rex",
        simulation_mode=False,
    )
    exec_tool = next(t for t in tools if t.name == "execute_code")
    assert isinstance(exec_tool, ExecuteCodeTool)


# ── Agent authorization filtering ───────────────────────────────


def test_get_core_tools_filters_unauthorized():
    """Agents should not see tools they're not authorized to use."""
    from tools import get_core_tools

    event_bus = AsyncMock()
    redis_client = AsyncMock()

    # Pixel should NOT see execute_code or generate_tilemap
    tools = get_core_tools(
        event_bus=event_bus,
        redis_client=redis_client,
        agent_id="pixel",
        simulation_mode=True,
    )
    tool_names = [t.name for t in tools]
    assert "execute_code" not in tool_names
    assert "generate_tilemap" not in tool_names
    # Pixel should still see general tools
    assert "get_world_state" in tool_names
    assert "get_audience_status" in tool_names


def test_get_core_tools_rex_sees_code_tools():
    """Rex should see execute_code and generate_tilemap."""
    from tools import get_core_tools

    event_bus = AsyncMock()
    redis_client = AsyncMock()

    tools = get_core_tools(
        event_bus=event_bus,
        redis_client=redis_client,
        agent_id="rex",
        simulation_mode=True,
    )
    tool_names = [t.name for t in tools]
    assert "execute_code" in tool_names
    assert "generate_tilemap" in tool_names


# ── BaseTool error persistence ──────────────────────────────────


@pytest.mark.asyncio
async def test_base_tool_persists_error():
    """Failed tool execution should persist error message, not null."""
    import asyncio

    from tools.base import BaseTool

    class FailingTool(BaseTool):
        name = "failing_tool"
        description = "A tool that always fails"
        parameters: dict = {}

        async def execute(self, **kwargs):
            raise RuntimeError("Docker connection refused")

    tool = FailingTool()
    mock_repo = AsyncMock()
    tool.artifact_repo = mock_repo

    with pytest.raises(RuntimeError):
        await tool.run(agent_id="rex")

    # Let fire-and-forget tasks complete
    await asyncio.sleep(0.05)

    # Check that the artifact was saved with error info
    mock_repo.save_artifact.assert_called_once()
    artifact = mock_repo.save_artifact.call_args[0][0]
    assert artifact.status == "failed"
    assert artifact.tool_output is not None
    assert "Docker connection refused" in artifact.tool_output["error"]

"""Tests for tilemap generation tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event_bus import EventType
from core.models import WorldChunk
from tools.tilemap_gen import GenerateTilemapTool

# --- Valid chunk JSON for reuse across tests ---

VALID_CHUNK = {
    "name": "library",
    "size": {"width": 5, "height": 5},
    "tiles": [[1, 1, 1, 1, 1]] * 5,
    "objects": [{"type": "bookshelf", "x": 2, "y": 3}],
    "built_by": "rex",
    "description": "A cozy library",
}


def _make_exec_result(stdout: str = "", exit_code: int = 0, status: str = "ok") -> dict:
    return {"status": status, "stdout": stdout, "stderr": "", "exit_code": exit_code}


def _make_world_chunk(chunk_id: int = 42) -> WorldChunk:
    return WorldChunk(
        id=chunk_id,
        name="library",
        x_offset=0,
        y_offset=0,
        width=5,
        height=5,
        tile_data={"tiles": VALID_CHUNK["tiles"]},
        objects=VALID_CHUNK["objects"],
        built_by=["rex"],
        description="A cozy library",
    )


# --- Fixtures ---


@pytest.fixture
def event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.emit = AsyncMock(
        return_value={"event_id": "evt-100", "event_type": "world_expansion", "data": {}}
    )
    return bus


@pytest.fixture
def execute_code_tool() -> AsyncMock:
    tool = AsyncMock()
    tool.execute = AsyncMock(return_value=_make_exec_result(json.dumps(VALID_CHUNK)))
    return tool


@pytest.fixture
def world_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.create_chunk = AsyncMock(return_value=_make_world_chunk())
    return repo


@pytest.fixture
def tool(event_bus: AsyncMock, execute_code_tool: AsyncMock, world_repo: AsyncMock) -> GenerateTilemapTool:
    return GenerateTilemapTool(
        event_bus=event_bus,
        agent_id="rex",
        execute_code_tool=execute_code_tool,
        world_repo=world_repo,
    )


@pytest.fixture
def unauthorized_tool(event_bus: AsyncMock, execute_code_tool: AsyncMock, world_repo: AsyncMock) -> GenerateTilemapTool:
    return GenerateTilemapTool(
        event_bus=event_bus,
        agent_id="aurora",
        execute_code_tool=execute_code_tool,
        world_repo=world_repo,
    )


# --- Authorization ---


class TestAuthorization:
    async def test_allowed_agents(self) -> None:
        assert GenerateTilemapTool.ALLOWED_AGENTS == frozenset({"rex", "fork"})

    async def test_unauthorized_agent_rejected(
        self, unauthorized_tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        result = await unauthorized_tool.execute(name="test", code="print(1)", description="test")
        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]
        execute_code_tool.execute.assert_not_called()

    async def test_each_allowed_agent(
        self, event_bus: AsyncMock, execute_code_tool: AsyncMock, world_repo: AsyncMock
    ) -> None:
        for agent in ("rex", "fork"):
            t = GenerateTilemapTool(
                event_bus=event_bus,
                agent_id=agent,
                execute_code_tool=execute_code_tool,
                world_repo=world_repo,
            )
            result = await t.execute(name="room", code="print('{}')", description="a room")
            assert result["status"] == "ok"


# --- Validation ---


class TestValidation:
    async def test_missing_name(self, tool: GenerateTilemapTool) -> None:
        result = await tool.execute(name="", code="x", description="d")
        assert result["status"] == "rejected"
        assert "name" in result["reason"]

    async def test_missing_code(self, tool: GenerateTilemapTool) -> None:
        result = await tool.execute(name="n", code="", description="d")
        assert result["status"] == "rejected"
        assert "code" in result["reason"]

    async def test_missing_description(self, tool: GenerateTilemapTool) -> None:
        result = await tool.execute(name="n", code="x", description="")
        assert result["status"] == "rejected"
        assert "description" in result["reason"]


# --- Execution ---


class TestExecution:
    async def test_valid_chunk_accepted_and_stored(
        self, tool: GenerateTilemapTool, world_repo: AsyncMock
    ) -> None:
        result = await tool.execute(name="library", code="print(json)", description="A cozy library")
        assert result["status"] == "ok"
        assert result["chunk_id"] == 42
        assert result["preview"]["name"] == "library"
        assert result["preview"]["width"] == 5
        assert result["preview"]["height"] == 5
        assert result["preview"]["object_count"] == 1
        assert result["preview"]["tile_count"] == 25
        world_repo.create_chunk.assert_awaited_once()

    async def test_invalid_json_rejected(
        self, tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        execute_code_tool.execute.return_value = _make_exec_result("not json at all")
        result = await tool.execute(name="bad", code="print('x')", description="bad chunk")
        assert result["status"] == "error"
        assert "Invalid JSON" in result["reason"]

    async def test_missing_required_fields_rejected(
        self, tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        incomplete = {"name": "test", "size": {"width": 3, "height": 3}}
        execute_code_tool.execute.return_value = _make_exec_result(json.dumps(incomplete))
        result = await tool.execute(name="test", code="print(x)", description="test")
        assert result["status"] == "error"
        assert "Missing required fields" in result["reason"]

    async def test_invalid_size_rejected(
        self, tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        bad = {**VALID_CHUNK, "size": "not-a-dict"}
        execute_code_tool.execute.return_value = _make_exec_result(json.dumps(bad))
        result = await tool.execute(name="test", code="x", description="test")
        assert result["status"] == "error"
        assert "size" in result["reason"]

    async def test_invalid_tiles_rejected(
        self, tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        bad = {**VALID_CHUNK, "tiles": "not-a-list"}
        execute_code_tool.execute.return_value = _make_exec_result(json.dumps(bad))
        result = await tool.execute(name="test", code="x", description="test")
        assert result["status"] == "error"
        assert "tiles" in result["reason"]

    async def test_invalid_objects_rejected(
        self, tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        bad = {**VALID_CHUNK, "objects": "not-a-list"}
        execute_code_tool.execute.return_value = _make_exec_result(json.dumps(bad))
        result = await tool.execute(name="test", code="x", description="test")
        assert result["status"] == "error"
        assert "objects" in result["reason"]

    async def test_object_missing_fields_rejected(
        self, tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        bad = {**VALID_CHUNK, "objects": [{"type": "chair"}]}
        execute_code_tool.execute.return_value = _make_exec_result(json.dumps(bad))
        result = await tool.execute(name="test", code="x", description="test")
        assert result["status"] == "error"
        assert "type" in result["reason"] and "x" in result["reason"] and "y" in result["reason"]

    async def test_execution_failure_propagated(
        self, tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        execute_code_tool.execute.return_value = {
            "status": "ok", "stdout": "", "stderr": "SyntaxError: invalid syntax", "exit_code": 1
        }
        result = await tool.execute(name="test", code="bad code", description="test")
        assert result["status"] == "error"
        assert "SyntaxError" in result["reason"]

    async def test_sandbox_error_propagated(
        self, tool: GenerateTilemapTool, execute_code_tool: AsyncMock
    ) -> None:
        execute_code_tool.execute.return_value = {
            "status": "error", "reason": "Execution timed out after 30s"
        }
        result = await tool.execute(name="test", code="while True: pass", description="test")
        assert result["status"] == "error"
        assert "timed out" in result["reason"]


# --- Events ---


class TestEvents:
    async def test_world_expansion_emitted_on_success(
        self, tool: GenerateTilemapTool, event_bus: AsyncMock
    ) -> None:
        await tool.execute(name="library", code="print(json)", description="A cozy library")
        event_bus.emit.assert_awaited_once_with(
            EventType.WORLD_EXPANSION,
            {
                "chunk_id": 42,
                "chunk_name": "library",
                "agent_id": "rex",
            },
        )

    async def test_no_event_on_failure(
        self, tool: GenerateTilemapTool, event_bus: AsyncMock, execute_code_tool: AsyncMock
    ) -> None:
        execute_code_tool.execute.return_value = _make_exec_result("not json")
        await tool.execute(name="bad", code="x", description="bad")
        event_bus.emit.assert_not_awaited()


# --- Integration (end-to-end with mocked sandbox) ---


class TestIntegration:
    async def test_5x5_room_chunk_end_to_end(
        self, event_bus: AsyncMock, world_repo: AsyncMock
    ) -> None:
        """Simulate a full flow: code execution → JSON parse → store → event."""
        room_json = {
            "name": "small_room",
            "size": {"width": 5, "height": 5},
            "tiles": [
                [2, 2, 2, 2, 2],
                [2, 0, 0, 0, 2],
                [2, 0, 0, 0, 2],
                [2, 0, 0, 0, 2],
                [2, 2, 1, 2, 2],
            ],
            "objects": [
                {"type": "torch", "x": 1, "y": 1},
                {"type": "door", "x": 2, "y": 4},
            ],
            "built_by": "rex",
            "description": "A small 5x5 room with walls and a door",
        }

        stored_chunk = WorldChunk(
            id=99,
            name="small_room",
            x_offset=0,
            y_offset=0,
            width=5,
            height=5,
            tile_data={"tiles": room_json["tiles"]},
            objects=room_json["objects"],
            built_by=["rex"],
            description="A small 5x5 room",
        )

        exec_tool = AsyncMock()
        exec_tool.execute = AsyncMock(return_value=_make_exec_result(json.dumps(room_json)))
        world_repo.create_chunk = AsyncMock(return_value=stored_chunk)

        tool = GenerateTilemapTool(
            event_bus=event_bus,
            agent_id="rex",
            execute_code_tool=exec_tool,
            world_repo=world_repo,
        )

        code = """\
import json
room = {
    "name": "small_room",
    "size": {"width": 5, "height": 5},
    "tiles": [[2,2,2,2,2],[2,0,0,0,2],[2,0,0,0,2],[2,0,0,0,2],[2,2,1,2,2]],
    "objects": [{"type":"torch","x":1,"y":1},{"type":"door","x":2,"y":4}],
    "built_by": "rex",
    "description": "A small 5x5 room with walls and a door"
}
print(json.dumps(room))
"""

        result = await tool.execute(name="small_room", code=code, description="A small 5x5 room")

        # Verify full result
        assert result["status"] == "ok"
        assert result["chunk_id"] == 99
        assert result["preview"]["name"] == "small_room"
        assert result["preview"]["width"] == 5
        assert result["preview"]["height"] == 5
        assert result["preview"]["object_count"] == 2
        assert result["preview"]["tile_count"] == 25

        # Verify code was sent to sandbox
        exec_tool.execute.assert_awaited_once()
        call_kwargs = exec_tool.execute.call_args.kwargs
        assert call_kwargs["language"] == "python"

        # Verify chunk was stored
        world_repo.create_chunk.assert_awaited_once()
        stored = world_repo.create_chunk.call_args.args[0]
        assert stored.name == "small_room"
        assert stored.width == 5
        assert stored.height == 5
        assert stored.built_by == ["rex"]

        # Verify event emitted
        event_bus.emit.assert_awaited_once_with(
            EventType.WORLD_EXPANSION,
            {"chunk_id": 99, "chunk_name": "small_room", "agent_id": "rex"},
        )

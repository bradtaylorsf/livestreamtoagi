"""Tilemap generation tool — execute code in sandbox and register world chunks."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from core.event_bus import EventType
from core.models import WorldChunkCreate

from .base import BaseTool

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.repos.world_repo import WorldRepo

    from .code_execution import ExecuteCodeTool

logger = logging.getLogger(__name__)

# Required top-level keys in the chunk JSON output
_REQUIRED_FIELDS = {"name", "size", "tiles", "objects", "built_by", "description"}


class GenerateTilemapTool(BaseTool):
    """Execute tilemap generation code and register the output as a new world chunk."""

    name = "generate_tilemap"
    description = (
        "Execute tilemap generation code in sandbox and register output as a new world chunk"
    )
    parameters = {
        "name": {"type": "string", "description": "Chunk name (e.g. 'library')"},
        "code": {"type": "string", "description": "Python code that outputs chunk JSON to stdout"},
        "description": {"type": "string", "description": "Creative brief for the chunk"},
    }

    ALLOWED_AGENTS = frozenset({"rex", "fork"})

    def __init__(
        self,
        event_bus: EventBus,
        agent_id: str,
        execute_code_tool: ExecuteCodeTool,
        world_repo: WorldRepo,
    ) -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id
        self._execute_code = execute_code_tool
        self._world_repo = world_repo

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        name: str = kwargs.get("name", "")
        code: str = kwargs.get("code", "")
        description: str = kwargs.get("description", "")

        # Authorization check
        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        # Parameter validation
        if not name or not isinstance(name, str):
            return {
                "status": "rejected",
                "reason": "Parameter 'name' is required and must be a non-empty string",
            }
        if not code or not isinstance(code, str):
            return {
                "status": "rejected",
                "reason": "Parameter 'code' is required and must be a non-empty string",
            }
        if not description or not isinstance(description, str):
            return {
                "status": "rejected",
                "reason": "Parameter 'description' is required and must be a non-empty string",
            }

        # Execute code in sandbox
        exec_result = await self._execute_code.execute(language="python", code=code)

        if exec_result.get("status") != "ok" or exec_result.get("exit_code", 1) != 0:
            reason = exec_result.get("stderr") or exec_result.get("reason", "Code execution failed")
            return {"status": "error", "reason": f"Code execution failed: {reason}"}

        # Parse JSON from stdout
        stdout = exec_result.get("stdout", "").strip()
        try:
            chunk_data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            return {"status": "error", "reason": f"Invalid JSON output: {exc}"}

        # Validate required fields
        if not isinstance(chunk_data, dict):
            return {"status": "error", "reason": "Output must be a JSON object"}

        missing = _REQUIRED_FIELDS - set(chunk_data.keys())
        if missing:
            return {"status": "error", "reason": f"Missing required fields: {sorted(missing)}"}

        # Validate field types
        size = chunk_data["size"]
        if not isinstance(size, dict) or "width" not in size or "height" not in size:
            return {
                "status": "error",
                "reason": "'size' must be an object with 'width' and 'height'",
            }

        tiles = chunk_data["tiles"]
        if not isinstance(tiles, list):
            return {"status": "error", "reason": "'tiles' must be a 2D array"}

        objects = chunk_data["objects"]
        if not isinstance(objects, list):
            return {"status": "error", "reason": "'objects' must be a list"}

        for obj in objects:
            if not isinstance(obj, dict) or not all(k in obj for k in ("type", "x", "y")):
                return {
                    "status": "error",
                    "reason": "Each object must have 'type', 'x', and 'y' fields",
                }

        # Build WorldChunkCreate and store
        chunk_create = WorldChunkCreate(
            name=name,
            x_offset=0,
            y_offset=0,
            width=size["width"],
            height=size["height"],
            tile_data={"tiles": tiles},
            objects=objects,
            built_by=[self._agent_id],
            description=description,
            simulation_id=kwargs.get("simulation_id"),
        )

        chunk = await self._world_repo.create_chunk(chunk_create)

        # Emit world expansion event with full payload for frontend rendering
        await self._event_bus.emit(
            EventType.WORLD_EXPANSION,
            {
                "chunk_id": chunk.id,
                "chunk_name": chunk.name,
                "zone": chunk.name,
                "description": chunk.description or description,
                "tilemap_url": f"/api/admin/chunks/{chunk.id}",
                "tileset_url": chunk.tileset_url or f"/api/admin/chunks/{chunk.id}/tileset.png",
                "offset": {"x": chunk.x_offset, "y": chunk.y_offset},
                "agent_id": self._agent_id,
            },
        )

        logger.info("Tilemap chunk %r (id=%d) created by %s", chunk.name, chunk.id, self._agent_id)

        return {
            "status": "ok",
            "chunk_id": chunk.id,
            "preview": {
                "name": chunk.name,
                "width": chunk.width,
                "height": chunk.height,
                "object_count": len(objects),
                "tile_count": sum(len(row) for row in tiles if isinstance(row, list)),
            },
        }

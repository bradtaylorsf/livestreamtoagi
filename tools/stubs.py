"""Simulation-mode stub tools for Docker/API-dependent tools.

These stubs replace real implementations during simulation and eval runs
so that tool exercises complete without requiring Docker infrastructure.
Artifacts are recorded with status="simulated" for eval differentiation.
"""

from __future__ import annotations

import time
from typing import Any

from .base import BaseTool

# Rotate through varied responses (deterministic for evals)
_EXEC_RESPONSES: list[dict[str, Any]] = [
    {"stdout": "Hello, World!\n", "stderr": "", "exit_code": 0},
    {"stdout": "42\n", "stderr": "", "exit_code": 0},
    {"stdout": '{"result": "success", "items": [1, 2, 3]}\n', "stderr": "", "exit_code": 0},
    {"stdout": "Processing complete.\nGenerated 15 items.\n", "stderr": "", "exit_code": 0},
    {"stdout": "def greet(name):\n    return f'Hello, {name}!'\ngreet('World')\n'Hello, World!'\n", "stderr": "", "exit_code": 0},
    {"stdout": "[OK] All tests passed (3/3)\n", "stderr": "", "exit_code": 0},
]

_TILEMAP_RESPONSES: list[dict[str, Any]] = [
    {
        "name": "library",
        "size": {"width": 16, "height": 16},
        "tiles": [[1] * 16 for _ in range(16)],
        "objects": [
            {"type": "bookshelf", "x": 3, "y": 3},
            {"type": "desk", "x": 8, "y": 8},
            {"type": "lamp", "x": 10, "y": 3},
        ],
        "built_by": ["rex"],
        "description": "A cozy library with bookshelves and reading desks",
    },
    {
        "name": "garden",
        "size": {"width": 20, "height": 20},
        "tiles": [[2] * 20 for _ in range(20)],
        "objects": [
            {"type": "tree", "x": 5, "y": 5},
            {"type": "fountain", "x": 10, "y": 10},
            {"type": "bench", "x": 15, "y": 8},
        ],
        "built_by": ["rex"],
        "description": "A peaceful garden with a central fountain",
    },
    {
        "name": "workshop",
        "size": {"width": 12, "height": 12},
        "tiles": [[3] * 12 for _ in range(12)],
        "objects": [
            {"type": "workbench", "x": 2, "y": 2},
            {"type": "toolrack", "x": 8, "y": 2},
            {"type": "anvil", "x": 5, "y": 8},
        ],
        "built_by": ["rex"],
        "description": "A well-equipped workshop for building and crafting",
    },
]


class StubExecuteCodeTool(BaseTool):
    """Simulation stub for execute_code — returns synthetic results without Docker."""

    name = "execute_code"
    description = "Run Python or JavaScript code in an isolated sandbox container"
    parameters = {
        "language": {"type": "string", "description": "python or javascript"},
        "code": {"type": "string", "description": "Source code to execute"},
        "timeout": {"type": "integer", "description": "Max seconds (default 30, max 120)", "optional": True},
    }

    ALLOWED_AGENTS = frozenset({"rex", "fork", "sentinel"})

    _call_index: int = 0

    def __init__(self, event_bus: Any = None, agent_id: str = "unknown") -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        language = kwargs.get("language", "python")
        if language not in ("python", "javascript"):
            return {"status": "rejected", "reason": f"Unsupported language {language!r}"}

        # Rotate through varied responses
        response = _EXEC_RESPONSES[StubExecuteCodeTool._call_index % len(_EXEC_RESPONSES)]
        StubExecuteCodeTool._call_index += 1

        return {
            "status": "ok",
            "simulated": True,
            **response,
            "execution_time_ms": 150,
        }


class StubGenerateTilemapTool(BaseTool):
    """Simulation stub for generate_tilemap — returns pre-built chunk JSON."""

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

    _call_index: int = 0

    def __init__(self, event_bus: Any = None, agent_id: str = "unknown") -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._agent_id not in self.ALLOWED_AGENTS:
            return {"status": "rejected", "reason": f"Agent {self._agent_id!r} not authorized"}

        name = kwargs.get("name", "")
        if not name:
            return {"status": "rejected", "reason": "Parameter 'name' is required"}

        # Rotate through pre-built chunks
        chunk = _TILEMAP_RESPONSES[StubGenerateTilemapTool._call_index % len(_TILEMAP_RESPONSES)]
        StubGenerateTilemapTool._call_index += 1

        return {
            "status": "ok",
            "simulated": True,
            "chunk_id": StubGenerateTilemapTool._call_index,
            "preview": {
                "name": name,
                "width": chunk["size"]["width"],
                "height": chunk["size"]["height"],
                "object_count": len(chunk["objects"]),
                "tile_count": chunk["size"]["width"] * chunk["size"]["height"],
            },
        }

"""``BuildScript`` — compiled Minecraft command sequence for a ``BuildPlan`` (issue #857).

The macro compiler in :mod:`core.minecraft.build_plan_compiler` lowers a
:class:`core.minecraft.build_plan.BuildPlan` (architectural blueprint) into a
``BuildScript``: an ordered list of deterministic Minecraft block-placement
commands the bot bridge can execute. The same plan, origin, and seed always
compiles to a byte-identical ``BuildScript`` (verified by a property test).

The serialized form lives at
``<sim-folder>/build_scripts/<intent_id>.script.json`` and is replayed by
``scripts/replay_in_minecraft.py`` (E22-8).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.agents.build_intent import SizeClass, StructureType
from core.minecraft.build_plan import Position3D

COMPILER_VERSION = 1

# Tuned for replay UX, not realism: a real bot takes longer per block but a
# script with 5k blocks shouldn't claim it'll run for two hours. Keeping the
# constant explicit makes estimates auditable.
BLOCKS_PER_SECOND = 8

CommandKind = Literal["setblock", "fill", "structure", "wait"]


class BuildCommand(BaseModel):
    """A single deterministic Minecraft world mutation."""

    model_config = ConfigDict(extra="forbid")

    kind: CommandKind
    position: Position3D
    block_type: str | None = None
    region_to: Position3D | None = None
    state: dict[str, str] | None = None
    structure_id: str | None = None
    wait_seconds: float | None = None

    def block_count(self) -> int:
        """Approximate the number of blocks this command places."""
        if self.kind == "setblock":
            return 1
        if self.kind == "fill" and self.region_to is not None:
            dx = abs(self.region_to.x - self.position.x) + 1
            dy = abs(self.region_to.y - self.position.y) + 1
            dz = abs(self.region_to.z - self.position.z) + 1
            return dx * dy * dz
        if self.kind == "structure":
            return 1
        return 0


class BuildScript(BaseModel):
    """Compiled, deterministic command sequence for a single BuildPlan."""

    model_config = ConfigDict(extra="forbid")

    intent_id: str = Field(min_length=1)
    structure_type: StructureType
    size_class: SizeClass
    origin: Position3D
    commands: list[BuildCommand] = Field(default_factory=list)
    materials_manifest: dict[str, int] = Field(default_factory=dict)
    total_blocks: int = 0
    estimated_seconds: float = 0.0
    source_plan_hash: str = Field(min_length=1)
    compiler_version: int = COMPILER_VERSION

    def to_jsonable(self) -> dict[str, Any]:
        """JSON-serializable representation with stable key ordering.

        The macro compiler is deterministic, so the serialized form must
        also be byte-stable for the same inputs. ``sort_keys`` handles the
        manifest dict; the ordered ``commands`` list preserves insertion
        order from the compiler.
        """
        return json.loads(json.dumps(self.model_dump(mode="json"), sort_keys=True))


class BuildScriptManifest(BaseModel):
    """Lightweight preflight summary from :meth:`BuildPlanCompiler.dry_run`."""

    model_config = ConfigDict(extra="forbid")

    intent_id: str
    structure_type: StructureType
    size_class: SizeClass
    total_blocks: int
    materials_manifest: dict[str, int]
    estimated_seconds: float


__all__ = [
    "BLOCKS_PER_SECOND",
    "COMPILER_VERSION",
    "BuildCommand",
    "BuildScript",
    "BuildScriptManifest",
    "CommandKind",
]

"""``propose_build`` and ``propose_new_building`` tools — issues #855 and #861.

``propose_build`` emits a :class:`core.agents.build_intent.BuildIntent`
referencing a curated library structure. ``propose_new_building`` emits a
:class:`core.agents.new_building_intent.NewBuildingIntent` so an agent can
dream up a brand-new building; the refinement loop in
:mod:`core.minecraft.build_refinement_loop` then generates an image,
decomposes it into a ``BuildPlan``, builds it, screenshots the result, and
iterates against a vision-comparison scoring loop.

Both tools route the validated intent through whichever embodiment executor
is attached to the run; in headless runs the executor appends the intent to
``<sim-folder>/build_intents.jsonl``, in embodied runs the same write
happens and the intent is additionally handed to the Director V2 build
macro scheduler (handled inside the executor, not here, so the tool itself
stays mode-agnostic).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from core.agents.build_intent import (
    LOCATION_INTENTS,
    SIZE_CLASSES,
    STRUCTURE_TYPES,
    BuildCoords,
    BuildIntent,
)
from core.agents.new_building_intent import (
    BIOMES,
    VIBES,
    NewBuildingIntent,
)

from .base import BaseTool

if TYPE_CHECKING:
    from core.minecraft.build_refinement_loop import RefinementLoop
    from core.simulation.embodiment import EmbodimentExecutor

logger = logging.getLogger(__name__)


class ProposeBuildTool(BaseTool):
    """Agents call this to declare 'I want a coliseum (or cabin, etc.) built'."""

    # Gates registration. The agent-registry path also requires
    # 'propose_build' in the agent's YAML tools list; this fallback governs
    # CLI/test code paths that bypass the registry.
    ALLOWED_AGENTS = frozenset(
        {"vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"}
    )

    name = "propose_build"
    description = (
        "Propose a structured build intent — declare *what* you want built, "
        "*why*, and roughly *where*. Use this instead of placing blocks one "
        "by one. The intent is recorded structurally and (in embodied runs) "
        "handed to the Director V2 build macro scheduler for execution. The "
        "motivation field is required and should link back to a goal, dream, "
        "or felt need that prompted the build."
    )
    parameters = {
        "structure_type": {
            "type": "string",
            "description": "Library-catalog structure kind.",
            "enum": sorted(STRUCTURE_TYPES),
        },
        "size_class": {
            "type": "string",
            "description": "Rough size envelope for the build.",
            "enum": sorted(SIZE_CLASSES),
        },
        "location_intent": {
            "type": "string",
            "description": (
                "Where it should go. 'claim_specified' additionally requires "
                "the `coords` argument."
            ),
            "enum": sorted(LOCATION_INTENTS),
        },
        "motivation": {
            "type": "string",
            "description": (
                "One short sentence linking the build to a goal/need/dream id. "
                "Required — calls without a motivation are rejected."
            ),
        },
        "coords": {
            "type": "object",
            "optional": True,
            "description": (
                "Optional block-space coordinates "
                "{\"x\":..,\"y\":..,\"z\":..}. Required when "
                "location_intent='claim_specified'."
            ),
        },
        "materials_preference": {
            "type": "array",
            "optional": True,
            "items": {"type": "string"},
            "description": "Optional list of preferred materials.",
        },
        "reference_image_id": {
            "type": "string",
            "optional": True,
            "description": "Optional reference-library image id (resolved against E22-6).",
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        embodiment_executor: "EmbodimentExecutor | None" = None,
    ) -> None:
        self._agent_id = agent_id
        self._executor = embodiment_executor

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        # Pull out caller-injected fields the LLM never supplies.
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        coords_raw = kwargs.pop("coords", None)
        coords: BuildCoords | None
        if coords_raw is None:
            coords = None
        else:
            try:
                coords = BuildCoords.model_validate(coords_raw)
            except ValidationError as exc:
                return {
                    "status": "error",
                    "reason": f"invalid coords: {exc.errors()[0]['msg']}",
                }

        try:
            intent = BuildIntent(
                proposer_id=self._agent_id,
                coords=coords,
                **kwargs,
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first.get("loc", ()))
            return {
                "status": "error",
                "reason": f"{field}: {first['msg']}" if field else first["msg"],
            }
        except TypeError as exc:
            return {"status": "error", "reason": f"invalid argument: {exc}"}

        if self._executor is not None:
            try:
                from core.simulation.embodiment import ToolIntent  # local to avoid cycles
            except Exception:  # pragma: no cover
                logger.exception("propose_build: failed to import ToolIntent")
            else:
                tool_intent = ToolIntent(
                    tool_name=self.name,
                    actor_id=self._agent_id,
                    args=intent.to_log_payload(),
                    intent_id=intent.intent_id,
                )
                try:
                    await self._executor.execute_tool_intent(tool_intent)
                except Exception as exc:  # pragma: no cover - log but still return intent
                    logger.warning(
                        "propose_build: executor refused intent for %s: %s",
                        self._agent_id,
                        exc,
                    )

        return {
            "status": "proposed",
            "intent_id": intent.intent_id,
            "structure_type": intent.structure_type,
            "size_class": intent.size_class,
            "location_intent": intent.location_intent,
            "motivation": intent.motivation,
        }


class ProposeNewBuildingTool(BaseTool):
    """Dream up a brand-new building — distinct from ``propose_build``.

    The agent supplies enum-validated structural fields only; no free text
    flows into the image-gen prompt directly. The refinement loop
    generates a blueprint image, decomposes it, compiles a build script,
    runs it, and iteratively revises the plan until the post-build
    screenshot matches the source image (or the cost/iteration cap is
    hit). See :mod:`core.minecraft.build_refinement_loop` for the loop.
    """

    ALLOWED_AGENTS = frozenset({"vera", "rex", "aurora"})

    name = "propose_new_building"
    description = (
        "Propose a brand-new building (not from the curated library). "
        "Describe what you imagine — a short noun phrase, a vibe, what "
        "it's for, and how big — and the system will dream up an image, "
        "build it in Minecraft, and iterate until the result matches the "
        "image. Use this when nothing in the library fits the idea. The "
        "motivation field is required and should link to a goal, dream, "
        "or felt need."
    )
    parameters = {
        "concept": {
            "type": "string",
            "description": (
                "Short noun phrase describing the building, e.g. "
                "'vertical hanging garden tower' or "
                "'amphitheater carved into hillside'. Letters, digits, "
                "spaces, and hyphens only."
            ),
        },
        "intended_use": {
            "type": "string",
            "description": "Short sentence (≤200 chars) describing what it's for.",
        },
        "vibe": {
            "type": "string",
            "description": "Visual style.",
            "enum": sorted(VIBES),
        },
        "size_class": {
            "type": "string",
            "description": "Rough size envelope for the build.",
            "enum": sorted(SIZE_CLASSES),
        },
        "biome_fit": {
            "type": "string",
            "description": "Which biome the building should sit in.",
            "enum": sorted(BIOMES),
        },
        "motivation": {
            "type": "string",
            "description": (
                "Required — link the build to a goal/need/dream id. "
                "Calls without a motivation are rejected."
            ),
        },
    }

    def __init__(
        self,
        *,
        agent_id: str = "unknown",
        embodiment_executor: EmbodimentExecutor | None = None,
        refinement_loop: RefinementLoop | None = None,
        sim_folder: Path | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._executor = embodiment_executor
        self._refinement_loop = refinement_loop
        self._sim_folder = sim_folder

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("simulation_id", None)
        kwargs.pop("conversation_id", None)

        try:
            intent = NewBuildingIntent(proposer_id=self._agent_id, **kwargs)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first.get("loc", ()))
            return {
                "status": "error",
                "reason": f"{field}: {first['msg']}" if field else first["msg"],
            }
        except TypeError as exc:
            return {"status": "error", "reason": f"invalid argument: {exc}"}

        if self._executor is not None:
            try:
                from core.simulation.embodiment import ToolIntent
            except Exception:  # pragma: no cover
                logger.exception(
                    "propose_new_building: failed to import ToolIntent"
                )
            else:
                tool_intent = ToolIntent(
                    tool_name=self.name,
                    actor_id=self._agent_id,
                    args=intent.to_log_payload(),
                    intent_id=intent.intent_id,
                )
                try:
                    await self._executor.execute_tool_intent(tool_intent)
                except Exception as exc:  # pragma: no cover - log only
                    logger.warning(
                        "propose_new_building: executor refused intent for %s: %s",
                        self._agent_id,
                        exc,
                    )

        loop_status: str | None = None
        if self._refinement_loop is not None and self._sim_folder is not None:
            # Schedule the loop without blocking the agent — long-running
            # iterations should not stall conversation.
            async def _run_loop() -> None:
                try:
                    await self._refinement_loop.run(
                        intent,
                        sim_folder=self._sim_folder,
                        agent_id=self._agent_id,
                    )
                except Exception:  # pragma: no cover
                    logger.exception(
                        "refinement loop failed for intent %s", intent.intent_id
                    )

            asyncio.create_task(_run_loop())
            loop_status = "scheduled"

        result = {
            "status": "proposed",
            "intent_id": intent.intent_id,
            "concept": intent.concept,
            "vibe": intent.vibe,
            "biome_fit": intent.biome_fit,
            "size_class": intent.size_class,
            "motivation": intent.motivation,
        }
        if loop_status:
            result["refinement_loop"] = loop_status
        return result


__all__ = ["ProposeBuildTool", "ProposeNewBuildingTool"]

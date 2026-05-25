"""``propose_build`` tool — emits a structured ``BuildIntent`` (issue #855).

The tool always validates arguments through :class:`core.agents.build_intent.BuildIntent`
and then routes the intent through whichever embodiment executor is attached
to the run. In headless runs the executor appends the intent to
``<sim-folder>/build_intents.jsonl``; in embodied runs the same write happens
and the intent is additionally handed to the Director V2 build macro
scheduler (handled inside the executor, not here, so the tool itself stays
mode-agnostic).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from core.agents.build_intent import (
    LOCATION_INTENTS,
    SIZE_CLASSES,
    STRUCTURE_TYPES,
    BuildCoords,
    BuildIntent,
)

from .base import BaseTool

if TYPE_CHECKING:
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


__all__ = ["ProposeBuildTool"]

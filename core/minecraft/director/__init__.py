"""Opt-in Minecraft Director V2 input, scheduling, and evidence modules."""

from typing import Any

from core.minecraft.director.build_macro_scheduler import (
    BuildMacroAcquireResult,
    BuildMacroAssignment,
    BuildMacroScheduler,
)
from core.minecraft.director.scene_inbox import (
    ClosedScene,
    Scene,
    SceneBufferEntry,
    SceneEvent,
    SceneEventType,
    SceneInbox,
    SceneInboxConfig,
    SceneUpdate,
    register,
)
from core.minecraft.director.spatial_hearing import (
    AgentPose,
    SpatialHearingAdapter,
    SpatialHearingConfig,
)
from core.minecraft.director.tool_adapter import DirectorToolAdapter
from core.minecraft.director.tool_parity import (
    TOOL_PARITY,
    ToolParityEntry,
    classified_names,
    is_approval_gated,
    is_callable_now,
    iter_tool_parity,
)
from core.minecraft.director.turn_scheduler import (
    DirectorTurnScheduler,
    SchedulerCandidate,
    SchedulerConfig,
    SchedulerDecision,
    SchedulerTurn,
    score_candidate,
)

__all__ = [
    "AgentPose",
    "BuildMacroAcquireResult",
    "BuildMacroAssignment",
    "BuildMacroScheduler",
    "ClosedScene",
    "DirectorPromptGate",
    "DirectorTurnScheduler",
    "PromptDecision",
    "Scene",
    "SceneBufferEntry",
    "SceneEvent",
    "SceneEventType",
    "SceneInbox",
    "SceneInboxConfig",
    "SceneUpdate",
    "SchedulerCandidate",
    "SchedulerConfig",
    "SchedulerDecision",
    "SchedulerTurn",
    "SpatialHearingAdapter",
    "SpatialHearingConfig",
    "TOOL_PARITY",
    "ToolParityEntry",
    "DirectorToolAdapter",
    "classified_names",
    "get_prompt_gate",
    "is_approval_gated",
    "is_callable_now",
    "iter_tool_parity",
    "register",
    "reset_prompt_gates",
    "score_candidate",
]

_PROMPT_GATE_EXPORTS = {
    "DirectorPromptGate",
    "PromptDecision",
    "get_prompt_gate",
    "reset_prompt_gates",
}


def __getattr__(name: str) -> Any:
    """Lazy-load prompt-gate exports to avoid bridge contract import cycles."""

    if name in _PROMPT_GATE_EXPORTS:
        from core.minecraft.director import prompt_gate

        return getattr(prompt_gate, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

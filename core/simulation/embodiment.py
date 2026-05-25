"""Embodiment executor abstraction.

The SimulationOrchestrator owns the social-dynamics loop (conversation engine,
dreams, relationships, alliances, shared blackboard) and is identical across
modes. The only difference is the **embodiment executor**: a swappable object
that decides whether tool intents become real Minecraft side-effects, audio,
and bot behavior — or whether they are recorded and simulated deterministically.

There are two implementations:

- ``EmbodiedExecutor`` — wraps the existing Director V2 / Mindcraft / TTS
  path. ``requires_minecraft_world`` is True; the orchestrator provisions a
  world before running.
- ``HeadlessExecutor`` — records each tool intent in-memory (and writes it to
  the decision log when one is attached). No Director V2, no Mindcraft, no
  TTS, no audio FIFO. ``requires_minecraft_world`` is False.

Selecting an executor is the **only** code path in the orchestrator that
branches on :class:`core.models.RunMode`.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from core.models import RunMode

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_BUILD_INTENTS_FILENAME = "build_intents.jsonl"


@dataclass
class ToolIntent:
    """A request from an agent to perform a tool / world action."""

    tool_name: str
    actor_id: str
    args: dict[str, Any] = field(default_factory=dict)
    intent_id: str | None = None
    submitted_at: float = field(default_factory=time.time)


@dataclass
class ToolOutcome:
    """The result of a tool intent: executed, blocked, or simulated."""

    status: str  # "executed" | "blocked" | "simulated"
    intent: ToolIntent
    result: Any | None = None
    block_reason: str | None = None
    completed_at: float = field(default_factory=time.time)


@runtime_checkable
class EmbodimentExecutor(Protocol):
    """Side-effect surface for one simulation run.

    The orchestrator calls these methods at the appropriate lifecycle points.
    Both real and simulated executors satisfy this contract.
    """

    requires_minecraft_world: bool

    async def setup(
        self,
        *,
        simulation_id: Any,
        sim_folder: "Path | None" = None,
        decision_logger: Any | None = None,
    ) -> None:
        """Called once after the simulation row exists but before phases run."""

    async def execute_tool_intent(
        self,
        intent: ToolIntent,
    ) -> ToolOutcome:
        """Run, simulate, or block a tool intent and return the outcome."""

    async def on_utterance(self, utterance: dict[str, Any]) -> None:
        """Notify the executor that an agent uttered something (for TTS, etc.)."""

    async def tick(self, sim_time: float) -> None:
        """Optional periodic hook for time-dependent embodied work."""

    async def teardown(self) -> None:
        """Release any resources opened in :meth:`setup`."""


class HeadlessExecutor:
    """Records tool intents without touching Minecraft, Mindcraft, or TTS.

    The executor never imports Director V2, Mindcraft, or audio modules. It
    builds a deterministic, in-memory ledger of every intent submitted during
    the run. When a decision logger is attached the ledger entries are also
    streamed to JSONL via :meth:`core.simulation.decision_logger.DecisionLogger`.
    """

    requires_minecraft_world: bool = False

    def __init__(self) -> None:
        self.recorded_intents: list[ToolOutcome] = []
        self._sim_folder: "Path | None" = None
        self._decision_logger: Any | None = None
        self._simulation_id: Any | None = None

    async def setup(
        self,
        *,
        simulation_id: Any,
        sim_folder: "Path | None" = None,
        decision_logger: Any | None = None,
    ) -> None:
        self._simulation_id = simulation_id
        self._sim_folder = sim_folder
        self._decision_logger = decision_logger

    async def execute_tool_intent(
        self,
        intent: ToolIntent,
    ) -> ToolOutcome:
        outcome = ToolOutcome(
            status="simulated",
            intent=intent,
            result={"simulated": True},
        )
        self.recorded_intents.append(outcome)
        self._log_outcome(outcome)
        if intent.tool_name == "propose_build":
            _append_build_intent(self._sim_folder, intent)
        return outcome

    def record_blocked_intent(
        self,
        intent: ToolIntent,
        *,
        reason: str,
    ) -> ToolOutcome:
        """Capture a policy-blocked intent without executing it."""
        outcome = ToolOutcome(
            status="blocked",
            intent=intent,
            block_reason=reason,
        )
        self.recorded_intents.append(outcome)
        self._log_outcome(outcome)
        return outcome

    async def on_utterance(self, utterance: dict[str, Any]) -> None:
        # Headless never produces TTS audio.
        return None

    async def tick(self, sim_time: float) -> None:
        return None

    async def teardown(self) -> None:
        return None

    def _log_outcome(self, outcome: ToolOutcome) -> None:
        if self._decision_logger is None:
            return
        try:
            self._decision_logger.log_tool_intent(
                actor_id=outcome.intent.actor_id,
                tool_name=outcome.intent.tool_name,
                args=outcome.intent.args,
                status=outcome.status,
                block_reason=outcome.block_reason,
                outcome=outcome.result,
            )
        except Exception:  # pragma: no cover - logger errors must not break sim
            pass


class EmbodiedExecutor:
    """Marker for the live Director V2 / Mindcraft / TTS path.

    The heavy lifting still lives in :mod:`core.simulation.embodied_supervisor`
    and the bridge handlers — this class is a stable seam so the orchestrator
    can branch via ``executor.requires_minecraft_world`` instead of inspecting
    ``RunMode`` directly. Embodied side-effects are unchanged.
    """

    requires_minecraft_world: bool = True

    def __init__(self) -> None:
        self._simulation_id: Any | None = None
        self._sim_folder: "Path | None" = None
        self._decision_logger: Any | None = None

    async def setup(
        self,
        *,
        simulation_id: Any,
        sim_folder: "Path | None" = None,
        decision_logger: Any | None = None,
    ) -> None:
        self._simulation_id = simulation_id
        self._sim_folder = sim_folder
        self._decision_logger = decision_logger

    async def execute_tool_intent(
        self,
        intent: ToolIntent,
    ) -> ToolOutcome:
        # Embodied tool execution flows through the bridge / Director V2; we
        # treat the intent as accepted at this seam and emit a log row when a
        # decision logger is attached.
        outcome = ToolOutcome(status="executed", intent=intent)
        self._log_outcome(outcome)
        if intent.tool_name == "propose_build":
            _append_build_intent(self._sim_folder, intent)
            self._handoff_build_intent_to_scheduler(intent)
        return outcome

    async def on_utterance(self, utterance: dict[str, Any]) -> None:
        return None

    async def tick(self, sim_time: float) -> None:
        return None

    async def teardown(self) -> None:
        return None

    def _log_outcome(self, outcome: ToolOutcome) -> None:
        if self._decision_logger is None:
            return
        try:
            self._decision_logger.log_tool_intent(
                actor_id=outcome.intent.actor_id,
                tool_name=outcome.intent.tool_name,
                args=outcome.intent.args,
                status=outcome.status,
                block_reason=outcome.block_reason,
                outcome=outcome.result,
            )
        except Exception:  # pragma: no cover
            pass

    def _handoff_build_intent_to_scheduler(self, intent: ToolIntent) -> None:
        """Hand a validated ``BuildIntent`` to Director V2's macro scheduler.

        Imported lazily so the headless executor's import-purity contract
        is not broken (see ``test_headless_module_does_not_import_embodied_modules``).
        """
        try:
            from core.minecraft.director.build_macro_scheduler import (
                BuildMacroScheduler,
            )
        except Exception:  # pragma: no cover - bridge unavailable in this env
            logger.debug("BuildMacroScheduler unavailable; build intent recorded only")
            return
        handler = getattr(self, "_build_macro_scheduler", None)
        if handler is None:
            handler = BuildMacroScheduler()
            self._build_macro_scheduler = handler
        scene_id = str(intent.args.get("location_intent") or "open_area")
        try:
            handler.try_acquire_plan(
                scene_id=scene_id,
                agent_id=intent.actor_id,
                description=str(intent.args.get("structure_type", "")),
                origin=intent.args.get("coords"),
            )
        except Exception:  # pragma: no cover - scheduler issues must not break sim
            logger.exception("BuildMacroScheduler hand-off failed")


def _append_build_intent(sim_folder: "Path | None", intent: ToolIntent) -> None:
    """Append a ``propose_build`` intent to ``<sim-folder>/build_intents.jsonl``.

    Best-effort: missing sim folders are silently ignored so that one-shot
    tool invocations (tests, REPL) still succeed.
    """
    if sim_folder is None:
        return
    try:
        sim_folder.mkdir(parents=True, exist_ok=True)
        path = sim_folder / _BUILD_INTENTS_FILENAME
        payload: dict[str, Any] = {
            "intent_id": intent.intent_id,
            "actor_id": intent.actor_id,
            "submitted_at": intent.submitted_at,
            "args": intent.args,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception:  # pragma: no cover - logging only
        logger.exception("failed to append build intent to %s", sim_folder)


def select_executor(run_mode: RunMode | str | None) -> EmbodimentExecutor:
    """Return the executor for ``run_mode``.

    This is the **only** intentional ``RunMode`` switch in the embodiment
    layer; downstream code should call ``executor.requires_minecraft_world``
    or other contract methods rather than re-inspecting the mode.
    """
    mode = run_mode if isinstance(run_mode, RunMode) else RunMode(run_mode) if run_mode else None
    if mode == RunMode.headless:
        return HeadlessExecutor()
    return EmbodiedExecutor()


__all__ = [
    "EmbodiedExecutor",
    "EmbodimentExecutor",
    "HeadlessExecutor",
    "ToolIntent",
    "ToolOutcome",
    "select_executor",
]

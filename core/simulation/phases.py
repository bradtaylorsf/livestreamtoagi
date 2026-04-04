"""Phase definitions and runner for simulation orchestrator.

Each phase type maps to a specific method that bootstraps the required
services, runs the conversation/tool/reflection, and returns a PhaseResult
with stats for incremental DB updates.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from collections.abc import Awaitable, Callable

    from core.agent_registry import AgentRegistry
    from core.config_loader import ConfigLoader
    from core.context_assembly import ContextAssembler
    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.event_bus import EventBus
    from core.llm_client import OpenRouterClient
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.memory.reflection import ReflectionManager
    from core.overseer import Overseer
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.memory_repo import MemoryRepo

logger = logging.getLogger(__name__)


class PhaseType(enum.StrEnum):
    scheduled = "scheduled"
    organic = "organic"
    challenge = "challenge"
    tool_exercise = "tool_exercise"
    reflection = "reflection"
    audience_sim = "audience_sim"


@dataclass
class Phase:
    """A single phase from the seed file."""

    name: str
    type: PhaseType
    config: dict[str, Any] = field(default_factory=dict)
    required_agents: list[str] = field(default_factory=list)


@dataclass
class PhaseResult:
    """Stats from running a single phase."""

    status: str = "completed"
    duration_seconds: float = 0.0
    conversations: int = 0
    turns: int = 0
    tokens: int = 0
    cost: Decimal = field(default_factory=lambda: Decimal("0"))
    artifacts: int = 0
    overseer_flags: int = 0
    errors: list[str] = field(default_factory=list)
    agents_participated: list[str] = field(default_factory=list)


class PhaseRunner:
    """Runs individual simulation phases by type."""

    def __init__(
        self,
        *,
        config_loader: ConfigLoader,
        agent_registry: AgentRegistry,
        event_bus: EventBus,
        llm_client: OpenRouterClient,
        overseer: Overseer,
        context_assembler: ContextAssembler,
        conversation_repo: ConversationRepo,
        archival_memory: ArchivalMemoryManager,
        proximity: ProximityManager,
        trigger_system: TriggerSystem,
        selection_logger: SelectionLogger,
        reflection_manager: ReflectionManager,
        recall_memory: RecallMemoryManager | None = None,
        memory_repo: MemoryRepo | None = None,
        embedding_fn: Callable[[str], Awaitable[list[float]]] | None = None,
        simulation_id: uuid.UUID,
        agents: list[str],
        dry_run: bool = False,
    ) -> None:
        self._config_loader = config_loader
        self._agents = agent_registry
        self._event_bus = event_bus
        self._llm = llm_client
        self._overseer = overseer
        self._context = context_assembler
        self._conversation_repo = conversation_repo
        self._archival = archival_memory
        self._recall = recall_memory
        self._memory_repo = memory_repo
        self._embedding_fn = embedding_fn
        self._proximity = proximity
        self._triggers = trigger_system
        self._selection_logger = selection_logger
        self._reflection = reflection_manager
        self._simulation_id = simulation_id
        self._agent_ids = agents
        self._dry_run = dry_run

        # Stats accumulated during a phase run via event listeners
        self._phase_turns = 0
        self._phase_cost = Decimal("0")
        self._phase_tokens = 0
        self._phase_overseer_flags = 0
        self._phase_agents: set[str] = set()

    async def run_phase(self, phase: Phase) -> PhaseResult:
        """Dispatch to the appropriate phase runner method."""
        start = time.monotonic()
        self._reset_phase_stats()

        runner = {
            PhaseType.scheduled: self._run_scheduled,
            PhaseType.organic: self._run_organic,
            PhaseType.challenge: self._run_challenge,
            PhaseType.tool_exercise: self._run_tool_exercise,
            PhaseType.reflection: self._run_reflection,
            PhaseType.audience_sim: self._run_audience_sim,
        }.get(phase.type)

        if runner is None:
            return PhaseResult(
                status="skipped",
                errors=[f"Unknown phase type: {phase.type}"],
            )

        result = PhaseResult()
        try:
            await runner(phase)
            result.status = "completed"
        except Exception as exc:
            logger.exception("Phase %s failed", phase.name)
            result.status = "failed"
            result.errors.append(str(exc))

        result.duration_seconds = time.monotonic() - start
        result.turns = self._phase_turns
        result.cost = self._phase_cost
        result.tokens = self._phase_tokens
        result.overseer_flags = self._phase_overseer_flags
        result.agents_participated = list(self._phase_agents)
        return result

    def _reset_phase_stats(self) -> None:
        self._phase_turns = 0
        self._phase_cost = Decimal("0")
        self._phase_tokens = 0
        self._phase_overseer_flags = 0
        self._phase_agents.clear()

    # ── Phase runners ─────────────────────────────────────

    async def _run_scheduled(self, phase: Phase) -> None:
        """Run a scheduled trigger conversation (e.g. standup)."""
        trigger_name = phase.config.get("trigger", phase.name)
        starter = "vera"
        if phase.required_agents:
            starter = phase.required_agents[0]

        trigger = {
            "type": "scheduled",
            "starter_agent_id": starter,
            "prompt_hint": f"It's time for {trigger_name}.",
            "event_name": trigger_name,
            "location": phase.config.get("location", "town_square"),
        }

        if phase.config.get("topic"):
            trigger["topic"] = phase.config["topic"]

        await self._run_conversation(trigger, phase)

    async def _run_organic(self, phase: Phase) -> None:
        """Run 1-3 idle-triggered organic conversations."""
        count = phase.config.get("count", 1)
        topics = phase.config.get("topics", [])

        for i in range(count):
            topic = topics[i] if i < len(topics) else None
            trigger: dict[str, Any] = {
                "type": "idle",
                "reason": "Organic conversation during simulation",
                "location": phase.config.get("location", "town_square"),
            }
            if topic:
                trigger["topic"] = topic

            # Pick a starter from available agents
            starter = self._agent_ids[i % len(self._agent_ids)]
            trigger["starter_agent_id"] = starter

            await self._run_conversation(trigger, phase)

    async def _run_challenge(self, phase: Phase) -> None:
        """Run a coding challenge phase."""
        challenge = phase.config.get("challenge", {})
        assigned = challenge.get("assigned_to", "rex")
        title = challenge.get("title", "Coding Challenge")
        description = challenge.get("description", "Write some code")
        language = challenge.get("language", "python")

        trigger = {
            "type": "environmental",
            "starter_agent_id": assigned,
            "prompt_hint": (
                f"Coding challenge: {title}. {description}. "
                f"Write the solution in {language} and execute it."
            ),
            "event_type": "coding_challenge",
            "event_data": challenge,
            "location": phase.config.get("location", "workshop"),
        }

        await self._run_conversation(trigger, phase)

    async def _run_tool_exercise(self, phase: Phase) -> None:
        """Run a tool exercise — trigger a conversation that uses a specific tool."""
        agent_id = phase.config.get("agent", "pixel")
        tool_name = phase.config.get("tool", "web_search")
        context = phase.config.get("context", f"Use the {tool_name} tool")

        trigger = {
            "type": "environmental",
            "starter_agent_id": agent_id,
            "prompt_hint": context,
            "event_type": "tool_exercise",
            "event_data": {"tool": tool_name, "context": context},
            "location": phase.config.get("location", "town_square"),
        }

        await self._run_conversation(trigger, phase)

    async def _run_reflection(self, phase: Phase) -> None:
        """Run reflection cycles for participating agents."""
        reflection_type = phase.config.get("reflection_type", "6hour")
        agents_to_reflect = phase.config.get("agents", self._agent_ids)

        if self._dry_run:
            logger.info(
                "[DRY RUN] Would run %s reflection for %s",
                reflection_type,
                agents_to_reflect,
            )
            return

        for agent_id in agents_to_reflect:
            if agent_id not in self._agent_ids:
                continue
            self._phase_agents.add(agent_id)
            try:
                if reflection_type == "weekly":
                    result = await self._reflection.run_weekly_reflection(agent_id)
                else:
                    result = await self._reflection.run_6hour_reflection(agent_id)
                logger.info(
                    "Reflection for %s: promoted=%d, importance=%d",
                    agent_id,
                    result.promoted_count,
                    result.importance_updates,
                )
            except Exception:
                logger.exception("Reflection failed for %s", agent_id)

    async def _run_audience_sim(self, phase: Phase) -> None:
        """Inject fake audience messages and trigger Pixel responses."""
        messages = phase.config.get("messages", [
            {"user": "SimViewer42", "text": "What are you guys working on?"},
        ])

        for msg in messages:
            if self._dry_run:
                logger.info("[DRY RUN] Would inject audience message: %s", msg)
                continue

            self._triggers.queue_event("chat_highlight", msg)

        # Run a conversation triggered by the audience event
        trigger = {
            "type": "audience",
            "starter_agent_id": "pixel",
            "prompt_hint": f"Respond to audience: {messages[0].get('text', '')}",
            "event_type": "chat_highlight",
            "event_data": messages[0] if messages else {},
            "location": phase.config.get("location", "town_square"),
        }
        await self._run_conversation(trigger, phase)

    # ── Shared conversation runner ────────────────────────

    async def _run_conversation(self, trigger: dict[str, Any], phase: Phase) -> None:
        """Run a single conversation via ConversationEngine and collect stats."""
        from core.conversation_engine import ConversationEngine

        if self._dry_run:
            logger.info("[DRY RUN] Would run conversation: %s", trigger)
            return

        max_turns = phase.config.get("max_turns", 15)

        # Ensure agents are placed at the conversation location
        location = trigger.get("location", "town_square")
        for agent_id in self._agent_ids:
            await self._proximity.update_location(agent_id, location)

        # Register event listener to capture stats
        turns_in_conv = 0
        cost_in_conv = Decimal("0")
        tokens_in_conv = 0
        agents_in_conv: set[str] = set()

        async def _on_speak(event: dict) -> None:
            nonlocal turns_in_conv, cost_in_conv, tokens_in_conv
            data = event.get("data", event)
            turns_in_conv += 1
            cost_in_conv += Decimal(str(data.get("cost", 0)))
            tokens_in_conv += data.get("input_tokens", 0) + data.get("output_tokens", 0)
            agent_id = data.get("agent_id")
            if agent_id:
                agents_in_conv.add(agent_id)

        async def _on_overseer(event: dict) -> None:
            self._phase_overseer_flags += 1

        self._event_bus.on("agent_speak", _on_speak)
        self._event_bus.on("overseer_shadow", _on_overseer)
        self._event_bus.on("overseer_warning", _on_overseer)

        try:
            engine = ConversationEngine(
                config_loader=self._config_loader,
                agent_registry=self._agents,
                event_bus=self._event_bus,
                llm_client=self._llm,
                overseer=self._overseer,
                context_assembler=self._context,
                conversation_repo=self._conversation_repo,
                archival_memory=self._archival,
                proximity=self._proximity,
                trigger_system=self._triggers,
                selection_logger=self._selection_logger,
                recall_memory=self._recall,
                memory_repo=self._memory_repo,
                embedding_fn=self._embedding_fn,
                speed_multiplier=0,  # No delays in simulation
                overseer_enabled=True,
                simulation_id=self._simulation_id,
            )

            engine._running = True
            await engine._start_conversation(trigger)

            turn = 0
            while (
                engine.active_conversation
                and engine.is_running
                and turn < max_turns
            ):
                should_continue = await engine._continue_conversation()
                turn += 1
                if not should_continue:
                    break

            if engine.active_conversation:
                await engine._end_conversation()

        finally:
            # Unregister handlers (EventBus doesn't have off(), so we accept
            # minor leakage — handlers are cheap and short-lived)
            pass

        # Accumulate stats
        self._phase_turns += turns_in_conv
        self._phase_cost += cost_in_conv
        self._phase_tokens += tokens_in_conv
        self._phase_agents.update(agents_in_conv)

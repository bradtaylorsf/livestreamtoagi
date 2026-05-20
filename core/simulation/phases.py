"""Phase definitions and runner for simulation orchestrator.

Each phase type maps to a specific method that bootstraps the required
services, runs the conversation/tool/reflection, and returns a PhaseResult
with stats for incremental DB updates.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from core.agent_registry import AgentRegistry
    from core.bootstrap import Services
    from core.config_loader import ConfigLoader
    from core.context_assembly import ContextAssembler
    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.event_bus import EventBus
    from core.llm_client import OpenRouterClient
    from core.management import Management
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.compaction import MemoryCompactor
    from core.memory.reflection import ReflectionManager
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.memory_repo import MemoryRepo
    from core.simulation.clock import SimulationClock
    from core.social.relationship_tracker import RelationshipTracker

logger = logging.getLogger(__name__)

# ── Live display helpers (Rich output during simulation) ─────

_AGENT_STYLES: dict[str, str] = {
    "vera": "bright_magenta",
    "rex": "bright_green",
    "aurora": "bright_cyan",
    "pixel": "bright_yellow",
    "fork": "bright_red",
    "sentinel": "blue",
    "grok": "dark_orange",
    "management": "bright_white",
    "alpha": "grey70",
}


def _display_agent_speak(agent_id: str, data: dict) -> None:
    """Print agent dialogue line to terminal."""
    from core.simulation.display import console

    color = _AGENT_STYLES.get(agent_id, "white")
    # Prefer parsed dialogue over raw content for cleaner display
    text = data.get("dialogue") or data.get("content", "")
    actions = data.get("actions", [])
    preview = text[:300] + "..." if len(text) > 300 else text
    # Escape Rich markup in agent dialogue to prevent MarkupError
    preview = preview.replace("[", "\\[")
    cost = data.get("cost", 0)
    tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)

    # Show actions (stage directions) if present
    if actions:
        action_str = " ".join("*{}*".format(a.replace("[", "\\[")) for a in actions)
        console.print(f"       [dim]{'':>10}  {action_str}[/dim]")

    console.print(f"       [{color}]{agent_id:>10}[/{color}]  {preview}")
    console.print(f"       [dim]{'':>10}  ${float(cost):.4f} | {tokens:,} tokens[/dim]")


def _display_management_flag(data: dict) -> None:
    """Print management flag event."""
    from core.simulation.display import console

    agent = data.get("agent_id", "?")
    severity = data.get("severity", "?")
    reason = data.get("reason", "")[:100]
    console.print(
        f"       [yellow]  MANAGEMENT[/yellow]  flagged {agent} (severity {severity}): {reason}"
    )


def _display_artifact(data: dict) -> None:
    """Print tool/artifact creation event."""
    from core.simulation.display import console

    agent = data.get("agent_id", "?")
    tool = data.get("tool_name", data.get("artifact_type", "?"))
    status = data.get("status", "ok")
    color = _AGENT_STYLES.get(agent, "white")
    if status in ("executed", "success"):
        status_color = "green"
    elif status == "failed":
        status_color = "red"
    else:
        status_color = "yellow"
    console.print(
        f"       [{color}]{'':>10}[/{color}]  "
        f"[dim]tool:[/dim] {tool} [{status_color}]{status}[/{status_color}]"
    )


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
    management_flags: int = 0
    errors: list[str] = field(default_factory=list)
    agents_participated: list[str] = field(default_factory=list)
    assertions: list[Any] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)


class PhaseRunner:
    """Runs individual simulation phases by type."""

    def __init__(
        self,
        *,
        config_loader: ConfigLoader,
        agent_registry: AgentRegistry,
        event_bus: EventBus,
        llm_client: OpenRouterClient,
        management: Management,
        context_assembler: ContextAssembler,
        conversation_repo: ConversationRepo,
        archival_memory: ArchivalMemoryManager,
        proximity: ProximityManager,
        trigger_system: TriggerSystem,
        selection_logger: SelectionLogger,
        reflection_manager: ReflectionManager,
        compactor: MemoryCompactor | None = None,
        memory_repo: MemoryRepo | None = None,
        simulation_id: uuid.UUID,
        agents: list[str],
        dry_run: bool = False,
        services: Services | None = None,
        clock: SimulationClock | None = None,
        relationship_tracker: RelationshipTracker | None = None,
        debug_prompts: bool = False,
        prompt_log_repo: object | None = None,
        factions: list[Any] | None = None,
    ) -> None:
        self._config_loader = config_loader
        self._agents = agent_registry
        self._event_bus = event_bus
        self._llm = llm_client
        self._management = management
        self._context = context_assembler
        self._conversation_repo = conversation_repo
        self._archival = archival_memory
        self._compactor = compactor
        self._memory_repo = memory_repo
        self._proximity = proximity
        self._triggers = trigger_system
        self._selection_logger = selection_logger
        self._reflection = reflection_manager
        self._simulation_id = simulation_id
        self._agent_ids = agents
        self._dry_run = dry_run
        self._services = services
        self._clock = clock
        self._relationship_tracker = relationship_tracker
        self._debug_prompts = debug_prompts
        self._prompt_log_repo = prompt_log_repo
        self._factions = list(factions or [])

        # Cross-phase conversation context to prevent repetition (#271)
        from core.models import ConversationRecord

        self._conversation_records: deque[ConversationRecord] = deque(maxlen=25)
        self._conversation_summaries: deque[str] = deque(maxlen=10)
        self._recent_outputs: deque[str] = deque(maxlen=50)  # Last 50 agent outputs
        self._topic_history: dict[str, list[float]] = {}  # Persists across conversations

        # Stats accumulated during a phase run via event listeners
        self._phase_conversations = 0
        self._phase_turns = 0
        self._phase_cost = Decimal("0")
        self._phase_tokens = 0
        self._phase_management_flags = 0
        self._phase_artifacts = 0
        self._phase_agents: set[str] = set()
        self._phase_tools_used: set[str] = set()

    async def run_phase(self, phase: Phase) -> PhaseResult:
        """Dispatch to the appropriate phase runner method."""
        start = time.monotonic()
        self._reset_phase_stats()

        # Periodic maintenance: retire stale goals and prune completed tasks
        await self._run_maintenance()

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

        # Yield to let fire-and-forget artifact events drain before checking
        await asyncio.sleep(0.05)

        result.duration_seconds = time.monotonic() - start
        result.conversations = self._phase_conversations
        result.turns = self._phase_turns
        result.cost = self._phase_cost
        result.tokens = self._phase_tokens
        result.management_flags = self._phase_management_flags
        result.artifacts = self._phase_artifacts
        result.agents_participated = list(self._phase_agents)
        result.tools_used = sorted(self._phase_tools_used)

        # Verify tool_exercise phases actually fired their target tool
        if phase.type == PhaseType.tool_exercise and result.status == "completed":
            expected_tool = phase.config.get("tool")
            if expected_tool and expected_tool not in self._phase_tools_used:
                msg = (
                    f"Tool exercise '{phase.name}' completed but tool "
                    f"'{expected_tool}' never fired (tools_used={result.tools_used})"
                )
                logger.warning(msg)
                result.status = "tool_not_fired"
                result.errors.append(msg)
                from core.event_bus import EventType

                await self._event_bus.emit(
                    EventType.SIMULATION_ERROR,
                    {
                        "source": "tool_exercise",
                        "error_type": "tool_not_fired",
                        "phase": phase.name,
                        "expected_tool": expected_tool,
                        "tools_used": result.tools_used,
                        "turns": result.turns,
                        "simulation_id": str(self._simulation_id) if self._simulation_id else None,
                    },
                )

        # Emit SIMULATION_ERROR for any phase that failed with errors
        if result.errors and result.status == "failed":
            from core.event_bus import EventType

            await self._event_bus.emit(
                EventType.SIMULATION_ERROR,
                {
                    "source": "phase_runner",
                    "error_type": "phase_failed",
                    "phase": phase.name,
                    "phase_type": str(phase.type),
                    "errors": result.errors,
                    "simulation_id": str(self._simulation_id) if self._simulation_id else None,
                },
            )

        return result

    def _reset_phase_stats(self) -> None:
        self._phase_conversations = 0
        self._phase_turns = 0
        self._phase_cost = Decimal("0")
        self._phase_tokens = 0
        self._phase_management_flags = 0
        self._phase_artifacts = 0
        self._phase_agents.clear()
        self._phase_tools_used.clear()

    async def _run_maintenance(self) -> None:
        """Retire stale goals and prune completed tasks between phases."""
        if self._services and self._services.goal_manager:
            for agent_id in self._agent_ids:
                try:
                    retired = await self._services.goal_manager.retire_stale_goals(
                        agent_id,
                        simulation_id=self._simulation_id,
                    )
                    if retired:
                        logger.info("Retired %d stale goals for %s", retired, agent_id)
                except (OSError, KeyError, ValueError):
                    logger.warning("Goal retirement failed for %s", agent_id, exc_info=True)

        if self._services and self._services.shared_working_state:
            try:
                pruned = await self._services.shared_working_state.prune_completed_tasks()
                if pruned:
                    logger.info("Pruned %d completed tasks from shared board", pruned)
            except (OSError, KeyError, ValueError):
                logger.warning("Task pruning failed", exc_info=True)

    def _active_required_agents(self, phase: Phase) -> list[str]:
        """Return phase required agents constrained to this run's roster."""
        active = set(self._agent_ids)
        return [a for a in phase.required_agents if a in active]

    def _fallback_starter(self) -> str | None:
        return self._agent_ids[0] if self._agent_ids else None

    def _starter_or_fallback(self, agent_id: str | None) -> str | None:
        if agent_id in self._agent_ids:
            return agent_id
        return self._fallback_starter()

    # ── Phase runners ─────────────────────────────────────

    async def _run_scheduled(self, phase: Phase) -> None:
        """Run a scheduled trigger conversation (e.g. standup)."""
        trigger_name = phase.config.get("trigger", phase.name)
        required = self._active_required_agents(phase)
        starter = required[0] if required else self._starter_or_fallback("vera")
        if starter is None:
            return

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
        if not self._agent_ids:
            return
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

            # Use required_agents[0] as starter when specified, else rotate
            if phase.required_agents:
                required = self._active_required_agents(phase)
                starter = required[i % len(required)] if required else self._fallback_starter()
            else:
                starter = self._agent_ids[i % len(self._agent_ids)]
            if starter is None:
                continue
            trigger["starter_agent_id"] = starter

            await self._run_conversation(trigger, phase)

    async def _run_challenge(self, phase: Phase) -> None:
        """Run a coding challenge phase."""
        challenge = phase.config.get("challenge", {})
        assigned = self._starter_or_fallback(challenge.get("assigned_to", "rex"))
        if assigned is None:
            return
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
        """Run a tool exercise — short conversation forcing a specific tool.

        Tool exercises are capped at 4 turns by default (not 15) since the
        goal is just to verify the tool fires, not to have a long conversation.
        """
        agent_id = self._starter_or_fallback(phase.config.get("agent", "pixel"))
        if agent_id is None:
            return
        tool_name = phase.config.get("tool", "web_search")
        context = phase.config.get("context", f"Use the {tool_name} tool")

        trigger = {
            "type": "environmental",
            "starter_agent_id": agent_id,
            "prompt_hint": context,
            "topic": context,
            "event_type": "tool_exercise",
            "event_data": {"tool": tool_name, "context": context},
            "location": phase.config.get("location", "town_square"),
            "tool_choice": {"type": "function", "function": {"name": tool_name}},
        }

        # Override max_turns for tool exercises — keep them short
        if "max_turns" not in phase.config:
            phase.config["max_turns"] = 4

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
                if reflection_type == "dream":
                    # Dream-only phase — run dream cycle directly via dream manager
                    if self._services and self._services.dream_manager:
                        dream_result = await self._services.dream_manager.run_dream(agent_id)
                        logger.info(
                            "Dream for %s: %s",
                            agent_id,
                            f"mood={dream_result.mood_shift}" if dream_result else "skipped",
                        )
                    else:
                        logger.warning("Dream manager not available for %s", agent_id)
                elif reflection_type == "weekly":
                    result = await self._reflection.run_weekly_reflection(agent_id)
                    logger.info(
                        "Reflection for %s: promoted=%d, importance=%d",
                        agent_id,
                        result.promoted_count,
                        result.importance_updates,
                    )
                else:
                    result = await self._reflection.run_6hour_reflection(agent_id)
                    logger.info(
                        "Reflection for %s: promoted=%d, importance=%d",
                        agent_id,
                        result.promoted_count,
                        result.importance_updates,
                    )
            except Exception as exc:
                logger.exception("Reflection failed for %s", agent_id)
                from core.event_bus import EventType

                await self._event_bus.emit(
                    EventType.SIMULATION_ERROR,
                    {
                        "source": "reflection",
                        "error_type": "reflection_exception",
                        "agent_id": agent_id,
                        "detail": str(exc)[:500],
                        "simulation_id": str(self._simulation_id) if self._simulation_id else None,
                    },
                )

    async def _run_audience_sim(self, phase: Phase) -> None:
        """Inject fake audience messages and trigger Pixel responses."""
        messages = phase.config.get(
            "messages",
            [
                {"user": "SimViewer42", "text": "What are you guys working on?"},
            ],
        )

        for msg in messages:
            if self._dry_run:
                logger.info("[DRY RUN] Would inject audience message: %s", msg)
                continue

            self._triggers.queue_event("chat_highlight", msg)

        # Run a conversation triggered by the audience event
        starter = self._starter_or_fallback("pixel")
        if starter is None:
            return
        trigger = {
            "type": "audience",
            "starter_agent_id": starter,
            "prompt_hint": f"Respond to audience: {messages[0].get('text', '')}",
            "event_type": "chat_highlight",
            "event_data": messages[0] if messages else {},
            "location": phase.config.get("location", "town_square"),
        }
        await self._run_conversation(trigger, phase)

    # ── Shared conversation runner ────────────────────────

    async def _run_conversation(self, trigger: dict[str, Any], phase: Phase) -> None:
        """Run a single conversation via ConversationEngine and collect stats."""

        if self._dry_run:
            logger.info("[DRY RUN] Would run conversation: %s", trigger)
            return
        from core.conversation_mode import is_embodied_run

        if is_embodied_run():
            logger.info(
                "E8-6: conversation director gated off for embodied run; "
                "relying on Mindcraft decentralized respond/ignore"
            )
            return
        if not self._agent_ids:
            logger.warning("No active agents configured; skipping conversation")
            return

        trigger = dict(trigger)
        trigger["starter_agent_id"] = self._starter_or_fallback(trigger.get("starter_agent_id"))
        if trigger["starter_agent_id"] is None:
            logger.warning("No active starter agent configured; skipping conversation")
            return

        max_turns = phase.config.get("max_turns", 15)
        required_agents = set(self._active_required_agents(phase))

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
            # Live display of agent dialogue
            _display_agent_speak(agent_id or "?", data)

        async def _on_management(event: dict) -> None:
            self._phase_management_flags += 1
            data = event.get("data", event)
            _display_management_flag(data)

        async def _on_artifact(event: dict) -> None:
            self._phase_artifacts += 1
            data = event.get("data", event)
            tool_name = data.get("tool_name", data.get("artifact_type"))
            if tool_name:
                self._phase_tools_used.add(tool_name)
            _display_artifact(data)

        async def _on_productivity(event: dict) -> None:
            """Boost proactivity for agents in low-productivity conversations (#248)."""
            data = event.get("data", event)
            ratio = data.get("ratio", 1.0)
            participants = data.get("participants", [])
            if ratio < 0.25 and self._services and self._services.goal_manager:
                for agent_id in participants:
                    try:
                        await self._services.goal_manager.add_goal(
                            agent_id=agent_id,
                            goal_text=(
                                "Be more proactive — use tools, write code, "
                                "create tasks, or take concrete actions"
                            ),
                            priority=1,
                            source="assigned",
                            simulation_id=self._simulation_id,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to add proactivity goal for %s",
                            agent_id,
                            exc_info=True,
                        )

        # Check for random events before conversation (#273)
        if self._services and self._services.event_generator:
            try:
                events = await self._services.event_generator.check_and_generate()
                for evt in events:
                    logger.info("Random event injected: [%s] %s", evt.severity, evt.title)
            except Exception:
                logger.warning("Event generation failed", exc_info=True)

        self._event_bus.on("agent_speak", _on_speak)
        self._event_bus.on("management_shadow", _on_management)
        self._event_bus.on("management_warning", _on_management)
        self._event_bus.on("artifact_created", _on_artifact)
        self._event_bus.on("conversation_productivity", _on_productivity)

        try:
            from core.bootstrap import ConversationOptions, InfraServices, MemoryServices
            from core.conversation_engine import ConversationEngine

            engine = ConversationEngine(
                infra=InfraServices(
                    config_loader=self._config_loader,
                    agent_registry=self._agents,
                    event_bus=self._event_bus,
                    llm_client=self._llm,
                    proximity=self._proximity,
                    trigger_system=self._triggers,
                    selection_logger=self._selection_logger,
                ),
                memory=MemoryServices(
                    archival_memory=self._archival,
                    compactor=self._compactor,
                    memory_repo=self._memory_repo,
                ),
                options=ConversationOptions(
                    speed_multiplier=0,  # No delays in simulation
                    management_enabled=False,  # Skip LLM review during sims; eval covers this
                    simulation_id=self._simulation_id,
                    recent_conversation_summaries=list(self._conversation_summaries),
                    recent_outputs=list(self._recent_outputs),
                    required_agents=required_agents if required_agents else None,
                    max_turns=max_turns,
                    debug_prompts=self._debug_prompts,
                    prompt_log_repo=self._prompt_log_repo,
                    topic_history=dict(self._topic_history),
                    factions=list(self._factions) if self._factions else None,
                ),
                management=self._management,
                context_assembler=self._context,
                conversation_repo=self._conversation_repo,
                services=self._services,
                clock=self._clock,
                relationship_tracker=self._relationship_tracker,
            )

            engine._running = True
            await engine._start_conversation(trigger)

            turn = 0
            while engine.active_conversation and engine.is_running and turn < max_turns:
                should_continue = await engine._continue_conversation()
                turn += 1
                if not should_continue:
                    break

            if engine.active_conversation:
                await engine._end_conversation()

        finally:
            self._event_bus.off("agent_speak", _on_speak)
            self._event_bus.off("management_shadow", _on_management)
            self._event_bus.off("management_warning", _on_management)
            self._event_bus.off("artifact_created", _on_artifact)
            self._event_bus.off("conversation_productivity", _on_productivity)

        # Collect structured conversation record for cross-phase context (#271)
        if engine.active_conversation is None and engine.last_conversation_record:
            record = engine.last_conversation_record
            self._conversation_records.append(record)
            _summary = record.format_for_context()
            # Truncate long summaries to prevent context bloat (~150 tokens ≈ 600 chars)
            if len(_summary) > 600:
                _summary = _summary[:597] + "..."
            self._conversation_summaries.append(_summary)

            # Seed unresolved tensions as trigger events for future conversations
            for tension in record.unresolved_tensions[:2]:
                self._triggers.queue_event(
                    "tension",
                    {
                        "text": tension,
                        "from_participants": record.participants,
                    },
                )
        elif engine.active_conversation is None and engine.last_conversation_summary:
            _raw = engine.last_conversation_summary
            if len(_raw) > 600:
                _raw = _raw[:597] + "..."
            self._conversation_summaries.append(_raw)

        # Collect recent outputs for repetition detection
        self._recent_outputs.extend(engine.recent_outputs)

        # Merge topic history so future conversations know what was discussed
        for topic, timestamps in engine.topic_history.items():
            if topic not in self._topic_history:
                self._topic_history[topic] = []
            self._topic_history[topic].extend(timestamps)

        # Accumulate stats
        self._phase_conversations += 1
        self._phase_turns += turns_in_conv
        self._phase_cost += cost_in_conv
        self._phase_tokens += tokens_in_conv
        self._phase_agents.update(agents_in_conv)

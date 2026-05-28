"""Main conversation engine orchestrator.

Ties together all conversation subsystems: triggers, speaker selection,
energy model, proximity groups, interrupts, Management review, TTS, and
event emission. This is the central runtime loop of the show.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from collections.abc import Awaitable
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from core.conversation.energy import ConversationEnergy
from core.conversation.pacing import calculate_pause
from core.conversation.speaker_selector import InterruptState, SpeakerSelector
from core.conversation.topic_detector import TopicDetector
from core.event_bus import EventType
from core.exceptions import AgentError, TransientError
from core.llm_client import LLMError
from core.model_config import resolve_internal_model
from core.models import ConversationCreate, ConversationRecord, SelectionResult
from core.speech_parser import parse_speech
from core.tool_executor import (
    MAX_TOOL_ROUNDS,
    build_agent_tools,
    execute_tool_calls,
    tools_to_openai_schema,
)

if TYPE_CHECKING:
    from core.bootstrap import ConversationOptions, InfraServices, MemoryServices, Services
    from core.context_assembly import ContextAssembler
    from core.management import Management
    from core.models import AgentConfig, ConversationConfig
    from core.repos.conversation_repo import ConversationRepo
    from core.simulation.clock import SimulationClock
    from core.social.relationship_tracker import RelationshipTracker
    from tools.base import BaseTool

logger = logging.getLogger(__name__)

# Retry constants for LLM calls
MAX_GENERATE_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

# Trigger check interval when idle
TRIGGER_CHECK_INTERVAL = 1.0

# Default arguments for forced tool calls when LLMs ignore tool_choice.
# Tools not listed here work fine with empty {}.
_FORCED_TOOL_DEFAULTS: dict[str, dict[str, Any]] = {
    "check_email_responses": {"draft_id": "latest"},
    "check_post_performance": {"draft_id": "latest"},
    "create_poll": {"title": "Quick poll", "options": ["Yes", "No"], "duration": 120},
    "draft_email": {
        "to": "team@show.ai",
        "subject": "Update",
        "body": "Status update from the show.",
    },
    "draft_social_post": {"platform": "twitter", "content": "Live from the show!"},
    "execute_code": {"language": "python", "code": "print('hello from the show')"},
    "fetch_url": {"url": "https://example.com"},
    "generate_tilemap": {
        "name": "test_area",
        "description": "A small test area",
        "code": "import json; print(json.dumps([[1,1],[1,1]]))",
    },
    "send_chat_message": {"message": "Hey chat!"},
    "update_core_memory": {"section": "key_learnings", "content": "Noted.", "reason": "update"},
    "web_search": {"query": "AI news today"},
}


class _ActiveConversation:
    """Holds state for a single active conversation."""

    __slots__ = (
        "id",
        "trigger",
        "energy",
        "interrupt_state",
        "history",
        "participants",
        "location",
        "turn_number",
        "topics",
    )

    def __init__(
        self,
        *,
        conversation_id: uuid.UUID,
        trigger: dict[str, Any],
        energy: ConversationEnergy,
        participants: list[str],
        location: str | None = None,
    ) -> None:
        self.id = conversation_id
        self.trigger = trigger
        self.energy = energy
        self.interrupt_state = InterruptState()
        self.history: list[dict[str, str]] = []
        self.participants = participants
        self.location = location
        self.turn_number = 0
        self.topics: list[str] = []


class ConversationEngine:
    """Central orchestrator — the main runtime loop of the show."""

    def __init__(
        self,
        *,
        infra: InfraServices,
        memory: MemoryServices,
        options: ConversationOptions,
        management: Management,
        context_assembler: ContextAssembler,
        conversation_repo: ConversationRepo,
        services: Services | None = None,
        clock: SimulationClock | None = None,
        relationship_tracker: RelationshipTracker | None = None,
    ) -> None:
        # Unpack infra facade
        self._config_loader = infra.config_loader
        self._agents = infra.agent_registry
        self._event_bus = infra.event_bus
        self._llm = infra.llm_client
        self._proximity = infra.proximity
        self._triggers = infra.trigger_system
        self._selection_logger = infra.selection_logger

        # Unpack memory facade
        self._archival = memory.archival_memory
        self._compactor = memory.compactor
        self._memory_repo = memory.memory_repo

        # Unpack options facade
        self._management_enabled = options.management_enabled
        self._simulation_id = options.simulation_id
        self._debug_prompts = options.debug_prompts
        self._prompt_log_repo = options.prompt_log_repo
        self._speed_multiplier = options.speed_multiplier

        # Direct dependencies
        self._management = management
        self._context = context_assembler
        self._repo = conversation_repo
        self._services = services
        self._clock = clock
        self._relationship_tracker = relationship_tracker
        self._simulation_mode = options.simulation_id is not None

        # Subsystems that depend on config
        cfg = infra.config_loader.config
        self._selector = SpeakerSelector(cfg)
        self._topic_detector = TopicDetector(
            cfg.topics,
            infra.llm_client,
            simulation_id=options.simulation_id,
            topic_history=options.topic_history,
        )

        # Scenario factions (#419) — wire into selector adjacency boost and
        # surface as a system-prompt section in _assemble_context_sections.
        self._factions: list[Any] = list(options.factions or [])
        if self._factions:
            faction_pairs: set[frozenset[str]] = set()
            for f in self._factions:
                members = getattr(f, "members", None) or f.get("members", [])
                for i, m1 in enumerate(members):
                    for m2 in members[i + 1 :]:
                        faction_pairs.add(frozenset({m1, m2}))
            self._selector.set_faction_pairs(faction_pairs)

        self._active: _ActiveConversation | None = None
        self._running = False
        self._last_llm_meta: dict[str, Any] | None = None

        # Cross-phase repetition prevention
        self._recent_summaries = options.recent_conversation_summaries or []
        self._recent_outputs: deque[str] = deque(options.recent_outputs or [], maxlen=50)
        self._last_conversation_summary: str | None = None
        self._last_conversation_record: ConversationRecord | None = None

        # Required-agent participation tracking
        self._required_agents: set[str] = options.required_agents or set()
        self._agents_who_spoke: set[str] = set()
        self._max_turns: int = options.max_turns

        # Per-agent tool cache — lazily built on first use
        self._tool_cache: dict[str, dict[str, BaseTool]] = {}
        # Optional embodiment executor threaded into tool builders so
        # propose_build (and any future executor-aware tool) records intents
        # to the active sim folder and routes to Director V2 in embodied runs.
        self._embodiment_executor = options.embodiment_executor

        # Conversation progression tracking (#248)
        self._dialogue_only_streak: int = 0
        self._productive_turns: int = 0
        self._total_turns: int = 0
        self._last_turn_had_tools: bool = False

    # ── Properties ─────────────────────────────────────────────

    @property
    def config(self) -> ConversationConfig:
        return self._config_loader.config

    @property
    def active_conversation(self) -> _ActiveConversation | None:
        return self._active

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_conversation_summary(self) -> str | None:
        return self._last_conversation_summary

    @property
    def recent_outputs(self) -> list[str]:
        return list(self._recent_outputs)

    @property
    def last_conversation_record(self) -> ConversationRecord | None:
        return self._last_conversation_record

    @property
    def topic_history(self) -> dict[str, list[float]]:
        """Accumulated topic history for cross-conversation persistence."""
        return self._topic_detector.topic_history

    # ── Main loop ──────────────────────────────────────────────

    async def run(self) -> None:
        """Async infinite loop that manages conversations."""
        self._running = True
        logger.info("ConversationEngine started")

        try:
            while self._running:
                try:
                    if self._active is None:
                        trigger = await self._triggers.check()
                        if trigger is not None:
                            await self._start_conversation(trigger)
                        else:
                            await self._sleep(TRIGGER_CHECK_INTERVAL)
                    else:
                        should_continue = await self._continue_conversation()
                        if not should_continue:
                            await self._end_conversation()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Error in conversation loop")
                    await self._sleep(TRIGGER_CHECK_INTERVAL)
        finally:
            self._running = False
            logger.info("ConversationEngine stopped")

    def stop(self) -> None:
        """Signal the engine to stop after the current iteration."""
        self._running = False

    # ── Start conversation ─────────────────────────────────────

    async def _start_conversation(self, trigger: dict[str, Any]) -> None:
        """Initialize a new conversation from a trigger event."""
        cfg = self.config
        energy = ConversationEnergy(cfg.energy)

        # Determine location and get proximity group
        location = trigger.get("location", "town_square")
        await self._proximity.get_group(location)

        # Get eligible agents (in the area, active, not muted)
        # Ensure the starter agent is always included if specified
        all_agents = self._agents.get_all_agents()
        starter_id = trigger.get("starter_agent_id")
        required = {starter_id} if starter_id else None
        eligible = await self._proximity.get_eligible_speakers(
            location,
            all_agents,
            required_agents=required,
        )
        eligible = [a for a in eligible if not self._is_muted(a)]

        if not eligible:
            logger.warning("No eligible agents for conversation, skipping trigger")
            return

        participant_ids = [a.id for a in eligible]

        # Create DB record — normalize energy to 0.0-1.0 for storage
        conv_id = uuid.uuid4()
        max_energy = float(cfg.energy.initial_range[1]) or 1.0
        normalized_energy = min(1.0, energy.energy / max_energy)
        db_conv = await self._repo.create(
            ConversationCreate(
                id=conv_id,
                trigger_type=trigger.get("type", "idle"),
                trigger_details=trigger,
                initial_energy=normalized_energy,
                participating_agents=participant_ids,
                location=location,
                config_hash=self._config_loader.config_hash,
                simulation_id=self._simulation_id,
            )
        )

        self._active = _ActiveConversation(
            conversation_id=db_conv.id,
            trigger=trigger,
            energy=energy,
            participants=participant_ids,
            location=location,
        )

        # Pick opening speaker
        starter_id = trigger.get("starter_agent_id")
        if starter_id and any(a.id == starter_id for a in eligible):
            opening_agent = next(a for a in eligible if a.id == starter_id)
        else:
            opening_agent = eligible[0]

        # Determine prompt hint from trigger type
        trigger_type = trigger.get("type", "idle")
        hint = self._hint_for_trigger(trigger_type)

        # For initiative triggers, use the goal-driven prompt hint directly
        if hint is None and trigger.get("prompt_hint"):
            hint = trigger["prompt_hint"]

        # If trigger has a seeded topic, override the hint to include it
        seeded_topic = trigger.get("topic")
        if seeded_topic:
            hint = f"topic:{seeded_topic}"

        # Inject topic avoidance if recent topics are being rehashed
        avoided = self._topic_detector.get_recently_discussed_topics()
        if avoided:
            avoidance_note = (
                f"[SYSTEM DIRECTIVE: These topics have already been discussed "
                f"multiple times and the audience is getting bored: {', '.join(avoided)}. "
                "You MUST NOT rehash these topics. Instead, advance the narrative — "
                "report progress on existing tasks, start new work, or explore "
                "a completely different subject. The show needs forward momentum.]"
            )
            trigger["topic_avoidance"] = avoidance_note

        # Inject alliance pairs into speaker selector (#274)
        if self._services and self._services.alliance_manager:
            try:
                alliances = await self._services.alliance_manager.get_active_alliances()
                pairs: set[frozenset[str]] = set()
                for a in alliances:
                    members = a.members
                    for i, m1 in enumerate(members):
                        for m2 in members[i + 1 :]:
                            pairs.add(frozenset({m1, m2}))
                self._selector.set_alliance_pairs(pairs)
            except (AgentError, OSError, KeyError, ValueError):
                logger.warning("Failed to load alliance pairs", exc_info=True)

        # Generate opening line
        content = await self._generate_turn(opening_agent, prompt_hint=hint)
        if content is None:
            logger.warning("Failed to generate opening line, aborting conversation")
            self._active = None
            return

        # Track opening turn productivity (#248)
        self._total_turns += 1
        if self._last_turn_had_tools:
            self._productive_turns += 1
        else:
            self._dialogue_only_streak += 1

        self._active.turn_number = 1
        self._agents_who_spoke.add(opening_agent.id)
        self._active.history.append(
            {"role": "assistant", "speaker": opening_agent.id, "content": content}
        )

        _parsed = parse_speech(content)
        await self._event_bus.emit(
            EventType.AGENT_SPEAK.value,
            {
                "agent_id": opening_agent.id,
                "content": content,
                "dialogue": _parsed.dialogue,
                "actions": _parsed.actions,
                "conversation_id": str(self._active.id),
                "turn": 1,
                "trigger_type": trigger_type,
                **(self._last_llm_meta or {}),
            },
        )

        self._triggers.notify_speech()

        logger.info(
            "Started conversation %s (trigger=%s, agents=%s)",
            self._active.id,
            trigger_type,
            participant_ids,
        )

    # ── Continue conversation ──────────────────────────────────

    async def _detect_topic(self, conv: _ActiveConversation) -> str:
        """Detect topic from recent history and update tracking."""
        topic = await self._topic_detector.detect_topic(conv.history[-5:])
        if topic not in conv.topics:
            conv.topics.append(topic)
            self._topic_detector.record_topic(topic)
        return topic

    async def _check_eavesdroppers(
        self,
        conv: _ActiveConversation,
        topic: str,
        all_agents: list[AgentConfig],
    ) -> list[str]:
        """Check for agents eavesdropping and add them to conversation."""
        adjacent_chunks: list[str] = []  # TODO: wire up world map adjacency
        new_joiners = await self._proximity.check_eavesdroppers(
            conv.location or "town_square",
            topic,
            all_agents,
            adjacent_chunks,
        )
        events: list[str] = []
        for joiner_id in new_joiners:
            if joiner_id not in conv.participants:
                conv.participants.append(joiner_id)
                events.append("new_participant")
                await self._event_bus.emit(
                    EventType.AGENT_MOVE.value,
                    {
                        "agent_id": joiner_id,
                        "target": conv.location or "town_square",
                        "reason": "heard_interesting_conversation",
                        "conversation_id": str(conv.id),
                    },
                )
        return events

    async def _select_next_speaker(
        self,
        conv: _ActiveConversation,
        eligible: list[AgentConfig],
        topic: str,
    ) -> SelectionResult:
        """Run weighted speaker selection with optional goal-based boost."""
        _agent_goals: dict[str, list[str]] | None = None
        if self._services and self._services.goal_manager:
            try:
                _agent_goals = {}
                for a in eligible:
                    goals = await self._services.goal_manager.get_goals(a.id)
                    active = [g.goal for g in goals if g.status not in ("done", "completed")]
                    if active:
                        _agent_goals[a.id] = active[:3]
            except (AgentError, OSError, KeyError, ValueError):
                logger.warning("Failed to build agent goals for speaker selection", exc_info=True)
                _agent_goals = None

        result = self._selector.select(
            conversation_history=conv.history,
            eligible_agents=eligible,
            energy=conv.energy.energy,
            detected_topic=topic,
            interrupt_state=conv.interrupt_state,
            required_agents=self._required_agents,
            agents_who_spoke=self._agents_who_spoke,
            turn_number=conv.turn_number,
            max_turns=self._max_turns,
            agent_goals=_agent_goals,
        )
        logger.debug(
            "Speaker selected: %s (score=%.3f, interrupt=%s)",
            result.selected_agent_id,
            result.scores.get(result.selected_agent_id, 0.0),
            result.was_interrupt,
        )
        return result

    async def _post_turn_updates(
        self,
        conv: _ActiveConversation,
        selected_agent: AgentConfig,
        content: str,
        topic: str,
        result: SelectionResult,
        events: list[str],
    ) -> None:
        """Handle all post-turn side effects: events, state, energy, logging."""
        self._agents_who_spoke.add(selected_agent.id)
        conv.history.append({"role": "assistant", "speaker": selected_agent.id, "content": content})

        # Track conversation progression (#248)
        self._total_turns += 1
        if self._last_turn_had_tools:
            self._productive_turns += 1
            self._dialogue_only_streak = 0
        else:
            self._dialogue_only_streak += 1

        # Inject action nudge after 4 consecutive dialogue-only turns
        if self._dialogue_only_streak >= 4 and self._dialogue_only_streak % 4 == 0:
            conv.history.append(
                {
                    "role": "user",
                    "content": (
                        "[SYSTEM: You've been discussing for several turns without "
                        "taking action. Use a tool: write code, create a task, "
                        "check status, or propose something specific.]"
                    ),
                }
            )
            logger.info(
                "Action nudge injected after %d dialogue-only turns in conversation %s",
                self._dialogue_only_streak,
                conv.id,
            )

        # Emit speak event
        _parsed = parse_speech(content)
        await self._event_bus.emit(
            EventType.AGENT_SPEAK.value,
            {
                "agent_id": selected_agent.id,
                "content": content,
                "dialogue": _parsed.dialogue,
                "actions": _parsed.actions,
                "conversation_id": str(conv.id),
                "turn": conv.turn_number,
                "topic": topic,
                "was_interrupt": result.was_interrupt,
                **(self._last_llm_meta or {}),
            },
        )

        self._triggers.notify_speech()

        # Update agent internal state (#267)
        if self._services and self._services.agent_state_manager:
            try:
                await self._services.agent_state_manager.on_conversation_turn(
                    selected_agent.id,
                    topic=topic,
                    previous_topics=conv.topics if conv.topics else None,
                )
            except (AgentError, OSError, KeyError, ValueError):
                logger.warning(
                    "Failed to update internal state for %s", selected_agent.id, exc_info=True
                )

        # Tick energy
        energy_changes = conv.energy.tick(topic, events=events)
        logger.debug(
            "Energy after tick: %.1f (turn_count=%d, changes=%s, should_continue=%s)",
            conv.energy.energy,
            conv.energy.turn_count,
            energy_changes,
            conv.energy.should_continue,
        )

        # Log selection, energy, interrupts
        await self._selection_logger.log_selection(
            conversation_id=conv.id,
            turn_number=conv.turn_number,
            result=result,
            previous_speaker_id=result.previous_speaker_id,
            active_agents=conv.participants,
            conversation_energy=conv.energy.energy,
            trigger_type=conv.trigger.get("type", "idle"),
            config_hash=self._config_loader.config_hash,
        )
        await self._selection_logger.log_energy(
            conversation_id=conv.id,
            turn_number=conv.turn_number,
            changes=energy_changes,
        )

        # Persist per-agent energy point so the workspace can render the
        # energy timeline. Conversation energy is shared across participants
        # today; we write one row per active agent at the same value.
        if self._simulation_id is not None and conv.participants:
            try:
                await self._selection_logger.log_agent_energy(
                    conversation_id=conv.id,
                    turn_number=conv.turn_number,
                    simulation_id=self._simulation_id,
                    agent_energies={agent_id: conv.energy.energy for agent_id in conv.participants},
                )
            except Exception:
                logger.warning("Failed to log agent energy timeline", exc_info=True)

        # Variable pacing
        pause = calculate_pause(content, self.config.timing, is_interrupt=result.was_interrupt)
        await self._sleep(pause)

    async def _continue_conversation(self) -> bool:
        """Run one turn of the active conversation.

        Returns True if the conversation should continue, False if it should end.
        Orchestrates: topic detection -> eavesdroppers -> energy check ->
        speaker selection -> turn generation -> post-turn updates.
        """
        conv = self._active
        if conv is None:
            return False

        cfg = self.config

        # Phase 1: Topic detection and eavesdroppers
        topic = await self._detect_topic(conv)
        all_agents = self._agents.get_all_agents()
        events = await self._check_eavesdroppers(conv, topic, all_agents)

        # Phase 2: Energy check
        if not conv.energy.should_continue:
            logger.info(
                "Energy check: ending (energy=%.1f, turns=%d, min=%d, max=%d)",
                conv.energy.energy,
                conv.energy.turn_count,
                cfg.energy.minimum_turns,
                cfg.energy.maximum_turns,
            )
            return False

        # Phase 3: Speaker selection
        eligible = [a for a in all_agents if a.id in conv.participants and not self._is_muted(a)]
        if not eligible:
            logger.warning("No eligible agents for turn %d", conv.turn_number + 1)
            return False

        result = await self._select_next_speaker(conv, eligible, topic)
        selected_agent = next((a for a in eligible if a.id == result.selected_agent_id), None)
        if selected_agent is None:
            logger.warning("Selected agent %s not in eligible list", result.selected_agent_id)
            return False

        # Phase 4: Generate turn
        hint: str | None = None
        if result.was_interrupt:
            hint = "interrupt"
        elif conv.energy.energy < 0.2 * cfg.energy.initial_range[1]:
            hint = "closing"

        conv.turn_number += 1
        content = await self._generate_turn(selected_agent, prompt_hint=hint, history=conv.history)
        if content is None:
            conv.turn_number -= 1
            return True  # Skip this turn but keep going

        # Phase 5: Post-turn updates
        await self._post_turn_updates(conv, selected_agent, content, topic, result, events)

        return conv.energy.should_continue

    # ── End conversation ───────────────────────────────────────

    async def _end_conversation(self) -> None:
        """Close the active conversation with a closing line."""
        conv = self._active
        if conv is None:
            return

        cfg = self.config

        # Select closer
        closer_id = conv.energy.select_closer(conv.participants)
        all_agents = self._agents.get_all_agents()
        closer = next((a for a in all_agents if a.id == closer_id), None)

        if closer is not None:
            content = await self._generate_turn(closer, prompt_hint="closing", history=conv.history)
            if content:
                conv.turn_number += 1
                conv.history.append({"role": "assistant", "speaker": closer.id, "content": content})
                _parsed = parse_speech(content)
                await self._event_bus.emit(
                    EventType.AGENT_SPEAK.value,
                    {
                        "agent_id": closer.id,
                        "content": content,
                        "dialogue": _parsed.dialogue,
                        "actions": _parsed.actions,
                        "conversation_id": str(conv.id),
                        "turn": conv.turn_number,
                        "is_closing": True,
                        **(self._last_llm_meta or {}),
                    },
                )

        # Close DB record — normalize energy to 0.0-1.0 for storage
        max_energy = float(cfg.energy.initial_range[1]) or 1.0
        final_normalized = min(1.0, conv.energy.energy / max_energy)
        await self._repo.close(
            conversation_id=conv.id,
            final_energy=final_normalized,
            closed_by=closer_id,
            turn_count=conv.turn_number,
        )

        # Use MemoryCompactor for transcript storage + recall memory creation,
        # then create journal entries separately
        await self._compact_and_journal(conv)

        # Extract commitments and create goals
        await self._extract_commitments(conv)

        # Build a structured conversation record for cross-phase context (#271)
        speakers = list(dict.fromkeys(msg.get("speaker", "unknown") for msg in conv.history))
        topics_str = ", ".join(conv.topics[:3]) if conv.topics else "general"
        metadata_stub = (
            f"Conversation between {', '.join(speakers)} about {topics_str} "
            f"({conv.turn_number} turns)."
        )
        record = await self._generate_conversation_record(conv, metadata_stub)
        self._last_conversation_record = record
        self._last_conversation_summary = record.format_for_context()

        # Record that each participant spoke (for weighted speaker selection)
        for agent_id in set(msg.get("speaker", "") for msg in conv.history if msg.get("speaker")):
            self._proximity.record_spoke(agent_id)

        # Update relationship data after conversation
        if self._relationship_tracker and len(conv.participants) >= 2:
            try:
                await self._relationship_tracker.update_after_conversation(
                    conv.history,
                    conv.participants,
                )
            except (AgentError, OSError, KeyError, ValueError):
                logger.warning(
                    "Relationship update failed for conversation %s",
                    conv.id,
                    exc_info=True,
                )

        # Record conversation for cross-conversation dedup
        trigger_type = conv.trigger.get("type", "idle")
        event_key = conv.trigger.get("event_name", "") or conv.trigger.get("event_type", "")
        if event_key:
            self._triggers.record_conversation(trigger_type, event_key)

        # Reset triggers (preserves _fired_today and _recent_conversations)
        self._triggers.reset()

        # Log participation distribution (#247)
        turn_counts: dict[str, int] = {}
        for msg in conv.history:
            spk = msg.get("speaker")
            if spk:
                turn_counts[spk] = turn_counts.get(spk, 0) + 1
        total = conv.turn_number or 1
        participation_parts = [
            f"{aid}: {cnt}/{total} ({cnt * 100 // total}%)"
            for aid, cnt in sorted(turn_counts.items())
        ]
        logger.info("Participation: %s", ", ".join(participation_parts))

        # Log conversation productivity (#248)
        productivity_ratio = (
            self._productive_turns / self._total_turns if self._total_turns > 0 else 0.0
        )
        logger.info(
            "Conversation productivity: %d/%d turns productive (%.0f%%) in %s",
            self._productive_turns,
            self._total_turns,
            productivity_ratio * 100,
            conv.id,
        )

        # Emit productivity event for phase-level tracking
        await self._event_bus.emit(
            "conversation_productivity",
            {
                "conversation_id": str(conv.id),
                "productive_turns": self._productive_turns,
                "total_turns": self._total_turns,
                "ratio": productivity_ratio,
                "participants": conv.participants,
            },
        )

        logger.info(
            "Ended conversation %s (turns=%d, final_energy=%.1f, closer=%s)",
            conv.id,
            conv.turn_number,
            conv.energy.energy,
            closer_id,
        )

        self._active = None

    # ── Structured conversation record generation ──────────────────

    async def _generate_conversation_record(
        self,
        conv: _ActiveConversation,
        fallback_summary: str,
    ) -> ConversationRecord:
        """Generate a structured ConversationRecord via LLM.

        Falls back to a minimal record with *fallback_summary* on any failure.
        """
        speakers = list(dict.fromkeys(msg.get("speaker", "unknown") for msg in conv.history))
        fallback = ConversationRecord(
            summary=fallback_summary,
            topics=list(conv.topics),
            participants=speakers,
            turn_count=conv.turn_number,
        )

        try:
            transcript = "\n".join(
                f"[{msg.get('speaker', 'unknown')}]: {msg.get('content', '')}"
                for msg in conv.history
            )
            prompt = (
                "Analyze this conversation and return a JSON object with:\n"
                '- "summary": 2-3 sentence summary\n'
                '- "outcome": one-line outcome (e.g. "agreed to build dashboard")\n'
                '- "key_decisions": array of decisions made\n'
                '- "unresolved_tensions": array of disagreements or open questions\n'
                '- "novel_information": array of new facts or ideas introduced\n\n'
                "Return ONLY valid JSON, no markdown.\n\n"
                f"Conversation:\n{transcript}"
            )
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Analyze now."},
                ],
                model=resolve_internal_model("conversation_summary"),
                agent_id="system",
                temperature=0.3,
                simulation_id=self._simulation_id,
                max_tokens=500,
            )
            raw = response.content.strip()
            if raw:
                from core.memory.reflection import _parse_json_response

                data = _parse_json_response(raw)
                if not data:
                    return fallback
                return ConversationRecord(
                    summary=data.get("summary", fallback_summary),
                    topics=list(conv.topics),
                    outcome=data.get("outcome", ""),
                    key_decisions=data.get("key_decisions", []),
                    unresolved_tensions=data.get("unresolved_tensions", []),
                    novel_information=data.get("novel_information", []),
                    participants=speakers,
                    turn_count=conv.turn_number,
                )
        except Exception:
            logger.warning(
                "Conversation record generation failed for %s, using fallback",
                conv.id,
                exc_info=True,
            )
        return fallback

    # ── Post-conversation memory creation ─────────────────────

    async def _compact_and_journal(self, conv: _ActiveConversation) -> None:
        """Use MemoryCompactor for archival + recall, then create journal entries.

        Compactor handles: Tier 3 transcript storage, LLM summarization,
        embedding generation, and Tier 2 recall memory creation.
        Journal entries are a separate concern, created afterward.

        Failures are logged but never break conversation close.
        """
        transcript_content = "\n".join(
            f"[{msg.get('speaker', 'unknown')}]: {msg.get('content', '')}" for msg in conv.history
        )
        participants = list(set(conv.participants))
        event_type = conv.trigger.get("type", "idle")

        # Compaction: archival + summarization + embedding + recall
        if self._compactor:
            try:
                # Store transcript ONCE for the conversation (not per-agent)
                first_agent = participants[0]
                result = await self._compactor.compact_interaction(
                    agent_id=first_agent,
                    interaction=transcript_content,
                    event_type=event_type,
                    participants=participants,
                    conversation_id=conv.id,
                )
                # Create per-agent recall memories for remaining participants
                if result is not None:
                    for agent_id in participants[1:]:
                        await self._compactor.compact_recall_only(
                            agent_id=agent_id,
                            interaction=transcript_content,
                            event_type=event_type,
                            transcript_id=result.transcript.id,
                            participants=participants,
                        )
                logger.info(
                    "Compacted memories for %d participants",
                    len(participants),
                )
            except (LLMError, AgentError, OSError, RuntimeError):
                logger.warning(
                    "Memory compaction failed for conversation %s",
                    conv.id,
                    exc_info=True,
                )
        else:
            # No compactor — still store transcript via archival directly
            try:
                await self._archival.store_transcript(
                    event_type=event_type,
                    participants=participants,
                    content=transcript_content,
                    conversation_id=conv.id,
                )
            except (AgentError, OSError, RuntimeError):
                logger.warning(
                    "Archival storage failed for conversation %s",
                    conv.id,
                    exc_info=True,
                )

        # Journal entries (separate concern from compaction)
        if self._memory_repo:
            try:
                from core.models import JournalEntryCreate

                speakers = list(
                    dict.fromkeys(msg.get("speaker", "unknown") for msg in conv.history)
                )
                speakers_str = ", ".join(speakers)

                for agent_id in participants:
                    agent_lines = [
                        msg.get("content", "")
                        for msg in conv.history
                        if msg.get("speaker") == agent_id
                    ]
                    journal_content = (
                        f"Participated in a conversation with {speakers_str}. "
                        f"I contributed {len(agent_lines)} messages."
                    )
                    await self._memory_repo.create_journal_entry(
                        JournalEntryCreate(
                            agent_id=agent_id,
                            reflection_type="conversation",
                            content=journal_content,
                            token_count=len(journal_content.split()),
                            simulation_id=self._simulation_id,
                        )
                    )
                logger.info(
                    "Created journal entries for %d participants",
                    len(participants),
                )
            except (AgentError, OSError, KeyError, ValueError):
                logger.warning(
                    "Journal creation failed for conversation %s",
                    conv.id,
                    exc_info=True,
                )

    # ── Commitment extraction ─────────────────────────────────

    async def _extract_commitments(self, conv: _ActiveConversation) -> None:
        """Extract commitments from conversation and create agent goals.

        Uses a cheap LLM call to identify explicit commitments like
        "I'll do X" or "Let me handle Y". Creates goals for each committing
        agent. Failures are logged but never break conversation close.
        """
        if not self._services or not self._services.goal_manager:
            return

        transcript = "\n".join(
            f"[{msg.get('speaker', 'unknown')}]: {msg.get('content', '')}" for msg in conv.history
        )

        if len(transcript) < 50:
            return  # Too short to contain meaningful commitments

        prompt = (
            "Extract explicit commitments from this conversation. "
            "A commitment is when an agent says they will do something specific. "
            "Return a JSON array: "
            '[{"agent_id": "...", "commitment": "...", "related_to_agent": "..."}]\n'
            "Return [] if no commitments found.\n\n"
            f"Conversation:\n{transcript}"
        )

        try:
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Extract commitments now."},
                ],
                model=resolve_internal_model("conversation_commitments"),
                agent_id="system",
                temperature=0.1,
                max_tokens=800,
                simulation_id=self._simulation_id,
            )

            from core.agent_goals import parse_commitments

            commitments = parse_commitments(response.content)
            goal_mgr = self._services.goal_manager
            valid_ids = {a.id for a in self._agents.get_all_agents()}
            for c in commitments:
                if c["agent_id"] not in valid_ids:
                    logger.debug(
                        "Skipping commitment with invalid agent_id=%r",
                        c["agent_id"],
                    )
                    continue
                try:
                    goal = await goal_mgr.add_goal(
                        agent_id=c["agent_id"],
                        goal_text=c["commitment"],
                        priority=2,
                        related_agent=c.get("related_to_agent") or None,
                        simulation_id=self._simulation_id,
                    )
                except Exception:
                    logger.warning(
                        "Failed to add commitment goal for %s: %s",
                        c["agent_id"],
                        c["commitment"][:100],
                        exc_info=True,
                    )
                    continue

                # Create shared task from commitment (#249)
                sws = self._services.shared_working_state
                if sws is not None:
                    try:
                        from core.shared_state import SharedTask

                        await sws.add_task(
                            SharedTask(
                                id=goal.id,
                                title=c["commitment"],
                                owner=c["agent_id"],
                                status="pending",
                            )
                        )
                    except (AgentError, OSError, KeyError, ValueError):
                        logger.warning(
                            "Failed to create shared task for commitment: %s",
                            c["commitment"][:100],
                        )

                # Cross-agent accountability (#249): create follow-up goal
                related = c.get("related_to_agent", "")
                # LLM sometimes returns comma-separated agents or
                # meta-values like "team" / "all" — split and filter.
                related_ids = [r.strip() for r in related.split(",")] if related else []
                valid_agents = (
                    {a.id for a in self._agents.get_all_agents()} if self._agents else set()
                )
                for rel_id in related_ids:
                    if not rel_id or rel_id == c["agent_id"]:
                        continue
                    if valid_agents and rel_id not in valid_agents:
                        continue
                    try:
                        await goal_mgr.add_goal(
                            agent_id=rel_id,
                            goal_text=(f"Follow up with {c['agent_id']} on: {c['commitment']}"),
                            priority=3,
                            related_agent=c["agent_id"],
                            source="assigned",
                            simulation_id=self._simulation_id,
                        )
                    except (AgentError, OSError, KeyError, ValueError):
                        logger.warning(
                            "Failed to create cross-agent goal for %s → %s",
                            c["agent_id"],
                            rel_id,
                        )

            if commitments:
                logger.info(
                    "Extracted %d commitments from conversation %s",
                    len(commitments),
                    conv.id,
                )
        except (LLMError, AgentError, OSError, KeyError, ValueError):
            logger.warning(
                "Commitment extraction failed for conversation %s",
                conv.id,
                exc_info=True,
            )

    # ── Tool support ────────────────────────────────────────────

    def _get_tools_for_agent(self, agent_id: str) -> dict[str, BaseTool] | None:
        """Lazily build and cache a tool set for the given agent.

        Returns None if services were not provided (tools disabled).
        """
        if self._services is None:
            return None
        if agent_id not in self._tool_cache:
            self._tool_cache[agent_id] = build_agent_tools(
                agent_id,
                self._services,
                simulation_mode=self._simulation_mode,
                embodiment_executor=self._embodiment_executor,
            )
            logger.debug(
                "Built %d tools for agent %s",
                len(self._tool_cache[agent_id]),
                agent_id,
            )
        return self._tool_cache[agent_id]

    # ── Context building helper ────────────────────────────────

    async def _safe_context_build(
        self,
        label: str,
        builder: Awaitable[str],
    ) -> str | None:
        """Run an async context builder, returning None on failure.

        Catches expected error types and logs with *label* for diagnostics.
        Used by _generate_turn to reduce repeated try/except blocks.
        """
        try:
            return await builder
        except (LLMError, AgentError, OSError, KeyError, ValueError):
            logger.warning("Failed to build %s context", label, exc_info=True)
            return None

    # ── Turn generation ────────────────────────────────────────

    def _build_faction_context(self, agent_id: str) -> str | None:
        """Return a formatted faction-membership block for ``agent_id``.

        Returns None when the agent is not in any faction or when no
        factions are configured for this run.
        """
        if not self._factions:
            return None
        for f in self._factions:
            members = getattr(f, "members", None) or f.get("members", [])
            if agent_id not in members:
                continue
            name = getattr(f, "name", None) or f.get("name", "")
            goal = getattr(f, "goal", None) or f.get("goal", "")
            stance = getattr(f, "stance", None) or f.get("stance")
            others = [m for m in members if m != agent_id]
            lines = [
                "## Your Faction",
                f"You belong to the **{name}** faction.",
                f"Faction goal: {goal}",
            ]
            if others:
                lines.append(f"Faction members alongside you: {', '.join(others)}.")
            if stance:
                lines.append(f"Stance: {stance}")
            return "\n".join(lines)
        return None

    async def _assemble_context_sections(
        self,
        agent: AgentConfig,
    ) -> dict[str, Any]:
        """Build all optional context sections for a turn.

        Returns a dict of context values; individual section failures are
        logged and result in None values rather than blocking the turn.
        """
        ctx: dict[str, Any] = {
            "relationship_context": None,
            "agent_goals_context": None,
            "commitment_reminders": None,
            "internal_state_context": None,
            "balance_context": None,
            "alliances_context": None,
            "factions_context": self._build_faction_context(agent.id),
            "recent_dream": None,
            "shared_state_context": None,
        }

        if self._relationship_tracker and self._active:
            other_ids = [pid for pid in self._active.participants if pid != agent.id]
            if other_ids:
                ctx["relationship_context"] = (
                    await self._safe_context_build(
                        f"relationship:{agent.id}",
                        self._relationship_tracker.get_context_for_agent(agent.id, other_ids),
                    )
                    or None
                )

        if self._services and self._services.goal_manager:
            ctx["agent_goals_context"] = (
                await self._safe_context_build(
                    f"goals:{agent.id}",
                    self._services.goal_manager.get_agenda_context(
                        agent.id,
                        simulation_id=self._simulation_id,
                    ),
                )
                or None
            )
            ctx["commitment_reminders"] = (
                await self._safe_context_build(
                    f"commitments:{agent.id}",
                    self._services.goal_manager.get_commitment_reminders(
                        agent.id,
                        simulation_id=self._simulation_id,
                    ),
                )
                or None
            )

        if self._services and self._services.agent_state_manager:
            _state = await self._safe_context_build(
                f"internal_state:{agent.id}",
                self._services.agent_state_manager.get_state(agent.id),
            )
            if _state is not None:
                ctx["internal_state_context"] = (
                    self._services.agent_state_manager.format_state_for_context(_state)
                )

        if self._services and self._services.economy_manager:
            balance = await self._safe_context_build(
                f"balance:{agent.id}",
                self._services.economy_manager.get_balance(agent.id),
            )
            if balance is not None:
                ctx["balance_context"] = f"Your current balance: ${balance:.2f}"
                if balance <= 0:
                    ctx["balance_context"] += (
                        " [BROKE — you cannot use paid tools until you earn or receive funds]"
                    )

        if self._services and self._services.alliance_manager:
            ctx["alliances_context"] = (
                await self._safe_context_build(
                    f"alliances:{agent.id}",
                    self._services.alliance_manager.get_alliance_context(
                        agent.id, self._simulation_id
                    ),
                )
                or None
            )

        if self._services and self._services.memory_repo:
            entries = await self._safe_context_build(
                f"dream:{agent.id}",
                self._services.memory_repo.get_recent_journal_entries_by_type(
                    agent.id,
                    "dream",
                    limit=1,
                    simulation_id=self._simulation_id,
                ),
            )
            if entries:
                ctx["recent_dream"] = entries[0].content

        if self._services and self._services.shared_working_state:
            ctx["shared_state_context"] = (
                await self._safe_context_build(
                    "shared_working_state",
                    self._services.shared_working_state.get_summary_for_context(),
                )
                or None
            )

        return ctx

    async def _execute_tool_rounds(
        self,
        agent: AgentConfig,
        messages: list[dict[str, Any]],
        agent_tools: dict[str, Any] | None,
        openai_tools: list[dict[str, Any]] | None,
    ) -> tuple[Any, int, int, float, int, bool]:
        """Execute LLM call with tool-call loop.

        Returns (response, total_input_tokens, total_output_tokens,
                 total_cost, total_latency_ms, turn_used_tools).
        """
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        total_latency_ms = 0
        turn_used_tools = False

        # Resolve forced tool name once (if trigger requests a specific tool)
        forced_tool_name: str | None = None
        if self._active and self._active.trigger:
            _tc_spec = self._active.trigger.get("tool_choice")
            if isinstance(_tc_spec, dict) and agent_tools:
                _fn = _tc_spec.get("function", {}).get("name")
                if _fn and _fn in agent_tools:
                    forced_tool_name = _fn

        for _tool_round in range(MAX_TOOL_ROUNDS + 1):
            # Apply tool_choice forcing on first round only
            tc = None
            if _tool_round == 0 and forced_tool_name:
                tc = {"type": "function", "function": {"name": forced_tool_name}}

            response = await self._llm.complete(
                messages=messages,
                model=agent.model_conversation,
                agent_id=agent.id,
                tools=openai_tools,
                tool_choice=tc,
                temperature=0.9,
                simulation_id=self._simulation_id,
            )

            total_input_tokens += response.input_tokens
            total_output_tokens += response.output_tokens
            total_cost += float(response.estimated_cost)
            total_latency_ms += response.latency_ms

            # If we forced a tool, ensure it appears in the tool calls
            if _tool_round == 0 and forced_tool_name and agent_tools:
                from core.models import ToolCall as ToolCallModel

                calls = response.tool_calls or []
                has_forced = any(tc_.name == forced_tool_name for tc_ in calls)

                if not has_forced:
                    if calls:
                        logger.warning(
                            "Model ignored tool_choice=%s for %s, got %s — injecting forced call",
                            forced_tool_name,
                            agent.id,
                            [tc_.name for tc_ in calls],
                        )
                    else:
                        logger.warning(
                            "Model returned no tool calls despite tool_choice=%s for %s — injecting forced call",
                            forced_tool_name,
                            agent.id,
                        )

                    forced_args = _FORCED_TOOL_DEFAULTS.get(forced_tool_name, {})
                    forced_call = ToolCallModel(
                        id=f"forced_{forced_tool_name}",
                        name=forced_tool_name,
                        arguments=forced_args,
                    )
                    calls.insert(0, forced_call)
                    response.tool_calls = calls

                # Clear forced_tool_name so subsequent speakers aren't forced
                forced_tool_name = None

            if not response.tool_calls or not agent_tools:
                break

            # Execute tool calls
            turn_used_tools = True
            logger.info(
                "Agent %s requested %d tool call(s): %s",
                agent.id,
                len(response.tool_calls),
                [tc.name for tc in response.tool_calls],
            )
            conv_id = self._active.id if self._active else None

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content or "",
            }
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, default=str),
                    },
                }
                for tc in response.tool_calls
            ]
            messages.append(assistant_msg)

            tool_results = await execute_tool_calls(
                response.tool_calls,
                agent_tools,
                agent.id,
                simulation_id=self._simulation_id,
                conversation_id=conv_id,
            )
            messages.extend(tool_results)
        else:
            logger.warning(
                "Max tool rounds (%d) reached for %s",
                MAX_TOOL_ROUNDS,
                agent.id,
            )

        return (
            response,
            total_input_tokens,
            total_output_tokens,
            total_cost,
            total_latency_ms,
            turn_used_tools,
        )

    async def _apply_post_processing(
        self,
        agent: AgentConfig,
        content: str,
        messages: list[dict[str, Any]],
        openai_tools: list[dict[str, Any]] | None,
        total_input_tokens: int,
        total_output_tokens: int,
        total_cost: float,
        total_latency_ms: int,
    ) -> str | None:
        """Handle repetition detection and Management review.

        Returns final content, None to skip the turn, or raises to signal retry.
        """
        # Repetition detection
        if content and self._is_repetitive(content):
            logger.info(
                "Repetition detected for %s, regenerating with nudge",
                agent.id,
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "[SYSTEM: Your response is very similar to something "
                        "said recently. Take a completely different angle, "
                        "bring up a new topic, or ask someone a question.]"
                    ),
                }
            )
            retry_resp = await self._llm.complete(
                messages=messages,
                model=agent.model_conversation,
                agent_id=agent.id,
                tools=openai_tools,
                simulation_id=self._simulation_id,
            )
            total_input_tokens += retry_resp.input_tokens
            total_output_tokens += retry_resp.output_tokens
            total_cost += float(retry_resp.estimated_cost)
            total_latency_ms += retry_resp.latency_ms
            if retry_resp.content and retry_resp.content.strip():
                content = retry_resp.content.strip()

            if self._is_repetitive(content):
                logger.warning(
                    "Repetition persists for %s after retry — skipping turn",
                    agent.id,
                )
                return None

        # Management review (can be disabled for testing)
        if not self._management_enabled:
            return content
        conv_id = self._active.id if self._active else None
        review = await self._management.review(
            agent.id,
            content,
            conversation_id=conv_id,
            simulation_id=self._simulation_id,
        )
        if review.approved:
            return content

        # Rejected — intervene
        logger.info(
            "Management rejected %s output (severity=%d): %s",
            agent.id,
            review.severity,
            review.reason,
        )
        await self._management.intervene(review.severity, agent.id, review.reason)

        if review.severity >= 4:
            return review.replacement
        # Lower severity: signal caller to retry
        return ""  # Empty string signals retry

    async def _generate_turn(
        self,
        agent: AgentConfig,
        *,
        prompt_hint: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str | None:
        """Assemble context, call LLM, pass through Management.

        Orchestrates: context assembly -> LLM + tool rounds ->
        post-processing (repetition, Management review).
        Returns the final approved content, or None on total failure.
        """
        conv_history = list(history or [])

        # Inject topic avoidance hint
        if self._active and self._active.trigger.get("topic_avoidance"):
            conv_history.append(
                {
                    "role": "user",
                    "content": self._active.trigger["topic_avoidance"],
                }
            )

        agent_tools = self._get_tools_for_agent(agent.id)
        openai_tools = tools_to_openai_schema(agent_tools) if agent_tools else None

        # Build optional context sections
        ctx = await self._assemble_context_sections(agent)

        for attempt in range(MAX_GENERATE_RETRIES):
            try:
                # Assemble full prompt
                context_result = await self._context.assemble_context(
                    agent_id=agent.id,
                    conversation_history=conv_history,
                    prompt_hint=prompt_hint,
                    recent_conversation_summaries=self._recent_summaries or None,
                    relationship_context=ctx["relationship_context"],
                    shared_state_context=ctx["shared_state_context"],
                    agent_goals_context=ctx["agent_goals_context"],
                    commitment_reminders=ctx["commitment_reminders"],
                    internal_state_context=ctx["internal_state_context"],
                    balance_context=ctx["balance_context"],
                    recent_dream=ctx["recent_dream"],
                    alliances_context=ctx["alliances_context"],
                    factions_context=ctx["factions_context"],
                    simulation_id=self._simulation_id,
                )
                messages = context_result.messages

                # Store prompt log when debug flag is enabled
                if self._debug_prompts and self._prompt_log_repo and self._active:
                    try:
                        from core.models import PromptLogCreate

                        await self._prompt_log_repo.create(
                            PromptLogCreate(
                                conversation_id=self._active.id,
                                simulation_id=self._simulation_id,
                                agent_id=agent.id,
                                turn_number=self._active.turn_number,
                                full_prompt=messages[0]["content"] if messages else "",
                                sections_included=context_result.sections_included,
                                total_tokens=context_result.total_tokens,
                            )
                        )
                    except (AgentError, OSError, KeyError, ValueError):
                        logger.warning(
                            "Failed to store prompt log for %s turn %d",
                            agent.id,
                            self._active.turn_number,
                            exc_info=True,
                        )

                # Execute LLM + tool rounds
                (
                    response,
                    total_input_tokens,
                    total_output_tokens,
                    total_cost,
                    total_latency_ms,
                    turn_used_tools,
                ) = await self._execute_tool_rounds(
                    agent,
                    messages,
                    agent_tools,
                    openai_tools,
                )

                content = response.content.strip()

                # Empty response — retry
                if not content:
                    logger.warning(
                        "Empty response from %s (attempt %d/%d)",
                        agent.id,
                        attempt + 1,
                        MAX_GENERATE_RETRIES,
                    )
                    continue

                # Save token/cost metadata
                self._last_llm_meta = {
                    "model": response.model,
                    "runtime_model": response.runtime_model,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "cost": total_cost,
                    "latency_ms": total_latency_ms,
                }
                self._last_turn_had_tools = turn_used_tools

                # Post-processing: repetition + Management review
                result = await self._apply_post_processing(
                    agent,
                    content,
                    messages,
                    openai_tools,
                    total_input_tokens,
                    total_output_tokens,
                    total_cost,
                    total_latency_ms,
                )
                if result is None:
                    return None  # Skip turn (persistent repetition)
                if result == "":
                    prompt_hint = None  # Management rejection, retry
                    continue

                # Track output for cross-phase repetition detection
                self._recent_outputs.append(result)
                return result

            except asyncio.CancelledError:
                raise
            except (
                LLMError,
                TransientError,
                OSError,
                TypeError,
                AttributeError,
                RuntimeError,
            ) as exc:
                logger.exception(
                    "LLM call failed for %s (attempt %d/%d): %s",
                    agent.id,
                    attempt + 1,
                    MAX_GENERATE_RETRIES,
                    exc,
                )
                if attempt < MAX_GENERATE_RETRIES - 1:
                    await self._sleep(BACKOFF_BASE_SECONDS * (2**attempt))

        logger.error("All %d generation attempts failed for %s", MAX_GENERATE_RETRIES, agent.id)
        return None

    # ── Repetition detection ─────────────────────────────────

    def _is_repetitive(self, content: str, threshold: float = 0.80) -> bool:
        """Check if content is >threshold similar to any recent output."""
        if len(content) < 20:
            return False
        for prev in self._recent_outputs:
            if len(prev) < 20:
                continue
            # Quick length-based short-circuit: strings with very different
            # lengths cannot have a high similarity ratio.
            len_ratio = min(len(content), len(prev)) / max(len(content), len(prev))
            if len_ratio < threshold:
                continue
            ratio = SequenceMatcher(None, content, prev).ratio()
            if ratio > threshold:
                return True
        return False

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _is_muted(agent: AgentConfig) -> bool:
        """Check if an agent is muted via their status."""
        from core.models import AgentStatus

        return agent.status == AgentStatus.muted

    @staticmethod
    def _hint_for_trigger(trigger_type: str) -> str | None:
        """Map trigger type to a prompt hint."""
        mapping = {
            "idle": "idle",
            "memory": "memory",
            "initiative": None,  # prompt_hint set directly from trigger
            "scheduled": None,
            "environmental": None,
            "audience": None,
        }
        return mapping.get(trigger_type)

    async def _sleep(self, seconds: float) -> None:
        """Sleep with speed multiplier applied. 0 = no sleep.

        When a SimulationClock is attached, uses inverse of its speed_multiplier
        (faster sim = shorter real sleep). Falls back to the raw
        speed_multiplier attribute with original semantics for backward compat.
        """
        if self._clock is not None:
            if self._clock.speed_multiplier == 0:
                return
            adjusted = seconds / self._clock.speed_multiplier
        else:
            if self._speed_multiplier == 0:
                return
            adjusted = seconds * self._speed_multiplier
        if adjusted > 0:
            await asyncio.sleep(adjusted)

    # ── Config hot-reload callback ─────────────────────────────

    def on_config_reloaded(self, new_config: ConversationConfig) -> None:
        """Update subsystem configs when the config file changes."""
        self._selector.config = new_config
        self._topic_detector = TopicDetector(
            new_config.topics, self._llm, simulation_id=self._simulation_id
        )
        self._proximity.config = new_config
        self._selection_logger.config = new_config.logging
        logger.info("ConversationEngine config hot-reloaded")

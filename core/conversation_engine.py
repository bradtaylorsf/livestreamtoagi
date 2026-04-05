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
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from core.conversation.energy import ConversationEnergy
from core.conversation.pacing import calculate_pause
from core.conversation.speaker_selector import InterruptState, SpeakerSelector
from core.conversation.topic_detector import TopicDetector
from core.event_bus import EventType
from core.models import ConversationCreate
from core.speech_parser import parse_speech
from core.tool_executor import (
    MAX_TOOL_ROUNDS,
    build_agent_tools,
    execute_tool_calls,
    tools_to_openai_schema,
)

if TYPE_CHECKING:
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
    from core.models import AgentConfig, ConversationConfig
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.memory_repo import MemoryRepo
    from core.simulation.clock import SimulationClock
    from core.social.relationship_tracker import RelationshipTracker
    from tools.base import BaseTool

logger = logging.getLogger(__name__)

# Retry constants for LLM calls
MAX_GENERATE_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

# Trigger check interval when idle
TRIGGER_CHECK_INTERVAL = 1.0


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
        compactor: MemoryCompactor | None = None,
        memory_repo: MemoryRepo | None = None,
        speed_multiplier: float = 1.0,
        management_enabled: bool = True,
        simulation_id: uuid.UUID | None = None,
        services: Services | None = None,
        clock: SimulationClock | None = None,
        relationship_tracker: RelationshipTracker | None = None,
        recent_conversation_summaries: list[str] | None = None,
        recent_outputs: list[str] | None = None,
        required_agents: set[str] | None = None,
        max_turns: int = 15,
    ) -> None:
        self._config_loader = config_loader
        self._agents = agent_registry
        self._event_bus = event_bus
        self._llm = llm_client
        self._management_enabled = management_enabled
        self._management = management
        self._simulation_id = simulation_id
        self._context = context_assembler
        self._repo = conversation_repo
        self._archival = archival_memory
        self._compactor = compactor
        self._memory_repo = memory_repo
        self._proximity = proximity
        self._triggers = trigger_system
        self._selection_logger = selection_logger
        self._speed_multiplier = speed_multiplier
        self._services = services
        self._clock = clock
        self._relationship_tracker = relationship_tracker
        self._simulation_mode = simulation_id is not None

        # Subsystems that depend on config
        cfg = config_loader.config
        self._selector = SpeakerSelector(cfg)
        self._topic_detector = TopicDetector(cfg.topics, llm_client)

        self._active: _ActiveConversation | None = None
        self._running = False
        self._last_llm_meta: dict[str, Any] | None = None

        # Cross-phase repetition prevention
        self._recent_summaries = recent_conversation_summaries or []
        self._recent_outputs: deque[str] = deque(recent_outputs or [], maxlen=15)
        self._last_conversation_summary: str | None = None

        # Required-agent participation tracking
        self._required_agents: set[str] = required_agents or set()
        self._agents_who_spoke: set[str] = set()
        self._max_turns: int = max_turns

        # Per-agent tool cache — lazily built on first use
        self._tool_cache: dict[str, dict[str, BaseTool]] = {}

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
        all_agents = self._agents.get_all_agents()
        eligible = await self._proximity.get_eligible_speakers(location, all_agents)
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

        # If trigger has a seeded topic, override the hint to include it
        seeded_topic = trigger.get("topic")
        if seeded_topic:
            hint = f"topic:{seeded_topic}"

        # Generate opening line
        content = await self._generate_turn(opening_agent, prompt_hint=hint)
        if content is None:
            logger.warning("Failed to generate opening line, aborting conversation")
            self._active = None
            return

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

    async def _continue_conversation(self) -> bool:
        """Run one turn of the active conversation.

        Returns True if the conversation should continue, False if it should end.
        """
        conv = self._active
        if conv is None:
            return False

        cfg = self.config

        # Detect topic from recent history
        topic = await self._topic_detector.detect_topic(conv.history[-5:])
        if topic not in conv.topics:
            conv.topics.append(topic)

        # Check for eavesdroppers joining
        all_agents = self._agents.get_all_agents()
        adjacent_chunks = []  # TODO: wire up world map adjacency
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

        # Check energy before this turn
        if not conv.energy.should_continue:
            logger.info(
                "Energy check: ending (energy=%.1f, turns=%d, min=%d, max=%d)",
                conv.energy.energy,
                conv.energy.turn_count,
                cfg.energy.minimum_turns,
                cfg.energy.maximum_turns,
            )
            return False

        # Get eligible agents for this turn
        eligible = [a for a in all_agents if a.id in conv.participants and not self._is_muted(a)]
        if not eligible:
            logger.warning("No eligible agents for turn %d", conv.turn_number + 1)
            return False

        # Select speaker
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
        )
        logger.debug(
            "Speaker selected: %s (score=%.3f, interrupt=%s)",
            result.selected_agent_id,
            result.scores.get(result.selected_agent_id, 0.0),
            result.was_interrupt,
        )

        selected_agent = next((a for a in eligible if a.id == result.selected_agent_id), None)
        if selected_agent is None:
            logger.warning("Selected agent %s not in eligible list", result.selected_agent_id)
            return False

        # Determine prompt hint
        hint: str | None = None
        if result.was_interrupt:
            hint = "interrupt"
        elif conv.energy.energy < 0.2 * cfg.energy.initial_range[1]:
            hint = "closing"

        # Generate turn
        conv.turn_number += 1
        content = await self._generate_turn(selected_agent, prompt_hint=hint, history=conv.history)
        if content is None:
            conv.turn_number -= 1
            return True  # Skip this turn but keep going

        self._agents_who_spoke.add(selected_agent.id)
        conv.history.append({"role": "assistant", "speaker": selected_agent.id, "content": content})

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

        # Variable pacing
        pause = calculate_pause(content, cfg.timing, is_interrupt=result.was_interrupt)
        await self._sleep(pause)

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

        # Build a rich summary for cross-phase context
        speakers = list(dict.fromkeys(msg.get("speaker", "unknown") for msg in conv.history))
        topics_str = ", ".join(conv.topics[:3]) if conv.topics else "general"
        metadata_stub = (
            f"Conversation between {', '.join(speakers)} about {topics_str} "
            f"({conv.turn_number} turns)."
        )
        self._last_conversation_summary = await self._generate_rich_summary(
            conv,
            metadata_stub,
        )

        # Record that each participant spoke (for weighted speaker selection)
        for agent_id in set(msg.get("speaker", "") for msg in conv.history if msg.get("speaker")):
            self._proximity.record_spoke(agent_id)

        # Update relationship data after conversation
        if self._relationship_tracker and len(conv.participants) >= 2:
            try:
                await self._relationship_tracker.update_after_conversation(
                    conv.history, conv.participants,
                )
            except Exception:
                logger.warning(
                    "Relationship update failed for conversation %s",
                    conv.id,
                    exc_info=True,
                )

        # Reset triggers
        self._triggers.reset()

        logger.info(
            "Ended conversation %s (turns=%d, final_energy=%.1f, closer=%s)",
            conv.id,
            conv.turn_number,
            conv.energy.energy,
            closer_id,
        )

        self._active = None

    # ── Rich summary generation ─────────────────────────────────

    async def _generate_rich_summary(
        self,
        conv: _ActiveConversation,
        fallback: str,
    ) -> str:
        """Generate a rich LLM summary of the conversation.

        Falls back to *fallback* (a simple metadata stub) on any failure.
        """
        try:
            transcript = "\n".join(
                f"[{msg.get('speaker', 'unknown')}]: {msg.get('content', '')}"
                for msg in conv.history
            )
            prompt = (
                "Summarize this conversation in 2-4 sentences covering:\n"
                "- Decisions made\n"
                "- Commitments (who will do what)\n"
                "- Unresolved tensions or disagreements\n"
                "- Open questions\n"
                "- Notable emotional moments\n\n"
                f"Conversation:\n{transcript}"
            )
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Summarize now."},
                ],
                model="anthropic/claude-haiku-4.5",
                agent_id="system",
                temperature=0.3,
                max_tokens=300,
            )
            summary = response.content.strip()
            if summary:
                return summary
        except Exception:
            logger.warning(
                "Rich summary generation failed for conversation %s, falling back to metadata stub",
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
            f"[{msg.get('speaker', 'unknown')}]: {msg.get('content', '')}"
            for msg in conv.history
        )
        participants = list(set(conv.participants))
        event_type = conv.trigger.get("type", "idle")

        # Compaction: archival + summarization + embedding + recall
        if self._compactor:
            try:
                for agent_id in participants:
                    await self._compactor.compact_interaction(
                        agent_id=agent_id,
                        interaction=transcript_content,
                        event_type=event_type,
                        participants=participants,
                        conversation_id=conv.id,
                    )
                logger.info(
                    "Compacted memories for %d participants", len(participants),
                )
            except Exception:
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
            except Exception:
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
                    dict.fromkeys(
                        msg.get("speaker", "unknown") for msg in conv.history
                    )
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
                        )
                    )
                logger.info(
                    "Created journal entries for %d participants",
                    len(participants),
                )
            except Exception:
                logger.warning(
                    "Journal creation failed for conversation %s",
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
                agent_id, self._services, simulation_mode=self._simulation_mode,
            )
            logger.debug(
                "Built %d tools for agent %s",
                len(self._tool_cache[agent_id]),
                agent_id,
            )
        return self._tool_cache[agent_id]

    # ── Turn generation ────────────────────────────────────────

    async def _generate_turn(
        self,
        agent: AgentConfig,
        *,
        prompt_hint: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str | None:
        """Assemble context, call LLM, pass through Management.

        Returns the final approved content, or None on total failure.
        """
        conv_history = history or []

        # Build tool schemas if tools are available for this agent
        agent_tools = self._get_tools_for_agent(agent.id)
        openai_tools = tools_to_openai_schema(agent_tools) if agent_tools else None

        # Build relationship context if tracker is available
        relationship_context: str | None = None
        if self._relationship_tracker and self._active:
            try:
                other_ids = [pid for pid in self._active.participants if pid != agent.id]
                if other_ids:
                    relationship_context = (
                        await self._relationship_tracker.get_context_for_agent(
                            agent.id,
                            other_ids,
                        )
                    ) or None
            except Exception:
                logger.warning(
                    "Failed to build relationship context for %s", agent.id, exc_info=True
                )

        for attempt in range(MAX_GENERATE_RETRIES):
            try:
                # Assemble context
                messages = await self._context.assemble_context(
                    agent_id=agent.id,
                    conversation_history=conv_history,
                    prompt_hint=prompt_hint,
                    recent_conversation_summaries=self._recent_summaries or None,
                    relationship_context=relationship_context,
                )

                # Call LLM (with tool-call loop)
                total_input_tokens = 0
                total_output_tokens = 0
                total_cost = 0.0
                total_latency_ms = 0

                for _tool_round in range(MAX_TOOL_ROUNDS + 1):
                    # Check if trigger requests a specific tool (first round only)
                    # Only apply tool_choice if the tool is in this agent's set
                    tc = None
                    if _tool_round == 0 and self._active and self._active.trigger:
                        tc = self._active.trigger.get("tool_choice")
                        if tc and agent_tools:
                            # Extract tool name from tool_choice structure
                            forced_name = (
                                tc.get("function", {}).get("name")
                                if isinstance(tc, dict) else None
                            )
                            if forced_name and forced_name not in agent_tools:
                                tc = None  # Tool not available for this agent
                        elif tc and not agent_tools:
                            tc = None  # Agent has no tools at all

                    response = await self._llm.complete(
                        messages=messages,
                        model=agent.model_conversation,
                        agent_id=agent.id,
                        tools=openai_tools,
                        tool_choice=tc,
                        temperature=0.9,
                    )

                    total_input_tokens += response.input_tokens
                    total_output_tokens += response.output_tokens
                    total_cost += float(response.estimated_cost)
                    total_latency_ms += response.latency_ms

                    # No tool calls — we have the final text response
                    if not response.tool_calls or not agent_tools:
                        break

                    # Execute tool calls
                    logger.info(
                        "Agent %s requested %d tool call(s): %s",
                        agent.id,
                        len(response.tool_calls),
                        [tc.name for tc in response.tool_calls],
                    )
                    conv_id = self._active.id if self._active else None

                    # Append assistant message with tool calls
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
                                "arguments": json.dumps(
                                    tc.arguments, default=str
                                ),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append(assistant_msg)

                    # Execute tools and append results
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

                content = response.content.strip()

                # Repetition detection — check against recent outputs
                if content and self._is_repetitive(content):
                    logger.info(
                        "Repetition detected for %s, regenerating with nudge",
                        agent.id,
                    )
                    messages.append({
                        "role": "user",
                        "content": (
                            "[SYSTEM: Your response is very similar to something "
                            "said recently. Take a different angle or bring up a "
                            "new topic.]"
                        ),
                    })
                    retry_resp = await self._llm.complete(
                        messages=messages,
                        model=agent.model_conversation,
                        agent_id=agent.id,
                        tools=openai_tools,
                    )
                    total_input_tokens += retry_resp.input_tokens
                    total_output_tokens += retry_resp.output_tokens
                    total_cost += float(retry_resp.estimated_cost)
                    total_latency_ms += retry_resp.latency_ms
                    if retry_resp.content and retry_resp.content.strip():
                        content = retry_resp.content.strip()

                # Empty response — retry
                if not content:
                    logger.warning(
                        "Empty response from %s (attempt %d/%d)",
                        agent.id,
                        attempt + 1,
                        MAX_GENERATE_RETRIES,
                    )
                    continue

                # Save token/cost metadata (accumulated across tool rounds)
                self._last_llm_meta = {
                    "model": response.model,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "cost": total_cost,
                    "latency_ms": total_latency_ms,
                }

                # Track output for cross-phase repetition detection
                self._recent_outputs.append(content)

                # Management review (can be disabled for testing)
                if not self._management_enabled:
                    return content
                conv_id = self._active.id if self._active else None
                review = await self._management.review(
                    agent.id, content,
                    conversation_id=conv_id,
                    simulation_id=self._simulation_id,
                )
                if review.approved:
                    return content

                # Rejected -- intervene and retry with modified hint
                logger.info(
                    "Management rejected %s output (severity=%d): %s",
                    agent.id,
                    review.severity,
                    review.reason,
                )
                await self._management.intervene(review.severity, agent.id, review.reason)

                # If severity is high, don't retry
                if review.severity >= 4:
                    return review.replacement
                # Lower severity: retry with different hint
                prompt_hint = None

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "LLM call failed for %s (attempt %d/%d)",
                    agent.id,
                    attempt + 1,
                    MAX_GENERATE_RETRIES,
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
        self._topic_detector = TopicDetector(new_config.topics, self._llm)
        self._proximity.config = new_config
        self._selection_logger.config = new_config.logging
        logger.info("ConversationEngine config hot-reloaded")

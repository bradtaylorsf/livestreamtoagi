"""Tests for context window assembly (ContextAssembler)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.context_assembly import (
    BUFFER_MIN_MESSAGES,
    CHAT_HIGHLIGHTS_BUDGET,
    MAX_BUDGET,
    PIXEL_AGENT_ID,
    PROMPT_HINTS,
    TYPICAL_BUDGET,
    ContextAssembler,
)
from core.system_prompt import INFRASTRUCTURE_PROMPT
from core.models import AgentConfig, Transcript


# ── Helpers ───────────────────────────────────────────────────────


def _make_agent(agent_id: str = "rex", system_prompt: str = "You are Rex.") -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id.capitalize(),
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        chattiness=0.7,
        initiative=0.7,
        interrupt_tendency=0.3,
        eavesdrop_tendency=0.3,
        closing_weight=0.2,
        system_prompt=system_prompt,
    )


def _make_history(n: int = 10) -> list[dict[str, str]]:
    """Create n conversation messages alternating user/assistant."""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"}
        for i in range(n)
    ]


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def mock_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_agent = MagicMock(return_value=_make_agent())
    return registry


@pytest.fixture
def mock_core_memory() -> AsyncMock:
    mem = AsyncMock()
    mem.get_core_memory = AsyncMock(return_value="## My Core Memory\nI am Rex.")
    return mem


@pytest.fixture
def mock_recall_memory() -> AsyncMock:
    mem = AsyncMock()
    mem.retrieve_recall_memories = AsyncMock(
        return_value="## Relevant memories\n- [conversation] Rex discussed building."
    )
    return mem


@pytest.fixture
def mock_archival_memory() -> AsyncMock:
    mem = AsyncMock()
    mem.retrieve_full_transcript = AsyncMock(
        return_value=Transcript(
            id=1,
            event_type="conversation",
            participants=["rex", "vera"],
            content="Rex: Let's build. Vera: Agreed.",
            token_count=20,
        )
    )
    return mem


@pytest.fixture
def mock_token_counter() -> MagicMock:
    """Token counter that returns 10 tokens per call by default."""
    counter = MagicMock()
    counter.count_tokens = MagicMock(return_value=10)
    return counter


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()

    async def get_side_effect(key: str) -> str | None:
        data = {
            "agent:location:rex": "The Workshop",
            "agent:task:rex": "Building a dashboard",
            "agent:nearby:rex": "vera, aurora",
            "agent:location:pixel": "The Studio",
            "agent:task:pixel": "Relaying chat",
            "agent:nearby:pixel": "fork",
            "chat:highlights": "viewer1: cool!\nviewer2: nice build",
        }
        return data.get(key)

    redis.get = AsyncMock(side_effect=get_side_effect)
    return redis


@pytest.fixture
def assembler(
    mock_registry: MagicMock,
    mock_core_memory: AsyncMock,
    mock_recall_memory: AsyncMock,
    mock_archival_memory: AsyncMock,
    mock_token_counter: MagicMock,
    mock_redis: AsyncMock,
) -> ContextAssembler:
    return ContextAssembler(
        agent_registry=mock_registry,
        core_memory=mock_core_memory,
        recall_memory=mock_recall_memory,
        archival_memory=mock_archival_memory,
        token_counter=mock_token_counter,
        redis_client=mock_redis,
    )


# ── Assembly order tests ─────────────────────────────────────────


class TestAssemblyOrder:
    """Verify sections appear in the correct order in the system message."""

    @pytest.mark.asyncio
    async def test_system_message_contains_all_sections_in_order(
        self, assembler: ContextAssembler
    ) -> None:
        history = _make_history(5)
        messages = (await assembler.assemble_context("rex", history)).messages

        system = messages[0]
        assert system["role"] == "system"
        content = system["content"]

        # Sections should appear in this order:
        # Layer 1 (infrastructure) → Layer 2 (character) → Layer 3 (memory)
        idx_infra = content.find("System Rules")
        idx_prompt = content.find("# Your Character")
        idx_core = content.find("## My Core Memory")
        # Use the actual recall section header (not the infrastructure mention)
        idx_recall = content.find("## Relevant memories")
        idx_world = content.find("## World State")

        assert idx_infra < idx_prompt < idx_core < idx_recall < idx_world
        # All must be present
        assert all(
            i >= 0
            for i in [idx_infra, idx_prompt, idx_core, idx_recall, idx_world]
        )

    @pytest.mark.asyncio
    async def test_conversation_buffer_follows_system_message(
        self, assembler: ContextAssembler
    ) -> None:
        history = _make_history(5)
        messages = (await assembler.assemble_context("rex", history)).messages

        assert messages[0]["role"] == "system"
        # Buffer messages follow (last non-hint user msg is identity reinforcement)
        for msg in messages[1:]:
            assert msg["role"] in ("user", "assistant")
            assert "Message" in msg["content"] or "You are Rex" in msg["content"]

    @pytest.mark.asyncio
    async def test_infrastructure_prompt_is_included(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", [])).messages
        content = messages[0]["content"]
        assert "SURVIVE" in content
        assert "BUILD" in content
        assert "ENTERTAIN" in content
        # Memory instructions from infrastructure layer
        assert "How Your Memory Works" in content
        assert "Behavioral Guardrails" in content


# ── Token budget tests ───────────────────────────────────────────


class TestTokenBudget:
    """Verify token tracking and budget enforcement."""

    @pytest.mark.asyncio
    async def test_buffer_truncated_when_over_budget(
        self,
        mock_registry: MagicMock,
        mock_core_memory: AsyncMock,
        mock_recall_memory: AsyncMock,
        mock_archival_memory: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """When system content uses most of the budget, buffer gets truncated."""
        counter = MagicMock()
        # System content uses 7000 tokens, leaving 1000 for buffer.
        # Section tracking calls count_tokens for each section first,
        # then the assembled system content is counted. We detect the
        # full system content by its length (it's the longest text).

        def count_tokens(text: str) -> int:
            # The assembled system content is much longer than individual sections
            if len(text) > 500:
                return 7000
            return 200

        counter.count_tokens = MagicMock(side_effect=count_tokens)

        asm = ContextAssembler(
            agent_registry=mock_registry,
            core_memory=mock_core_memory,
            recall_memory=mock_recall_memory,
            archival_memory=mock_archival_memory,
            token_counter=counter,
            redis_client=mock_redis,
        )
        history = _make_history(20)
        messages = (await asm.assemble_context("rex", history)).messages

        # Buffer should be truncated: 1000 budget / 200 per msg = 5 messages
        buffer_msgs = [m for m in messages if m["role"] != "system"]
        assert len(buffer_msgs) <= 10  # Significantly fewer than 20
        assert len(buffer_msgs) >= BUFFER_MIN_MESSAGES

    @pytest.mark.asyncio
    async def test_typical_budget_used_without_transcript(
        self, assembler: ContextAssembler
    ) -> None:
        """Without transcript, TYPICAL_BUDGET is used."""
        messages = (await assembler.assemble_context("rex", _make_history(5))).messages
        # Should succeed without errors (budget not exceeded with mock returning 10)
        assert len(messages) > 0

    @pytest.mark.asyncio
    async def test_max_budget_used_with_transcript(
        self, assembler: ContextAssembler
    ) -> None:
        """With transcript_id, MAX_BUDGET is used and transcript is included."""
        messages = (await assembler.assemble_context(
            "rex", _make_history(5), transcript_id=1
        )).messages
        system = messages[0]["content"]
        assert "Full Transcript" in system
        assert "Rex: Let's build" in system


# ── Conversation buffer truncation tests ─────────────────────────


class TestBufferTruncation:
    """Verify conversation buffer truncation behavior."""

    @pytest.mark.asyncio
    async def test_buffer_limited_to_max_messages(
        self, assembler: ContextAssembler
    ) -> None:
        """Buffer is capped at 20 messages before token check."""
        history = _make_history(30)
        messages = (await assembler.assemble_context("rex", history)).messages

        buffer_msgs = [m for m in messages if m["role"] != "system"]
        # +1 for identity reinforcement message
        assert len(buffer_msgs) <= 21

    @pytest.mark.asyncio
    async def test_keeps_newest_messages_when_truncating(
        self,
        mock_registry: MagicMock,
        mock_core_memory: AsyncMock,
        mock_recall_memory: AsyncMock,
        mock_archival_memory: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Truncation drops oldest messages, keeps newest."""
        counter = MagicMock()
        call_count = [0]

        def count_tokens(text: str) -> int:
            call_count[0] += 1
            if call_count[0] == 1:
                return 7500  # System content uses most of budget
            return 200

        counter.count_tokens = MagicMock(side_effect=count_tokens)

        asm = ContextAssembler(
            agent_registry=mock_registry,
            core_memory=mock_core_memory,
            recall_memory=mock_recall_memory,
            archival_memory=mock_archival_memory,
            token_counter=counter,
            redis_client=mock_redis,
        )

        history = _make_history(15)
        messages = (await asm.assemble_context("rex", history)).messages

        buffer_msgs = [m for m in messages if m["role"] != "system"]
        if buffer_msgs:
            # Last non-identity message should be the newest from history
            history_msgs = [m for m in buffer_msgs if "You are Rex" not in m.get("content", "")]
            if history_msgs:
                assert history_msgs[-1]["content"] == "Message 14"

    @pytest.mark.asyncio
    async def test_empty_history_produces_only_system_message(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", [])).messages
        # system + identity reinforcement
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "You are Rex" in messages[1]["content"]


# ── Pixel chat highlights tests ──────────────────────────────────


class TestChatHighlights:
    """Verify Pixel gets chat highlights and other agents don't."""

    @pytest.mark.asyncio
    async def test_pixel_gets_chat_highlights(
        self, assembler: ContextAssembler, mock_registry: MagicMock
    ) -> None:
        mock_registry.get_agent = MagicMock(
            return_value=_make_agent(PIXEL_AGENT_ID, "You are Pixel.")
        )
        messages = (await assembler.assemble_context(PIXEL_AGENT_ID, [])).messages
        system = messages[0]["content"]
        assert "Recent Chat Messages" in system
        assert "viewer1: cool!" in system

    @pytest.mark.asyncio
    async def test_non_pixel_agent_has_no_chat_highlights(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", [])).messages
        system = messages[0]["content"]
        assert "Recent Chat Messages" not in system

    @pytest.mark.asyncio
    async def test_pixel_without_redis_has_no_highlights(
        self,
        mock_registry: MagicMock,
        mock_core_memory: AsyncMock,
        mock_recall_memory: AsyncMock,
        mock_archival_memory: AsyncMock,
        mock_token_counter: MagicMock,
    ) -> None:
        """Pixel without Redis gracefully degrades."""
        mock_registry.get_agent = MagicMock(
            return_value=_make_agent(PIXEL_AGENT_ID, "You are Pixel.")
        )
        asm = ContextAssembler(
            agent_registry=mock_registry,
            core_memory=mock_core_memory,
            recall_memory=mock_recall_memory,
            archival_memory=mock_archival_memory,
            token_counter=mock_token_counter,
            redis_client=None,
        )
        messages = (await asm.assemble_context(PIXEL_AGENT_ID, [])).messages
        system = messages[0]["content"]
        assert "Recent Chat Messages" not in system


# ── Prompt hint tests ────────────────────────────────────────────


class TestPromptHints:
    """Verify prompt hints are correctly appended."""

    @pytest.mark.asyncio
    async def test_interrupt_hint_appended(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context(
            "rex", _make_history(3), prompt_hint="interrupt"
        )).messages
        last = messages[-1]
        assert last["role"] == "user"
        assert "jump in right now" in last["content"]

    @pytest.mark.asyncio
    async def test_idle_hint_appended(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context(
            "rex", _make_history(3), prompt_hint="idle"
        )).messages
        last = messages[-1]
        assert "been quiet" in last["content"]

    @pytest.mark.asyncio
    async def test_memory_hint_appended(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context(
            "rex", _make_history(3), prompt_hint="memory"
        )).messages
        last = messages[-1]
        assert "remembered something" in last["content"]

    @pytest.mark.asyncio
    async def test_closing_hint_appended(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context(
            "rex", _make_history(3), prompt_hint="closing"
        )).messages
        last = messages[-1]
        assert "winding down" in last["content"]

    @pytest.mark.asyncio
    async def test_no_hint_when_none(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", _make_history(3))).messages
        # Last message is identity reinforcement (no prompt hint added)
        # No prompt hint should appear
        hint_msgs = [
            m for m in messages
            if m.get("role") == "user"
            and "[SYSTEM:" in m.get("content", "")
            and "You are Rex" not in m.get("content", "")
        ]
        assert len(hint_msgs) == 0

    @pytest.mark.asyncio
    async def test_unknown_hint_ignored(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context(
            "rex", _make_history(3), prompt_hint="nonexistent"
        )).messages
        # Unknown hint should not produce a hint message
        hint_msgs = [
            m for m in messages
            if m.get("role") == "user"
            and "[SYSTEM:" in m.get("content", "")
            and "You are Rex" not in m.get("content", "")
        ]
        assert len(hint_msgs) == 0


# ── World state tests ────────────────────────────────────────────


class TestWorldState:
    """Verify world state is fetched from Redis and included."""

    @pytest.mark.asyncio
    async def test_world_state_included(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", [])).messages
        system = messages[0]["content"]
        assert "World State" in system
        assert "The Workshop" in system
        assert "Building a dashboard" in system
        assert "vera, aurora" in system

    @pytest.mark.asyncio
    async def test_world_state_graceful_without_redis(
        self,
        mock_registry: MagicMock,
        mock_core_memory: AsyncMock,
        mock_recall_memory: AsyncMock,
        mock_archival_memory: AsyncMock,
        mock_token_counter: MagicMock,
    ) -> None:
        """Without Redis, world state is omitted gracefully."""
        asm = ContextAssembler(
            agent_registry=mock_registry,
            core_memory=mock_core_memory,
            recall_memory=mock_recall_memory,
            archival_memory=mock_archival_memory,
            token_counter=mock_token_counter,
            redis_client=None,
        )
        messages = (await asm.assemble_context("rex", [])).messages
        system = messages[0]["content"]
        assert "World State" not in system

    @pytest.mark.asyncio
    async def test_world_state_graceful_on_redis_error(
        self, assembler: ContextAssembler, mock_redis: AsyncMock
    ) -> None:
        """Redis errors don't crash assembly."""
        mock_redis.get = AsyncMock(side_effect=ConnectionError("offline"))
        messages = (await assembler.assemble_context("rex", [])).messages
        system = messages[0]["content"]
        assert "World State" not in system


# ── Transcript injection tests ───────────────────────────────────


class TestTranscriptInjection:
    """Verify optional full transcript (Tier 3) injection."""

    @pytest.mark.asyncio
    async def test_transcript_injected_when_requested(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context(
            "rex", _make_history(3), transcript_id=1
        )).messages
        system = messages[0]["content"]
        assert "Full Transcript" in system
        assert "Rex: Let's build. Vera: Agreed." in system

    @pytest.mark.asyncio
    async def test_no_transcript_without_id(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", _make_history(3))).messages
        system = messages[0]["content"]
        assert "Full Transcript" not in system

    @pytest.mark.asyncio
    async def test_transcript_failure_graceful(
        self, assembler: ContextAssembler, mock_archival_memory: AsyncMock
    ) -> None:
        mock_archival_memory.retrieve_full_transcript = AsyncMock(
            side_effect=Exception("DB error")
        )
        messages = (await assembler.assemble_context(
            "rex", _make_history(3), transcript_id=99
        )).messages
        system = messages[0]["content"]
        assert "Full Transcript" not in system


# ── Recall memory tests ─────────────────────────────────────────


class TestRecallMemory:
    """Verify recall memory retrieval behavior."""

    @pytest.mark.asyncio
    async def test_recall_memories_included(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", _make_history(5))).messages
        system = messages[0]["content"]
        assert "Relevant memories" in system

    @pytest.mark.asyncio
    async def test_recall_query_derived_from_recent_messages(
        self, assembler: ContextAssembler, mock_recall_memory: AsyncMock
    ) -> None:
        history = _make_history(5)
        await assembler.assemble_context("rex", history)
        # Should have been called with content from last 3 messages
        call_args = mock_recall_memory.retrieve_recall_memories.call_args
        query = call_args[1].get("query_text") or call_args[0][1]
        assert "Message 2" in query
        assert "Message 3" in query
        assert "Message 4" in query

    @pytest.mark.asyncio
    async def test_recall_failure_graceful(
        self, assembler: ContextAssembler, mock_recall_memory: AsyncMock
    ) -> None:
        mock_recall_memory.retrieve_recall_memories = AsyncMock(
            side_effect=Exception("vector search failed")
        )
        messages = (await assembler.assemble_context("rex", _make_history(3))).messages
        system = messages[0]["content"]
        # The recall section header should not appear (infrastructure mention is OK)
        assert "## Relevant memories" not in system


# ── Edge case tests ──────────────────────────────────────────────


class TestEdgeCases:
    """Verify edge cases and graceful degradation."""

    @pytest.mark.asyncio
    async def test_no_core_memory_still_works(
        self, assembler: ContextAssembler, mock_core_memory: AsyncMock
    ) -> None:
        mock_core_memory.get_core_memory = AsyncMock(return_value=None)
        messages = (await assembler.assemble_context("rex", [])).messages
        assert messages[0]["role"] == "system"
        assert "Livestream to AGI" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_empty_history_with_hint(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context(
            "rex", [], prompt_hint="idle"
        )).messages
        assert len(messages) == 3  # system + identity reinforcement + hint
        assert "been quiet" in messages[-1]["content"]

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts_with_role_and_content(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", _make_history(3))).messages
        for msg in messages:
            assert "role" in msg
            assert "content" in msg
            assert msg["role"] in ("system", "user", "assistant")


# ── Conversation continuity tests ───────────────────────────────


class TestConversationContinuity:
    """Verify conversation continuity enhancements (#221)."""

    @pytest.mark.asyncio
    async def test_recent_summaries_section_reframed(
        self, assembler: ContextAssembler
    ) -> None:
        """Summaries section uses 'What happened earlier today' framing."""
        messages = (await assembler.assemble_context(
            "rex",
            _make_history(3),
            recent_conversation_summaries=["Vera and Rex decided to build a dashboard."],
        )).messages
        system = messages[0]["content"]
        assert "What happened earlier today" in system
        assert "Build on these conversations" in system
        assert "do NOT repeat these" not in system

    @pytest.mark.asyncio
    async def test_relationship_context_section_appears(
        self, assembler: ContextAssembler
    ) -> None:
        """Relationship context is injected when provided."""
        rel_ctx = "- rex: positive sentiment, high trust (5 prior interactions)"
        messages = (await assembler.assemble_context(
            "vera",
            _make_history(3),
            relationship_context=rel_ctx,
        )).messages
        system = messages[0]["content"]
        assert "Your relationships with other agents" in system
        assert "positive sentiment" in system

    @pytest.mark.asyncio
    async def test_relationship_context_omitted_when_none(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", _make_history(3))).messages
        system = messages[0]["content"]
        assert "Your relationships with other agents" not in system

    @pytest.mark.asyncio
    async def test_shared_state_context_section_appears(
        self, assembler: ContextAssembler
    ) -> None:
        """Shared state context is injected when provided."""
        state_ctx = "**Active tasks:**\n  [pending] Build API (owner: rex)"
        messages = (await assembler.assemble_context(
            "rex",
            _make_history(3),
            shared_state_context=state_ctx,
        )).messages
        system = messages[0]["content"]
        assert "Current project status" in system
        assert "Build API" in system

    @pytest.mark.asyncio
    async def test_shared_state_context_omitted_when_none(
        self, assembler: ContextAssembler
    ) -> None:
        messages = (await assembler.assemble_context("rex", _make_history(3))).messages
        system = messages[0]["content"]
        assert "Current project status" not in system


# ── ContextResult section metadata tests ─────────────────────────


class TestContextResultMetadata:
    """Verify ContextResult includes correct section metadata."""

    @pytest.mark.asyncio
    async def test_sections_included_has_expected_keys(
        self, assembler: ContextAssembler
    ) -> None:
        result = await assembler.assemble_context("rex", _make_history(3))
        expected_sections = {
            "infrastructure", "character", "core_memory", "recall",
            "transcript", "world_state", "chat_highlights", "summaries",
            "relationships", "goals", "shared_state", "commitment_reminders",
            "internal_state", "balance", "alliances", "recent_dream",
        }
        assert set(result.sections_included.keys()) == expected_sections

    @pytest.mark.asyncio
    async def test_included_sections_marked_true(
        self, assembler: ContextAssembler
    ) -> None:
        result = await assembler.assemble_context("rex", _make_history(3))
        # Infrastructure is always included
        assert result.sections_included["infrastructure"]["included"] is True
        # Character prompt is included (mock returns non-empty)
        assert result.sections_included["character"]["included"] is True
        # Core memory is included (mock returns non-empty)
        assert result.sections_included["core_memory"]["included"] is True

    @pytest.mark.asyncio
    async def test_excluded_sections_marked_false(
        self, assembler: ContextAssembler
    ) -> None:
        result = await assembler.assemble_context("rex", _make_history(3))
        # No summaries or goals provided
        assert result.sections_included["summaries"]["included"] is False
        assert result.sections_included["relationships"]["included"] is False
        assert result.sections_included["goals"]["included"] is False

    @pytest.mark.asyncio
    async def test_total_tokens_populated(
        self, assembler: ContextAssembler
    ) -> None:
        result = await assembler.assemble_context("rex", _make_history(3))
        assert result.total_tokens > 0

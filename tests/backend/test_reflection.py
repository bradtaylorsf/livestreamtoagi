"""Tests for the reflection cycle (ReflectionManager)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.memory.core_memory import TOKEN_LIMIT
from core.memory.embeddings import EMBEDDING_DIMENSION
from core.memory.reflection import ReflectionManager, _parse_json_response
from core.models import (
    JournalEntry,
    LLMResponse,
    RecallMemory,
    SelfModificationProposal,
)

# ── Helpers ──────────────────────────────────────────────────────


def _make_recall_memory(
    id: int = 1,  # noqa: A002
    agent_id: str = "vera",
    summary: str = "Discussed plans with Rex about the dashboard.",
    importance_score: float = 0.5,
) -> RecallMemory:
    return RecallMemory(
        id=id,
        agent_id=agent_id,
        summary=summary,
        embedding=[0.1] * EMBEDDING_DIMENSION,
        event_type="conversation",
        participants=["vera", "rex"],
        transcript_id=1,
        importance_score=importance_score,
        timestamp=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        recalled_count=0,
    )


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-sonnet-4-6",
        input_tokens=500,
        output_tokens=300,
        estimated_cost=Decimal("0.01"),
        latency_ms=1200,
        openrouter_id="test-reflection-123",
    )


def _make_journal_entry(
    agent_id: str = "vera",
    reflection_type: str = "6hour",
    content: str = "Today I reflected on my conversations...",
) -> JournalEntry:
    return JournalEntry(
        id=1,
        agent_id=agent_id,
        reflection_type=reflection_type,
        content=content,
        token_count=150,
        created_at=datetime(2026, 4, 1, 14, 0, 0, tzinfo=UTC),
    )


def _make_proposal(
    agent_id: str = "vera",
    proposal_type: str = "personality_tweak",
) -> SelfModificationProposal:
    return SelfModificationProposal(
        id=1,
        agent_id=agent_id,
        proposal_type=proposal_type,
        description="I want to be more assertive in group discussions.",
        reasoning="I've noticed I tend to defer too much to Rex.",
        status="pending",
        created_at=datetime(2026, 4, 1, 20, 0, 0, tzinfo=UTC),
    )


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def memory_repo() -> AsyncMock:
    mock = AsyncMock()
    mock.get_recent_recall_memories.return_value = [
        _make_recall_memory(id=1, summary="Discussed dashboard with Rex."),
        _make_recall_memory(id=2, summary="Aurora proposed a new logo design."),
    ]
    mock.update_importance_score.return_value = None
    mock.create_journal_entry.return_value = _make_journal_entry()
    mock.create_proposal.return_value = _make_proposal()
    return mock


@pytest.fixture
def llm_client() -> AsyncMock:
    mock = AsyncMock()
    # Default: 6-hour reflection response
    mock.complete.return_value = _make_llm_response(
        json.dumps({
            "importance_scores": {"1": 0.8, "2": 0.3},
            "promotions": [
                {
                    "section": "key_learnings",
                    "content": "- Rex prefers iterative development\n- Dashboard is top priority",
                    "reason": "Rex's working style is important to remember",
                }
            ],
        })
    )
    return mock


@pytest.fixture
def core_memory_mgr() -> AsyncMock:
    mock = AsyncMock()
    mock.get_core_memory.return_value = "## My Core Memory\n\n### Key learnings\n- No learnings yet"
    mock.update_core_memory.return_value = None
    mock.get_token_count.return_value = 500
    return mock


@pytest.fixture
def token_counter() -> MagicMock:
    mock = MagicMock()
    mock.count_tokens.return_value = 250
    return mock


@pytest.fixture
def agent_registry() -> MagicMock:
    mock = MagicMock()
    agent_config = MagicMock()
    agent_config.id = "vera"
    agent_config.model_building = "claude-sonnet-4-6"
    mock.get_agent.return_value = agent_config
    mock.get_active_agents.return_value = [agent_config]
    return mock


@pytest.fixture
def reflection_mgr(
    memory_repo: AsyncMock,
    llm_client: AsyncMock,
    core_memory_mgr: AsyncMock,
    token_counter: MagicMock,
    agent_registry: MagicMock,
) -> ReflectionManager:
    return ReflectionManager(
        memory_repo=memory_repo,
        llm_client=llm_client,
        core_memory_mgr=core_memory_mgr,
        token_counter=token_counter,
        agent_registry=agent_registry,
    )


# ── 6-hour reflection tests ─────────────────────────────────────


class TestSixHourReflection:
    """Tests for run_6hour_reflection."""

    @pytest.mark.asyncio
    async def test_updates_importance_scores(
        self, reflection_mgr: ReflectionManager, memory_repo: AsyncMock
    ) -> None:
        """6-hour reflection updates importance scores on recall memories."""
        result = await reflection_mgr.run_6hour_reflection("vera")

        assert result.importance_updates == 2
        # Verify both memories got their scores updated
        calls = memory_repo.update_importance_score.call_args_list
        assert len(calls) == 2
        # Memory 1 -> 0.8, Memory 2 -> 0.3
        assert calls[0].args == (1, 0.8)
        assert calls[1].args == (2, 0.3)

    @pytest.mark.asyncio
    async def test_promotes_learnings_to_core_memory(
        self, reflection_mgr: ReflectionManager, core_memory_mgr: AsyncMock
    ) -> None:
        """6-hour reflection promotes important learnings to Tier 1."""
        result = await reflection_mgr.run_6hour_reflection("vera")

        assert result.promoted_count == 1
        core_memory_mgr.update_core_memory.assert_awaited_once()
        call_args = core_memory_mgr.update_core_memory.call_args
        assert call_args.args[0] == "vera"
        assert call_args.args[1] == "key_learnings"
        assert "Rex prefers iterative development" in call_args.args[2]

    @pytest.mark.asyncio
    async def test_generates_journal_entry(
        self, reflection_mgr: ReflectionManager, memory_repo: AsyncMock
    ) -> None:
        """6-hour reflection generates and stores a journal entry."""
        result = await reflection_mgr.run_6hour_reflection("vera")

        assert result.journal_entry is not None
        assert result.journal_entry.agent_id == "vera"
        assert result.journal_entry.reflection_type == "6hour"
        memory_repo.create_journal_entry.assert_awaited()

    @pytest.mark.asyncio
    async def test_uses_building_model(
        self, reflection_mgr: ReflectionManager, llm_client: AsyncMock
    ) -> None:
        """Reflection uses the agent's building model, not conversation model."""
        await reflection_mgr.run_6hour_reflection("vera")

        # First call is the analysis, second is the journal entry
        for call in llm_client.complete.call_args_list:
            assert call.kwargs.get("model") == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_no_recall_memories_skips_analysis(
        self,
        reflection_mgr: ReflectionManager,
        memory_repo: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        """When no recall memories exist, skip analysis but still generate journal."""
        memory_repo.get_recent_recall_memories.return_value = []

        result = await reflection_mgr.run_6hour_reflection("vera")

        assert result.promoted_count == 0
        assert result.importance_updates == 0
        assert result.journal_entry is not None
        # Only journal entry LLM call, no analysis call
        assert llm_client.complete.await_count == 1

    @pytest.mark.asyncio
    async def test_invalid_section_in_promotion_skipped(
        self,
        reflection_mgr: ReflectionManager,
        llm_client: AsyncMock,
        core_memory_mgr: AsyncMock,
    ) -> None:
        """Promotions with invalid section names are silently skipped."""
        llm_client.complete.return_value = _make_llm_response(
            json.dumps({
                "importance_scores": {},
                "promotions": [
                    {
                        "section": "invalid_section",
                        "content": "some content",
                        "reason": "test",
                    }
                ],
            })
        )

        result = await reflection_mgr.run_6hour_reflection("vera")

        assert result.promoted_count == 0
        core_memory_mgr.update_core_memory.assert_not_awaited()


# ── Weekly reflection tests ──────────────────────────────────────


class TestWeeklyReflection:
    """Tests for run_weekly_reflection."""

    @pytest.mark.asyncio
    async def test_trims_core_memory_under_token_limit(
        self,
        reflection_mgr: ReflectionManager,
        llm_client: AsyncMock,
        core_memory_mgr: AsyncMock,
    ) -> None:
        """Weekly reflection verifies core memory stays under 3,000 tokens."""
        llm_client.complete.return_value = _make_llm_response(
            json.dumps({
                "updates": [
                    {
                        "section": "key_learnings",
                        "content": "- Learning 1\n- Learning 2",
                        "reason": "pruned to top items",
                    }
                ],
                "self_modifications": [],
            })
        )
        # Simulate token count within limit
        core_memory_mgr.get_token_count.return_value = 2500

        result = await reflection_mgr.run_weekly_reflection("vera")

        assert result.promoted_count == 1
        # Token count was checked
        core_memory_mgr.get_token_count.assert_awaited_once_with("vera")

    @pytest.mark.asyncio
    async def test_triggers_trim_when_over_limit(
        self,
        reflection_mgr: ReflectionManager,
        llm_client: AsyncMock,
        core_memory_mgr: AsyncMock,
    ) -> None:
        """Weekly reflection triggers trimming when core memory exceeds token limit."""
        # First call: weekly analysis, second: journal, third: trim
        llm_client.complete.side_effect = [
            _make_llm_response(json.dumps({
                "updates": [],
                "self_modifications": [],
            })),
            _make_llm_response("My weekly journal entry..."),
            _make_llm_response(json.dumps({
                "updates": [
                    {
                        "section": "key_learnings",
                        "content": "- Trimmed learning",
                        "reason": "token trimming",
                    }
                ],
            })),
        ]
        core_memory_mgr.get_token_count.return_value = TOKEN_LIMIT + 500

        await reflection_mgr.run_weekly_reflection("vera")

        # Should have made 3 LLM calls: analysis + journal + trim
        assert llm_client.complete.await_count == 3

    @pytest.mark.asyncio
    async def test_creates_self_modification_proposals(
        self,
        reflection_mgr: ReflectionManager,
        llm_client: AsyncMock,
        memory_repo: AsyncMock,
    ) -> None:
        """Weekly reflection creates self-modification proposals."""
        llm_client.complete.return_value = _make_llm_response(
            json.dumps({
                "updates": [],
                "self_modifications": [
                    {
                        "proposal_type": "personality_tweak",
                        "description": "Be more assertive",
                        "reasoning": "I defer too much to Rex",
                    }
                ],
            })
        )

        result = await reflection_mgr.run_weekly_reflection("vera")

        assert len(result.proposals) == 1
        memory_repo.create_proposal.assert_awaited_once()
        call_args = memory_repo.create_proposal.call_args.args[0]
        assert call_args.agent_id == "vera"
        assert call_args.proposal_type == "personality_tweak"
        assert call_args.description == "Be more assertive"

    @pytest.mark.asyncio
    async def test_generates_weekly_journal_entry(
        self,
        reflection_mgr: ReflectionManager,
        memory_repo: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        """Weekly reflection generates a journal entry."""
        llm_client.complete.return_value = _make_llm_response(
            json.dumps({"updates": [], "self_modifications": []})
        )

        result = await reflection_mgr.run_weekly_reflection("vera")

        assert result.journal_entry is not None
        memory_repo.create_journal_entry.assert_awaited()


# ── Journal entry tests ──────────────────────────────────────────


class TestJournalEntry:
    """Tests for journal entry generation."""

    @pytest.mark.asyncio
    async def test_journal_entry_stored_with_token_count(
        self,
        reflection_mgr: ReflectionManager,
        memory_repo: AsyncMock,
        token_counter: MagicMock,
    ) -> None:
        """Journal entries are stored with accurate token count."""
        await reflection_mgr.run_6hour_reflection("vera")

        memory_repo.create_journal_entry.assert_awaited()
        entry = memory_repo.create_journal_entry.call_args.args[0]
        assert entry.agent_id == "vera"
        assert entry.reflection_type == "6hour"
        assert entry.token_count == 250  # from mock
        token_counter.count_tokens.assert_called()

    @pytest.mark.asyncio
    async def test_journal_uses_building_model(
        self,
        reflection_mgr: ReflectionManager,
        llm_client: AsyncMock,
    ) -> None:
        """Journal entry generation uses the building model."""
        await reflection_mgr.run_6hour_reflection("vera")

        # The journal call (second complete call)
        assert llm_client.complete.await_count == 2
        journal_call = llm_client.complete.call_args_list[1]
        assert journal_call.kwargs["model"] == "claude-sonnet-4-6"


# ── Self-modification proposal tests ─────────────────────────────


class TestSelfModificationProposal:
    """Tests for self-modification proposals."""

    @pytest.mark.asyncio
    async def test_proposal_created_with_pending_status(
        self,
        reflection_mgr: ReflectionManager,
        memory_repo: AsyncMock,
        llm_client: AsyncMock,
    ) -> None:
        """Self-modification proposals are created with pending status (not auto-applied)."""
        llm_client.complete.return_value = _make_llm_response(
            json.dumps({
                "updates": [],
                "self_modifications": [
                    {
                        "proposal_type": "goal_change",
                        "description": "Focus more on building",
                        "reasoning": "I spend too much time talking",
                    }
                ],
            })
        )

        result = await reflection_mgr.run_weekly_reflection("vera")

        assert len(result.proposals) == 1
        proposal_create = memory_repo.create_proposal.call_args.args[0]
        assert proposal_create.agent_id == "vera"
        assert proposal_create.proposal_type == "goal_change"
        # The returned proposal has pending status
        assert result.proposals[0].status == "pending"


# ── JSON parsing tests ───────────────────────────────────────────


class TestParseJsonResponse:
    """Tests for _parse_json_response utility."""

    def test_parses_plain_json(self) -> None:
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parses_json_in_code_fence(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_returns_empty_dict_on_invalid_json(self) -> None:
        result = _parse_json_response("not json at all")
        assert result == {}

    def test_handles_empty_string(self) -> None:
        result = _parse_json_response("")
        assert result == {}


# ── Integration test (marked for CI with real services) ──────────


@pytest.mark.integration
class TestReflectionIntegration:
    """Integration tests requiring real LLM calls and database.

    Run with: pytest -m integration
    """

    @pytest.mark.asyncio
    async def test_full_6hour_reflection_cycle(self) -> None:
        """Full 6-hour reflection with real services.

        Requires OPENROUTER_API_KEY and running Docker services.
        """
        pytest.skip("Requires OPENROUTER_API_KEY and running services")

    @pytest.mark.asyncio
    async def test_full_weekly_reflection_cycle(self) -> None:
        """Full weekly reflection with real services.

        Requires OPENROUTER_API_KEY and running Docker services.
        """
        pytest.skip("Requires OPENROUTER_API_KEY and running services")

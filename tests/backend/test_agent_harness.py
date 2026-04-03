"""Tests for scripts/test_agent.py — single-agent CLI test harness."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.test_agent import (
    AUTO_PROMPTS,
    SessionStats,
    parse_args,
)


# ── Arg parsing ───────────────────────────────────────────────────


class TestArgParsing:
    def test_defaults(self):
        args = parse_args([])
        assert args.agent == "rex"
        assert not args.auto
        assert not args.dry_run
        assert not args.interactive
        assert not args.verbose
        assert not args.list_agents

    def test_agent_flag(self):
        args = parse_args(["--agent", "vera"])
        assert args.agent == "vera"

    def test_agent_short_flag(self):
        args = parse_args(["-a", "aurora"])
        assert args.agent == "aurora"

    def test_interactive_mode(self):
        args = parse_args(["--interactive"])
        assert args.interactive

    def test_auto_mode(self):
        args = parse_args(["--auto"])
        assert args.auto

    def test_dry_run_mode(self):
        args = parse_args(["--dry-run"])
        assert args.dry_run

    def test_list_agents_mode(self):
        args = parse_args(["--list-agents"])
        assert args.list_agents

    def test_verbose_flag(self):
        args = parse_args(["--verbose"])
        assert args.verbose

    def test_verbose_short_flag(self):
        args = parse_args(["-v"])
        assert args.verbose

    def test_reflect_mode(self):
        args = parse_args(["--reflect"])
        assert args.reflect

    def test_reflect_all(self):
        args = parse_args(["--reflect", "--all"])
        assert args.reflect
        assert args.all

    def test_modes_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            parse_args(["--auto", "--dry-run"])

    def test_combined_flags(self):
        args = parse_args(["-a", "fork", "--auto", "-v"])
        assert args.agent == "fork"
        assert args.auto
        assert args.verbose


# ── SessionStats ──────────────────────────────────────────────────


class TestSessionStats:
    def test_initial_state(self):
        stats = SessionStats()
        assert stats.turns == 0
        assert stats.total_input_tokens == 0
        assert stats.total_output_tokens == 0
        assert stats.total_cost == Decimal("0")
        assert stats.memories_stored == 0
        assert stats.memories_recalled == 0

    def test_record_llm_call(self):
        stats = SessionStats()
        stats.record_llm_call(
            input_tokens=100,
            output_tokens=50,
            cost=Decimal("0.001"),
            latency_ms=500,
        )
        assert stats.turns == 1
        assert stats.total_input_tokens == 100
        assert stats.total_output_tokens == 50
        assert stats.total_cost == Decimal("0.001")
        assert stats.total_latency_ms == 500

    def test_multiple_calls_accumulate(self):
        stats = SessionStats()
        for _ in range(3):
            stats.record_llm_call(
                input_tokens=100,
                output_tokens=50,
                cost=Decimal("0.001"),
                latency_ms=200,
            )
        assert stats.turns == 3
        assert stats.total_input_tokens == 300
        assert stats.total_output_tokens == 150
        assert stats.total_cost == Decimal("0.003")


# ── Auto prompt sequence ──────────────────────────────────────────


class TestAutoPrompts:
    def test_has_required_steps(self):
        assert len(AUTO_PROMPTS) >= 4, "Need at least: intro, store, unrelated, recall"

    def test_all_prompts_have_required_fields(self):
        for step in AUTO_PROMPTS:
            assert "label" in step
            assert "prompt" in step
            assert len(step["prompt"]) > 10

    def test_recall_step_references_stored_fact(self):
        """The recall prompt should reference the budget fact stored earlier."""
        recall_step = AUTO_PROMPTS[3]
        assert "budget" in recall_step["prompt"].lower()


# ── Dry-run bootstrap ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_bootstrap():
    """Dry-run bootstrap should work without DB/Redis — just loads agent configs."""
    from scripts.test_agent import bootstrap_services

    services = await bootstrap_services(dry_run=True)
    assert services["db"] is None
    assert services["redis"] is None
    assert services["llm_client"] is None
    assert services["agent_registry"] is not None
    assert services["context_assembler"] is not None
    assert services["token_counter"] is not None

    # Should have loaded agents
    agents = services["agent_registry"].get_all_agents()
    assert len(agents) > 0


@pytest.mark.asyncio
async def test_dry_run_context_assembly():
    """Dry-run should assemble context for any agent without errors."""
    from scripts.test_agent import bootstrap_services

    services = await bootstrap_services(dry_run=True)
    assembler = services["context_assembler"]

    messages = await assembler.assemble_context(
        agent_id="rex",
        conversation_history=[{"role": "user", "content": "Hello Rex!"}],
    )
    assert len(messages) >= 1
    assert messages[0]["role"] == "system"
    # System message should contain Rex's prompt
    assert "rex" in messages[0]["content"].lower() or "Rex" in messages[0]["content"]


# ── Run turn with mock LLM ───────────────────────────────────────


@pytest.mark.asyncio
async def test_run_turn_with_mock_llm():
    """run_turn should work end-to-end with a mocked LLM client."""
    from core.models import LLMResponse

    from scripts.test_agent import SessionStats, bootstrap_services, run_turn

    services = await bootstrap_services(dry_run=True)

    # Create mock LLM client
    mock_response = LLMResponse(
        content="Sure. I'm Rex. I build things that ship.",
        model="claude-haiku-4-5",
        input_tokens=500,
        output_tokens=20,
        estimated_cost=Decimal("0.0005"),
        latency_ms=300,
        openrouter_id="test-123",
    )
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=mock_response)
    services["llm_client"] = mock_llm

    stats = SessionStats()
    history: list[dict[str, str]] = []

    result = await run_turn(
        agent_id="rex",
        user_message="Who are you?",
        conversation_history=history,
        services=services,
        stats=stats,
        verbose=False,
    )

    assert result == "Sure. I'm Rex. I build things that ship."
    assert stats.turns == 1
    assert stats.total_input_tokens == 500
    assert stats.total_output_tokens == 20
    assert len(history) == 2  # user + assistant
    mock_llm.complete.assert_called_once()

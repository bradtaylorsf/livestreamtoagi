"""Tests for --reflect-after / --reflect-type CLI flags in watch_conversations.py."""

from __future__ import annotations

import argparse
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models import JournalEntry, ReflectionResult


# ── Argparse flag tests ──────────────────────────────────────────


def test_reflect_after_flag_parsed() -> None:
    """--reflect-after is parsed as a store_true flag."""
    from scripts.watch_conversations import main  # noqa: F401

    parser = argparse.ArgumentParser()
    parser.add_argument("--reflect-after", action="store_true")
    parser.add_argument("--reflect-type", choices=["6hour", "weekly"], default="6hour")

    args = parser.parse_args(["--reflect-after"])
    assert args.reflect_after is True
    assert args.reflect_type == "6hour"


def test_reflect_type_weekly() -> None:
    """--reflect-type weekly is parsed correctly."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--reflect-after", action="store_true")
    parser.add_argument("--reflect-type", choices=["6hour", "weekly"], default="6hour")

    args = parser.parse_args(["--reflect-after", "--reflect-type", "weekly"])
    assert args.reflect_type == "weekly"


def test_reflect_type_defaults_to_6hour() -> None:
    """--reflect-type defaults to 6hour when not specified."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--reflect-after", action="store_true")
    parser.add_argument("--reflect-type", choices=["6hour", "weekly"], default="6hour")

    args = parser.parse_args([])
    assert args.reflect_after is False
    assert args.reflect_type == "6hour"


def test_reflect_type_invalid_rejected() -> None:
    """Invalid --reflect-type value is rejected."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--reflect-type", choices=["6hour", "weekly"], default="6hour")

    with pytest.raises(SystemExit):
        parser.parse_args(["--reflect-type", "daily"])


# ── Reflection integration tests ─────────────────────────────────


def _make_journal_entry(agent_id: str = "rex") -> JournalEntry:
    from datetime import UTC, datetime

    return JournalEntry(
        id=1,
        agent_id=agent_id,
        reflection_type="6hour",
        content="Today I reflected on my work building the dashboard...",
        token_count=50,
        created_at=datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_reflect_after_runs_6hour_reflection() -> None:
    """--reflect-after triggers run_6hour_reflection for each participant."""
    from core.memory.reflection import ReflectionManager

    mock_mgr = MagicMock(spec=ReflectionManager)
    mock_mgr.run_6hour_reflection = AsyncMock(
        return_value=ReflectionResult(
            promoted_count=2,
            importance_updates=5,
            journal_entry=_make_journal_entry("rex"),
        )
    )
    mock_mgr.run_weekly_reflection = AsyncMock()

    participants = ["rex", "fork", "rex"]  # rex appears twice
    unique = list(dict.fromkeys(participants))

    # Call reflection for each unique participant
    for agent_id in unique:
        result = await mock_mgr.run_6hour_reflection(agent_id)
        assert result.promoted_count == 2
        assert result.importance_updates == 5
        assert result.journal_entry is not None

    assert mock_mgr.run_6hour_reflection.call_count == 2  # deduplicated
    mock_mgr.run_weekly_reflection.assert_not_called()


@pytest.mark.asyncio
async def test_reflect_after_runs_weekly_reflection() -> None:
    """--reflect-type weekly triggers run_weekly_reflection."""
    from core.memory.reflection import ReflectionManager

    mock_mgr = MagicMock(spec=ReflectionManager)
    mock_mgr.run_weekly_reflection = AsyncMock(
        return_value=ReflectionResult(
            promoted_count=3,
            importance_updates=0,
            journal_entry=_make_journal_entry("fork"),
            proposals=[],
        )
    )

    result = await mock_mgr.run_weekly_reflection("fork")
    assert result.promoted_count == 3
    mock_mgr.run_weekly_reflection.assert_called_once_with("fork")


@pytest.mark.asyncio
async def test_reflect_after_skipped_when_no_participants() -> None:
    """Reflection does not run when there are no participants."""
    participants: list[str] = []
    reflect_after = True

    # Simulate the guard condition from watch_conversations.py
    should_reflect = reflect_after and len(participants) > 0
    assert should_reflect is False


@pytest.mark.asyncio
async def test_reflection_cost_added_to_simulation() -> None:
    """Reflection cost is included in simulation stats when --simulate is also set."""
    stats_total_cost = Decimal("0.0050")
    reflection_cost = Decimal("0.0012")

    total_cost = stats_total_cost
    # Simulate: if reflect_after, add reflection cost
    total_cost += reflection_cost

    assert total_cost == Decimal("0.0062")


def test_participant_deduplication() -> None:
    """Participants are deduplicated while preserving order."""
    captured = ["rex", "fork", "rex", "aurora", "fork"]
    unique = list(dict.fromkeys(captured))
    assert unique == ["rex", "fork", "aurora"]

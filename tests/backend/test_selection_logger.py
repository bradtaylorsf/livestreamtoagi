"""Unit tests for the conversation selection logger."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.conversation.selection_logger import SelectionLogger
from core.models import (
    EnergyLogCreate,
    InterruptAttempt,
    InterruptLogCreate,
    LoggingConfig,
    SelectionLog,
    SelectionLogCreate,
    SelectionResult,
)


# ── Fixtures ────────────────────────────────────────────────


def _make_logging_config(**overrides) -> LoggingConfig:
    defaults = {
        "log_every_selection": True,
        "log_interrupts": True,
        "log_energy_changes": True,
        "log_trigger_events": True,
        "log_topic_classifications": True,
        "retention_days": 30,
        "export_format": "jsonl",
    }
    defaults.update(overrides)
    return LoggingConfig(**defaults)


def _make_selection_result(**overrides) -> SelectionResult:
    defaults = {
        "selected_agent_id": "rex",
        "scores": {"rex": 0.8, "vera": 0.6, "aurora": 0.4},
        "score_breakdown": {
            "rex": {
                "time_since": 0.25,
                "relevance": 0.30,
                "chattiness": 0.10,
                "adjacency": 0.10,
                "jitter": 0.05,
                "final": 0.80,
            },
            "vera": {
                "time_since": 0.15,
                "relevance": 0.20,
                "chattiness": 0.10,
                "adjacency": 0.10,
                "jitter": 0.05,
                "final": 0.60,
            },
            "aurora": {
                "time_since": 0.10,
                "relevance": 0.10,
                "chattiness": 0.08,
                "adjacency": 0.07,
                "jitter": 0.05,
                "final": 0.40,
            },
        },
        "eligible_agents": ["rex", "vera", "aurora"],
        "previous_speaker_id": "vera",
        "detected_topic": "code",
        "was_interrupt": False,
        "interrupt_attempts": [],
    }
    defaults.update(overrides)
    return SelectionResult(**defaults)


def _make_repo() -> MagicMock:
    repo = MagicMock()
    repo.log_selection = AsyncMock()
    repo.log_interrupt = AsyncMock()
    repo.log_energy = AsyncMock()
    repo.cleanup_old_logs = AsyncMock()
    return repo


# ── log_selection tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_log_selection_stores_all_required_fields():
    """Selection log contains all required fields from the acceptance criteria."""
    repo = _make_repo()
    config = _make_logging_config()
    logger = SelectionLogger(repo, config)
    conv_id = uuid.uuid4()
    result = _make_selection_result()

    await logger.log_selection(
        conversation_id=conv_id,
        turn_number=5,
        result=result,
        previous_speaker_id="vera",
        active_agents=["rex", "vera", "aurora"],
        conversation_energy=9.5,
        trigger_type="idle",
        config_hash="abc123",
    )

    repo.log_selection.assert_awaited_once()
    entry: SelectionLogCreate = repo.log_selection.call_args[0][0]

    assert entry.conversation_id == conv_id
    assert entry.turn_number == 5
    assert entry.selected_agent_id == "rex"
    assert entry.was_interrupt is False
    assert entry.detected_topic == "code"
    assert entry.previous_speaker_id == "vera"
    assert entry.conversation_energy == 9.5
    assert entry.active_agents == ["rex", "vera", "aurora"]
    assert entry.trigger_type == "idle"
    assert entry.config_hash == "abc123"

    # agent_scores must contain per-agent score breakdown
    scores = entry.agent_scores
    assert "rex" in scores
    assert "vera" in scores
    assert "aurora" in scores
    # Each agent's breakdown has the required sub-scores
    for agent_id in ("rex", "vera", "aurora"):
        breakdown = scores[agent_id]
        for key in ("time_since", "relevance", "chattiness", "adjacency", "jitter", "final"):
            assert key in breakdown, f"Missing {key} in {agent_id} breakdown"


@pytest.mark.asyncio
async def test_log_selection_also_logs_interrupt_attempts():
    """When result has interrupt_attempts, each one is logged via log_interrupt."""
    repo = _make_repo()
    config = _make_logging_config()
    logger = SelectionLogger(repo, config)
    conv_id = uuid.uuid4()

    attempts = [
        InterruptAttempt(
            attempting_agent_id="fork",
            would_have_spoken_id="rex",
            interrupt_score=0.92,
            threshold=0.85,
            succeeded=True,
            reason="high relevance",
        ),
        InterruptAttempt(
            attempting_agent_id="grok",
            would_have_spoken_id="rex",
            interrupt_score=0.70,
            threshold=0.85,
            succeeded=False,
            reason="below threshold",
        ),
    ]
    result = _make_selection_result(
        was_interrupt=True,
        interrupt_attempts=attempts,
    )

    await logger.log_selection(
        conversation_id=conv_id,
        turn_number=3,
        result=result,
        previous_speaker_id="vera",
        active_agents=["rex", "vera", "fork", "grok"],
        conversation_energy=10.0,
        trigger_type="idle",
        config_hash="def456",
    )

    assert repo.log_interrupt.await_count == 2


# ── log_interrupt tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_log_interrupt_success():
    """Interrupt log records a successful interrupt."""
    repo = _make_repo()
    config = _make_logging_config()
    logger = SelectionLogger(repo, config)
    conv_id = uuid.uuid4()

    await logger.log_interrupt(
        conversation_id=conv_id,
        attempting_agent="fork",
        would_have_spoken="rex",
        score=0.92,
        threshold=0.85,
        succeeded=True,
        reason="high relevance to topic",
    )

    repo.log_interrupt.assert_awaited_once()
    entry: InterruptLogCreate = repo.log_interrupt.call_args[0][0]
    assert entry.attempting_agent_id == "fork"
    assert entry.would_have_spoken_id == "rex"
    assert entry.interrupt_score == 0.92
    assert entry.threshold_at_time == 0.85
    assert entry.succeeded is True
    assert entry.reason == "high relevance to topic"


@pytest.mark.asyncio
async def test_log_interrupt_failure():
    """Interrupt log records a failed interrupt."""
    repo = _make_repo()
    config = _make_logging_config()
    logger = SelectionLogger(repo, config)
    conv_id = uuid.uuid4()

    await logger.log_interrupt(
        conversation_id=conv_id,
        attempting_agent="grok",
        would_have_spoken="vera",
        score=0.60,
        threshold=0.85,
        succeeded=False,
        reason="below threshold",
    )

    entry: InterruptLogCreate = repo.log_interrupt.call_args[0][0]
    assert entry.succeeded is False
    assert entry.interrupt_score == 0.60


# ── log_energy tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_energy_captures_change_breakdown():
    """Energy log captures the full change breakdown dict."""
    repo = _make_repo()
    config = _make_logging_config()
    logger = SelectionLogger(repo, config)
    conv_id = uuid.uuid4()

    changes = {
        "decay": -1.0,
        "topic_shift": 3.0,
        "repetition": 0.0,
        "disagreement": 0.0,
        "audience": 0.0,
        "new_participant": 0.0,
        "net": 2.0,
        "resulting_energy": 11.0,
    }

    await logger.log_energy(
        conversation_id=conv_id,
        turn_number=7,
        changes=changes,
    )

    repo.log_energy.assert_awaited_once()
    entry: EnergyLogCreate = repo.log_energy.call_args[0][0]
    assert entry.conversation_id == conv_id
    assert entry.turn_number == 7
    assert entry.changes == changes
    assert entry.changes["net"] == 2.0
    assert entry.changes["resulting_energy"] == 11.0


# ── config_hash tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_config_hash_passed_through():
    """config_hash from caller is stored in the selection log entry."""
    repo = _make_repo()
    config = _make_logging_config()
    logger = SelectionLogger(repo, config)
    conv_id = uuid.uuid4()
    result = _make_selection_result()

    await logger.log_selection(
        conversation_id=conv_id,
        turn_number=1,
        result=result,
        previous_speaker_id=None,
        active_agents=["rex", "vera"],
        conversation_energy=10.0,
        trigger_type="idle",
        config_hash="hash_from_config_loader",
    )

    entry: SelectionLogCreate = repo.log_selection.call_args[0][0]
    assert entry.config_hash == "hash_from_config_loader"


# ── export_jsonl tests ──────────────────────────────────────


def test_export_jsonl_produces_valid_jsonl():
    """export_jsonl produces valid JSONL with one JSON object per line."""
    now = datetime.now(tz=timezone.utc)
    records = [
        SelectionLog(
            id=1,
            conversation_id=uuid.uuid4(),
            turn_number=1,
            timestamp=now,
            selected_agent_id="rex",
            was_interrupt=False,
            agent_scores={"rex": 0.8, "vera": 0.6},
            detected_topic="code",
            previous_speaker_id=None,
            conversation_energy=10.0,
            active_agents=["rex", "vera"],
            trigger_type="idle",
            config_hash="abc",
        ),
        SelectionLog(
            id=2,
            conversation_id=uuid.uuid4(),
            turn_number=2,
            timestamp=now,
            selected_agent_id="vera",
            was_interrupt=True,
            agent_scores={"rex": 0.5, "vera": 0.9},
            detected_topic="budget",
            previous_speaker_id="rex",
            conversation_energy=8.0,
            active_agents=["rex", "vera"],
            trigger_type="audience",
            config_hash="abc",
        ),
    ]

    output = SelectionLogger.export_jsonl(records)
    lines = output.strip().split("\n")
    assert len(lines) == 2

    for line in lines:
        parsed = json.loads(line)
        assert "selected_agent_id" in parsed
        assert "agent_scores" in parsed
        assert "conversation_id" in parsed


def test_export_jsonl_empty_list():
    """export_jsonl returns empty string for empty list."""
    assert SelectionLogger.export_jsonl([]) == ""


# ── cleanup tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_uses_config_retention_days():
    """cleanup defaults to config.retention_days."""
    repo = _make_repo()
    config = _make_logging_config(retention_days=14)
    logger = SelectionLogger(repo, config)

    await logger.cleanup()

    repo.cleanup_old_logs.assert_awaited_once_with(14)


@pytest.mark.asyncio
async def test_cleanup_uses_override_retention_days():
    """cleanup uses explicit retention_days when provided."""
    repo = _make_repo()
    config = _make_logging_config(retention_days=30)
    logger = SelectionLogger(repo, config)

    await logger.cleanup(retention_days=7)

    repo.cleanup_old_logs.assert_awaited_once_with(7)


# ── config flag tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_log_selection_skipped_when_disabled():
    """log_selection is a no-op when log_every_selection is False."""
    repo = _make_repo()
    config = _make_logging_config(log_every_selection=False)
    logger = SelectionLogger(repo, config)

    await logger.log_selection(
        conversation_id=uuid.uuid4(),
        turn_number=1,
        result=_make_selection_result(),
        previous_speaker_id=None,
        active_agents=["rex"],
        conversation_energy=10.0,
        trigger_type="idle",
        config_hash="x",
    )

    repo.log_selection.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_interrupt_skipped_when_disabled():
    """log_interrupt is a no-op when log_interrupts is False."""
    repo = _make_repo()
    config = _make_logging_config(log_interrupts=False)
    logger = SelectionLogger(repo, config)

    await logger.log_interrupt(
        conversation_id=uuid.uuid4(),
        attempting_agent="fork",
        would_have_spoken="rex",
        score=0.9,
        threshold=0.85,
        succeeded=True,
    )

    repo.log_interrupt.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_energy_skipped_when_disabled():
    """log_energy is a no-op when log_energy_changes is False."""
    repo = _make_repo()
    config = _make_logging_config(log_energy_changes=False)
    logger = SelectionLogger(repo, config)

    await logger.log_energy(
        conversation_id=uuid.uuid4(),
        turn_number=1,
        changes={"decay": -1.0, "net": -1.0},
    )

    repo.log_energy.assert_not_awaited()

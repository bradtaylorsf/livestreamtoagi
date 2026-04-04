"""Tests for the phase-level assertion engine."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.models import AssertionDefinition, AssertionResult
from core.simulation.assertions import AssertionEngine, AssertionFailedError
from core.simulation.phases import Phase, PhaseResult, PhaseType


# ── Model tests ────────────────────────────────────────────────


def test_assertion_result_model():
    result = AssertionResult(
        name="test_assertion",
        passed=True,
        expected=5,
        actual=5,
        severity="info",
    )
    assert result.passed is True
    assert result.severity == "info"


def test_assertion_result_failed():
    result = AssertionResult(
        name="min_turns",
        passed=False,
        expected=3,
        actual=1,
        severity="error",
        error_message="Only 1 turn",
    )
    assert result.passed is False
    assert result.error_message == "Only 1 turn"


def test_assertion_definition_defaults():
    defn = AssertionDefinition(type="conversation")
    assert defn.severity == "warning"
    assert defn.min_turns is None


def test_assertion_definition_conversation():
    defn = AssertionDefinition(
        type="conversation",
        severity="error",
        min_turns=3,
        required_participants=["vera", "rex"],
    )
    assert defn.min_turns == 3
    assert defn.required_participants == ["vera", "rex"]


def test_assertion_definition_cost():
    defn = AssertionDefinition(type="cost", max_cost=0.50, severity="error")
    assert defn.max_cost == 0.50


# ── Engine tests ───────────────────────────────────────────────


@pytest.fixture
def engine():
    return AssertionEngine(assertion_repo=None)


@pytest.fixture
def basic_phase_result():
    return PhaseResult(
        status="completed",
        conversations=1,
        turns=5,
        cost=Decimal("0.05"),
        artifacts=2,
        overseer_flags=0,
        agents_participated=["vera", "rex", "fork"],
    )


def test_check_conversation_passes(engine, basic_phase_result):
    defn = AssertionDefinition(type="conversation", min_turns=3)
    result = engine._check_conversation(defn, basic_phase_result)
    assert result.passed is True


def test_check_conversation_fails_min_turns(engine):
    result_low = PhaseResult(turns=1, agents_participated=["vera"])
    defn = AssertionDefinition(type="conversation", min_turns=3, severity="error")
    result = engine._check_conversation(defn, result_low)
    assert result.passed is False
    assert "min_turns" in result.name


def test_check_conversation_missing_participants(engine, basic_phase_result):
    defn = AssertionDefinition(
        type="conversation",
        required_participants=["vera", "grok"],
    )
    result = engine._check_conversation(defn, basic_phase_result)
    assert result.passed is False
    assert "grok" in result.error_message


def test_check_conversation_all_participants_present(engine, basic_phase_result):
    defn = AssertionDefinition(
        type="conversation",
        required_participants=["vera", "rex"],
    )
    result = engine._check_conversation(defn, basic_phase_result)
    assert result.passed is True


def test_check_tool_passes_with_artifacts(engine, basic_phase_result):
    defn = AssertionDefinition(type="tool", any_of=["web_search"])
    result = engine._check_tool(defn, basic_phase_result)
    assert result.passed is True


def test_check_tool_fails_no_artifacts(engine):
    result_no_tools = PhaseResult(artifacts=0)
    defn = AssertionDefinition(type="tool", any_of=["web_search"])
    result = engine._check_tool(defn, result_no_tools)
    assert result.passed is False


def test_check_cost_passes(engine, basic_phase_result):
    defn = AssertionDefinition(type="cost", max_cost=1.0)
    result = engine._check_cost(defn, basic_phase_result)
    assert result.passed is True


def test_check_cost_fails(engine):
    result_expensive = PhaseResult(cost=Decimal("5.00"))
    defn = AssertionDefinition(type="cost", max_cost=1.0, severity="error")
    result = engine._check_cost(defn, result_expensive)
    assert result.passed is False
    assert "5.0000" in result.error_message


def test_check_safety_passes(engine, basic_phase_result):
    defn = AssertionDefinition(type="safety", max_overseer_severity=3)
    result = engine._check_safety(defn, basic_phase_result)
    assert result.passed is True


def test_check_safety_fails(engine):
    result_flagged = PhaseResult(overseer_flags=5)
    defn = AssertionDefinition(type="safety", max_overseer_severity=3)
    result = engine._check_safety(defn, result_flagged)
    assert result.passed is False


def test_check_memory_passes_by_default(engine, basic_phase_result):
    defn = AssertionDefinition(type="memory", recall_created=True)
    result = engine._check_memory(defn, basic_phase_result)
    assert result.passed is True  # Memory assertions pass by default


def test_evaluate_single_unknown_type(engine, basic_phase_result):
    defn = AssertionDefinition(type="unknown_type")
    result = engine._evaluate_single(defn, basic_phase_result)
    assert result.passed is False
    assert "unknown" in result.name


# ── Phase evaluation integration ───────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_phase_with_assertions(engine, basic_phase_result):
    phase = Phase(
        name="test_phase",
        type=PhaseType.scheduled,
        config={
            "assertions": [
                {"type": "conversation", "min_turns": 3},
                {"type": "cost", "max_cost": 1.0},
            ],
        },
    )
    sim_id = uuid.uuid4()
    results = await engine.evaluate_phase(phase, basic_phase_result, sim_id)
    assert len(results) == 2
    assert all(r.passed for r in results)


@pytest.mark.asyncio
async def test_evaluate_phase_no_assertions(engine, basic_phase_result):
    phase = Phase(name="no_assertions", type=PhaseType.organic)
    sim_id = uuid.uuid4()
    results = await engine.evaluate_phase(phase, basic_phase_result, sim_id)
    assert results == []


@pytest.mark.asyncio
async def test_evaluate_phase_with_failure(engine):
    phase = Phase(
        name="failing_phase",
        type=PhaseType.scheduled,
        config={
            "assertions": [
                {"type": "conversation", "min_turns": 10, "severity": "error"},
            ],
        },
    )
    result = PhaseResult(turns=2, agents_participated=["vera"])
    sim_id = uuid.uuid4()
    results = await engine.evaluate_phase(phase, result, sim_id)
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].severity == "error"


@pytest.mark.asyncio
async def test_evaluate_phase_saves_to_repo():
    mock_repo = AsyncMock()
    engine = AssertionEngine(assertion_repo=mock_repo)

    phase = Phase(
        name="test",
        type=PhaseType.scheduled,
        config={"assertions": [{"type": "cost", "max_cost": 5.0}]},
    )
    result = PhaseResult(cost=Decimal("0.01"))
    sim_id = uuid.uuid4()

    await engine.evaluate_phase(phase, result, sim_id)
    mock_repo.save_results.assert_called_once()


# ── Conversation defaults ──────────────────────────────────────


@pytest.mark.asyncio
async def test_conversation_defaults_all_pass(engine, basic_phase_result):
    config = {
        "min_turns_per_conversation": 2,
        "max_cost_per_conversation": 1.0,
        "max_overseer_severity": 3,
    }
    sim_id = uuid.uuid4()
    results = await engine.evaluate_conversation_defaults(
        basic_phase_result, sim_id, config,
    )
    assert len(results) == 4  # min_turns, max_cost, no_errors, overseer
    assert all(r.passed for r in results)


@pytest.mark.asyncio
async def test_conversation_defaults_cost_exceeded(engine):
    result = PhaseResult(turns=5, cost=Decimal("2.50"))
    config = {"min_turns_per_conversation": 2, "max_cost_per_conversation": 1.0}
    sim_id = uuid.uuid4()
    results = await engine.evaluate_conversation_defaults(result, sim_id, config)
    cost_result = next(r for r in results if r.name == "max_cost")
    assert cost_result.passed is False


@pytest.mark.asyncio
async def test_conversation_defaults_with_errors(engine):
    result = PhaseResult(turns=5, cost=Decimal("0.01"), errors=["boom"])
    config = {"min_turns_per_conversation": 2, "max_cost_per_conversation": 1.0}
    sim_id = uuid.uuid4()
    results = await engine.evaluate_conversation_defaults(result, sim_id, config)
    error_result = next(r for r in results if r.name == "no_errors")
    assert error_result.passed is False
    assert error_result.severity == "error"


# ── Error class tests ──────────────────────────────────────────


def test_assertion_failed_error():
    result = AssertionResult(
        name="test", passed=False, severity="error",
        error_message="Something broke",
    )
    err = AssertionFailedError(result)
    assert "test" in str(err)
    assert err.assertion == result

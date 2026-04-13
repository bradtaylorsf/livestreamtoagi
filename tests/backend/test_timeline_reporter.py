"""Tests for the simulation timeline reporter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from core.reporting.formatters import format_json, format_markdown, format_terminal
from core.reporting.sections.cost_analysis import generate_cost_analysis
from core.reporting.sections.daily_breakdown import generate_daily_breakdown
from core.reporting.sections.executive_summary import generate_executive_summary
from core.reporting.sections.key_moments import generate_key_moments
from core.reporting.sections.memory_evolution import generate_memory_evolution
from core.reporting.sections.relationship_evolution import generate_relationship_evolution
from core.reporting.sections.tool_usage import generate_tool_usage
from core.reporting.timeline_reporter import ComparisonReport, Report, ReportSection


# ── Executive Summary tests ────────────────────────────────────


def _make_sim(**overrides) -> dict[str, Any]:
    base = {
        "name": "test-sim",
        "simulated_duration": timedelta(days=1),
        "real_duration": timedelta(minutes=30),
        "total_tokens": 5000,
        "agents_participated": ["vera", "rex", "fork"],
        "status": "completed",
    }
    base.update(overrides)
    return base


def _make_conversation(**overrides) -> dict[str, Any]:
    base = {
        "turn_count": 5,
        "participating_agents": ["vera", "rex"],
        "started_at": datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        "trigger_type": "idle",
        "topics_discussed": ["code"],
    }
    base.update(overrides)
    return base


def _make_cost(**overrides) -> dict[str, Any]:
    base = {
        "amount": Decimal("0.01"),
        "agent_id": "rex",
        "cost_type": "llm_call",
        "created_at": datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        "details": {"input_tokens": 100, "output_tokens": 50},
    }
    base.update(overrides)
    return base


def _make_artifact(**overrides) -> dict[str, Any]:
    base = {
        "tool_name": "web_search",
        "agent_id": "pixel",
        "status": "executed",
        "created_at": datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


def test_executive_summary_basic():
    sim = _make_sim()
    convs = [_make_conversation(turn_count=5), _make_conversation(turn_count=8)]
    costs = [_make_cost(amount=Decimal("0.01")), _make_cost(amount=Decimal("0.02"))]
    artifacts = [_make_artifact()]
    management_flags = []

    result = generate_executive_summary(sim, convs, costs, artifacts, management_flags)

    assert result["total_conversations"] == 2
    assert result["total_turns"] == 13
    assert result["total_cost"] == "0.03"
    assert result["total_tool_invocations"] == 1
    assert result["status"] == "completed"


def test_executive_summary_trajectory():
    # 8 conversations: first 4 with 3 turns, last 4 with 8 turns → improving
    convs = [_make_conversation(turn_count=3)] * 4 + [_make_conversation(turn_count=8)] * 4
    result = generate_executive_summary(_make_sim(), convs, [], [], [])
    assert result["trajectory"] == "improving"


def test_executive_summary_insufficient_data():
    result = generate_executive_summary(_make_sim(), [_make_conversation()], [], [], [])
    assert result["trajectory"] == "insufficient_data"


def test_executive_summary_none_durations():
    """Duration fields should show 'N/A' when DB value is None, not 'None'."""
    sim = _make_sim(simulated_duration=None, real_duration=None)
    result = generate_executive_summary(sim, [], [], [], [])
    assert result["simulated_duration"] == "N/A"
    assert result["real_duration"] == "N/A"


# ── Daily Breakdown tests ──────────────────────────────────────


def test_daily_breakdown_groups_by_day():
    convs = [
        _make_conversation(started_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC)),
        _make_conversation(started_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC)),
        _make_conversation(started_at=datetime(2026, 1, 6, 10, 0, tzinfo=UTC)),
    ]
    costs = [
        _make_cost(created_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC)),
        _make_cost(created_at=datetime(2026, 1, 6, 10, 0, tzinfo=UTC)),
    ]

    result = generate_daily_breakdown(convs, costs, [])
    assert result["total_days"] == 2
    assert result["days"][0]["conversations"] == 2
    assert result["days"][1]["conversations"] == 1


def test_daily_breakdown_empty():
    result = generate_daily_breakdown([], [], [])
    assert result["total_days"] == 0
    assert result["days"] == []


# ── Memory Evolution tests ─────────────────────────────────────


def test_memory_evolution_counts_changes():
    history = [
        {"agent_id": "rex", "version": 1, "changed_at": datetime(2026, 1, 5, tzinfo=UTC), "change_reason": "init"},
        {"agent_id": "rex", "version": 2, "changed_at": datetime(2026, 1, 6, tzinfo=UTC), "change_reason": "reflection"},
    ]
    recall_counts = {"rex": 10, "fork": 5}
    journals = [
        {"agent_id": "rex", "reflection_type": "6hour", "content": "test", "created_at": datetime.now(UTC)},
    ]

    result = generate_memory_evolution(history, recall_counts, journals, ["rex", "fork", "vera"])

    assert result["core_memory_changes"]["rex"] == 2
    assert result["recall_memory_counts"]["rex"] == 10
    assert "vera" in result["agents_with_no_changes"]


# ── Relationship Evolution tests ───────────────────────────────


def test_relationship_evolution_unavailable():
    result = generate_relationship_evolution(None)
    assert result["available"] is False


def test_relationship_evolution_empty():
    result = generate_relationship_evolution([])
    assert result["available"] is True
    assert result["total_relationships"] == 0


def test_relationship_evolution_with_data():
    rels = [
        {
            "agent_id": "rex",
            "target_agent_id": "fork",
            "sentiment_score": Decimal("0.7"),
            "trust_score": Decimal("0.8"),
            "interaction_count": 5,
            "relationship_summary": "Trusted partner",
            "evolution_log": [
                {"sentiment_before": 0.0, "sentiment_after": 0.3, "timestamp": "t1"},
                {"sentiment_before": 0.3, "sentiment_after": 0.7, "timestamp": "t2"},
            ],
        },
    ]
    result = generate_relationship_evolution(rels)

    assert result["available"] is True
    assert result["total_relationships"] == 1
    assert "rex" in result["matrix"]
    assert len(result["biggest_changes"]) == 1


# ── Tool Usage tests ───────────────────────────────────────────


def test_tool_usage_empty():
    result = generate_tool_usage([], [])
    assert result["total_invocations"] == 0


def test_tool_usage_counts():
    artifacts = [
        _make_artifact(tool_name="web_search", status="executed"),
        _make_artifact(tool_name="web_search", status="executed"),
        _make_artifact(tool_name="execute_code", status="executed"),
    ]
    result = generate_tool_usage(artifacts, [])

    assert result["total_invocations"] == 3
    assert result["by_tool"]["web_search"]["count"] == 2
    assert result["success_rate"] == 100.0


# ── Cost Analysis tests ───────────────────────────────────────


def test_cost_analysis_basic():
    costs = [
        _make_cost(amount=Decimal("0.01"), agent_id="rex"),
        _make_cost(amount=Decimal("0.02"), agent_id="fork"),
    ]
    result = generate_cost_analysis(costs, _make_sim())

    assert result["total_cost"] == "0.03"
    assert "rex" in result["by_agent"]


def test_cost_analysis_projection():
    costs = [
        _make_cost(
            amount=Decimal("0.01"),
            created_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        ),
        _make_cost(
            amount=Decimal("0.02"),
            created_at=datetime(2026, 1, 6, 10, 0, tzinfo=UTC),
        ),
    ]
    result = generate_cost_analysis(costs, _make_sim())

    assert result["projection"] is not None
    assert "weekly_estimate" in result["projection"]
    assert "monthly_estimate" in result["projection"]


def test_cost_analysis_empty():
    result = generate_cost_analysis([], _make_sim())
    assert result["total_cost"] == "0"
    assert result["projection"] is None


# ── Key Moments tests ─────────────────────────────────────────


def test_key_moments_high_energy():
    convs = [
        _make_conversation(turn_count=3),
        _make_conversation(turn_count=15),
        _make_conversation(turn_count=8),
    ]
    result = generate_key_moments(convs, [], [])

    # Should include top conversations sorted by turn count
    assert result["total_moments"] >= 3
    assert any(m["type"] == "high_energy_conversation" for m in result["moments"])


def test_key_moments_participating_agents_string():
    """Ensure participating_agents as string doesn't iterate characters."""
    convs = [_make_conversation(turn_count=10, participating_agents="vera")]
    result = generate_key_moments(convs, [], [])
    desc = result["moments"][0]["description"]
    assert "participants: vera" in desc
    # Should NOT have "v, e, r, a"
    assert "v, e" not in desc


def test_key_moments_participating_agents_none():
    """Ensure None participating_agents doesn't crash."""
    convs = [_make_conversation(turn_count=10, participating_agents=None)]
    result = generate_key_moments(convs, [], [])
    assert "participants:" in result["moments"][0]["description"]


def test_key_moments_first_tool_usage():
    artifacts = [
        _make_artifact(tool_name="web_search"),
        _make_artifact(tool_name="execute_code"),
        _make_artifact(tool_name="web_search"),  # duplicate, shouldn't appear
    ]
    result = generate_key_moments([], [], artifacts)

    first_tool_moments = [m for m in result["moments"] if m["type"] == "first_tool_usage"]
    assert len(first_tool_moments) == 2  # web_search and execute_code


# ── Report model tests ─────────────────────────────────────────


def test_report_to_dict():
    report = Report(
        simulation_id="test-id",
        simulation_name="test-sim",
        sections=[ReportSection(title="Test", data={"key": "value"})],
    )
    d = report.to_dict()
    assert d["simulation_id"] == "test-id"
    assert len(d["sections"]) == 1


def test_comparison_report_to_dict():
    report = ComparisonReport(
        simulation_a={"name": "A"},
        simulation_b={"name": "B"},
        comparison={"delta": 0},
    )
    d = report.to_dict()
    assert d["simulation_a"]["name"] == "A"


# ── Formatter tests ────────────────────────────────────────────


def test_format_terminal():
    report = Report(
        simulation_id="test-id",
        simulation_name="test-sim",
        sections=[ReportSection(title="Summary", data={"cost": "0.03"})],
    )
    output = format_terminal(report)
    assert "SIMULATION TIMELINE REPORT" in output
    assert "test-sim" in output
    assert "cost: 0.03" in output


def test_format_json():
    report = Report(
        simulation_id="test-id",
        simulation_name="test-sim",
        sections=[ReportSection(title="Summary", data={"cost": "0.03"})],
    )
    output = format_json(report)
    import json

    parsed = json.loads(output)
    assert parsed["simulation_name"] == "test-sim"


def test_format_markdown():
    report = Report(
        simulation_id="test-id",
        simulation_name="test-sim",
        sections=[ReportSection(title="Summary", data={"cost": "0.03"})],
    )
    output = format_markdown(report)
    assert "# Simulation Timeline Report" in output
    assert "## Summary" in output

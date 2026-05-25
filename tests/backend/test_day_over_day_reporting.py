"""Tests for day-over-day comparison and cost projection (#195)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.reporting.comparison import ComparisonResult, CrossRunComparison, MetricComparison
from core.reporting.cost_projection import CostProjection, project_costs
from core.reporting.scorecard import LaunchScorecard, ScorecardCriterion, ScorecardResult
from core.reporting.sections.daily_breakdown import (
    _compute_day_over_day_metrics,
    generate_daily_breakdown,
)

# ── Day-over-day metrics tests ─────────────────────────────────


def _make_day(date, conversations=2, turns=10, cost="0.05", tools=None, agents=None):
    return {
        "date": date,
        "conversations": conversations,
        "turns": turns,
        "cost": cost,
        "tools_used": tools or ["web_search"],
        "agents_active": agents or ["rex", "fork"],
    }


def test_day_over_day_metrics_basic():
    from collections import Counter

    days = [
        _make_day("2026-01-05", turns=10, conversations=2, cost="0.05"),
        _make_day("2026-01-06", turns=15, conversations=3, cost="0.08"),
    ]
    agent_turns = {
        "2026-01-05": Counter({"rex": 5, "fork": 5}),
        "2026-01-06": Counter({"rex": 8, "fork": 7}),
    }
    metrics = _compute_day_over_day_metrics(days, agent_turns)

    assert "avg_turns_per_conversation" in metrics
    assert len(metrics["avg_turns_per_conversation"]) == 2
    assert "depth_trend" in metrics
    assert "cost_trend" in metrics
    assert "cumulative_tools" in metrics


def test_day_over_day_insufficient_data():

    days = [_make_day("2026-01-05")]
    metrics = _compute_day_over_day_metrics(days, {})
    assert metrics == {}


def test_daily_breakdown_includes_day_over_day():
    convs = [
        {
            "turn_count": 5,
            "participating_agents": ["rex"],
            "started_at": datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        },
        {
            "turn_count": 8,
            "participating_agents": ["fork"],
            "started_at": datetime(2026, 1, 6, 10, 0, tzinfo=UTC),
        },
    ]
    costs = [
        {"amount": Decimal("0.01"), "created_at": datetime(2026, 1, 5, 10, 0, tzinfo=UTC)},
        {"amount": Decimal("0.02"), "created_at": datetime(2026, 1, 6, 10, 0, tzinfo=UTC)},
    ]
    result = generate_daily_breakdown(convs, costs, [])
    assert "day_over_day" in result
    assert "depth_trend" in result["day_over_day"]


# ── Cost projection tests ─────────────────────────────────────


def test_project_costs_empty():
    proj = project_costs([])
    assert proj.weekly_estimate == Decimal("0")
    assert proj.is_sustainable is True
    assert len(proj.warnings) > 0


def test_project_costs_stable():
    daily = [Decimal("1.00"), Decimal("1.00"), Decimal("1.00"), Decimal("1.00")]
    proj = project_costs(daily, total_conversations=40)
    assert proj.weekly_estimate == Decimal("7.0000")
    assert proj.monthly_estimate == Decimal("30.0000")
    assert proj.is_sustainable is True
    assert proj.cost_per_1k_conversations is not None


def test_project_costs_growing():
    daily = [Decimal("1.00"), Decimal("1.00"), Decimal("5.00"), Decimal("5.00")]
    proj = project_costs(daily)
    assert proj.growth_rate > 0
    # 400% growth should be unsustainable
    assert proj.is_sustainable is False


def test_project_costs_declining():
    daily = [Decimal("5.00"), Decimal("5.00"), Decimal("2.00"), Decimal("2.00")]
    proj = project_costs(daily)
    assert proj.growth_rate < 0
    assert proj.is_sustainable is True


def test_project_costs_with_token_growth():
    daily = [Decimal("1.00"), Decimal("1.00"), Decimal("1.00"), Decimal("1.00")]
    tokens = [
        {"input": 100, "output": 50},
        {"input": 100, "output": 50},
        {"input": 500, "output": 200},
        {"input": 500, "output": 200},
    ]
    proj = project_costs(daily, daily_token_counts=tokens)
    # Should warn about token growth
    assert any("token" in w.lower() for w in proj.warnings)


def test_cost_projection_to_dict():
    proj = CostProjection(
        weekly_estimate=Decimal("7.00"),
        monthly_estimate=Decimal("30.00"),
        cost_per_1k_conversations=Decimal("25.00"),
        growth_rate=5.0,
        is_sustainable=True,
        warnings=[],
    )
    d = proj.to_dict()
    assert d["weekly_estimate"] == "7.00"
    assert d["is_sustainable"] is True


# ── Comparison tests ───────────────────────────────────────────


def test_metric_comparison():
    mc = MetricComparison(
        metric="total_cost",
        run_a_value="1.00",
        run_b_value="2.00",
        delta="1.00",
        better_run="a",
    )
    assert mc.better_run == "a"


def test_comparison_result_to_dict():
    result = ComparisonResult(
        run_a={"name": "A"},
        run_b={"name": "B"},
        metrics=[
            MetricComparison(
                metric="cost",
                run_a_value="1.00",
                run_b_value="2.00",
                delta="1.00",
                better_run="a",
            ),
        ],
    )
    d = result.to_dict()
    assert d["run_a"]["name"] == "A"
    assert len(d["metrics"]) == 1
    assert d["metrics"][0]["better_run"] == "a"


# ── Scorecard tests ────────────────────────────────────────────


def test_scorecard_criterion():
    c = ScorecardCriterion(
        name="tool_coverage",
        passed=True,
        evidence="5 tools used",
        required=True,
    )
    assert c.passed is True


def test_scorecard_result_ready():
    result = ScorecardResult(
        ready=True,
        criteria=[
            ScorecardCriterion(name="a", passed=True, evidence="ok", required=True),
            ScorecardCriterion(name="b", passed=True, evidence="ok", required=True),
        ],
    )
    d = result.to_dict()
    assert d["status"] == "READY"
    assert d["required_passed"] == 2


def test_scorecard_result_not_ready():
    result = ScorecardResult(
        ready=False,
        criteria=[
            ScorecardCriterion(name="a", passed=True, evidence="ok", required=True),
            ScorecardCriterion(name="b", passed=False, evidence="fail", required=True),
        ],
    )
    d = result.to_dict()
    assert d["status"] == "NOT READY"
    assert d["required_passed"] == 1


def test_scorecard_report_completeness_pass():
    from core.reporting.scorecard import LaunchScorecard

    scorecard = LaunchScorecard.__new__(LaunchScorecard)
    scorecard._report_sections = [
        {
            "title": "Tool Usage",
            "data": {"by_tool": {"web_search": {"count": 5}}, "total_invocations": 5},
        },
        {"title": "Memory Evolution", "data": {"core_memory_changes": {"rex": 2}}},
        {
            "title": "Relationship Evolution",
            "data": {"available": True, "matrix": {"rex": {"fork": {}}}},
        },
        {"title": "Cost Analysis", "data": {"by_day": {"2026-01-05": "0.01"}}},
    ]
    result = scorecard._check_report_completeness()
    assert result.passed is True


def test_scorecard_report_completeness_fail():
    from core.reporting.scorecard import LaunchScorecard

    scorecard = LaunchScorecard.__new__(LaunchScorecard)
    scorecard._report_sections = [
        {"title": "Tool Usage", "data": {"by_tool": {}, "total_invocations": 0}},
        {"title": "Memory Evolution", "data": {}},
        {"title": "Relationship Evolution", "data": {"available": False}},
        {"title": "Cost Analysis", "data": {}},
    ]
    result = scorecard._check_report_completeness()
    assert result.passed is False
    assert "tool usage" in result.evidence
    assert "memory evolution" in result.evidence


def test_scorecard_optional_failures_dont_block():
    result = ScorecardResult(
        ready=True,
        criteria=[
            ScorecardCriterion(name="required", passed=True, evidence="ok", required=True),
            ScorecardCriterion(name="optional", passed=False, evidence="fail", required=False),
        ],
    )
    # ready=True because all *required* criteria pass
    d = result.to_dict()
    assert d["status"] == "READY"


@pytest.mark.asyncio
async def test_scorecard_build_verification_passes_when_no_builds():
    scorecard = LaunchScorecard(
        db=AsyncMock(),
        simulation_id=str(uuid.uuid4()),
        report_sections=[
            {
                "title": "Embodied Activity",
                "data": {
                    "total_actions": 0,
                    "builds_attempted": 0,
                    "builds_verified": 0,
                },
            }
        ],
    )

    result = await scorecard._check_build_verification()

    assert result.name == "build_verification"
    assert result.passed is True
    assert result.required is False
    assert "0/0 builds verified" in result.evidence


@pytest.mark.asyncio
async def test_scorecard_build_verification_passes_or_fails_by_ratio():
    passing = LaunchScorecard(
        db=AsyncMock(),
        simulation_id=str(uuid.uuid4()),
        build_verification_threshold=0.75,
        report_sections=[
            {
                "title": "Embodied Activity",
                "data": {
                    "total_actions": 5,
                    "builds_attempted": 4,
                    "builds_verified": 3,
                },
            }
        ],
    )
    failing = LaunchScorecard(
        db=AsyncMock(),
        simulation_id=str(uuid.uuid4()),
        build_verification_threshold=0.75,
        report_sections=[
            {
                "title": "Embodied Activity",
                "data": {
                    "total_actions": 5,
                    "builds_attempted": 4,
                    "builds_verified": 2,
                },
            }
        ],
    )

    assert (await passing._check_build_verification()).passed is True
    failed_result = await failing._check_build_verification()
    assert failed_result.passed is False
    assert "2/4 builds verified" in failed_result.evidence


# ── CrossRunComparison mock test ───────────────────────────────


@pytest.mark.asyncio
async def test_cross_run_comparison():
    mock_db = AsyncMock()
    sim_a = {
        "id": str(uuid.uuid4()),
        "name": "Run A",
        "total_cost": Decimal("1.00"),
        "total_conversations": 10,
        "total_turns": 50,
    }
    sim_b = {
        "id": str(uuid.uuid4()),
        "name": "Run B",
        "total_cost": Decimal("2.00"),
        "total_conversations": 15,
        "total_turns": 90,
    }

    mock_db.fetchrow = AsyncMock(side_effect=[sim_a, sim_b, {"cnt": 3}, {"cnt": 5}])

    comparison = CrossRunComparison(
        db=mock_db,
        simulation_ids=[sim_a["id"], sim_b["id"]],
    )
    result = await comparison.compare()

    assert len(result.metrics) >= 3
    # Run A has lower cost, should be "better"
    cost_metric = next(m for m in result.metrics if m.metric == "total_cost")
    assert cost_metric.better_run == "a"


@pytest.mark.asyncio
async def test_cross_run_comparison_wrong_count():
    mock_db = AsyncMock()
    comparison = CrossRunComparison(db=mock_db, simulation_ids=["only-one"])
    result = await comparison.compare()
    assert result.metrics == []

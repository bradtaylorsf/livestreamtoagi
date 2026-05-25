"""Tests for comparison summaries across experimental starting conditions."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.reporting.comparison import CrossRunComparison
from core.simulation.orchestrator import SimulationConfig


def _experimental_row(
    *,
    name: str,
    persona_backstory: str,
    agent_goal: str,
    phases_completed: int,
) -> dict:
    cfg = SimulationConfig(
        name=name,
        seed_file="scenarios/experimental_short_run.yaml",
        agents=["vera", "rex"],
        run_mode="experimental",
        dry_run=True,
        experimental_goal={"kind": "phases_complete", "target": 3},
        persona_overrides=[
            {
                "agent_id": "vera",
                "backstory": persona_backstory,
            }
        ],
        agent_goals={"vera": [agent_goal]},
        factions=[
            {
                "name": "testers",
                "members": ["vera", "rex"],
                "goal": "Compare starting conditions.",
            }
        ],
        world_config={"world_type": "flat", "seed": 607, "persistent": False},
        duration=timedelta(minutes=10),
    )
    config = {
        **cfg.to_dict(),
        "experimental_progress": {
            "phases_completed": phases_completed,
            "turns": 6,
            "artifacts": 1,
        },
        "experimental_stop_reason": "goal_reached",
    }
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "config": config,
        "outcomes": {},
        "error_log": None,
        "factions": config["factions"],
        "total_cost": Decimal("0.01"),
        "total_conversations": 2,
        "total_turns": 6,
    }


@pytest.mark.asyncio
async def test_cross_run_comparison_includes_experimental_starting_condition_diff() -> None:
    run_a = _experimental_row(
        name="experiment-a",
        persona_backstory="Vera begins as a cautious planner.",
        agent_goal="Plan before building.",
        phases_completed=3,
    )
    run_b = _experimental_row(
        name="experiment-b",
        persona_backstory="Vera begins as a rapid builder.",
        agent_goal="Build before planning.",
        phases_completed=2,
    )

    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(side_effect=[run_a, run_b, {"cnt": 1}, {"cnt": 1}])

    result = await CrossRunComparison(
        db=mock_db,
        simulation_ids=[run_a["id"], run_b["id"]],
    ).compare()

    assert result.run_a["run_mode"] == "experimental"
    assert result.run_a["experimental_goal"] == {"kind": "phases_complete", "target": 3}
    assert result.run_a["duration_seconds"] == 600.0
    assert result.run_a["world.seed"] == 607
    assert result.run_a["starting_condition_diff"]["persona_overrides"][0]["backstory"] == (
        "Vera begins as a cautious planner."
    )
    assert result.run_b["starting_condition_diff"]["agent_goals"] == {
        "vera": ["Build before planning."]
    }
    phases = next(m for m in result.metrics if m.metric == "phases_completed")
    assert phases.run_a_value == 3
    assert phases.run_b_value == 2
    stop_reason = next(m for m in result.metrics if m.metric == "stop_reason")
    assert stop_reason.run_a_value == "goal_reached"


@pytest.mark.asyncio
async def test_cross_run_comparison_includes_embodied_metrics() -> None:
    started = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    run_a = _experimental_row(
        name="embodied-a",
        persona_backstory="Vera plans.",
        agent_goal="Build one shelter.",
        phases_completed=2,
    )
    run_b = _experimental_row(
        name="embodied-b",
        persona_backstory="Vera builds.",
        agent_goal="Build two shelters.",
        phases_completed=2,
    )
    run_a["started_at"] = started
    run_a["completed_at"] = started + timedelta(minutes=5)
    run_b["started_at"] = started + timedelta(minutes=10)
    run_b["completed_at"] = started + timedelta(minutes=20)

    def action_row(action_id: str, created_at: datetime, present: int) -> dict:
        return {
            "id": action_id,
            "event_type": "bridge_action_result",
            "participants": ["rex"],
            "created_at": created_at,
            "content": json.dumps(
                {
                    "agent_id": "rex",
                    "action": "buildFromPlan",
                    "action_id": action_id,
                    "status": "success" if present == 4 else "partial",
                    "outcome_class": "success" if present == 4 else "partial",
                    "detail": (
                        f"build: intended=4; present={present}; "
                        f"missing={4 - present}; completion={present / 4:.3f}"
                    ),
                }
            ),
        }

    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(side_effect=[run_a, run_b, {"cnt": 1}, {"cnt": 1}])
    mock_db.fetch = AsyncMock(
        side_effect=[
            [action_row("build-a", started + timedelta(minutes=1), 2)],
            [
                action_row("build-b1", started + timedelta(minutes=11), 4),
                action_row("build-b2", started + timedelta(minutes=12), 4),
            ],
        ]
    )

    result = await CrossRunComparison(
        db=mock_db,
        simulation_ids=[run_a["id"], run_b["id"]],
    ).compare()

    actions = next(m for m in result.metrics if m.metric == "total_embodied_actions")
    verified = next(m for m in result.metrics if m.metric == "builds_verified")
    completion = next(m for m in result.metrics if m.metric == "avg_build_completion")

    assert actions.run_a_value == 1
    assert actions.run_b_value == 2
    assert actions.better_run == "b"
    assert verified.run_a_value == 0
    assert verified.run_b_value == 2
    assert completion.run_a_value == 0.5
    assert completion.run_b_value == 1.0

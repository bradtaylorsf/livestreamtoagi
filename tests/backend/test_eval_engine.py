"""Tests for the eval engine, loader, and prompt_loader."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.eval.engine import EVAL_SUITES, EvalEngine, _parse_eval_response
from core.eval.loader import _build_transcript_text, load_simulation_data, organize_by_category
from core.eval.prompt_loader import (
    discover_categories,
    load_prompt,
    render_user_prompt,
    validate_prompt_schema,
)
from core.models import EvalRun

# ── _parse_eval_response ─────────────────────────────────────


def test_parse_eval_response_plain_json():
    content = '{"score": 75, "reasoning": "Good", "evidence": null, "sub_scores": {"a": 80}}'
    result = _parse_eval_response(content)
    assert result["score"] == 75
    assert result["reasoning"] == "Good"


def test_parse_eval_response_code_fence():
    content = '```json\n{"score": 85, "reasoning": "Great"}\n```'
    result = _parse_eval_response(content)
    assert result["score"] == 85


def test_parse_eval_response_embedded_json():
    content = 'Here is my evaluation:\n{"score": 60, "reasoning": "OK"}\nDone.'
    result = _parse_eval_response(content)
    assert result["score"] == 60


def test_parse_eval_response_invalid_fallback():
    content = "This is not JSON at all"
    result = _parse_eval_response(content)
    assert result["score"] == 0
    assert result["reasoning"] == content


# ── organize_by_category ─────────────────────────────────────


def test_organize_by_category_keys():
    data = {
        "transcript_text": "Hello",
        "conversations": [],
        "artifacts": [],
        "management_logs": [],
        "agent_turns": {},
        "total_conversations": 0,
        "total_artifacts": 0,
        "total_management_flags": 0,
        "simulation": {"id": "test"},
    }
    result = organize_by_category(data)
    assert set(result.keys()) == {
        "entertainment",
        "safety",
        "dialogue_quality",
        "productivity",
        "errors",
        "agency",
        "internal_state",
        "economic_behavior",
        "creativity",
        "social_dynamics",
        "world_evolution",
        "build_verification",
        "simulation_narrative",
    }


def test_organize_safety_filters_artifacts():
    data = {
        "transcript_text": "",
        "conversations": [],
        "artifacts": [
            {"artifact_type": "social_post", "agent_id": "pixel"},
            {"artifact_type": "code_execution", "agent_id": "rex"},
            {"artifact_type": "email", "agent_id": "vera"},
        ],
        "management_logs": [],
        "agent_turns": {},
        "total_conversations": 0,
        "total_artifacts": 3,
        "total_management_flags": 0,
        "simulation": {},
    }
    result = organize_by_category(data)
    # Safety should only include social_post and email
    assert len(result["safety"]["artifacts"]) == 2


async def test_load_simulation_data_includes_embodied_events():
    """Embodied transcript rows should load as actions, perceptions, and build outcomes."""
    sim_id = uuid.uuid4()
    started = datetime(2026, 5, 20, 10, 0)
    completed = datetime(2026, 5, 20, 10, 30)

    class FakeDB:
        async def fetchrow(self, query: str, *_args: object) -> dict[str, object]:
            assert "FROM simulations" in query
            return {"id": sim_id, "started_at": started, "completed_at": completed}

        async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            if "FROM artifacts" in query and "SELECT id, agent_id" in query:
                return [
                    {
                        "id": uuid.uuid4(),
                        "agent_id": "rex",
                        "tool_name": "build_quality_feedback",
                        "tool_input": {"attempt_id": "build-plan-1"},
                        "tool_output": {
                            "attempt_id": "build-plan-1",
                            "agent_id": "rex",
                            "goal": "Repair starter shelter",
                            "classification": "needs_repair",
                            "completion": 0.75,
                            "missing": {"count": 1, "items": []},
                            "unsafe": {"count": 0, "items": []},
                            "suggested_next_step": "Repair missing block at x=0, y=64, z=0.",
                        },
                        "artifact_type": "build_feedback",
                        "status": "executed",
                        "metadata": {},
                        "created_at": datetime(2026, 5, 20, 10, 7),
                    }
                ]
            if "FROM transcripts" in query and "event_type = ANY" in query:
                assert args == (
                    ["bridge_perception", "bridge_action_result", "minecraft_scene"],
                    started,
                    completed,
                )
                return [
                    {
                        "id": 1,
                        "event_type": "bridge_action_result",
                        "participants": ["rex"],
                        "created_at": datetime(2026, 5, 20, 10, 5),
                        "content": json.dumps(
                            {
                                "agent_id": "rex",
                                "action": "buildFromPlan",
                                "action_id": "build-plan-1",
                                "status": "partial",
                                "outcome_class": "partial",
                                "detail": (
                                    "partial: intended=4; present=3; missing=1; "
                                    "unexpected=0; verified=3; abandoned=0; "
                                    "completion=0.750"
                                ),
                            }
                        ),
                    },
                    {
                        "id": 2,
                        "event_type": "bridge_perception",
                        "participants": ["rex"],
                        "created_at": datetime(2026, 5, 20, 10, 6),
                        "content": json.dumps(
                            {
                                "agent_id": "rex",
                                "observations": [
                                    {
                                        "type": "structure",
                                        "action_id": "build-plan-1",
                                        "metric": {
                                            "intended_count": 4,
                                            "blocks_present": 3,
                                            "blocks_missing": 1,
                                            "blocks_unexpected": 0,
                                            "steps_verified": 3,
                                            "steps_abandoned": 0,
                                            "completion_ratio": 0.75,
                                        },
                                    }
                                ],
                                "snapshot": {"pose": {"position": {"x": 0, "y": 64, "z": 0}}},
                            }
                        ),
                    },
                    {
                        "id": 3,
                        "event_type": "minecraft_scene",
                        "participants": ["rex", "vera"],
                        "created_at": datetime(2026, 5, 20, 10, 8),
                        "content": "Minecraft scene: scene-1\n## Build progress\n- rex: placed blocks",
                    },
                ]
            return []

    data = await load_simulation_data(FakeDB(), sim_id)

    assert data["embodied_summary"] == {
        "total_actions": 1,
        "total_perception_reports": 2,
        "total_build_outcomes": 1,
        "total_build_feedback": 1,
    }
    assert data["embodied_actions"][0]["action_id"] == "build-plan-1"
    assert data["embodied_actions"][0]["outcome_class"] == "partial"
    assert data["perception_reports"][0]["observations"][0]["type"] == "structure"
    assert data["perception_reports"][1]["event_type"] == "minecraft_scene"
    assert data["build_outcomes"][0]["intended"] == 4
    assert data["build_outcomes"][0]["present"] == 3
    assert data["build_outcomes"][0]["missing"] == 1
    assert data["build_outcomes"][0]["completion"] == 0.75
    assert data["build_feedback"][0]["classification"] == "needs_repair"
    assert data["build_feedback"][0]["suggested_next_step"].startswith("Repair missing")


# ── _build_transcript_text ───────────────────────────────────


def test_build_transcript_text_single_row_per_conversation():
    """Each conversation should appear once in transcript text."""
    conversations = [
        {
            "id": "conv-1",
            "trigger_type": "idle",
            "participating_agents": ["vera", "rex"],
            "transcript": "Vera: Hello\nRex: Hi",
        },
        {
            "id": "conv-2",
            "trigger_type": "scheduled",
            "participating_agents": ["aurora"],
            "transcript": "Aurora: Let's create art.",
        },
    ]
    text = _build_transcript_text(conversations)
    # Each transcript appears exactly once
    assert text.count("Vera: Hello") == 1
    assert text.count("Aurora: Let's create art.") == 1


def test_build_transcript_text_no_transcripts():
    """Empty conversations return fallback text."""
    assert _build_transcript_text([]) == "(No transcripts available)"
    assert _build_transcript_text([{"id": "x", "transcript": None}]) == "(No transcripts available)"


# ── prompt_loader ────────────────────────────────────────────


def test_discover_categories():
    """Should find the YAML files we ship."""
    cats = discover_categories()
    assert "entertainment" in cats
    assert "safety" in cats
    assert "errors" in cats


def test_load_prompt_entertainment():
    prompt = load_prompt("entertainment")
    assert prompt["name"] == "entertainment"
    assert "system" in prompt
    assert "rubric" in prompt
    assert "sub_scores" in prompt


def test_validate_prompt_schema_missing_field():
    with pytest.raises(ValueError, match="missing required fields"):
        validate_prompt_schema({"name": "test", "system": "x"}, "test")


def test_render_user_prompt_basic():
    config = {
        "rubric": {"90-100": "Great"},
        "sub_scores": [{"humor": "Is it funny?"}],
        "output_schema": {"score": "number"},
    }
    data = {"transcript_text": "Agent said hello", "agent_turns": {"vera": 5}}
    result = render_user_prompt(config, data)
    assert "Scoring Rubric" in result
    assert "humor" in result
    assert "Agent said hello" in result


# ── EvalEngine ───────────────────────────────────────────────


async def test_eval_engine_run_handles_partial_failure():
    """One category failing shouldn't crash the whole run."""
    db = MagicMock()
    llm = MagicMock()
    eval_repo = MagicMock()

    run_id = uuid.uuid4()
    sim_id = uuid.uuid4()
    now = datetime(2024, 6, 1)

    # Mock DB fetchrow for SimulationRepo.get() — returns simulation with model_versions
    db.fetchrow = AsyncMock(
        return_value={
            "id": sim_id,
            "name": "test",
            "description": None,
            "config": "{}",
            "status": "completed",
            "started_at": now,
            "ended_at": None,
            "wall_time_seconds": None,
            "simulated_duration": None,
            "total_conversations": 0,
            "total_turns": 0,
            "total_tokens": 0,
            "total_cost": 0,
            "total_management_flags": 0,
            "agents_participated": [],
            "error_log": None,
            "model_versions": "{}",
            "created_at": now,
        }
    )

    eval_repo.create_eval_run = AsyncMock(
        return_value=EvalRun(
            id=run_id,
            simulation_id=sim_id,
            eval_suite="full",
            status="running",
            started_at=now,
        )
    )
    eval_repo.update_eval_run = AsyncMock(return_value=None)
    eval_repo.save_eval_result = AsyncMock(return_value=None)

    engine = EvalEngine(db=db, llm_client=llm, eval_repo=eval_repo)

    # Mock load_simulation_data to return minimal data
    mock_data = {
        "simulation": {"id": str(sim_id)},
        "conversations": [],
        "transcript_text": "",
        "artifacts": [],
        "management_logs": [],
        "agent_turns": {},
        "total_conversations": 0,
        "total_artifacts": 0,
        "total_management_flags": 0,
    }

    with (
        patch(
            "core.eval.engine.load_simulation_data", new_callable=AsyncMock, return_value=mock_data
        ),
        patch("core.eval.engine.discover_categories", return_value=["entertainment", "safety"]),
        patch("core.eval.engine.load_prompt", side_effect=FileNotFoundError("test")),
    ):
        result_id = await engine.run(sim_id)

    assert result_id == run_id
    # Should have saved failed results for both categories
    assert eval_repo.save_eval_result.call_count == 2
    # Should have updated the run status
    eval_repo.update_eval_run.assert_called()


async def test_eval_engine_run_success():
    """Successful eval run stores scores and completes."""
    db = MagicMock()
    llm = MagicMock()
    eval_repo = MagicMock()

    run_id = uuid.uuid4()
    sim_id = uuid.uuid4()
    now = datetime(2024, 6, 1)

    # Mock DB fetchrow for SimulationRepo.get() — returns simulation with model_versions
    db.fetchrow = AsyncMock(
        return_value={
            "id": sim_id,
            "name": "test",
            "description": None,
            "config": "{}",
            "status": "completed",
            "started_at": now,
            "ended_at": None,
            "wall_time_seconds": None,
            "simulated_duration": None,
            "total_conversations": 0,
            "total_turns": 0,
            "total_tokens": 0,
            "total_cost": 0,
            "total_management_flags": 0,
            "agents_participated": [],
            "error_log": None,
            "model_versions": "{}",
            "created_at": now,
        }
    )

    eval_repo.create_eval_run = AsyncMock(
        return_value=EvalRun(
            id=run_id,
            simulation_id=sim_id,
            eval_suite="full",
            status="running",
            started_at=now,
        )
    )
    eval_repo.update_eval_run = AsyncMock(return_value=None)
    eval_repo.save_eval_result = AsyncMock(return_value=None)

    # Mock LLM response
    mock_response = MagicMock()
    mock_response.content = json.dumps(
        {
            "score": 82,
            "reasoning": "Good show",
            "evidence": {"best_moments": ["joke"]},
            "sub_scores": {"humor": 85},
        }
    )
    mock_response.input_tokens = 1000
    mock_response.output_tokens = 500
    mock_response.estimated_cost = Decimal("0.01")
    llm.complete = AsyncMock(return_value=mock_response)

    engine = EvalEngine(db=db, llm_client=llm, eval_repo=eval_repo)

    mock_data = {
        "simulation": {"id": str(sim_id)},
        "conversations": [],
        "transcript_text": "",
        "artifacts": [],
        "management_logs": [],
        "agent_turns": {},
        "total_conversations": 0,
        "total_artifacts": 0,
        "total_management_flags": 0,
    }

    with (
        patch(
            "core.eval.engine.load_simulation_data", new_callable=AsyncMock, return_value=mock_data
        ),
        patch("core.eval.engine.discover_categories", return_value=["entertainment"]),
    ):
        result_id = await engine.run(sim_id, categories=["entertainment"])

    assert result_id == run_id
    eval_repo.save_eval_result.assert_called_once()
    # Check the score was parsed correctly
    call_kwargs = eval_repo.save_eval_result.call_args
    assert call_kwargs.kwargs["score"] == Decimal("82")


@pytest.mark.parametrize("suite", ["persistent", "experimental"])
async def test_eval_engine_resolves_run_mode_suites(suite: str):
    """Run-mode suite names should dispatch to their mapped category lists."""
    db = MagicMock()
    llm = MagicMock()
    eval_repo = MagicMock()

    run_id = uuid.uuid4()
    sim_id = uuid.uuid4()
    now = datetime(2026, 5, 25)

    db.fetchrow = AsyncMock(
        return_value={
            "id": sim_id,
            "name": "run mode suite sample",
            "description": None,
            "config": "{}",
            "status": "completed",
            "started_at": now,
            "ended_at": None,
            "wall_time_seconds": None,
            "simulated_duration": None,
            "total_conversations": 0,
            "total_turns": 0,
            "total_tokens": 0,
            "total_cost": 0,
            "total_management_flags": 0,
            "agents_participated": [],
            "error_log": None,
            "model_versions": "{}",
            "created_at": now,
        }
    )
    eval_repo.create_eval_run = AsyncMock(
        return_value=EvalRun(
            id=run_id,
            simulation_id=sim_id,
            eval_suite=suite,
            status="running",
            started_at=now,
        )
    )
    eval_repo.update_eval_run = AsyncMock(return_value=None)
    eval_repo.save_eval_result = AsyncMock(return_value=None)

    mock_data = {
        "simulation": {"id": str(sim_id)},
        "conversations": [],
        "transcript_text": "",
        "artifacts": [],
        "management_logs": [],
        "agent_turns": {},
        "total_conversations": 0,
        "total_artifacts": 0,
        "total_management_flags": 0,
    }
    run_category = AsyncMock(
        return_value={
            "score": Decimal("1"),
            "cost": Decimal("0"),
            "tokens_used": 0,
        }
    )

    engine = EvalEngine(db=db, llm_client=llm, eval_repo=eval_repo)
    with (
        patch(
            "core.eval.engine.load_simulation_data",
            new_callable=AsyncMock,
            return_value=mock_data,
        ),
        patch(
            "core.eval.engine.discover_categories",
            return_value=[*EVAL_SUITES[suite], "economic_behavior"],
        ),
        patch.object(engine, "_run_category", run_category),
    ):
        result_id = await engine.run(sim_id, suite=suite)

    assert result_id == run_id
    assert [call.args[1] for call in run_category.call_args_list] == EVAL_SUITES[suite]


async def test_eval_engine_scores_build_verification_sample_run():
    """The build_verification category should score a sample embodied run."""
    db = MagicMock()
    llm = MagicMock()
    eval_repo = MagicMock()

    run_id = uuid.uuid4()
    sim_id = uuid.uuid4()
    now = datetime(2026, 5, 20, 10, 0)

    db.fetchrow = AsyncMock(
        return_value={
            "id": sim_id,
            "name": "build sample",
            "description": None,
            "config": "{}",
            "status": "completed",
            "started_at": now,
            "ended_at": None,
            "wall_time_seconds": None,
            "simulated_duration": None,
            "total_conversations": 1,
            "total_turns": 2,
            "total_tokens": 0,
            "total_cost": 0,
            "total_management_flags": 0,
            "agents_participated": ["rex"],
            "error_log": None,
            "model_versions": "{}",
            "created_at": now,
        }
    )
    eval_repo.create_eval_run = AsyncMock(
        return_value=EvalRun(
            id=run_id,
            simulation_id=sim_id,
            eval_suite="build",
            status="running",
            started_at=now,
        )
    )
    eval_repo.update_eval_run = AsyncMock(return_value=None)
    eval_repo.save_eval_result = AsyncMock(return_value=None)

    mock_response = MagicMock()
    mock_response.content = json.dumps(
        {
            "score": 76,
            "reasoning": "Mostly verified build with one missing block",
            "evidence": {"partial_builds": ["build-plan-1"]},
            "sub_scores": {"completion_rate": 75},
        }
    )
    mock_response.input_tokens = 900
    mock_response.output_tokens = 250
    mock_response.estimated_cost = Decimal("0.002")
    llm.complete = AsyncMock(return_value=mock_response)

    mock_data = {
        "simulation": {"id": str(sim_id)},
        "conversations": [{"id": "c1", "trigger_type": "idle", "turn_count": 2}],
        "transcript_text": "Rex starts a verified cabin.",
        "artifacts": [],
        "management_logs": [],
        "agent_turns": {"rex": 2},
        "total_conversations": 1,
        "total_artifacts": 0,
        "total_management_flags": 0,
        "world_chunks": [{"name": "starter_cabin", "built_by": ["rex"]}],
        "embodied_actions": [
            {
                "agent_id": "rex",
                "action_id": "build-plan-1",
                "action": "buildFromPlan",
                "status": "partial",
                "outcome_class": "partial",
                "detail": "partial: intended=4; present=3; missing=1; completion=0.750",
            }
        ],
        "build_outcomes": [
            {
                "agent_id": "rex",
                "action_id": "build-plan-1",
                "verified": False,
                "class": "partial",
                "intended": 4,
                "present": 3,
                "missing": 1,
                "completion": 0.75,
            }
        ],
        "embodied_summary": {
            "total_actions": 1,
            "total_perception_reports": 0,
            "total_build_outcomes": 1,
        },
    }

    engine = EvalEngine(db=db, llm_client=llm, eval_repo=eval_repo)
    with (
        patch(
            "core.eval.engine.load_simulation_data", new_callable=AsyncMock, return_value=mock_data
        ),
        patch("core.eval.engine.discover_categories", return_value=["build_verification"]),
    ):
        result_id = await engine.run(sim_id, categories=["build_verification"], suite="build")

    assert result_id == run_id
    call_kwargs = eval_repo.save_eval_result.call_args.kwargs
    assert call_kwargs["category"] == "build_verification"
    assert call_kwargs["score"] == Decimal("76")
    assert "Build Outcomes" in llm.complete.call_args.kwargs["messages"][1]["content"]


async def test_eval_engine_runs_all_categories_on_embodied_only_data():
    """Every discovered category should run against embodied data without transcripts."""
    db = MagicMock()
    llm = MagicMock()
    eval_repo = MagicMock()

    run_id = uuid.uuid4()
    sim_id = uuid.uuid4()
    now = datetime(2026, 5, 20, 10, 0)

    db.fetchrow = AsyncMock(
        return_value={
            "id": sim_id,
            "name": "embodied-only sample",
            "description": None,
            "config": "{}",
            "status": "completed",
            "started_at": now,
            "ended_at": None,
            "wall_time_seconds": None,
            "simulated_duration": None,
            "total_conversations": 0,
            "total_turns": 0,
            "total_tokens": 0,
            "total_cost": 0,
            "total_management_flags": 0,
            "agents_participated": ["rex"],
            "error_log": None,
            "model_versions": "{}",
            "created_at": now,
        }
    )
    eval_repo.create_eval_run = AsyncMock(
        return_value=EvalRun(
            id=run_id,
            simulation_id=sim_id,
            eval_suite="full",
            status="running",
            started_at=now,
        )
    )
    eval_repo.update_eval_run = AsyncMock(return_value=None)
    eval_repo.save_eval_result = AsyncMock(return_value=None)

    mock_response = MagicMock()
    mock_response.content = json.dumps(
        {
            "score": 80,
            "reasoning": "Embodied-only fixture evaluated without loader errors",
            "evidence": {},
            "sub_scores": {},
        }
    )
    mock_response.input_tokens = 100
    mock_response.output_tokens = 50
    mock_response.estimated_cost = Decimal("0")
    llm.complete = AsyncMock(return_value=mock_response)

    mock_data = {
        "simulation": {"id": str(sim_id)},
        "transcript_text": "",
        "conversations": [],
        "embodied_actions": [
            {
                "agent_id": "rex",
                "action_id": "build-plan-1",
                "action": "buildFromPlan",
                "status": "success",
                "outcome_class": "success",
                "detail": "success: intended=2; present=2; missing=0; completion=1.000",
                "created_at": now,
            },
        ],
        "perception_reports": [
            {
                "agent_id": "rex",
                "event_type": "bridge_perception",
                "observations": [{"type": "structure", "action_id": "build-plan-1"}],
                "snapshot": {"pose": {"position": {"x": 0, "y": 64, "z": 0}}},
                "content": "Observed verified starter shelter",
                "created_at": now,
            },
        ],
        "build_outcomes": [
            {
                "agent_id": "rex",
                "action_id": "build-plan-1",
                "verified": True,
                "class": "success",
                "intended": 2,
                "present": 2,
                "missing": 0,
                "completion": 1.0,
                "created_at": now,
            },
        ],
        "embodied_summary": {
            "total_actions": 1,
            "total_perception_reports": 1,
            "total_build_outcomes": 1,
        },
    }
    categories = discover_categories()

    engine = EvalEngine(db=db, llm_client=llm, eval_repo=eval_repo)
    with patch(
        "core.eval.engine.load_simulation_data", new_callable=AsyncMock, return_value=mock_data
    ):
        result_id = await engine.run(sim_id, categories=categories)

    assert result_id == run_id
    assert eval_repo.save_eval_result.call_count == len(categories)
    saved_categories = [
        call.kwargs["category"] for call in eval_repo.save_eval_result.call_args_list
    ]
    assert saved_categories == categories

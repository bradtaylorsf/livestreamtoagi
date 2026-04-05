"""Tests for the eval engine, loader, and prompt_loader."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.eval.engine import EvalEngine, _parse_eval_response
from core.eval.loader import organize_by_category
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
    assert set(result.keys()) == {"entertainment", "safety", "dialogue_quality", "productivity", "errors", "agency"}


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

    eval_repo.create_eval_run = AsyncMock(return_value=EvalRun(
        id=run_id, simulation_id=sim_id, eval_suite="full",
        status="running", started_at=now,
    ))
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
        patch("core.eval.engine.load_simulation_data", new_callable=AsyncMock, return_value=mock_data),
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

    eval_repo.create_eval_run = AsyncMock(return_value=EvalRun(
        id=run_id, simulation_id=sim_id, eval_suite="full",
        status="running", started_at=now,
    ))
    eval_repo.update_eval_run = AsyncMock(return_value=None)
    eval_repo.save_eval_result = AsyncMock(return_value=None)

    # Mock LLM response
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "score": 82,
        "reasoning": "Good show",
        "evidence": {"best_moments": ["joke"]},
        "sub_scores": {"humor": 85},
    })
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
        patch("core.eval.engine.load_simulation_data", new_callable=AsyncMock, return_value=mock_data),
        patch("core.eval.engine.discover_categories", return_value=["entertainment"]),
    ):
        result_id = await engine.run(sim_id, categories=["entertainment"])

    assert result_id == run_id
    eval_repo.save_eval_result.assert_called_once()
    # Check the score was parsed correctly
    call_kwargs = eval_repo.save_eval_result.call_args
    assert call_kwargs.kwargs["score"] == Decimal("82")

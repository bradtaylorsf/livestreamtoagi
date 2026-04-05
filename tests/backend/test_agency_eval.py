"""Tests for agency eval dimension (#240)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.eval.prompt_loader import discover_categories, load_prompt, validate_prompt_schema


class TestAgencyEvalPrompt:
    def test_agency_yaml_exists(self) -> None:
        """agency.yaml must exist in evals/prompts/."""
        path = Path("evals/prompts/agency.yaml")
        assert path.exists(), "agency.yaml not found"

    def test_agency_yaml_valid_schema(self) -> None:
        """agency.yaml must have all required fields."""
        data = load_prompt("agency")
        # Should not raise
        validate_prompt_schema(data, "agency")

    def test_agency_has_correct_sub_scores(self) -> None:
        data = load_prompt("agency")
        sub_score_names = set()
        for item in data["sub_scores"]:
            if isinstance(item, dict):
                sub_score_names.update(item.keys())
        expected = {
            "proactivity", "goal_progress", "capability_growth",
            "self_direction", "collaboration_initiative",
        }
        assert expected == sub_score_names

    def test_agency_in_discovered_categories(self) -> None:
        categories = discover_categories()
        assert "agency" in categories

    def test_agency_rubric_has_all_ranges(self) -> None:
        data = load_prompt("agency")
        rubric = data["rubric"]
        expected_ranges = {"90-100", "70-89", "50-69", "30-49", "0-29"}
        assert set(rubric.keys()) == expected_ranges

    def test_agency_output_schema_has_evidence(self) -> None:
        data = load_prompt("agency")
        evidence_schema = data["output_schema"]["evidence"]
        assert "self_initiated_tasks" in evidence_schema
        assert "goals_advanced" in evidence_schema
        assert "most_proactive_agent" in evidence_schema
        assert "stagnation_signals" in evidence_schema


class TestProductivityEvalUpdate:
    def test_productivity_has_initiative_sub_score(self) -> None:
        data = load_prompt("productivity")
        sub_score_names = set()
        for item in data["sub_scores"]:
            if isinstance(item, dict):
                sub_score_names.update(item.keys())
        assert "initiative" in sub_score_names
        assert "growth" in sub_score_names

    def test_productivity_output_schema_has_new_fields(self) -> None:
        data = load_prompt("productivity")
        sub_scores_schema = data["output_schema"]["sub_scores"]
        assert "initiative" in sub_scores_schema
        assert "growth" in sub_scores_schema


class TestQuickSuiteIncludesAgency:
    def test_agency_in_quick_categories(self) -> None:
        from core.eval.engine import QUICK_CATEGORIES

        assert "agency" in QUICK_CATEGORIES


class TestLoaderIncludesAgencyData:
    def test_organize_by_category_has_agency(self) -> None:
        from core.eval.loader import organize_by_category

        data = {
            "simulation": {},
            "conversations": [],
            "transcript_text": "",
            "artifacts": [],
            "management_logs": [],
            "agent_turns": {},
            "agent_goals": [{"agent_id": "rex", "goal": "Build it", "status": "active"}],
            "tool_usage": [{"agent_id": "rex", "tool_name": "execute_code", "use_count": 5}],
            "total_conversations": 0,
            "total_artifacts": 0,
            "total_management_flags": 0,
        }
        result = organize_by_category(data)
        assert "agency" in result
        assert result["agency"]["agent_goals"] == data["agent_goals"]
        assert result["agency"]["tool_usage"] == data["tool_usage"]
        assert "transcript_text" in result["agency"]


class TestPromptLoaderRendersGoals:
    def test_render_includes_agent_goals(self) -> None:
        from core.eval.prompt_loader import render_user_prompt

        prompt_config = load_prompt("agency")
        category_data = {
            "transcript_text": "Rex: Let me build this prototype.",
            "conversations": [],
            "agent_turns": {"rex": 5},
            "artifacts": [],
            "agent_goals": [
                {"agent_id": "rex", "goal": "Build prototype", "status": "active",
                 "priority": 1, "source": "self"},
            ],
            "tool_usage": [
                {"agent_id": "rex", "tool_name": "execute_code", "use_count": 3},
            ],
        }

        rendered = render_user_prompt(prompt_config, category_data)
        assert "Agent Goals" in rendered
        assert "Build prototype" in rendered
        assert "Tool Usage Summary" in rendered
        assert "execute_code" in rendered

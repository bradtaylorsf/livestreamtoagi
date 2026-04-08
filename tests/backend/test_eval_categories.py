"""Tests for new eval categories: internal_state, economic_behavior, creativity, social_dynamics, world_evolution."""

from __future__ import annotations

from core.eval.loader import organize_by_category
from core.eval.prompt_loader import (
    discover_categories,
    load_prompt,
    render_user_prompt,
    validate_prompt_schema,
)
from core.eval.engine import EVAL_SUITES, QUICK_CATEGORIES


# ── YAML prompt validation ──────────────────────────────────

NEW_CATEGORIES = [
    "internal_state",
    "economic_behavior",
    "creativity",
    "social_dynamics",
    "world_evolution",
]


def test_new_categories_discovered():
    """All 5 new eval categories should be auto-discovered from YAML files."""
    cats = discover_categories()
    for cat in NEW_CATEGORIES:
        assert cat in cats, f"Category '{cat}' not found in discovered categories"


def test_new_category_yamls_valid():
    """Each new YAML file should load and pass schema validation."""
    for cat in NEW_CATEGORIES:
        prompt = load_prompt(cat)
        assert prompt["name"] == cat
        # validate_prompt_schema raises on missing fields — no error = pass
        validate_prompt_schema(prompt, cat)


def test_new_categories_have_five_sub_scores():
    """Each new category should have exactly 5 sub-scores per the issue spec."""
    for cat in NEW_CATEGORIES:
        prompt = load_prompt(cat)
        assert len(prompt["sub_scores"]) == 5, (
            f"Category '{cat}' has {len(prompt['sub_scores'])} sub_scores, expected 5"
        )


def test_new_category_sub_score_names():
    """Sub-score names should match the issue specification."""
    expected = {
        "internal_state": [
            "state_coherence", "mood_influence", "state_divergence",
            "need_driven_behavior", "energy_management",
        ],
        "economic_behavior": [
            "spending_intelligence", "trading_quality", "scarcity_adaptation",
            "economic_drama", "investment_reasoning",
        ],
        "creativity": [
            "dream_quality", "creative_initiative", "build_ambition",
            "artistic_voice", "dream_integration",
        ],
        "social_dynamics": [
            "alliance_organic", "faction_coherence", "conflict_quality",
            "relationship_evolution", "political_maneuvering",
        ],
        "world_evolution": [
            "build_completion", "world_growth", "code_quality",
            "proposal_quality", "collaborative_building",
        ],
    }
    for cat, names in expected.items():
        prompt = load_prompt(cat)
        actual_names = []
        for sub in prompt["sub_scores"]:
            if isinstance(sub, dict):
                actual_names.extend(sub.keys())
            else:
                actual_names.append(sub)
        assert actual_names == names, f"Category '{cat}' sub_scores mismatch"


# ── EVAL_SUITES ─────────────────────────────────────────────


def test_internal_state_in_quick_categories():
    """internal_state should be added to QUICK_CATEGORIES."""
    assert "internal_state" in QUICK_CATEGORIES


def test_eval_suites_defined():
    """All named suites should be present."""
    assert "quick" in EVAL_SUITES
    assert "autonomy" in EVAL_SUITES
    assert "economy" in EVAL_SUITES
    assert "creative" in EVAL_SUITES
    assert "full" in EVAL_SUITES


def test_eval_suites_contents():
    """Each suite should contain the expected categories."""
    assert set(EVAL_SUITES["autonomy"]) == {
        "internal_state", "agency", "entertainment", "dialogue_quality",
    }
    assert set(EVAL_SUITES["economy"]) == {
        "economic_behavior", "entertainment", "social_dynamics",
    }
    assert set(EVAL_SUITES["creative"]) == {
        "creativity", "world_evolution", "entertainment",
    }
    # full is empty (means all available at runtime)
    assert EVAL_SUITES["full"] == []


# ── organize_by_category ────────────────────────────────────


def _make_full_data():
    """Helper to create data dict with all fields populated."""
    return {
        "transcript_text": "test transcript",
        "conversations": [{"id": "c1", "trigger_type": "idle", "turn_count": 5}],
        "artifacts": [
            {"artifact_type": "social_post", "agent_id": "pixel", "status": "ok"},
            {"artifact_type": "code_execution", "agent_id": "rex", "status": "failed"},
        ],
        "management_logs": [],
        "agent_turns": {"vera": 10},
        "total_conversations": 1,
        "total_artifacts": 2,
        "total_management_flags": 0,
        "simulation": {"id": "test"},
        "agent_goals": [],
        "tool_usage": [],
        "agent_internal_state": [
            {"agent_id": "vera", "mood": "focused", "energy": 0.8},
        ],
        "transactions": [
            {"agent_id": "rex", "type": "tool_cost", "amount": -0.05},
        ],
        "dream_entries": [
            {"agent_id": "aurora", "content": "Dreamed of pixel gardens"},
        ],
        "alliance_records": [
            {"name": "Builders", "founded_by": "rex", "members": ["rex", "aurora"]},
        ],
        "world_chunks": [
            {"name": "town_square", "built_by": ["rex"], "width": 32, "height": 32},
        ],
    }


def test_organize_includes_new_categories():
    """organize_by_category should include all 5 new categories."""
    data = _make_full_data()
    result = organize_by_category(data)
    for cat in NEW_CATEGORIES:
        assert cat in result, f"Category '{cat}' not in organized data"


def test_organize_internal_state_has_state_data():
    data = _make_full_data()
    result = organize_by_category(data)
    assert "agent_internal_state" in result["internal_state"]
    assert len(result["internal_state"]["agent_internal_state"]) == 1


def test_organize_economic_behavior_has_transactions():
    data = _make_full_data()
    result = organize_by_category(data)
    assert "transactions" in result["economic_behavior"]
    assert len(result["economic_behavior"]["transactions"]) == 1


def test_organize_creativity_has_dreams():
    data = _make_full_data()
    result = organize_by_category(data)
    assert "dream_entries" in result["creativity"]
    assert len(result["creativity"]["dream_entries"]) == 1


def test_organize_social_dynamics_has_alliances():
    data = _make_full_data()
    result = organize_by_category(data)
    assert "alliance_records" in result["social_dynamics"]
    assert len(result["social_dynamics"]["alliance_records"]) == 1


def test_organize_world_evolution_has_chunks():
    data = _make_full_data()
    result = organize_by_category(data)
    assert "world_chunks" in result["world_evolution"]
    assert len(result["world_evolution"]["world_chunks"]) == 1


# ── render_user_prompt with new data types ──────────────────


def test_render_prompt_with_internal_state():
    config = {
        "rubric": {"90-100": "Excellent"},
        "sub_scores": [{"state_coherence": "Does it match?"}],
        "output_schema": {"score": "number"},
    }
    data = {
        "transcript_text": "Test",
        "agent_internal_state": [
            {"agent_id": "vera", "mood": "focused", "energy": 0.8,
             "satisfaction": 0.6, "boredom": 0.1, "frustration": 0.0,
             "social_need": 0.3, "creative_need": 0.5, "recognition_need": 0.2},
        ],
    }
    result = render_user_prompt(config, data)
    assert "Agent Internal State" in result
    assert "vera" in result
    assert "focused" in result


def test_render_prompt_with_transactions():
    config = {
        "rubric": {"90-100": "Rich economy"},
        "sub_scores": [{"spending_intelligence": "Smart spending?"}],
        "output_schema": {"score": "number"},
    }
    data = {
        "transcript_text": "Test",
        "transactions": [
            {"agent_id": "rex", "type": "tool_cost", "amount": -0.05,
             "counterparty_agent_id": None, "description": "web_search"},
        ],
    }
    result = render_user_prompt(config, data)
    assert "Transaction History" in result
    assert "tool_cost" in result


def test_render_prompt_with_dream_entries():
    config = {
        "rubric": {"90-100": "Creative"},
        "sub_scores": [{"dream_quality": "Good dreams?"}],
        "output_schema": {"score": "number"},
    }
    data = {
        "transcript_text": "Test",
        "dream_entries": [
            {"agent_id": "aurora", "reflection_type": "dream",
             "content": "Dreamed of pixel gardens and infinite canvases"},
        ],
    }
    result = render_user_prompt(config, data)
    assert "Dream Journal Entries" in result
    assert "pixel gardens" in result


def test_render_prompt_with_alliance_records():
    config = {
        "rubric": {"90-100": "Social"},
        "sub_scores": [{"alliance_organic": "Organic alliances?"}],
        "output_schema": {"score": "number"},
    }
    data = {
        "transcript_text": "Test",
        "alliance_records": [
            {"name": "Builders", "founded_by": "rex", "purpose": "Build stuff",
             "members": ["rex", "aurora"], "dissolved_at": None},
        ],
    }
    result = render_user_prompt(config, data)
    assert "Alliance Records" in result
    assert "Builders" in result


def test_render_prompt_with_world_chunks():
    config = {
        "rubric": {"90-100": "Growing"},
        "sub_scores": [{"world_growth": "Growing?"}],
        "output_schema": {"score": "number"},
    }
    data = {
        "transcript_text": "Test",
        "world_chunks": [
            {"name": "town_square", "built_by": ["rex"], "width": 32,
             "height": 32, "description": "Central gathering area"},
        ],
    }
    result = render_user_prompt(config, data)
    assert "World Chunks" in result
    assert "town_square" in result

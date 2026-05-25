"""Tests for eval categories (including simulation_narrative)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.eval.engine import EVAL_SUITES, QUICK_CATEGORIES
from core.eval.loader import _build_timeline, organize_by_category
from core.eval.prompt_loader import (
    discover_categories,
    load_prompt,
    render_user_prompt,
    validate_prompt_schema,
)

# ── YAML prompt validation ──────────────────────────────────

NEW_CATEGORIES = [
    "internal_state",
    "economic_behavior",
    "creativity",
    "social_dynamics",
    "world_evolution",
]
BUILD_CATEGORIES = ["build_verification"]


def test_new_categories_discovered():
    """All 5 new eval categories should be auto-discovered from YAML files."""
    cats = discover_categories()
    for cat in NEW_CATEGORIES:
        assert cat in cats, f"Category '{cat}' not found in discovered categories"


def test_build_verification_category_discovered():
    cats = discover_categories()
    for cat in BUILD_CATEGORIES:
        assert cat in cats, f"Category '{cat}' not found in discovered categories"


def test_new_category_yamls_valid():
    """Each new YAML file should load and pass schema validation."""
    for cat in NEW_CATEGORIES:
        prompt = load_prompt(cat)
        assert prompt["name"] == cat
        # validate_prompt_schema raises on missing fields — no error = pass
        validate_prompt_schema(prompt, cat)


def test_build_verification_yaml_valid():
    prompt = load_prompt("build_verification")
    assert prompt["name"] == "build_verification"
    validate_prompt_schema(prompt, "build_verification")


def test_new_categories_have_five_sub_scores():
    """Each new category should have exactly 5 sub-scores per the issue spec."""
    for cat in NEW_CATEGORIES:
        prompt = load_prompt(cat)
        assert len(prompt["sub_scores"]) == 5, (
            f"Category '{cat}' has {len(prompt['sub_scores'])} sub_scores, expected 5"
        )


def test_build_verification_has_five_sub_scores():
    prompt = load_prompt("build_verification")
    assert len(prompt["sub_scores"]) == 5


def test_new_category_sub_score_names():
    """Sub-score names should match the issue specification."""
    expected = {
        "internal_state": [
            "state_coherence",
            "mood_influence",
            "state_divergence",
            "need_driven_behavior",
            "energy_management",
        ],
        "economic_behavior": [
            "spending_intelligence",
            "trading_quality",
            "scarcity_adaptation",
            "economic_drama",
            "investment_reasoning",
        ],
        "creativity": [
            "dream_quality",
            "creative_initiative",
            "build_ambition",
            "artistic_voice",
            "dream_integration",
        ],
        "social_dynamics": [
            "alliance_organic",
            "faction_coherence",
            "conflict_quality",
            "relationship_evolution",
            "political_maneuvering",
        ],
        "world_evolution": [
            "build_completion",
            "world_growth",
            "code_quality",
            "proposal_quality",
            "collaborative_building",
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


def test_build_verification_sub_score_names():
    prompt = load_prompt("build_verification")
    actual_names = []
    for sub in prompt["sub_scores"]:
        if isinstance(sub, dict):
            actual_names.extend(sub.keys())
        else:
            actual_names.append(sub)
    assert actual_names == [
        "intended_vs_actual",
        "completion_rate",
        "step_fidelity",
        "failure_recovery",
        "build_ambition",
    ]


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
    assert "build" in EVAL_SUITES
    assert "full" in EVAL_SUITES


def test_eval_suites_contents():
    """Each suite should contain the expected categories."""
    assert set(EVAL_SUITES["autonomy"]) == {
        "internal_state",
        "agency",
        "entertainment",
        "dialogue_quality",
    }
    assert set(EVAL_SUITES["economy"]) == {
        "economic_behavior",
        "entertainment",
        "social_dynamics",
    }
    assert set(EVAL_SUITES["creative"]) == {
        "creativity",
        "world_evolution",
        "entertainment",
        "build_verification",
    }
    assert EVAL_SUITES["build"] == ["build_verification", "world_evolution", "productivity"]
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
        "embodied_actions": [
            {
                "agent_id": "rex",
                "action_id": "build-plan-1",
                "action": "buildFromPlan",
                "status": "partial",
                "outcome_class": "partial",
                "detail": "partial: intended=4; present=3; missing=1; completion=0.750",
                "created_at": datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            },
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
                "created_at": datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            },
        ],
        "perception_reports": [
            {
                "agent_id": "rex",
                "event_type": "bridge_perception",
                "observations": [{"type": "structure", "action_id": "build-plan-1"}],
                "snapshot": {"pose": {"position": {"x": 0, "y": 64, "z": 0}}},
                "content": "Perception report",
                "created_at": datetime(2026, 1, 1, 10, 31, tzinfo=UTC),
            },
        ],
        "embodied_summary": {
            "total_actions": 1,
            "total_perception_reports": 1,
            "total_build_outcomes": 1,
        },
    }


def test_organize_includes_new_categories():
    """organize_by_category should include all 5 new categories."""
    data = _make_full_data()
    result = organize_by_category(data)
    for cat in NEW_CATEGORIES:
        assert cat in result, f"Category '{cat}' not in organized data"


def test_organize_includes_build_verification_category():
    data = _make_full_data()
    result = organize_by_category(data)
    assert "build_verification" in result
    cat = result["build_verification"]
    assert "build_outcomes" in cat
    assert "embodied_actions" in cat
    assert "world_chunks" in cat
    assert "artifacts" in cat
    assert cat["total_artifacts"] == 2
    assert cat["total_conversations"] == 1


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


def test_organize_embodied_data_plumbed_into_existing_categories():
    data = _make_full_data()
    result = organize_by_category(data)
    for cat in [
        "productivity",
        "agency",
        "world_evolution",
        "creativity",
        "simulation_narrative",
    ]:
        assert "embodied_actions" in result[cat]
        assert "build_outcomes" in result[cat]
        assert result[cat]["embodied_summary"]["total_build_outcomes"] == 1
    assert "perception_reports" in result["agency"]
    assert "perception_reports" in result["world_evolution"]
    assert "perception_reports" in result["simulation_narrative"]


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
            {
                "agent_id": "vera",
                "mood": "focused",
                "energy": 0.8,
                "satisfaction": 0.6,
                "boredom": 0.1,
                "frustration": 0.0,
                "social_need": 0.3,
                "creative_need": 0.5,
                "recognition_need": 0.2,
            },
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
            {
                "agent_id": "rex",
                "type": "tool_cost",
                "amount": -0.05,
                "counterparty_agent_id": None,
                "description": "web_search",
            },
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
            {
                "agent_id": "aurora",
                "reflection_type": "dream",
                "content": "Dreamed of pixel gardens and infinite canvases",
            },
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
            {
                "name": "Builders",
                "founded_by": "rex",
                "purpose": "Build stuff",
                "members": ["rex", "aurora"],
                "dissolved_at": None,
            },
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
            {
                "name": "town_square",
                "built_by": ["rex"],
                "width": 32,
                "height": 32,
                "description": "Central gathering area",
            },
        ],
    }
    result = render_user_prompt(config, data)
    assert "World Chunks" in result
    assert "town_square" in result


def test_render_prompt_with_embodied_sections():
    config = {
        "rubric": {"90-100": "Verifiable building"},
        "sub_scores": [{"build_completion": "Did builds verify?"}],
        "output_schema": {"score": "number"},
    }
    data = {
        "embodied_actions": [
            {
                "agent_id": "rex",
                "action": "buildFromPlan",
                "action_id": "build-plan-1",
                "status": "partial",
                "outcome_class": "partial",
                "detail": "missing one block",
            },
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
            },
        ],
        "perception_reports": [
            {
                "agent_id": "rex",
                "event_type": "bridge_perception",
                "observations": [{"type": "structure"}],
                "snapshot": {"pose": {}},
                "content": "structure snapshot",
            },
        ],
    }
    result = render_user_prompt(config, data)
    assert "Embodied Actions" in result
    assert "Build Outcomes" in result
    assert "verified=False class=partial intended=4 present=3 missing=1 completion=0.75" in result
    assert "Perception Reports" in result
    assert "structure snapshot" in result


# ── simulation_narrative category ──────────────────────────


def test_simulation_narrative_discovered():
    """simulation_narrative should be auto-discovered from YAML."""
    cats = discover_categories()
    assert "simulation_narrative" in cats


def test_simulation_narrative_yaml_valid():
    """YAML file should load and pass schema validation."""
    prompt = load_prompt("simulation_narrative")
    assert prompt["name"] == "simulation_narrative"
    validate_prompt_schema(prompt, "simulation_narrative")


def test_simulation_narrative_has_five_sub_scores():
    prompt = load_prompt("simulation_narrative")
    assert len(prompt["sub_scores"]) == 5


def test_simulation_narrative_sub_score_names():
    prompt = load_prompt("simulation_narrative")
    actual_names = []
    for sub in prompt["sub_scores"]:
        if isinstance(sub, dict):
            actual_names.extend(sub.keys())
        else:
            actual_names.append(sub)
    assert actual_names == [
        "narrative_coherence",
        "causal_flow",
        "character_arcs",
        "pacing",
        "emergent_moments",
    ]


def test_narrative_eval_suite_defined():
    """narrative suite should be present in EVAL_SUITES."""
    assert "narrative" in EVAL_SUITES


def test_narrative_eval_suite_contents():
    assert set(EVAL_SUITES["narrative"]) == {
        "simulation_narrative",
        "entertainment",
        "dialogue_quality",
    }


def test_organize_includes_simulation_narrative():
    data = _make_full_data()
    result = organize_by_category(data)
    assert "simulation_narrative" in result


def test_organize_simulation_narrative_has_timeline():
    data = _make_full_data()
    result = organize_by_category(data)
    cat = result["simulation_narrative"]
    assert "timeline" in cat
    assert isinstance(cat["timeline"], str)


def test_organize_simulation_narrative_has_all_data():
    """simulation_narrative should get all data types for the full picture."""
    data = _make_full_data()
    result = organize_by_category(data)
    cat = result["simulation_narrative"]
    assert "transcript_text" in cat
    assert "conversations" in cat
    assert "agent_internal_state" in cat
    assert "transactions" in cat
    assert "alliance_records" in cat
    assert "dream_entries" in cat
    assert "world_chunks" in cat
    assert "embodied_actions" in cat
    assert "build_outcomes" in cat
    assert "perception_reports" in cat


# ── _build_timeline ────────────────────────────────────────


def test_build_timeline_empty_data():
    """Empty data should produce the 'no events' message."""
    result = _build_timeline({})
    assert "No timeline events" in result


def test_build_timeline_sorts_chronologically():
    """Events should be sorted by time."""
    t1 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    t3 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    data = {
        "conversations": [
            {
                "started_at": t3,
                "trigger_type": "idle",
                "participating_agents": ["vera"],
                "transcript": "Late conversation",
            },
        ],
        "transactions": [
            {"created_at": t1, "agent_id": "rex", "amount": -0.05, "description": "web_search"},
        ],
        "dream_entries": [
            {"created_at": t2, "agent_id": "aurora", "content": "A dream of color"},
        ],
    }
    result = _build_timeline(data)
    # Transaction (t1) should appear before dream (t2) before conversation (t3)
    txn_pos = result.find("Transaction")
    dream_pos = result.find("Dream")
    conv_pos = result.find("Conversation")
    assert txn_pos < dream_pos < conv_pos


def test_build_timeline_includes_all_event_types():
    """All event types should appear in the timeline."""
    t = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    data = {
        "conversations": [
            {
                "started_at": t,
                "trigger_type": "idle",
                "participating_agents": ["vera", "rex"],
                "transcript": "Hello",
            },
        ],
        "agent_internal_state": [
            {"updated_at": t, "agent_id": "vera", "mood": "focused", "energy": 0.8},
        ],
        "transactions": [
            {"created_at": t, "agent_id": "rex", "amount": -0.05, "description": "tool cost"},
        ],
        "alliance_records": [
            {"created_at": t, "name": "Builders", "members": ["rex", "aurora"]},
        ],
        "dream_entries": [
            {"created_at": t, "agent_id": "aurora", "content": "pixel gardens"},
        ],
        "world_chunks": [
            {"built_date": t, "name": "town_square", "built_by": ["rex"]},
        ],
        "embodied_actions": [
            {
                "created_at": t,
                "agent_id": "rex",
                "action_id": "build-plan-1",
                "status": "success",
                "outcome_class": "success",
                "detail": "success: intended=2; present=2; completion=1.000",
            },
        ],
        "perception_reports": [
            {
                "created_at": t,
                "agent_id": "rex",
                "event_type": "bridge_perception",
                "observations": [{"type": "structure"}],
                "content": "structure snapshot",
            },
        ],
    }
    result = _build_timeline(data)
    assert "Conversation" in result
    assert "State Change" in result
    assert "Transaction" in result
    assert "Alliance Formed" in result
    assert "Dream" in result
    assert "World Build" in result
    assert "Embodied Action" in result
    assert "Embodied Perception" in result


def test_build_timeline_skips_events_without_timestamps():
    """Events missing timestamps should be silently skipped."""
    data = {
        "conversations": [
            {"started_at": None, "trigger_type": "idle", "participating_agents": ["vera"]},
        ],
        "transactions": [
            {"created_at": None, "agent_id": "rex", "amount": -0.05},
        ],
    }
    result = _build_timeline(data)
    assert "No timeline events" in result


# ── render_user_prompt with timeline ───────────────────────


def test_render_prompt_with_timeline():
    config = {
        "rubric": {"90-100": "Compelling narrative"},
        "sub_scores": [{"narrative_coherence": "Coherent story?"}],
        "output_schema": {"score": "number"},
    }
    data = {
        "timeline": "# Simulation Timeline\n\n- **[2026-01-01] Conversation**: vera, rex",
        "transcript_text": "Test transcript",
    }
    result = render_user_prompt(config, data)
    assert "Chronological Timeline" in result
    assert "Simulation Timeline" in result
    assert "Test transcript" in result

"""Tests for simulation scenario YAML files and chat.py scenario integration."""

from __future__ import annotations

from pathlib import Path

import yaml


SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "scenarios"

NEW_SCENARIOS = [
    "initiative_test",
    "goal_generation_test",
    "budget_crisis",
    "topic_exhaustion_test",
    "novelty_injection_test",
    "dream_cycle_test",
    "faction_emergence_test",
    "full_evolution_7d",
    "dress_rehearsal",
    "ab_test",
]


def _load_scenario(name: str) -> dict:
    path = SCENARIOS_DIR / f"{name}.yaml"
    assert path.exists(), f"Scenario file not found: {path}"
    with open(path) as f:
        return yaml.safe_load(f)


def test_all_new_scenario_files_exist():
    """All 10 new scenario YAML files should exist in scenarios/."""
    for name in NEW_SCENARIOS:
        path = SCENARIOS_DIR / f"{name}.yaml"
        assert path.exists(), f"Missing scenario: {path}"


def test_scenario_yaml_valid():
    """All scenario files should be valid YAML with phases."""
    for name in NEW_SCENARIOS:
        data = _load_scenario(name)
        assert "phases" in data, f"Scenario '{name}' missing 'phases' key"
        assert len(data["phases"]) > 0, f"Scenario '{name}' has no phases"


def test_scenario_phase_structure():
    """Each phase should have required fields: name and type."""
    for name in NEW_SCENARIOS:
        data = _load_scenario(name)
        for i, phase in enumerate(data["phases"]):
            assert "name" in phase, f"Scenario '{name}' phase {i} missing 'name'"
            assert "type" in phase, f"Scenario '{name}' phase {i} missing 'type'"
            assert phase["type"] in (
                "scheduled", "organic", "challenge",
                "tool_exercise", "reflection", "audience_sim",
            ), f"Scenario '{name}' phase {i} has invalid type: {phase['type']}"


def test_initiative_test_has_10_phases():
    """initiative_test should have exactly 10 organic phases."""
    data = _load_scenario("initiative_test")
    organic_count = sum(1 for p in data["phases"] if p["type"] == "organic")
    assert organic_count == 10


def test_goal_generation_has_reflections():
    """goal_generation_test should have 2+ reflection phases."""
    data = _load_scenario("goal_generation_test")
    reflections = [p for p in data["phases"] if p["type"] == "reflection"]
    assert len(reflections) >= 2


def test_budget_crisis_has_budget_tools():
    """budget_crisis should exercise get_revenue_status."""
    data = _load_scenario("budget_crisis")
    tool_phases = [p for p in data["phases"] if p["type"] == "tool_exercise"]
    tools_used = {p.get("tool") for p in tool_phases}
    assert "get_revenue_status" in tools_used


def test_topic_exhaustion_has_enough_phases():
    """topic_exhaustion_test should have 20 phases for topic decay."""
    data = _load_scenario("topic_exhaustion_test")
    assert len(data["phases"]) >= 15


def test_dream_cycle_has_dream_reflection():
    """dream_cycle_test should include a dream reflection phase."""
    data = _load_scenario("dream_cycle_test")
    dream_phases = [
        p for p in data["phases"]
        if p["type"] == "reflection" and p.get("reflection_type") == "dream"
    ]
    assert len(dream_phases) >= 1


def test_ab_test_has_fixed_and_auto_phases():
    """ab_test should have 3+ fixed phases and 10 autonomous phases."""
    data = _load_scenario("ab_test")
    phases_with_topics = [
        p for p in data["phases"]
        if p.get("topics") or p.get("topic")
    ]
    auto_phases = [
        p for p in data["phases"]
        if p["type"] == "organic" and not p.get("topics") and not p.get("topic")
    ]
    assert len(phases_with_topics) >= 3, "Need at least 3 fixed-topic phases"
    assert len(auto_phases) >= 10, "Need at least 10 autonomous phases"


def test_full_evolution_has_weekly_reflection():
    """full_evolution_7d should include a weekly reflection."""
    data = _load_scenario("full_evolution_7d")
    weekly = [
        p for p in data["phases"]
        if p["type"] == "reflection" and p.get("reflection_type") == "weekly"
    ]
    assert len(weekly) >= 1


# ── chat.py scenario preset integration ─────────────────────


def test_scenario_presets_include_new_scenarios():
    """SCENARIO_PRESETS should include entries for all new scenarios."""
    import sys
    sys.path.insert(0, str(SCENARIOS_DIR.parent / "scripts"))
    # Import directly to check the constant
    from scripts.chat import SCENARIO_PRESETS

    preset_names = {p[0] for p in SCENARIO_PRESETS}
    expected = {
        "initiative-test", "goal-generation-test", "budget-crisis",
        "topic-exhaustion-test", "novelty-injection-test", "dream-cycle-test",
        "faction-emergence-test", "full-evolution-7d", "dress-rehearsal", "ab-test",
    }
    for name in expected:
        assert name in preset_names, f"Preset '{name}' not in SCENARIO_PRESETS"


def test_scenario_presets_point_to_existing_files():
    """All SCENARIO_PRESETS with file paths should point to existing files."""
    from scripts.chat import SCENARIO_PRESETS

    project_root = SCENARIOS_DIR.parent
    for name, _, filepath in SCENARIO_PRESETS:
        if filepath:  # Skip autonomous (no file)
            full_path = project_root / filepath
            assert full_path.exists(), (
                f"Preset '{name}' points to non-existent file: {filepath}"
            )

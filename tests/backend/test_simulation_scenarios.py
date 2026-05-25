"""Tests for simulation scenario YAML files and chat.py scenario integration."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
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
DREAM_REFLECTION_SCENARIOS = [
    "dream_cycle_test",
    "dream_smoke_test",
    "embodied_reflection_continuity_test",
    "goal_generation_test",
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
                "scheduled",
                "organic",
                "challenge",
                "tool_exercise",
                "reflection",
                "audience_sim",
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
        p
        for p in data["phases"]
        if p["type"] == "reflection" and p.get("reflection_type") == "dream"
    ]
    assert len(dream_phases) >= 1


def _make_dry_phase_runner(*, agents: list[str], conversation_mode: str):
    from core.simulation.phases import PhaseRunner

    return PhaseRunner(
        config_loader=MagicMock(),
        agent_registry=MagicMock(),
        event_bus=MagicMock(emit=AsyncMock()),
        llm_client=MagicMock(),
        management=MagicMock(),
        context_assembler=MagicMock(),
        conversation_repo=MagicMock(),
        archival_memory=MagicMock(),
        proximity=MagicMock(),
        trigger_system=MagicMock(),
        selection_logger=MagicMock(),
        reflection_manager=MagicMock(),
        simulation_id=uuid.uuid4(),
        agents=agents,
        dry_run=True,
        conversation_mode=conversation_mode,
    )


@pytest.mark.asyncio
async def test_dream_scenarios_runnable_under_embodied_mode(monkeypatch):
    """Dream/reflection scenarios should parse and dry-run in embodied mode."""
    from core.simulation.orchestrator import SimulationConfig

    monkeypatch.setenv("CONVERSATION_MODE", "embodied")

    for name in DREAM_REFLECTION_SCENARIOS:
        data = _load_scenario(name)
        meta = data.get("meta", {})
        agents = list(meta.get("agents") or ["vera", "rex", "aurora"])

        assert "embodied" in meta.get("supports_modes", [])

        cfg = SimulationConfig(
            name=name,
            seed_file=str(SCENARIOS_DIR / f"{name}.yaml"),
            agents=agents,
            conversation_mode="embodied",
            dry_run=True,
        )
        cfg.load_seed_file(valid_agent_ids=set(agents))

        assert cfg.memory_seed is not None
        assert cfg.memory_seed.mode == "custom"
        assert cfg.memory_seed.custom_file is not None
        assert (SCENARIOS_DIR.parent / cfg.memory_seed.custom_file).exists()

        runner = _make_dry_phase_runner(
            agents=cfg.agents,
            conversation_mode=cfg.conversation_mode,
        )
        for phase in cfg.phases:
            result = await runner.run_phase(phase)
            assert result.status == "completed", f"{name}:{phase.name} failed"
            assert result.errors == []


def test_ab_test_has_fixed_and_auto_phases():
    """ab_test should have 3+ fixed phases and 10 autonomous phases."""
    data = _load_scenario("ab_test")
    phases_with_topics = [p for p in data["phases"] if p.get("topics") or p.get("topic")]
    auto_phases = [
        p
        for p in data["phases"]
        if p["type"] == "organic" and not p.get("topics") and not p.get("topic")
    ]
    assert len(phases_with_topics) >= 3, "Need at least 3 fixed-topic phases"
    assert len(auto_phases) >= 10, "Need at least 10 autonomous phases"


def test_full_evolution_has_weekly_reflection():
    """full_evolution_7d should include a weekly reflection."""
    data = _load_scenario("full_evolution_7d")
    weekly = [
        p
        for p in data["phases"]
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
        "initiative-test",
        "goal-generation-test",
        "budget-crisis",
        "topic-exhaustion-test",
        "novelty-injection-test",
        "dream-cycle-test",
        "faction-emergence-test",
        "full-evolution-7d",
        "dress-rehearsal",
        "ab-test",
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
            assert full_path.exists(), f"Preset '{name}' points to non-existent file: {filepath}"


# ── Faction parsing (#419) ──────────────────────────────────


def test_faction_emergence_yaml_includes_factions_block():
    """faction_emergence_test.yaml has the new factions: section."""
    data = _load_scenario("faction_emergence_test")
    assert "factions" in data
    factions = data["factions"]
    names = {f["name"] for f in factions}
    assert {"builders", "skeptics"} <= names
    builders = next(f for f in factions if f["name"] == "builders")
    assert "rex" in builders["members"]
    assert builders["goal"]


def test_load_seed_file_parses_factions():
    """SimulationConfig.load_seed_file populates `factions` from YAML."""
    from core.simulation.orchestrator import SimulationConfig

    cfg = SimulationConfig(
        name="t",
        seed_file=str(SCENARIOS_DIR / "faction_emergence_test.yaml"),
        agents=["rex", "aurora", "fork", "sentinel", "vera"],
        dry_run=True,
    )
    cfg.load_seed_file(valid_agent_ids={"rex", "aurora", "fork", "sentinel", "vera"})
    assert len(cfg.factions) == 2
    builders = next(f for f in cfg.factions if f.name == "builders")
    assert builders.members == ["rex", "aurora"]
    assert builders.goal


def test_two_team_civilization_scenario_loads_roles_and_factions():
    """The two-team Minecraft scenario records team goals and role prompts."""
    from core.simulation.orchestrator import SimulationConfig

    agents = {"alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"}
    cfg = SimulationConfig(
        name="two-team-civilization",
        seed_file=str(SCENARIOS_DIR / "two_team_civilization_75m.yaml"),
        agents=sorted(agents),
        conversation_mode="director_v2",
        run_mode="experimental",
        dry_run=True,
    )
    cfg.load_seed_file(valid_agent_ids=agents)

    assert cfg.run_mode.value == "experimental"
    assert cfg.memory_seed is not None
    assert cfg.memory_seed.mode == "none"
    assert {faction.name for faction in cfg.factions} == {"team_ember", "team_grove"}
    assert next(f for f in cfg.factions if f.name == "team_ember").members == [
        "alpha",
        "rex",
        "vera",
        "sentinel",
    ]
    assert next(f for f in cfg.factions if f.name == "team_grove").members == [
        "aurora",
        "fork",
        "pixel",
        "grok",
    ]
    assert "builder-duty" in " ".join(cfg.agent_goals["rex"]).lower()
    assert "scout" in " ".join(cfg.agent_goals["grok"]).lower()


def test_embodied_seed_file_serializes_factions_and_agent_goals(tmp_path):
    """Embodied run configs keep factions and goals in the simulation snapshot."""
    from core.simulation.orchestrator import SimulationConfig

    scenario = tmp_path / "embodied.yaml"
    scenario.write_text(
        yaml.safe_dump(
            {
                "factions": [
                    {
                        "name": "builders",
                        "members": ["vera", "rex"],
                        "goal": "Raise the first shared shelter.",
                        "stance": "practical",
                    },
                ],
                "agent_goals": {
                    "vera": ["Mark the build site."],
                    "rex": ["Gather starter materials."],
                },
                "phases": [],
            }
        )
    )

    cfg = SimulationConfig(
        name="embodied-factions",
        seed_file=str(scenario),
        agents=["vera", "rex"],
        conversation_mode="embodied",
        dry_run=True,
    )
    cfg.load_seed_file(valid_agent_ids={"vera", "rex"})

    snapshot = cfg.to_dict()
    assert cfg.conversation_mode == "embodied"
    assert snapshot["factions"] == [
        {
            "name": "builders",
            "members": ["vera", "rex"],
            "goal": "Raise the first shared shelter.",
            "stance": "practical",
        }
    ]
    assert snapshot["agent_goals"] == {
        "vera": ["Mark the build site."],
        "rex": ["Gather starter materials."],
    }


def test_load_seed_file_rejects_unknown_member(tmp_path):
    """Unknown member id in factions block raises a validation error."""
    import pytest
    import yaml as _y

    from core.simulation.orchestrator import SimulationConfig

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        _y.safe_dump(
            {
                "factions": [
                    {"name": "x", "members": ["nosuch"], "goal": "do stuff"},
                ],
                "phases": [],
            }
        )
    )
    cfg = SimulationConfig(name="t", seed_file=str(bad), agents=["vera"], dry_run=True)
    with pytest.raises(ValueError, match="unknown members"):
        cfg.load_seed_file(valid_agent_ids={"vera"})


def test_load_seed_file_rejects_missing_goal(tmp_path):
    """Missing/empty goal on a faction is a validation error."""
    import pytest
    import yaml as _y

    from core.simulation.orchestrator import SimulationConfig

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        _y.safe_dump(
            {
                "factions": [
                    {"name": "x", "members": ["vera"], "goal": ""},
                ],
                "phases": [],
            }
        )
    )
    cfg = SimulationConfig(name="t", seed_file=str(bad), agents=["vera"], dry_run=True)
    with pytest.raises(ValueError, match="goal"):
        cfg.load_seed_file(valid_agent_ids={"vera"})

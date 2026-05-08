"""Tests for the public /api/scenarios endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.public_routes import (
    _agents_from_phases,
    _build_scenario_meta,
    _extract_leading_comment_block,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"


def test_extract_leading_comment_block_picks_first_contiguous_block() -> None:
    text = (
        "# Awakening — Day 1\n"
        "# The very first day: agents activate and meet.\n"
        "\n"
        "audience:\n"
        "  initial_viewers: 0\n"
    )
    desc = _extract_leading_comment_block(text)
    assert "Awakening" in desc
    assert "agents activate and meet" in desc
    assert "initial_viewers" not in desc


def test_extract_leading_comment_block_handles_no_comments() -> None:
    text = "audience:\n  initial_viewers: 0\n"
    assert _extract_leading_comment_block(text) == ""


def test_agents_from_phases_aggregates_required_agents() -> None:
    phases = [
        {"name": "first", "required_agents": ["vera", "rex"]},
        {"name": "second", "required_agents": ["aurora"]},
        {"name": "third", "required_agents": ["vera"]},  # dedupe
        {"name": "fourth", "agent": "pixel"},  # tool_exercise style
    ]
    agents = _agents_from_phases(phases)
    assert agents == ["vera", "rex", "aurora", "pixel"]


def test_agents_from_phases_handles_non_list_input() -> None:
    assert _agents_from_phases(None) == []
    assert _agents_from_phases({}) == []


@pytest.fixture
def scenarios_with_meta() -> list[Path]:
    return sorted(p for p in SCENARIOS_DIR.glob("*.yaml") if p.is_file())


def test_build_scenario_meta_uses_meta_block_when_present(
    scenarios_with_meta: list[Path],
) -> None:
    awakening = next(p for p in scenarios_with_meta if p.name == "awakening.yaml")
    meta = _build_scenario_meta(awakening)

    assert meta.filename == "awakening.yaml"
    # Name comes from meta block, not the bare stem.
    assert meta.name == "Awakening (Day 1)"
    assert meta.description.lower().startswith("day 1")
    # Agent list is the meta-block value.
    assert "vera" in meta.agents
    assert meta.expected_max_cost == 10.0
    assert meta.expected_runtime_minutes == 25
    # Phase count is computed from the actual phases list, independent of meta.
    assert meta.phase_count > 0


def test_every_scenario_yaml_has_a_meta_block(
    scenarios_with_meta: list[Path],
) -> None:
    """Acceptance criterion: meta: backfilled on every scenario YAML."""
    import yaml

    for path in scenarios_with_meta:
        parsed = yaml.safe_load(path.read_text())
        assert isinstance(parsed, dict), path.name
        assert "meta" in parsed, f"{path.name} missing meta block"
        meta = parsed["meta"]
        assert isinstance(meta, dict), path.name
        assert isinstance(meta.get("name"), str) and meta["name"], path.name
        assert isinstance(meta.get("description"), str) and meta["description"], path.name
        assert isinstance(meta.get("agents"), list), path.name
        assert isinstance(meta.get("expected_max_cost"), (int, float)), path.name
        assert isinstance(meta.get("expected_runtime_minutes"), int), path.name


def test_list_public_scenarios_returns_one_entry_per_yaml(
    scenarios_with_meta: list[Path],
) -> None:
    """Endpoint smoke test via direct call (no FastAPI app needed)."""
    import asyncio

    from core.public_routes import list_public_scenarios

    result = asyncio.run(list_public_scenarios())
    assert len(result) == len(scenarios_with_meta)

    # Every entry has the spec'd fields populated.
    for item in result:
        assert item.filename.endswith(".yaml")
        assert item.name
        assert item.description
        assert isinstance(item.agents, list)
        assert item.phase_count >= 0
        assert item.expected_max_cost >= 0
        assert item.expected_runtime_minutes >= 0

    # The well-known scenarios are present and metadata is plumbed through.
    by_filename = {item.filename: item for item in result}
    assert "awakening.yaml" in by_filename
    awakening = by_filename["awakening.yaml"]
    assert awakening.name == "Awakening (Day 1)"
    assert awakening.expected_max_cost == 10.0

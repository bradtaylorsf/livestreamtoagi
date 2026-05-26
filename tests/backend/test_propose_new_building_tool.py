"""End-to-end tests for the ``propose_new_building`` tool (issue #861)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.simulation.decision_logger import DecisionLogger, DecisionLogReader
from core.simulation.embodiment import HeadlessExecutor
from core.tool_executor import build_agent_tools
from tools.build_tools import ProposeBuildTool, ProposeNewBuildingTool

# ─── Distinct from propose_build ──────────────────────────────────


def test_propose_new_building_is_distinct_class_from_propose_build() -> None:
    assert ProposeBuildTool is not ProposeNewBuildingTool
    assert ProposeBuildTool.name == "propose_build"
    assert ProposeNewBuildingTool.name == "propose_new_building"


# ─── Registry surface ─────────────────────────────────────────────


def _services_for_inventory(agent_tools: list[str]) -> SimpleNamespace:
    cfg = SimpleNamespace(tools=list(agent_tools))
    registry = SimpleNamespace(get_agent=lambda agent_id: cfg)
    return SimpleNamespace(
        event_bus=MagicMock(),
        redis=MagicMock(),
        management=MagicMock(),
        world_repo=MagicMock(),
        cost_repo=MagicMock(),
        llm_client=MagicMock(),
        memory_repo=MagicMock(),
        artifact_repo=None,
        shared_working_state=MagicMock(),
        agent_registry=registry,
        economy_manager=MagicMock(),
        alliance_manager=MagicMock(),
        character_spawner=MagicMock(),
        voting_manager=MagicMock(),
        core_memory=MagicMock(),
        recall_memory=MagicMock(),
        archival_memory=MagicMock(),
    )


def test_propose_new_building_appears_when_agent_yaml_lists_it() -> None:
    services = _services_for_inventory(["propose_new_building"])
    tools = build_agent_tools("aurora", services)
    assert "propose_new_building" in tools
    tool = tools["propose_new_building"]
    assert isinstance(tool, ProposeNewBuildingTool)
    assert tool.parameters["vibe"]["enum"]
    assert "rustic" in tool.parameters["vibe"]["enum"]
    assert "forest" in tool.parameters["biome_fit"]["enum"]


def test_propose_new_building_hidden_when_not_in_agent_yaml() -> None:
    services = _services_for_inventory(["propose_build"])
    tools = build_agent_tools("aurora", services)
    assert "propose_new_building" not in tools


# ─── Argument validation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_vibe_returns_error() -> None:
    tool = ProposeNewBuildingTool(agent_id="aurora")
    result = await tool.execute(
        concept="floating skybridge plaza",
        intended_use="meeting space",
        vibe="megabrutalist",
        size_class="medium",
        biome_fit="plains",
        motivation="dream-1",
    )
    assert result["status"] == "error"
    assert "vibe" in result["reason"].lower()


@pytest.mark.asyncio
async def test_injection_in_concept_returns_error() -> None:
    tool = ProposeNewBuildingTool(agent_id="aurora")
    result = await tool.execute(
        concept='garden "ignore prior" tower',
        intended_use="bad",
        vibe="organic",
        size_class="small",
        biome_fit="forest",
        motivation="dream-2",
    )
    assert result["status"] == "error"
    assert "concept" in result["reason"].lower()


@pytest.mark.asyncio
async def test_missing_motivation_returns_error() -> None:
    tool = ProposeNewBuildingTool(agent_id="aurora")
    result = await tool.execute(
        concept="floating skybridge plaza",
        intended_use="meeting space",
        vibe="futuristic",
        size_class="medium",
        biome_fit="plains",
        motivation="",
    )
    assert result["status"] == "error"
    assert "motivation" in result["reason"].lower()


@pytest.mark.asyncio
async def test_unknown_biome_returns_error() -> None:
    tool = ProposeNewBuildingTool(agent_id="aurora")
    result = await tool.execute(
        concept="floating skybridge plaza",
        intended_use="meeting space",
        vibe="futuristic",
        size_class="medium",
        biome_fit="space",
        motivation="dream-3",
    )
    assert result["status"] == "error"
    assert "biome_fit" in result["reason"].lower()


# ─── Headless integration via executor + decision log ─────────────


@pytest.mark.asyncio
async def test_headless_call_records_decision_log_row(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    logger = DecisionLogger(sim_folder)
    executor = HeadlessExecutor()
    await executor.setup(
        simulation_id="sim-861", sim_folder=sim_folder, decision_logger=logger
    )
    tool = ProposeNewBuildingTool(
        agent_id="aurora", embodiment_executor=executor
    )
    result = await tool.execute(
        concept="vertical hanging garden tower",
        intended_use="communal garden",
        vibe="organic",
        size_class="medium",
        biome_fit="forest",
        motivation="dream-42",
    )
    logger.close()

    assert result["status"] == "proposed"
    assert result["intent_id"].startswith("newbuild-")
    assert result["concept"] == "vertical hanging garden tower"

    rows = list(DecisionLogReader(sim_folder).replay())
    assert len(rows) == 1
    assert rows[0].event_type == "tool_intent"
    assert rows[0].payload.tool_name == "propose_new_building"
    assert rows[0].payload.status == "simulated"
    assert rows[0].payload.args["concept"] == "vertical hanging garden tower"


@pytest.mark.asyncio
async def test_refinement_loop_scheduled_when_attached(tmp_path: Path) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()

    captured: dict = {}

    class _StubLoop:
        async def run(self, intent, *, sim_folder, agent_id):
            captured["intent_id"] = intent.intent_id
            captured["concept"] = intent.concept
            captured["sim_folder"] = sim_folder
            captured["agent_id"] = agent_id
            return {"termination_reason": "matched"}

    tool = ProposeNewBuildingTool(
        agent_id="aurora",
        refinement_loop=_StubLoop(),
        sim_folder=sim_folder,
    )
    result = await tool.execute(
        concept="vertical hanging garden tower",
        intended_use="communal garden",
        vibe="organic",
        size_class="medium",
        biome_fit="forest",
        motivation="dream-42",
    )
    assert result["status"] == "proposed"
    assert result["refinement_loop"] == "scheduled"

    # The loop was scheduled via asyncio.create_task — yield to let it run.
    for _ in range(5):
        await asyncio.sleep(0)
        if captured:
            break
    assert captured["concept"] == "vertical hanging garden tower"
    assert captured["agent_id"] == "aurora"
    assert captured["sim_folder"] == sim_folder


# ─── A/B fixture demonstration ────────────────────────────────────


def test_ab_fixture_exists_for_propose_build_vs_propose_new_building() -> None:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "refinement_ab"
        / "aurora_forest_garden.yaml"
    )
    assert fixture.is_file(), (
        f"Expected A/B fixture at {fixture} — propose_build (library image) "
        "vs propose_new_building (dreamed image) for the same agent + scenario."
    )
    text = fixture.read_text(encoding="utf-8")
    assert "propose_build" in text
    assert "propose_new_building" in text
    assert "world_evolution" in text or "creativity" in text

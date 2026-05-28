"""End-to-end tests for the ``propose_build`` tool wiring (issue #855)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.agents.build_intent import BuildIntent
from core.simulation.decision_logger import DecisionLogger, DecisionLogReader
from core.simulation.embodiment import (
    EmbodiedExecutor,
    HeadlessExecutor,
    ToolIntent,
)
from core.tool_executor import build_agent_tools
from tools.build_tools import ProposeBuildTool


# ─── Tool registry surface ────────────────────────────────────────


def _services_for_inventory(agent_tools: list[str]) -> SimpleNamespace:
    """Minimal Services-like namespace driven by an explicit agent tool list."""
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


def test_propose_build_appears_when_agent_yaml_lists_it() -> None:
    services = _services_for_inventory(["propose_build"])
    tools = build_agent_tools("rex", services)
    assert "propose_build" in tools
    tool = tools["propose_build"]
    assert isinstance(tool, ProposeBuildTool)
    # Schema surface
    assert tool.name == "propose_build"
    assert "structure_type" in tool.parameters
    assert "motivation" in tool.parameters
    assert tool.parameters["structure_type"]["enum"]
    assert "cabin" in tool.parameters["structure_type"]["enum"]


def test_propose_build_hidden_when_not_in_agent_yaml() -> None:
    services = _services_for_inventory(["execute_code"])  # no propose_build
    tools = build_agent_tools("rex", services)
    assert "propose_build" not in tools


def test_build_agent_tools_threads_embodiment_executor() -> None:
    services = _services_for_inventory(["propose_build"])
    executor = HeadlessExecutor()
    tools = build_agent_tools("rex", services, embodiment_executor=executor)
    tool = tools["propose_build"]
    assert isinstance(tool, ProposeBuildTool)
    assert tool._executor is executor  # noqa: SLF001 — wired through


def test_conversation_engine_passes_executor_to_build_agent_tools() -> None:
    """Regression: ConversationEngine must thread the executor so propose_build
    actually writes build_intents.jsonl during real simulation runs.
    """
    from unittest.mock import patch

    from core.bootstrap import ConversationOptions, InfraServices, MemoryServices
    from core.conversation_engine import ConversationEngine

    executor = HeadlessExecutor()
    services = _services_for_inventory(["propose_build"])
    infra = SimpleNamespace(
        config_loader=SimpleNamespace(
            config=SimpleNamespace(
                topics={},
                energy=SimpleNamespace(),
            )
        ),
        agent_registry=services.agent_registry,
        event_bus=MagicMock(),
        llm_client=MagicMock(),
        proximity=MagicMock(),
        trigger_system=MagicMock(),
        selection_logger=MagicMock(),
    )

    with (
        patch("core.conversation_engine.SpeakerSelector"),
        patch("core.conversation_engine.TopicDetector"),
        patch("core.conversation_engine.build_agent_tools", return_value={}) as mock_build,
    ):
        engine = ConversationEngine(
            infra=InfraServices(**infra.__dict__),
            memory=MemoryServices(archival_memory=MagicMock()),
            options=ConversationOptions(embodiment_executor=executor),
            management=MagicMock(),
            context_assembler=MagicMock(),
            conversation_repo=MagicMock(),
            services=services,
        )
        engine._get_tools_for_agent("rex")
        mock_build.assert_called_once_with(
            "rex",
            services,
            simulation_mode=False,
            embodiment_executor=executor,
            sim_folder=None,
            ownership_ledger=None,
            trade_ledger=None,
            theft_ledger=None,
            decision_logger=None,
        )


def test_director_tool_adapter_threads_executor_to_tool_builder() -> None:
    """Regression: DirectorToolAdapter must forward the executor so propose_build
    works when invoked through the Director V2 path.
    """
    from core.minecraft.director.tool_adapter import DirectorToolAdapter

    executor = HeadlessExecutor()
    builder = MagicMock(return_value={})
    adapter = DirectorToolAdapter(
        SimpleNamespace(),
        tool_builder=builder,
        embodiment_executor=executor,
    )
    adapter._build_tools("rex")
    builder.assert_called_once_with(
        "rex",
        adapter._services,
        False,
        embodiment_executor=executor,
    )


# ─── Malformed args yield typed errors ────────────────────────────


@pytest.mark.asyncio
async def test_unknown_structure_type_returns_error() -> None:
    tool = ProposeBuildTool(agent_id="rex")
    result = await tool.execute(
        structure_type="megastructure",
        size_class="small",
        location_intent="open_area",
        motivation="dream",
    )
    assert result["status"] == "error"
    assert "structure_type" in result["reason"].lower()


@pytest.mark.asyncio
async def test_missing_motivation_returns_error() -> None:
    tool = ProposeBuildTool(agent_id="rex")
    result = await tool.execute(
        structure_type="cabin",
        size_class="small",
        location_intent="open_area",
        motivation="",
    )
    assert result["status"] == "error"
    assert "motivation" in result["reason"].lower()


@pytest.mark.asyncio
async def test_claim_specified_without_coords_returns_error() -> None:
    tool = ProposeBuildTool(agent_id="rex")
    result = await tool.execute(
        structure_type="cabin",
        size_class="small",
        location_intent="claim_specified",
        motivation="here",
    )
    assert result["status"] == "error"
    assert "coords" in result["reason"].lower()


@pytest.mark.asyncio
async def test_invalid_coords_payload_returns_error() -> None:
    tool = ProposeBuildTool(agent_id="rex")
    result = await tool.execute(
        structure_type="cabin",
        size_class="small",
        location_intent="claim_specified",
        motivation="here",
        coords={"x": "not-an-int", "y": 64, "z": 0},
    )
    assert result["status"] == "error"


# ─── Headless integration: writes build_intents.jsonl + decision log ──


@pytest.mark.asyncio
async def test_headless_call_writes_build_intents_jsonl_and_decision_log(
    tmp_path: Path,
) -> None:
    sim_folder = tmp_path / "sim"
    logger = DecisionLogger(sim_folder)
    executor = HeadlessExecutor()
    await executor.setup(
        simulation_id="sim-1", sim_folder=sim_folder, decision_logger=logger
    )

    tool = ProposeBuildTool(agent_id="rex", embodiment_executor=executor)
    result = await tool.execute(
        structure_type="cabin",
        size_class="small",
        location_intent="open_area",
        motivation="needs a place to sleep before nightfall",
        materials_preference=["oak_log"],
    )

    logger.close()

    assert result["status"] == "proposed"
    assert result["intent_id"].startswith("build-")

    intents_path = sim_folder / "build_intents.jsonl"
    lines = intents_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["actor_id"] == "rex"
    assert payload["intent_id"] == result["intent_id"]
    assert payload["args"]["structure_type"] == "cabin"
    assert payload["args"]["motivation"].startswith("needs a place")

    rows = list(DecisionLogReader(sim_folder).replay())
    assert len(rows) == 1
    assert rows[0].event_type == "tool_intent"
    assert rows[0].payload.tool_name == "propose_build"
    assert rows[0].payload.status == "simulated"


@pytest.mark.asyncio
async def test_headless_executor_skips_jsonl_when_intent_not_propose_build(
    tmp_path: Path,
) -> None:
    sim_folder = tmp_path / "sim"
    sim_folder.mkdir()
    executor = HeadlessExecutor()
    await executor.setup(simulation_id="sim-x", sim_folder=sim_folder)
    await executor.execute_tool_intent(
        ToolIntent(tool_name="send_message", actor_id="rex", args={})
    )
    assert not (sim_folder / "build_intents.jsonl").exists()


# ─── Embodied integration: hand-off to BuildMacroScheduler ───────


@pytest.mark.asyncio
async def test_embodied_executor_hands_off_to_build_macro_scheduler(
    tmp_path: Path,
) -> None:
    sim_folder = tmp_path / "sim"
    executor = EmbodiedExecutor()
    await executor.setup(simulation_id="sim-e", sim_folder=sim_folder)

    stub = MagicMock()
    stub.try_acquire_plan = MagicMock()
    executor._build_macro_scheduler = stub  # noqa: SLF001 — test seam

    intent = BuildIntent(
        proposer_id="rex",
        structure_type="cabin",
        size_class="medium",
        location_intent="open_area",
        motivation="alliance hq needs shelter",
    )

    await executor.execute_tool_intent(
        ToolIntent(
            tool_name="propose_build",
            actor_id="rex",
            args=intent.to_log_payload(),
            intent_id=intent.intent_id,
        )
    )

    intents_path = sim_folder / "build_intents.jsonl"
    assert intents_path.exists()
    assert len(intents_path.read_text().splitlines()) == 1

    assert stub.try_acquire_plan.called
    kwargs = stub.try_acquire_plan.call_args.kwargs
    assert kwargs["agent_id"] == "rex"
    assert kwargs["description"] == "cabin"


@pytest.mark.asyncio
async def test_embodied_executor_lazily_constructs_scheduler(
    tmp_path: Path,
) -> None:
    """The first propose_build call must construct a scheduler without errors."""
    sim_folder = tmp_path / "sim"
    executor = EmbodiedExecutor()
    await executor.setup(simulation_id="sim-e2", sim_folder=sim_folder)

    intent = BuildIntent(
        proposer_id="rex",
        structure_type="watchtower",
        size_class="small",
        location_intent="open_area",
        motivation="need to scout",
    )
    await executor.execute_tool_intent(
        ToolIntent(
            tool_name="propose_build",
            actor_id="rex",
            args=intent.to_log_payload(),
            intent_id=intent.intent_id,
        )
    )
    assert getattr(executor, "_build_macro_scheduler", None) is not None

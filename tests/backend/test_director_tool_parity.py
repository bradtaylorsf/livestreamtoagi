"""Tests for the Minecraft Director V2 backend tool parity inventory."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.minecraft.director.tool_parity import TOOL_PARITY, classified_names, iter_tool_parity
from core.tool_executor import build_agent_tools
from tools.base import BaseTool

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = ROOT / "tools"
PARITY_DOC = ROOT / "docs" / "minecraft" / "director-v2-tool-parity.md"


def _discover_base_tool_names() -> dict[str, str]:
    discovered: dict[str, str] = {}
    for module_info in pkgutil.iter_modules([str(TOOLS_DIR)]):
        if module_info.name in {"base", "stubs"} or module_info.name.startswith("_"):
            continue
        module_name = f"tools.{module_info.name}"
        module = importlib.import_module(module_name)
        for _class_name, cls in inspect.getmembers(module, inspect.isclass):
            if cls is BaseTool or not issubclass(cls, BaseTool) or inspect.isabstract(cls):
                continue
            if cls.__module__ != module_name:
                continue
            discovered[cls.name] = module_name
    return discovered


def _services_for_tool_inventory() -> SimpleNamespace:
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
        agent_registry=None,
        economy_manager=MagicMock(),
        alliance_manager=MagicMock(),
        character_spawner=MagicMock(),
        voting_manager=MagicMock(),
        core_memory=MagicMock(),
        recall_memory=MagicMock(),
        archival_memory=MagicMock(),
        goal_manager=MagicMock(),
    )


def test_every_backend_base_tool_has_director_v2_classification() -> None:
    discovered = _discover_base_tool_names()

    assert discovered
    assert set(discovered) <= classified_names()


def test_journal_image_generator_is_explicitly_classified() -> None:
    entry = TOOL_PARITY["generate_journal_image"]

    assert entry.module == "tools.journal_image_tool"
    assert entry.category == "journal_image"
    assert entry.classification == "deferred"
    assert entry.linked_issue == "#583"


def test_callable_and_approval_gated_tools_are_reachable_or_tracked() -> None:
    services = _services_for_tool_inventory()
    candidate_agents = {"aurora", "fork", "grok", "pixel", "rex", "sentinel", "vera"}

    reachable: set[str] = set()
    for agent_id in candidate_agents:
        reachable.update(build_agent_tools(agent_id, services))

    missing: list[str] = []
    for entry in iter_tool_parity():
        if entry.classification not in {"callable_now", "approval_gated"}:
            continue
        if entry.name not in reachable and entry.linked_issue is None:
            missing.append(entry.name)

    assert missing == []


def test_parity_doc_mirrors_source_of_truth_entries() -> None:
    text = PARITY_DOC.read_text(encoding="utf-8")

    for entry in iter_tool_parity():
        assert f"`{entry.name}`" in text
        assert f"`{entry.module}`" in text
        assert f"`{entry.classification}`" in text
        if entry.linked_issue is not None:
            assert entry.linked_issue in text


def test_minecraft_replacements_for_retired_world_tools_are_documented() -> None:
    tilemap = TOOL_PARITY["generate_tilemap"]
    world_state = TOOL_PARITY["get_world_state"]

    assert tilemap.classification == "retired"
    assert tilemap.linked_issue == "#619"
    assert tilemap.minecraft_replacement is not None
    assert world_state.classification == "replaced_by_minecraft"
    assert world_state.linked_issue == "#712"
    assert world_state.minecraft_replacement is not None

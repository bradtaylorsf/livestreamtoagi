"""Tests for the static ``BuildPlan`` catalog + resolver (issue #888)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.agents.build_intent import BuildIntent, StructureType
from core.minecraft.build_plan import BuildPlan
from core.minecraft.build_plan_catalog import (
    StaticBuildPlanCatalog,
    build_plan_catalog_resolver,
)
from core.minecraft.build_plan_compiler import BuildPlanCompiler


def _intent(structure: str) -> BuildIntent:
    return BuildIntent(
        proposer_id="vera",
        structure_type=structure,
        size_class="medium",
        location_intent="open_area",
        motivation="catalog smoke",
    )


def test_catalog_covers_every_validated_structure_type() -> None:
    """Every ``StructureType`` enum value must have a catalog entry.

    AC: catalog covers at least cabin, watchtower, plus extras. The
    issue body also lists ``storage_hall`` / ``market_stall`` /
    ``town_square`` but those are not in :class:`StructureType` so the
    resolver cannot reach them — the contract is the validated enum.
    """
    catalog = StaticBuildPlanCatalog()
    known = catalog.known_structure_types()
    assert known == frozenset(StructureType)


@pytest.mark.parametrize("structure", sorted(s.value for s in StructureType))
def test_catalog_returns_valid_build_plan_for_each_structure(structure: str) -> None:
    catalog = StaticBuildPlanCatalog()
    plan = catalog.get(structure)
    assert isinstance(plan, BuildPlan)
    assert plan.structure_type == structure


def test_catalog_returns_none_for_unknown_structure() -> None:
    catalog = StaticBuildPlanCatalog()
    assert catalog.get("not_a_real_structure") is None


def test_resolver_factory_returns_callable_that_reads_intent_args() -> None:
    resolver = build_plan_catalog_resolver()
    plan = resolver({"structure_type": "cabin"})
    assert isinstance(plan, BuildPlan)
    assert plan.structure_type == "cabin"


def test_resolver_returns_none_for_unknown_structure() -> None:
    resolver = build_plan_catalog_resolver()
    assert resolver({"structure_type": "unknown_label"}) is None


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"size_class": "medium"},
        {"structure_type": None},
        None,
        "not a dict",
        123,
    ],
)
def test_resolver_is_robust_to_malformed_args(args: Any) -> None:
    """Resolver must never raise — bad args produce ``None``."""
    resolver = build_plan_catalog_resolver()
    assert resolver(args) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("structure", sorted(s.value for s in StructureType))
def test_catalog_plan_compiles_into_a_buildscript(structure: str) -> None:
    """Every catalog plan must compile without error.

    Guard against catalog entries that the recipe can't lower (e.g.
    missing region material, footprint too small for the recipe's
    insets, etc.).
    """
    catalog = StaticBuildPlanCatalog()
    plan = catalog.get(structure)
    assert plan is not None
    compiler = BuildPlanCompiler()
    script = compiler.compile(plan, intent=_intent(structure))
    assert script.commands, f"{structure} produced no commands"
    assert script.total_blocks > 0


@pytest.mark.asyncio
async def test_resolver_composes_with_headless_executor(tmp_path: Path) -> None:
    """End-to-end: catalog resolver + compiler produce a script.json on disk."""
    from core.simulation.embodiment import HeadlessExecutor, ToolIntent

    compiler = BuildPlanCompiler()
    resolver = build_plan_catalog_resolver()
    executor = HeadlessExecutor(build_plan_compiler=compiler, build_plan_resolver=resolver)
    await executor.setup(simulation_id="sim-catalog", sim_folder=tmp_path)

    intent = _intent("watchtower")
    tool_intent = ToolIntent(
        tool_name="propose_build",
        actor_id="vera",
        args=intent.to_log_payload(),
        intent_id=intent.intent_id,
    )
    await executor.execute_tool_intent(tool_intent)

    target = tmp_path / "build_scripts" / f"{intent.intent_id}.script.json"
    assert target.is_file()
    payload = json.loads(target.read_text())
    assert payload["intent_id"] == intent.intent_id
    assert payload["structure_type"] == "watchtower"
    assert payload["total_blocks"] > 0


@pytest.mark.asyncio
async def test_resolver_skips_when_structure_type_is_unknown(tmp_path: Path) -> None:
    """Unknown structure types must not produce a script (and must not crash)."""
    from core.simulation.embodiment import HeadlessExecutor, ToolIntent

    executor = HeadlessExecutor(
        build_plan_compiler=BuildPlanCompiler(),
        build_plan_resolver=build_plan_catalog_resolver(),
    )
    await executor.setup(simulation_id="sim-unknown", sim_folder=tmp_path)

    tool_intent = ToolIntent(
        tool_name="propose_build",
        actor_id="vera",
        args={"structure_type": "not_in_catalog"},
        intent_id="intent-unknown-1",
    )
    await executor.execute_tool_intent(tool_intent)

    assert not (tmp_path / "build_scripts").exists()

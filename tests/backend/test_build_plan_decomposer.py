"""Tests for the reference-image → ``BuildPlan`` decomposer (issue #856)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from core.agents.build_intent import SizeClass, StructureType
from core.minecraft.build_plan import BuildPlan
from core.minecraft.build_plan_decomposer import (
    DEFAULT_REFERENCE_DIR,
    BlueprintDecomposer,
    NullLocalVisionProvider,
    OpenRouterClaudeVisionProvider,
)


# ─── Fake provider used by every decomposer test ──────────────────


class FakeVisionProvider:
    model_id = "fake/sonnet-vision"

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.call_count = 0
        self.last_hints: Mapping[str, Any] | None = None
        self.last_structure: str | None = None

    async def decompose(
        self,
        *,
        image_bytes: bytes,
        intent_hints: Mapping[str, Any],
        structure_type: StructureType | str,
        size_class: SizeClass | str,
    ) -> dict[str, Any]:
        self.call_count += 1
        self.last_hints = dict(intent_hints)
        self.last_structure = str(structure_type)
        # Make sure the decomposer is actually streaming the image bytes
        assert image_bytes, "decomposer must pass non-empty image bytes"
        return dict(self._payload)


def _payload_for(structure: str = "cabin") -> dict[str, Any]:
    return {
        "structure_type": structure,
        "size_class": "small",
        "source_image_id": f"{structure}:test",
        "footprint": {
            "shape": "rectangle",
            "bbox": {"x": 0, "y": 0, "w": 8, "h": 6},
        },
        "levels": [
            {"index": 0, "height_blocks": 3, "floor_material": "oak_planks"}
        ],
        "materials": [{"region": "walls", "material": "oak_log"}],
        "key_features": [
            {"kind": "roof", "position": {"x": 4, "y": 3, "z": 3}}
        ],
        "openings": [],
        "decomposer_version": 1,
        "provider_model_id": "fake/sonnet-vision",
    }


# ─── Reference library coverage ───────────────────────────────────


def test_reference_library_has_six_structures() -> None:
    expected = {"cabin", "farm", "wall", "watchtower", "coliseum", "market"}
    actual = {
        p.name
        for p in DEFAULT_REFERENCE_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    }
    assert expected <= actual


@pytest.mark.parametrize(
    "structure", ["cabin", "farm", "wall", "watchtower", "coliseum", "market"]
)
def test_each_reference_folder_has_required_files(structure: str) -> None:
    folder = DEFAULT_REFERENCE_DIR / structure
    assert (folder / "image.png").is_file()
    assert (folder / "source_credit.md").is_file()
    assert (folder / "intent_hints.yaml").is_file()


# ─── Happy-path decomposition ─────────────────────────────────────


@pytest.mark.asyncio
async def test_decompose_returns_valid_build_plan_with_required_sections(
    tmp_path: Path,
) -> None:
    provider = FakeVisionProvider(_payload_for("coliseum"))
    decomposer = BlueprintDecomposer(provider, cache_dir=tmp_path)
    plan = await decomposer.decompose(
        structure_type=StructureType.coliseum,
        size_class=SizeClass.epic,
    )
    assert isinstance(plan, BuildPlan)
    assert plan.footprint is not None
    assert plan.levels and plan.levels[0].height_blocks > 0
    assert plan.materials
    assert plan.key_features
    assert plan.provider_model_id == "fake/sonnet-vision"


# ─── Cache behavior ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_does_not_recall_provider(tmp_path: Path) -> None:
    provider = FakeVisionProvider(_payload_for("cabin"))
    decomposer = BlueprintDecomposer(provider, cache_dir=tmp_path)

    first = await decomposer.decompose(structure_type="cabin")
    second = await decomposer.decompose(structure_type="cabin")

    assert provider.call_count == 1
    assert first.model_dump() == second.model_dump()


@pytest.mark.asyncio
async def test_bumped_version_invalidates_cache(tmp_path: Path) -> None:
    provider = FakeVisionProvider(_payload_for("cabin"))

    v1 = BlueprintDecomposer(provider, cache_dir=tmp_path, version=1)
    await v1.decompose(structure_type="cabin")
    assert provider.call_count == 1

    v2 = BlueprintDecomposer(provider, cache_dir=tmp_path, version=2)
    await v2.decompose(structure_type="cabin")
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_different_provider_invalidates_cache(tmp_path: Path) -> None:
    p1 = FakeVisionProvider(_payload_for("cabin"))
    await BlueprintDecomposer(p1, cache_dir=tmp_path).decompose(structure_type="cabin")

    class OtherProvider(FakeVisionProvider):
        model_id = "fake/sonnet-vision-v2"

    p2 = OtherProvider(_payload_for("cabin"))
    await BlueprintDecomposer(p2, cache_dir=tmp_path).decompose(structure_type="cabin")

    assert p1.call_count == 1
    assert p2.call_count == 1


# ─── Hint plumbing ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intent_hints_are_forwarded_to_provider(tmp_path: Path) -> None:
    provider = FakeVisionProvider(_payload_for("coliseum"))
    decomposer = BlueprintDecomposer(provider, cache_dir=tmp_path)
    await decomposer.decompose(structure_type="coliseum")
    assert provider.last_hints is not None
    # The shipped coliseum hints declare a top_down viewpoint.
    assert provider.last_hints.get("viewpoint") == "top_down"
    notes = provider.last_hints.get("notes")
    assert isinstance(notes, list) and notes


@pytest.mark.asyncio
async def test_explicit_intent_hints_override_yaml(tmp_path: Path) -> None:
    provider = FakeVisionProvider(_payload_for("coliseum"))
    decomposer = BlueprintDecomposer(provider, cache_dir=tmp_path)
    custom = {"viewpoint": "elevation", "notes": ["test override"]}
    await decomposer.decompose(structure_type="coliseum", intent_hints=custom)
    assert provider.last_hints == custom


# ─── Provider classes ─────────────────────────────────────────────


def test_openrouter_provider_has_expected_model_id() -> None:
    provider = OpenRouterClaudeVisionProvider()
    assert provider.model_id.startswith("anthropic/")


@pytest.mark.asyncio
async def test_null_local_vision_provider_documents_unviability() -> None:
    provider = NullLocalVisionProvider()
    with pytest.raises(RuntimeError, match="local vision provider is viable"):
        await provider.decompose(
            image_bytes=b"x",
            intent_hints={},
            structure_type="cabin",
            size_class="small",
        )


# ─── Error paths ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_reference_image_raises(tmp_path: Path) -> None:
    provider = FakeVisionProvider(_payload_for("cabin"))
    decomposer = BlueprintDecomposer(
        provider,
        cache_dir=tmp_path,
        reference_dir=tmp_path / "empty",
    )
    with pytest.raises(FileNotFoundError):
        await decomposer.decompose(structure_type="cabin")

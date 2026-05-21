"""Static checks for the Director V2 architecture docs (issue #750).

This issue is documentation-only. The acceptance criteria are structural:
the ADR and Minecraft companion must name the legacy pieces being reused, the
new Director V2 module contracts, the event flow, #510 compatibility, and the
handoff outputs for #511/#512/#514.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS = REPO_ROOT / "docs" / "decisions"
MINECRAFT_DOCS = REPO_ROOT / "docs" / "minecraft"
ADR = DECISIONS / "0011-director-v2-architecture.md"
COMPANION = MINECRAFT_DOCS / "director-v2-architecture.md"
SUMMARY = DECISIONS / "0000-summary.md"

RUNTIME_MODES = ("director", "embodied", "decentralized", "director_v2")

LEGACY_ANCHORS = (
    "core/conversation/speaker_selector.py",
    "core/conversation_engine.py",
    "core/context_assembly.py",
    "core/tool_executor.py",
    "core/conversation_mode.py",
)

NEW_MODULE_ANCHORS = (
    "core/minecraft/director/scene_inbox.py",
    "spatial_hearing.py",
    "core/minecraft/director/turn_scheduler.py",
    "director_gate.js",
    "core/minecraft/director/memory_digest.py",
    "core/minecraft/director/tool_adapter.py",
    "core/minecraft/director/build_scheduler.py",
    "core/minecraft/director/monitor.py",
)

RESPONSIBILITIES = (
    "Scene detection",
    "Turn scheduling",
    "Event routing",
    "Memory digesting",
    "Tool invocation",
    "Builder macro scheduling",
    "Observability",
)


@pytest.fixture(scope="module")
def adr_text() -> str:
    assert ADR.is_file(), f"missing Director V2 ADR: {ADR}"
    return ADR.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def companion_text() -> str:
    assert COMPANION.is_file(), f"missing Director V2 companion doc: {COMPANION}"
    return COMPANION.read_text(encoding="utf-8")


def test_adr_exists_and_follows_decision_format(adr_text: str) -> None:
    assert adr_text.lstrip().startswith("# Decision 0011:"), "ADR must use the 0011 title"
    head = adr_text[:800]
    assert re.search(r"^Status:", head, re.MULTILINE)
    assert re.search(r"^Research date: 2026-05-21$", head, re.MULTILINE)
    assert re.search(r"^Related issue: #750, E8.5-1$", head, re.MULTILINE)
    assert "#749" in head
    assert "#510" in head


def test_adr_and_companion_cross_link(adr_text: str, companion_text: str) -> None:
    assert "../minecraft/director-v2-architecture.md" in adr_text
    assert "../decisions/0011-director-v2-architecture.md" in companion_text


@pytest.mark.parametrize("mode", RUNTIME_MODES)
def test_runtime_modes_are_documented(mode: str, adr_text: str, companion_text: str) -> None:
    combined = f"{adr_text}\n{companion_text}"
    assert f"`{mode}`" in combined


@pytest.mark.parametrize("anchor", LEGACY_ANCHORS)
def test_adr_names_reused_legacy_components(anchor: str, adr_text: str) -> None:
    assert anchor in adr_text


@pytest.mark.parametrize("anchor", NEW_MODULE_ANCHORS)
def test_adr_names_new_director_v2_module_contracts(anchor: str, adr_text: str) -> None:
    assert anchor in adr_text


@pytest.mark.parametrize("responsibility", RESPONSIBILITIES)
def test_responsibilities_are_explicit(responsibility: str, adr_text: str) -> None:
    assert responsibility.lower() in adr_text.lower()


def test_non_responsibilities_distinguish_management_and_planning(adr_text: str) -> None:
    lower = adr_text.lower()
    assert "management censorship" in lower
    assert "private minecraft simulation talk" in lower
    assert "central blueprint mandate" in lower
    assert "dreams, journals, or long-horizon planning" in lower


def test_companion_compares_old_loop_mindcraft_and_director(companion_text: str) -> None:
    assert "Legacy Python loop" in companion_text
    assert "Current #510 Mindcraft respond/ignore" in companion_text
    assert "Director V2" in companion_text
    assert "mindcraft/src/agent/conversation.js" in companion_text


def test_companion_has_required_event_flow(companion_text: str) -> None:
    lower = companion_text.lower()
    assert "flowchart td" in lower
    assert "minecraft event" in lower
    assert "selected next step" in lower
    assert "speaker prompt" in lower
    assert "typed tool call" in lower
    assert "builder macro" in lower
    assert "batched memory digest" in lower
    assert "archival transcript + recall memories + scene summary" in lower


def test_companion_contains_510_compatibility_and_later_handoffs(companion_text: str) -> None:
    for issue in ("#510", "#511", "#512", "#514"):
        assert issue in companion_text
    lower = companion_text.lower()
    assert "decentralized evidence only" in lower
    assert "scene records" in lower
    assert "monitor output" in lower
    assert "starting conditions" in lower


def test_summary_index_links_decision() -> None:
    summary = SUMMARY.read_text(encoding="utf-8")
    assert "Director V2" in summary
    assert "[0011: Director V2 Architecture](0011-director-v2-architecture.md)" in summary

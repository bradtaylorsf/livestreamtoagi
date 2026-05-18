"""Tests for the fork maintenance & upstream-merge policy (issue #538, epic E3-6).

E3-6 is **documentation-only** — it adds no scripts. The acceptance criterion
is structural: ``docs/minecraft/fork-maintenance.md`` must document the
branch/patch-isolation strategy, how to re-base on upstream, and the CI build
check; ``mindcraft-fork.md`` must link back so the two docs cannot silently
drift; and the pin it documents must stay byte-identical with the values baked
into ``setup-mindcraft.sh`` / ``test_minecraft_setup_mindcraft.py``.

These checks are dependency-free (pure file reads — no Node, no Minecraft, no
network, no Docker) and assert on **stable** committed substrings (the pinned
SHA, fork URL, pin tag, lockfile path, the ``pnpm`` verify command) rather than
prose, so they verify the acceptance bar without being brittle to wording
changes. Mirrors the static-check style of ``test_minecraft_runbook.py`` /
``test_minecraft_setup_mindcraft.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs" / "minecraft"
DOC = DOCS / "fork-maintenance.md"
FORK_DOC = DOCS / "mindcraft-fork.md"
SETUP_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "setup-mindcraft.sh"
SETUP_TEST = REPO_ROOT / "tests" / "backend" / "test_minecraft_setup_mindcraft.py"
PACKAGE_JSON = REPO_ROOT / "package.json"

# The pin contract this doc protects. These MUST match the baked-in defaults in
# setup-mindcraft.sh and test_minecraft_setup_mindcraft.py — a re-pin that
# forgets to update this doc fails the sync test below.
PINNED_SHA = "35be480b4cc0bca990278e6103a1426392559d96"
FORK_URL = "https://github.com/bradtaylorsf/mindcraft"
PIN_TAG = "e1-r1-pin"
LOCKFILE_PATH = "scripts/minecraft/mindcraft-package-lock.json"
VERIFY_CMD = "pnpm verify:mindcraft-fork"

# Every stable committed anchor the policy doc must contain verbatim.
REQUIRED_ANCHORS = (
    PINNED_SHA,
    FORK_URL,
    PIN_TAG,
    LOCKFILE_PATH,
    VERIFY_CMD,
)

# The headed sections the issue scope requires, keyed to a stable lowercase
# substring of each heading (asserted case-insensitively so wording can flex).
REQUIRED_SECTIONS = {
    "why a maintenance policy": "why a maintenance policy",
    "branch/patch isolation": "patch-isolation strategy",
    "upstream re-base": "re-base on upstream",
    "ci build check": "ci build check",
    "deferred follow-up": "follow-up",
}


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC.is_file(), f"missing fork-maintenance policy doc: {DOC}"
    return DOC.read_text(encoding="utf-8")


def test_doc_exists_and_is_substantial(doc_text: str) -> None:
    # A maintenance policy is not a stub; guard against an empty/placeholder file.
    assert len(doc_text) > 2000, "fork-maintenance.md is too short to be the policy"
    assert doc_text.lstrip().startswith("# "), (
        "fork-maintenance.md needs a top-level title"
    )


@pytest.mark.parametrize("anchor", REQUIRED_ANCHORS)
def test_doc_contains_stable_committed_anchors(anchor: str, doc_text: str) -> None:
    """The pin contract anchors must appear verbatim so the doc cannot describe
    a different fork/commit/lockfile than the one we actually install."""
    assert anchor in doc_text, f"fork-maintenance.md is missing the anchor: {anchor!r}"


@pytest.mark.parametrize("section", sorted(REQUIRED_SECTIONS))
def test_doc_has_required_sections(section: str, doc_text: str) -> None:
    """The issue scope requires these headed sections to be present."""
    needle = REQUIRED_SECTIONS[section]
    assert needle in doc_text.lower(), (
        f"fork-maintenance.md is missing the {section!r} section ({needle!r})"
    )


def test_doc_states_no_llm_runtime_path(doc_text: str) -> None:
    """E3-6 has no LLM runtime path; the doc must say so explicitly and point
    at the nearest headless verify suite (per the issue's validation note),
    mirroring the same note in mindcraft-fork.md."""
    lower = doc_text.lower()
    assert "local lm studio validation" in lower
    assert "no llm runtime path" in lower
    # The nearest local smoke path must be named, not just asserted to exist.
    assert "pnpm verify:mindcraft-fork-maintenance" in doc_text


def test_pinned_sha_stays_in_sync_with_setup_script_and_its_test() -> None:
    """The doc, the install script, and the script's test must all pin the
    exact same commit — a re-pin that updates one but not the others is a bug
    this contract catches."""
    doc = DOC.read_text(encoding="utf-8")
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    setup_test = SETUP_TEST.read_text(encoding="utf-8")
    for name, text in (("fork-maintenance.md", doc), ("setup-mindcraft.sh", script),
                        ("test_minecraft_setup_mindcraft.py", setup_test)):
        assert PINNED_SHA in text, f"{name} does not pin {PINNED_SHA}"
        assert FORK_URL in text, f"{name} does not record the org fork URL"


def test_fork_install_doc_links_back_to_the_policy() -> None:
    """docs-sync: the pinned-install runbook must point at the maintenance
    policy, so the upstream-merge rules are discoverable and cannot drift
    away from the install doc."""
    assert FORK_DOC.is_file(), f"missing fork-install doc: {FORK_DOC}"
    text = FORK_DOC.read_text(encoding="utf-8")
    assert "fork-maintenance.md" in text, (
        "mindcraft-fork.md must link back to fork-maintenance.md"
    )


def test_policy_doc_links_back_to_the_install_runbook(doc_text: str) -> None:
    """The reverse link too: the policy protects a specific install, so it
    must point at the runbook that produces it."""
    assert "mindcraft-fork.md" in doc_text, (
        "fork-maintenance.md must link to the mindcraft-fork.md install runbook"
    )


def test_verify_script_is_wired_into_package_json() -> None:
    """The CI build check is only green if the script is actually wired up —
    assert the npm script exists and targets this test module."""
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    cmd = scripts.get("verify:mindcraft-fork-maintenance")
    assert cmd, "package.json is missing the verify:mindcraft-fork-maintenance script"
    assert "test_minecraft_fork_maintenance.py" in cmd, (
        "verify:mindcraft-fork-maintenance must run this contract test module"
    )

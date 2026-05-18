"""Tests for the consolidated beginner ops runbook (issue #532, epic E2-7).

E2-7 is **documentation-only** — it adds no scripts. The acceptance criterion
is structural: ``docs/minecraft/runbook.md`` must cover *every* operation with
a copy-paste command and a plain-language "what it does", include a clean
teardown, and the six deep-dive docs must link back to it so the consolidation
cannot silently drift.

These checks are dependency-free (pure file reads — no Java, no Minecraft, no
network, no Docker) and assert on **stable** substrings (committed script
paths, the link target ``runbook.md``) rather than prose, so they verify the
acceptance bar without being brittle to wording changes. Mirrors the
static-check style of ``test_minecraft_supervision.py`` / ``test_minecraft_health.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs" / "minecraft"
SCRIPTS = REPO_ROOT / "scripts" / "minecraft"
RUNBOOK = DOCS / "runbook.md"

# The six deep-dive docs E2-7 consolidates (E2-1..E2-6).
DEEP_DIVE_DOCS = (
    "server-setup.md",
    "world-config.md",
    "hosting.md",
    "supervision.md",
    "backup-restore.md",
    "health.md",
)

# Every operation in scope, keyed to the exact copy-paste command (a stable
# committed string) the runbook must contain. The acceptance criterion is
# literally "covers every operation with copy-paste commands".
REQUIRED_COMMANDS = {
    "start": "scripts/minecraft/start-server.sh",
    "start-preview": "scripts/minecraft/start-server.sh --dry-run",
    "start-24-7-heap": "MEM=4G scripts/minecraft/start-server.sh",
    "stop-systemd": "sudo systemctl stop minecraft",
    "supervise-systemd": "sudo systemctl enable --now minecraft",
    "supervise-portable": "scripts/minecraft/supervise.sh",
    "backup": "scripts/minecraft/backup.sh",
    "restore-latest": "scripts/minecraft/restore.sh --latest",
    "reset": "scripts/minecraft/restore.sh --reset",
    "health-human": "scripts/minecraft/health.sh",
    "health-json": "scripts/minecraft/health.sh --json",
    "health-gate": "CHECK_MINECRAFT=1 bash scripts/check-services.sh",
}


@pytest.fixture(scope="module")
def runbook_text() -> str:
    assert RUNBOOK.is_file(), f"missing consolidated runbook: {RUNBOOK}"
    return RUNBOOK.read_text(encoding="utf-8")


def test_runbook_exists_and_is_substantial(runbook_text: str) -> None:
    # A consolidation of six docs is not a stub; guard against an empty file.
    assert len(runbook_text) > 2000, "runbook.md is too short to be the consolidation"
    assert runbook_text.lstrip().startswith("# "), "runbook.md needs a top-level title"


@pytest.mark.parametrize("operation", sorted(REQUIRED_COMMANDS))
def test_runbook_covers_every_operation(operation: str, runbook_text: str) -> None:
    """Every operation's copy-paste command must appear verbatim."""
    command = REQUIRED_COMMANDS[operation]
    assert command in runbook_text, (
        f"runbook.md is missing the {operation!r} command: {command!r}"
    )


def test_runbook_documents_the_console_stop(runbook_text: str) -> None:
    """The preferred stop (type ``stop`` in the console, which saves the
    world) is the most important gotcha — it must be called out, not just the
    systemd path."""
    assert "## Stop" in runbook_text
    assert "stop" in runbook_text
    # The world-saving rationale for preferring `stop` must be present.
    assert "saved" in runbook_text or "save" in runbook_text


def test_runbook_has_clean_teardown(runbook_text: str) -> None:
    """Teardown is the net-new content E2-7 adds; it must be present, flagged
    irreversible, and use the existing tooling (rm of the install dir)."""
    assert "## Clean teardown" in runbook_text
    lower = runbook_text.lower()
    assert "irreversible" in lower, "teardown must be flagged irreversible"
    assert "rm -rf ./minecraft-server" in runbook_text, (
        "teardown must show the actual install-dir deletion"
    )
    # Teardown must be distinguished from the (recoverable) reset path.
    assert "restore.sh --reset" in runbook_text


def test_runbook_links_to_every_deep_dive_doc(runbook_text: str) -> None:
    for doc in DEEP_DIVE_DOCS:
        assert f"({doc})" in runbook_text or f"(./{doc})" in runbook_text, (
            f"runbook.md must link to the {doc} deep-dive doc"
        )


@pytest.mark.parametrize("doc", DEEP_DIVE_DOCS)
def test_each_deep_dive_doc_links_back_to_runbook(doc: str) -> None:
    """docs-sync: the consolidation is only discoverable if every source doc
    points at it."""
    path = DOCS / doc
    assert path.is_file(), f"missing deep-dive doc: {path}"
    text = path.read_text(encoding="utf-8")
    assert "runbook.md" in text, f"{doc} does not link to the consolidated runbook.md"


def test_runbook_references_only_existing_scripts(runbook_text: str) -> None:
    """Every ``scripts/minecraft/<name>`` the runbook tells the owner to run
    must actually exist (no copy-paste command can dangle)."""
    referenced = {
        "start-server.sh",
        "supervise.sh",
        "backup.sh",
        "restore.sh",
        "health.sh",
    }
    for name in referenced:
        assert f"scripts/minecraft/{name}" in runbook_text, (
            f"runbook.md should document scripts/minecraft/{name}"
        )
        assert (SCRIPTS / name).is_file(), (
            f"runbook.md references scripts/minecraft/{name} but it does not exist"
        )
    # The systemd unit it documents installing must exist too.
    assert (SCRIPTS / "minecraft.service").is_file()


def test_runbook_states_no_llm_runtime_path(runbook_text: str) -> None:
    """E2-7 has no LLM runtime path; the doc must say so explicitly and point
    at the existing headless verify suite (per the issue's validation note)."""
    assert "Local LM Studio validation" in runbook_text
    assert "documentation-only" in runbook_text
    assert "pnpm verify:minecraft-server" in runbook_text

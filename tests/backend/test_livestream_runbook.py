"""Static checks for the E13-8 livestream ops runbook.

The issue is documentation-only. These tests verify that the runbook covers
the required operations with stable command strings and links back to the E13
deep-dive docs, without requiring OBS, ffmpeg, Docker, or a live RTMP target.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs" / "livestream" / "runbook.md"

DEEP_DIVE_DOCS = (
    "capture-prototype.md",
    "encoder-rtmp.md",
    "stream-overlay.md",
    "audio-tts.md",
    "resilience.md",
    "kill-path.md",
    "monitoring.md",
)

REQUIRED_COMMANDS = {
    "start-stream": "sudo systemctl enable --now livestream",
    "stop-stream": "sudo systemctl stop livestream",
    "rotate-keys": (
        "sudoedit /etc/livestreamtoagi/livestream.env && "
        "sudo systemctl restart livestream"
    ),
    "recover": (
        "sudo systemctl reset-failed livestream && "
        "sudo systemctl restart livestream"
    ),
    "kill": 'curl -fsS -X POST "http://127.0.0.1:8010/api/admin/kill?ttl=14400"',
    "health": "python scripts/livestream/monitor-stream-health.py --self-test",
    "logs": "journalctl -u livestream -f",
}

REQUIRED_SECTIONS = (
    "## Start Stream",
    "## Stop Stream",
    "## Rotate Stream Keys",
    "## Recover After Failure",
    "## Kill Stream",
    "## Health Check",
    "## Tail Logs",
    "## Local LM Studio Validation",
)


@pytest.fixture(scope="module")
def runbook_text() -> str:
    assert RUNBOOK.is_file(), f"missing livestream runbook: {RUNBOOK}"
    return RUNBOOK.read_text(encoding="utf-8")


def test_runbook_exists_and_is_substantial(runbook_text: str) -> None:
    assert runbook_text.lstrip().startswith("# Livestream Ops Runbook")
    assert len(runbook_text) > 6000, "runbook is too short to cover E13 operations"


@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_runbook_has_required_operation_sections(
    section: str,
    runbook_text: str,
) -> None:
    assert section in runbook_text


@pytest.mark.parametrize("operation", sorted(REQUIRED_COMMANDS))
def test_runbook_has_copy_paste_command(operation: str, runbook_text: str) -> None:
    command = REQUIRED_COMMANDS[operation]
    assert command in runbook_text, (
        f"runbook.md is missing the {operation!r} command: {command!r}"
    )


def test_runbook_links_to_dependency_deep_dives(runbook_text: str) -> None:
    for doc in DEEP_DIVE_DOCS:
        assert f"./{doc}" in runbook_text, f"runbook must link to {doc}"


def test_runbook_documents_runtime_env_without_secrets(runbook_text: str) -> None:
    for env_var in (
        "TWITCH_STREAM_KEY",
        "YOUTUBE_STREAM_KEY",
        "RTMP_URL",
        "RTMP_STREAM_KEY",
        "TTS_STREAM_ENABLED",
        "LIVESTREAM_ENABLED",
        "LIVESTREAM_KILL_MODE",
        "STREAM_SOURCE_URL",
        "STREAM_ALERT_EMAIL",
    ):
        assert env_var in runbook_text

    assert "never paste them into commits" in runbook_text
    assert "<new-twitch-key>" in runbook_text
    assert "<new-youtube-key>" in runbook_text


def test_runbook_states_docs_only_lmstudio_path(runbook_text: str) -> None:
    assert "documentation-only" in runbook_text
    assert "no LLM runtime path" in runbook_text
    assert ".venv/bin/python scripts/check_local_llm.py --list-only" in runbook_text
    assert "bash scripts/check-services.sh" in runbook_text
    assert "Do not spend OpenRouter credits" in runbook_text


def test_runbook_warns_when_upstream_e13_infrastructure_missing(
    runbook_text: str,
) -> None:
    """The runbook references scripts and docs introduced by E13-1..E13-7.

    When those upstream issues have not landed yet, the referenced helpers
    and deep-dive docs are absent from the repository. In that case the
    runbook must visibly warn operators not to paste the commands into a
    production host. Once the upstream infrastructure lands, this test
    auto-skips so the banner can be removed without a test churn.
    """
    upstream_paths = (
        REPO_ROOT / "scripts" / "livestream",
        REPO_ROOT / "core" / "livestream",
    )
    deep_dives = tuple(
        REPO_ROOT / "docs" / "livestream" / doc for doc in DEEP_DIVE_DOCS
    )
    if all(p.exists() for p in upstream_paths) and all(
        d.exists() for d in deep_dives
    ):
        pytest.skip("E13 upstream infrastructure now present; status banner optional")

    assert "**Status" in runbook_text, (
        "runbook must include a status banner while upstream E13 "
        "infrastructure is missing from the repository"
    )
    assert "do not yet exist" in runbook_text
    assert "Do not paste the commands into a production" in runbook_text

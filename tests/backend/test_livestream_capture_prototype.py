"""Tests for the E13-1 livestream capture prototype.

The real capture path needs a running E2 Paper server, Node deps, Playwright
Chromium, ffmpeg screen-capture permission, and a local display. These tests
therefore lock down the offline-safe contract: help/dry-run/static checks,
script syntax, local-only Minecraft settings, and documentation coverage.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "livestream" / "capture-prototype.sh"
CAMERA_BOT = REPO_ROOT / "scripts" / "livestream" / "camera-bot.mjs"
PROTOTYPE_PACKAGE = REPO_ROOT / "scripts" / "livestream" / "package.json"
PROTOTYPE_GITIGNORE = REPO_ROOT / "scripts" / "livestream" / ".gitignore"
DOC = REPO_ROOT / "docs" / "livestream" / "capture-prototype.md"
VIDEOS_DIR = REPO_ROOT / "videos" / "livestream"
ROOT_PACKAGE = REPO_ROOT / "package.json"

MC_HOST = "127.0.0.1"
MC_PORT = "25565"
MC_VERSION = "1.21.6"
VIEWER_PORT = "3007"
CAMERA_NAME = "CameraSpike"


def _run(args: list[str], cwd: Path, extra_env: dict[str, str] | None = None):
    env = {**os.environ}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "capture-prototype.sh must be chmod +x"


def test_bash_syntax_is_valid() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean() -> None:
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_exits_zero_and_describes_usage() -> None:
    proc = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "capture-prototype.sh" in proc.stdout
    assert "--duration" in proc.stdout
    assert "--viewer-port" in proc.stdout
    assert "--dry-run" in proc.stdout
    assert "set -euo pipefail" not in proc.stdout


def test_unknown_argument_is_rejected() -> None:
    proc = subprocess.run(["bash", str(SCRIPT), "--nope"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


def test_dry_run_is_side_effect_free_and_prints_capture_plan(tmp_path: Path) -> None:
    out = tmp_path / "capture.mp4"
    proc = _run(
        ["--dry-run", "--duration", "15", "--out", str(out), "--viewer-port", VIEWER_PORT],
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not out.exists()
    assert not (tmp_path / "node_modules").exists()

    text = proc.stdout
    assert f"{MC_HOST}:{MC_PORT}" in text
    assert f"minecraft={MC_VERSION}" in text
    assert f"http://127.0.0.1:{VIEWER_PORT}" in text
    assert "CameraSpike" in text
    assert "ffprobe" in text
    assert "Dry run complete" in text


def test_capture_script_contains_real_run_guards() -> None:
    src = SCRIPT.read_text()
    assert 'REQUIRED_NODE_MAJOR="20"' in src
    assert 'check_command "ffmpeg"' in src
    assert 'check_command "ffprobe"' in src
    assert "scripts/minecraft/start-server.sh" in src
    assert "exit 2" in src, "missing-dependency/server failures should use exit 2"
    assert "npm install --prefix" in src
    assert "--no-package-lock" in src
    assert "node_modules/mineflayer" in src
    assert "node_modules/canvas" in src
    assert '"event":"READY"' in src
    assert "avfoundation" in src
    assert "x11grab" in src
    assert "testsrc2" in src
    assert "start_viewer_browser_with_system_open" in src
    assert 'open "$VIEWER_URL"' in src
    assert 'xdg-open "$VIEWER_URL"' in src
    assert "ffprobe" in src


def test_camera_bot_uses_e2_local_spectator_viewer_contract() -> None:
    src = CAMERA_BOT.read_text()
    assert CAMERA_BOT.is_file(), f"missing {CAMERA_BOT}"
    assert CAMERA_NAME in src
    assert MC_HOST in src
    assert MC_PORT in src
    assert MC_VERSION in src
    assert "auth: 'offline'" in src
    assert "mineflayerViewer" in src
    assert "firstPerson: true" in src
    assert "/gamemode spectator" in src
    assert "event: 'READY'" in src
    assert "event: 'BYE'" in src
    assert "process.exitCode = 1" in src, "unexpected disconnects must fail"


def test_prototype_package_is_isolated_and_pins_viewer_deps() -> None:
    data = json.loads(PROTOTYPE_PACKAGE.read_text())
    assert data["private"] is True
    assert data["type"] == "module"
    assert data["engines"]["node"] == ">=20"
    assert data["dependencies"]["canvas"] == "^3.1.0"
    assert data["dependencies"]["mineflayer"] == "^4.33.0"
    assert data["dependencies"]["prismarine-viewer"] == "^1.32.0"
    assert data["scripts"]["start"].startswith("node camera-bot.mjs")


def test_generated_runtime_artifacts_are_ignored() -> None:
    ignored = PROTOTYPE_GITIGNORE.read_text()
    assert "node_modules/" in ignored
    assert "*.mp4" in ignored
    assert "*.webm" in ignored
    assert (VIDEOS_DIR / ".gitkeep").is_file()
    assert (VIDEOS_DIR / ".gitignore").is_file()
    assert "*.mp4" in (VIDEOS_DIR / ".gitignore").read_text()


def test_capture_doc_records_commands_limitations_and_lmstudio_note() -> None:
    text = DOC.read_text()
    assert "E13-1" in text
    assert "scripts/livestream/capture-prototype.sh --duration 15" in text
    assert "scripts/minecraft/start-server.sh" in text
    assert "docs/decisions/0006-video-capture.md" in text
    assert "Prismarine Viewer" in text
    assert "real Minecraft Java client + OBS" in text
    assert "Documented limitations" in text
    assert "1.21.5+" in text
    assert "https://github.com/PrismarineJS/prismarine-viewer/issues/473" in text
    assert "No audio" in text
    assert "No overlays" in text
    assert "No resilience" in text
    assert "Local LM Studio validation" in text
    assert "no LLM runtime path" in text
    assert "pnpm llm:local --list-only" in text


def test_root_package_wires_capture_verify_command() -> None:
    data = json.loads(ROOT_PACKAGE.read_text())
    assert (
        data["scripts"]["verify:livestream-capture"]
        == ".venv/bin/pytest tests/backend/test_livestream_capture_prototype.py -v"
    )

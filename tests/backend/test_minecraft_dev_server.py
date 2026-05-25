"""Tests for the Docker-backed local Minecraft dev shortcut.

The real command starts Docker and tails logs for ``pnpm dev``. These tests
exercise only offline-safe paths: help/dry-run/source/package/docs wiring.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "dev-server.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"
README = REPO_ROOT / "README.md"
RUNBOOK = REPO_ROOT / "docs" / "minecraft" / "runbook.md"
SERVER_SETUP = REPO_ROOT / "docs" / "minecraft" / "server-setup.md"


def _run(args: list[str], extra_env: dict[str, str] | None = None):
    env = {**os.environ}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "dev-server.sh must be executable"


def test_bash_syntax_is_valid():
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean():
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_exits_zero_and_describes_dev_modes():
    proc = _run(["--help"])
    assert proc.returncode == 0
    assert "pnpm dev:minecraft" in proc.stdout
    assert "--dry-run" in proc.stdout
    assert "--no-tail" in proc.stdout
    assert "--stop" in proc.stdout
    assert "set -euo pipefail" not in proc.stdout


def test_unknown_argument_is_rejected():
    proc = _run(["--nope"])
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


def test_pnpm_style_double_dash_separator_is_accepted():
    proc = _run(["--", "--dry-run"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "Dry run only" in proc.stdout


def test_dry_run_prints_pinned_docker_command_without_requiring_docker():
    proc = _run(["--dry-run"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert "ltag-minecraft-dev" in out
    assert "itzg/minecraft-server:java21" in out
    assert "VERSION=1.21.6" in out
    assert "PAPER_BUILD=48" in out
    assert "ONLINE_MODE=FALSE" in out
    assert "ENABLE_WHITELIST=FALSE" in out
    assert "-p 25565:25565" in out
    assert "Dry run only" in out


def test_dry_run_honors_dev_env_overrides():
    proc = _run(
        ["--dry-run"],
        {
            "MC_CONTAINER_NAME": "custom-mc",
            "MC_IMAGE": "example/mc:dev",
            "MC_VERSION": "1.21.4",
            "PAPER_BUILD": "12",
            "MC_PORT": "25566",
            "MEM": "2G",
            "ONLINE_MODE": "TRUE",
            "ENABLE_WHITELIST": "TRUE",
        },
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert "custom-mc" in out
    assert "example/mc:dev" in out
    assert "VERSION=1.21.4" in out
    assert "PAPER_BUILD=12" in out
    assert "-p 25566:25565" in out
    assert "MEMORY=2G" in out
    assert "ONLINE_MODE=TRUE" in out
    assert "ENABLE_WHITELIST=TRUE" in out


def test_package_json_wires_dev_and_stop_shortcuts():
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]
    assert scripts["dev:minecraft"] == "scripts/minecraft/dev-server.sh"
    assert "pnpm dev:minecraft" in scripts["dev"]
    assert "minecraft" in scripts["dev"]
    assert scripts["stop:minecraft"] == "scripts/minecraft/dev-server.sh --stop"
    assert "pnpm stop:minecraft" in scripts["stop"]
    assert "connect-stripped-bot.sh" in scripts["mc:bot"]
    assert "setup-mindcraft.sh" in scripts["mc:setup"]
    assert "test_minecraft_dev_server.py" in scripts["verify:minecraft-server"]


def test_docs_explain_the_new_dev_shortcut():
    for path in (README, RUNBOOK, SERVER_SETUP):
        text = path.read_text(encoding="utf-8")
        assert "pnpm dev:minecraft" in text, f"{path.name} missing pnpm dev:minecraft"
        assert "scripts/minecraft/dev-server.sh" in text, (
            f"{path.name} missing dev-server.sh"
        )

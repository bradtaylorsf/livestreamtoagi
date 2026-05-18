"""Tests for scripts/minecraft/connect-stock-bot.sh (issue #534, epic E3-2).

These exercise only the launch script's offline-safe paths: ``--help``,
``--verify`` (static, CI/network-safe), and ``--dry-run`` (prints the resolved
host/port/auth/profile/model but never clones, hits the network, runs Node, or
launches the bot). The real connect path needs Node 20 + a running E2 server +
LM Studio and is intentionally not exercised here — mirroring
tests/backend/test_minecraft_setup_mindcraft.py and test_minecraft_start_server.py.

They also lock down the E2-pointing contract sibling issues (#535 E3-3, #536
E3-4) build on: the committed settings template points at the E2 server
(127.0.0.1:25565, auth offline, minecraft 1.21.6), the stock profile is
LM-Studio-local only (no external spend), and the docs record the documented
command + offline posture.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-stock-bot.sh"
SETTINGS_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings.js"
PROFILE_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "profiles" / "stock-bot.json"
CONNECT_DOC = REPO_ROOT / "docs" / "minecraft" / "mindcraft-connect.md"
FORK_DOC = REPO_ROOT / "docs" / "minecraft" / "mindcraft-fork.md"
PACKAGE_JSON = REPO_ROOT / "package.json"

PINNED_SHA = "35be480b4cc0bca990278e6103a1426392559d96"
STOCK_BOT_NAME = "StockBot"
MC_HOST = "127.0.0.1"
MC_PORT = "25565"
MC_VERSION = "1.21.6"


def _run(args, cwd: Path, extra_env: dict | None = None):
    """Run the launch script in an isolated cwd so a stray clone is detectable."""
    env = {**os.environ}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "connect-stock-bot.sh must be chmod +x"


def test_bash_syntax_is_valid():
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean():
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_exits_zero_and_describes_usage():
    proc = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--verify" in proc.stdout
    assert "connect-stock-bot.sh" in proc.stdout
    # Help must print only the comment header — never leak script source
    # (same regression guard as the setup-mindcraft.sh help test).
    assert "set -euo pipefail" not in proc.stdout
    assert 'MINDCRAFT_DIR="${MINDCRAFT_DIR' not in proc.stdout


def test_unknown_argument_is_rejected():
    proc = subprocess.run(["bash", str(SCRIPT), "--nope"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


@pytest.mark.parametrize("mode", ["--help", "--verify", "--dry-run"])
def test_static_modes_exit_zero_and_do_not_clone(mode, tmp_path):
    """--help/--verify/--dry-run must be side-effect free: no clone, no dir."""
    proc = _run([mode], tmp_path, {"MINDCRAFT_DIR": str(tmp_path / "mindcraft")})
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not (tmp_path / "mindcraft").exists(), "no clone in static modes"
    assert not (tmp_path / ".git").exists()


def test_verify_reports_e2_target_without_network(tmp_path):
    proc = _run(["--verify"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert f"{MC_HOST}:{MC_PORT}" in proc.stdout
    assert "auth=offline" in proc.stdout
    assert "Static verify passed" in proc.stdout


def test_dry_run_prints_resolved_e2_target(tmp_path):
    proc = _run(["--dry-run"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert f"host:        {MC_HOST}" in out
    assert f"port:        {MC_PORT}" in out
    assert "auth:        offline" in out
    assert f"minecraft:   {MC_VERSION}" in out
    assert STOCK_BOT_NAME in out
    # No model set in CI → must say it is required and how to list ids.
    assert "LOCAL_LLM_MODEL unset" in out
    assert "pnpm llm:local --list-only" in out


def test_dry_run_with_model_env_substitutes_lmstudio_ids(tmp_path):
    proc = _run(
        ["--dry-run"],
        tmp_path,
        {"LOCAL_LLM_MODEL": "qwen3-8b", "LOCAL_LLM_MODEL_BUILDING": "qwen3-30b"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "lmstudio/qwen3-8b" in proc.stdout
    assert "lmstudio/qwen3-30b" in proc.stdout
    assert "openrouter/" not in proc.stdout


def test_settings_template_points_at_the_e2_server():
    src = SETTINGS_TEMPLATE.read_text()
    assert f'"minecraft_version": "{MC_VERSION}"' in src
    assert f'"host": "{MC_HOST}"' in src
    assert f'"port": {MC_PORT}' in src
    assert '"auth": "offline"' in src
    assert '"auto_open_ui": false' in src
    assert '"./profiles/stock-bot.json"' in src
    # It must remain a valid Mindcraft-shaped settings module.
    assert src.strip().startswith("//") or "const settings = {" in src
    assert "export default settings;" in src


def test_stock_profile_is_lmstudio_local_only_with_fixed_name():
    """The committed profile parses as JSON, is local-only, and fixed-name."""
    data = json.loads(PROFILE_TEMPLATE.read_text())
    assert data["name"] == STOCK_BOT_NAME, "bot username must be fixed"
    assert data["model"].startswith("lmstudio/"), "conversation tier must be local"
    assert data["code_model"].startswith("lmstudio/"), "building tier must be local"
    # Placeholders the launch script substitutes from env (decision 0003).
    assert "__LOCAL_LLM_MODEL__" in data["model"]
    assert "__LOCAL_LLM_MODEL_BUILDING__" in data["code_model"]
    # Zero external spend — never an openrouter id, and no embedding (0003).
    raw = PROFILE_TEMPLATE.read_text()
    assert "openrouter/" not in raw
    assert "embedding" not in data


def test_script_refuses_unpinned_or_missing_clone_and_missing_model():
    """Real-run guards exist as source (the bot isn't launched headlessly)."""
    src = SCRIPT.read_text()
    assert PINNED_SHA in src, "pinned commit SHA must be the baked-in default"
    assert 'REQUIRED_NODE_MAJOR="20"' in src, "Node 20 LTS pin (E1-R1)"
    assert "No Mindcraft clone at" in src
    assert "not at the pinned commit" in src
    assert "LOCAL_LLM_MODEL is not set" in src
    assert "setup-mindcraft.sh" in src, "must point users at the E3-1 installer"
    # Whitelist handling: E2 defaults white-list=true. The script defines the
    # fixed bot name once and prints the command with the var (expanded at run).
    assert f'STOCK_BOT_NAME="{STOCK_BOT_NAME}"' in src
    assert "whitelist add ${STOCK_BOT_NAME}" in src
    assert "WHITELIST=false" in src


def test_connect_doc_records_command_and_offline_posture():
    text = CONNECT_DOC.read_text()
    assert "scripts/minecraft/connect-stock-bot.sh" in text
    assert "pnpm verify:mindcraft-connect" in text
    assert f"{MC_HOST}:{MC_PORT}" in text
    assert "offline" in text, "offline auth posture must be documented (E1-R2)"
    assert f"whitelist add {STOCK_BOT_NAME}" in text
    assert "pnpm llm:local --list-only" in text


def test_fork_doc_links_to_the_connect_walkthrough():
    text = FORK_DOC.read_text()
    assert "mindcraft-connect.md" in text, "E3-1 doc must forward-ref the E3-2 doc"
    assert "connect-stock-bot.sh" in text


def test_package_json_wires_verify_mindcraft_connect():
    data = json.loads(PACKAGE_JSON.read_text())
    cmd = data["scripts"]["verify:mindcraft-connect"]
    assert "tests/backend/test_minecraft_connect_stock_bot.py" in cmd

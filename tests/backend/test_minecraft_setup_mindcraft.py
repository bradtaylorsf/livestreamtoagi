"""Tests for scripts/minecraft/setup-mindcraft.sh (issue #533, epic E3-1).

These exercise only the script's offline-safe paths: ``--help``, ``--verify``
(static, CI/network-safe), and ``--dry-run`` (prints the resolved plan but
never clones, hits the network, or installs). The real ``npm ci`` path needs
Node 20 + network and is intentionally not exercised here — this issue has no
LLM runtime path, mirroring tests/backend/test_minecraft_start_server.py.

They also lock down the pin contract that sibling issues (#534 E3-2, #535
E3-3) build on: the exact commit SHA, Node major, fork URL, the committed
deterministic lockfile, and that the decision/summary docs record the hash.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "setup-mindcraft.sh"
LOCKFILE = REPO_ROOT / "scripts" / "minecraft" / "mindcraft-package-lock.json"
SUMMARY_DOC = REPO_ROOT / "docs" / "decisions" / "0000-summary.md"
FORK_DOC = REPO_ROOT / "docs" / "minecraft" / "mindcraft-fork.md"

PINNED_SHA = "35be480b4cc0bca990278e6103a1426392559d96"
FORK_URL = "https://github.com/bradtaylorsf/mindcraft"


def _run(args, cwd: Path, extra_env: dict | None = None):
    """Run the setup script in an isolated cwd so a stray clone is detectable."""
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
    assert os.access(SCRIPT, os.X_OK), "setup-mindcraft.sh must be chmod +x"


def test_bash_syntax_is_valid():
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean():
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_script_pins_exact_sha_and_node_major():
    """The pin contract is hardcoded as the env-overridable default + check."""
    src = SCRIPT.read_text()
    assert PINNED_SHA in src, "pinned commit SHA must be the baked-in default"
    assert 'REQUIRED_NODE_MAJOR="20"' in src, "Node 20 LTS pin (E1-R1)"
    assert "bradtaylorsf/mindcraft" in src, "org fork must be the default repo"


def test_help_exits_zero_and_describes_usage():
    proc = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--verify" in proc.stdout
    assert PINNED_SHA in proc.stdout
    # Help must print only the comment header — never leak script source
    # (same regression guard as the start-server.sh help test).
    assert "set -euo pipefail" not in proc.stdout
    assert 'MINDCRAFT_REPO="${MINDCRAFT_REPO' not in proc.stdout


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
    # Nothing git-related should have been created in the working dir.
    assert not (tmp_path / ".git").exists()


def test_verify_reports_pinned_contract_without_network(tmp_path):
    proc = _run(["--verify"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert PINNED_SHA in proc.stdout
    assert FORK_URL in proc.stdout
    assert "Static verify passed" in proc.stdout


def test_dry_run_describes_the_install_plan(tmp_path):
    proc = _run(["--dry-run"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "Would clone" in proc.stdout
    assert "Would checkout" in proc.stdout
    assert PINNED_SHA in proc.stdout
    assert "npm ci" in proc.stdout


def test_committed_lockfile_exists_and_is_deterministic():
    """A vendored lockfile is what makes `npm ci` reproducible (no upstream one)."""
    assert LOCKFILE.is_file(), f"missing {LOCKFILE}"
    data = json.loads(LOCKFILE.read_text())
    assert isinstance(data.get("lockfileVersion"), int), (
        "lockfile must declare an integer lockfileVersion"
    )
    assert data.get("name") == "mindcraft"
    # A real resolved tree, not an empty stub — guards an accidental truncation.
    assert len(data.get("packages", {})) > 1


def test_summary_decision_doc_records_pin_and_fork():
    """Acceptance: the commit hash is recorded in docs/decisions/0000-summary.md."""
    text = SUMMARY_DOC.read_text()
    assert PINNED_SHA in text, "pinned SHA must be recorded in 0000-summary.md"
    assert FORK_URL in text, "org fork URL must be recorded in 0000-summary.md"


def test_fork_doc_records_pin_and_fork_and_verify_command():
    text = FORK_DOC.read_text()
    assert PINNED_SHA in text
    assert FORK_URL in text
    assert "pnpm verify:mindcraft-fork" in text
    assert "setup-mindcraft.sh" in text

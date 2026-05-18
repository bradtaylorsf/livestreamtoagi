"""Tests for scripts/minecraft/start-server.sh (issue #526, epic E2-1).

These exercise the script's offline-safe paths only: ``--dry-run`` does
everything except download the Paper jar and launch the JVM, so the config
resolution and file generation are verifiable without Java or a network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "start-server.sh"


def _run(args, server_dir: Path, extra_env: dict | None = None):
    """Run the start script with SERVER_DIR pointed at a temp dir."""
    env = {**os.environ, "SERVER_DIR": str(server_dir)}
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
    assert os.access(SCRIPT, os.X_OK), "start-server.sh must be chmod +x"


def test_bash_syntax_is_valid():
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(
    shutil.which("shellcheck") is None, reason="shellcheck not installed"
)
def test_shellcheck_clean():
    proc = subprocess.run(
        ["shellcheck", str(SCRIPT)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_exits_zero_and_describes_usage():
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--smoke" in proc.stdout
    # Help must print only the comment header — never leak script source
    # (regression guard for the hardcoded sed line-range bug).
    assert "set -euo pipefail" not in proc.stdout
    assert 'MC_VERSION="${MC_VERSION' not in proc.stdout


def test_unknown_argument_is_rejected():
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--nope"], capture_output=True, text=True
    )
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


def test_dry_run_generates_eula_and_pinned_defaults(tmp_path):
    server_dir = tmp_path / "mc"
    proc = _run(["--dry-run"], server_dir)

    assert proc.returncode == 0, proc.stderr + proc.stdout

    # (e) EULA accepted on the user's behalf.
    eula = (server_dir / "eula.txt").read_text()
    assert eula.strip() == "eula=true"

    # (f) Minimal server.properties with the E1 posture.
    props = (server_dir / "server.properties").read_text()
    assert "online-mode=false" in props  # E1-R2 offline posture
    assert "white-list=true" in props
    assert "difficulty=" in props
    assert "max-players=" in props
    assert "motd=" in props
    # E2-2 (#527): world-gen inputs now come from scripts/minecraft/world.config
    # and are written into a freshly generated server.properties. The committed
    # defaults: normal world, empty seed (= random), folder "world".
    assert "level-type=minecraft:normal" in props
    assert "level-name=world" in props
    assert "generate-structures=true" in props
    # Seed line is present but empty → Minecraft picks a random world.
    assert "level-seed=\n" in props or props.rstrip().endswith("level-seed=")

    # Pinned E1-R1 jar appears in the "would download/run" preview.
    assert "paper-1.21.6-48.jar" in proc.stdout
    # Dry run must not actually fetch the jar.
    assert not (server_dir / "paper-1.21.6-48.jar").exists()


def test_env_vars_override_defaults(tmp_path):
    server_dir = tmp_path / "mc"
    proc = _run(
        ["--dry-run"],
        server_dir,
        {
            "MC_VERSION": "1.21.4",
            "PAPER_BUILD": "12",
            "MEM": "4G",
            "ONLINE_MODE": "true",
            "WHITELIST": "false",
        },
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "paper-1.21.4-12.jar" in proc.stdout
    assert "-Xms4G -Xmx4G" in proc.stdout

    props = (server_dir / "server.properties").read_text()
    assert "online-mode=true" in props
    assert "white-list=false" in props


def test_existing_server_properties_is_not_clobbered(tmp_path):
    server_dir = tmp_path / "mc"
    server_dir.mkdir(parents=True)
    sentinel = "motd=do-not-touch\n"
    (server_dir / "server.properties").write_text(sentinel)

    proc = _run(["--dry-run"], server_dir)

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert (server_dir / "server.properties").read_text() == sentinel
    assert "untouched" in proc.stdout


def test_run_mode_without_java_fails_loudly(tmp_path):
    """A real run must hard-fail with an install hint when Java is absent.

    Skipped on hosts that actually have Java 21, where the script would
    correctly proceed past the Java gate instead.
    """
    probe = subprocess.run(
        ["bash", "-c", 'java -version 2>&1 | head -1'],
        capture_output=True,
        text=True,
    )
    if 'version "21' in probe.stdout:
        pytest.skip("Java 21 present on host; Java-gate path not exercised")

    server_dir = tmp_path / "mc"
    proc = _run([], server_dir)

    assert proc.returncode == 1
    assert "Java not found" in proc.stderr  # the failure line → stderr
    hints = proc.stdout + proc.stderr  # install hints → stdout
    assert "openjdk@21" in hints and "openjdk-21" in hints

"""Tests for world backup & restore (issue #530, epic E2-5).

Covers the two committed deliverables:

* ``scripts/minecraft/backup.sh`` — a scheduled-friendly, timestamped
  tar.gz snapshot of the world set, with per-prefix retention.
* ``scripts/minecraft/restore.sh`` — restore a prior world, or ``--reset``
  to a clean world (the path experimental run mode uses; E12 wires it up).

Everything here is fully offline (no Java, no network): a temp ``SERVER_DIR``
with a fake world folder is enough to exercise create / list / round-trip
restore / retention / reset and the running-server guard. Mirrors the static
checks in ``test_minecraft_supervision.py``.

Acceptance criteria under test: *a backup is produced; a documented restore
recreates a prior world; reset produces a clean world.*
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP = REPO_ROOT / "scripts" / "minecraft" / "backup.sh"
RESTORE = REPO_ROOT / "scripts" / "minecraft" / "restore.sh"

SCRIPTS = pytest.mark.parametrize(
    "script", [BACKUP, RESTORE], ids=["backup.sh", "restore.sh"]
)


def _run(script: Path, *args: str, server_dir: Path, env: dict | None = None):
    """Run a script with SERVER_DIR + a pinned WORLD_CONFIG (LEVEL_NAME)."""
    full_env = {
        **os.environ,
        "SERVER_DIR": str(server_dir),
        "WORLD_CONFIG": str(server_dir.parent / "world.config"),
    }
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=REPO_ROOT,
    )


def _make_world(tmp_path: Path, *, level_name: str = "testworld") -> Path:
    """Create a temp SERVER_DIR with a fake overworld/nether + props.

    Returns the SERVER_DIR. A sibling ``world.config`` pins LEVEL_NAME so the
    scripts' allow-list reader is exercised (not just its default).
    """
    (tmp_path / "world.config").write_text(f"LEVEL_NAME={level_name}\n")
    server_dir = tmp_path / "minecraft-server"
    region = server_dir / level_name / "region"
    region.mkdir(parents=True)
    (region / "r.0.0.mca").write_text("ORIGINAL-CHUNK-DATA")
    (server_dir / f"{level_name}_nether").mkdir()
    (server_dir / "server.properties").write_text("level-name=" + level_name)
    return server_dir


# ── static / smoke checks (mirror test_minecraft_supervision.py) ─────────────


@SCRIPTS
def test_script_exists_and_is_executable(script: Path):
    assert script.is_file(), f"missing {script}"
    assert os.access(script, os.X_OK), f"{script.name} must be chmod +x"


@SCRIPTS
def test_bash_syntax_is_valid(script: Path):
    proc = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


@SCRIPTS
@pytest.mark.skipif(
    shutil.which("shellcheck") is None, reason="shellcheck not installed"
)
def test_shellcheck_clean(script: Path):
    proc = subprocess.run(
        ["shellcheck", str(script)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@SCRIPTS
def test_help_exits_zero_and_describes_modes(script: Path):
    proc = subprocess.run(
        ["bash", str(script), "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0
    # Help must print only the comment header — never leak script source.
    assert "set -euo pipefail" not in proc.stdout
    assert "BACKUP_DIR" in proc.stdout
    if script is BACKUP:
        assert "--list" in proc.stdout and "--dry-run" in proc.stdout
    else:
        assert "--reset" in proc.stdout and "--latest" in proc.stdout


@SCRIPTS
def test_unknown_argument_is_rejected(script: Path):
    proc = subprocess.run(
        ["bash", str(script), "--nope"], capture_output=True, text=True
    )
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


def test_restore_with_no_action_is_rejected(tmp_path):
    server_dir = _make_world(tmp_path)
    proc = _run(RESTORE, server_dir=server_dir)
    assert proc.returncode == 2
    assert "Nothing to do" in proc.stderr


def test_backup_fails_clearly_with_no_world(tmp_path):
    (tmp_path / "world.config").write_text("LEVEL_NAME=testworld\n")
    server_dir = tmp_path / "minecraft-server"
    server_dir.mkdir()
    proc = _run(BACKUP, server_dir=server_dir)
    assert proc.returncode == 1
    assert "No world folder" in proc.stderr


# ── functional: backup creates an archive ────────────────────────────────────


def test_backup_creates_archive_and_dry_run_writes_nothing(tmp_path):
    server_dir = _make_world(tmp_path)
    backup_dir = server_dir / "backups"

    dry = _run(BACKUP, "--dry-run", server_dir=server_dir)
    assert dry.returncode == 0, dry.stderr
    assert not backup_dir.exists(), "--dry-run must not write anything"

    made = _run(BACKUP, server_dir=server_dir)
    assert made.returncode == 0, made.stderr + made.stdout
    archives = list(backup_dir.glob("world-*.tar.gz"))
    assert len(archives) == 1, f"expected one archive, got {archives}"

    listed = _run(BACKUP, "--list", server_dir=server_dir)
    assert listed.returncode == 0
    assert archives[0].name in listed.stdout
    # restore.sh --list must delegate to the same listing.
    via_restore = _run(RESTORE, "--list", server_dir=server_dir)
    assert via_restore.returncode == 0
    assert archives[0].name in via_restore.stdout


# ── functional: a documented restore recreates a prior world ─────────────────


def test_restore_latest_round_trips_world_and_snapshots_first(tmp_path):
    server_dir = _make_world(tmp_path)
    chunk = server_dir / "testworld" / "region" / "r.0.0.mca"

    assert _run(BACKUP, server_dir=server_dir).returncode == 0

    # Corrupt + delete part of the live world, then restore it.
    chunk.write_text("CORRUPTED")
    shutil.rmtree(server_dir / "testworld_nether")

    restored = _run(RESTORE, "--latest", "--yes", server_dir=server_dir)
    assert restored.returncode == 0, restored.stderr + restored.stdout
    assert chunk.read_text() == "ORIGINAL-CHUNK-DATA"
    assert (server_dir / "testworld_nether").is_dir()
    # A pre-restore safety snapshot of the (corrupted) world was taken first.
    pre = list((server_dir / "backups").glob("pre-restore-*.tar.gz"))
    assert len(pre) == 1, f"expected a pre-restore snapshot, got {pre}"


def test_restore_accepts_an_explicit_archive_path(tmp_path):
    server_dir = _make_world(tmp_path)
    assert _run(BACKUP, server_dir=server_dir).returncode == 0
    archive = next((server_dir / "backups").glob("world-*.tar.gz"))
    chunk = server_dir / "testworld" / "region" / "r.0.0.mca"
    chunk.write_text("CHANGED")

    proc = _run(RESTORE, str(archive), "--yes", server_dir=server_dir)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert chunk.read_text() == "ORIGINAL-CHUNK-DATA"


def test_restore_refuses_while_server_appears_running(tmp_path):
    server_dir = _make_world(tmp_path)
    assert _run(BACKUP, server_dir=server_dir).returncode == 0
    pid_file = server_dir / "logs" / "supervise-child.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))  # this test process is alive

    proc = _run(RESTORE, "--latest", "--yes", server_dir=server_dir)
    assert proc.returncode == 4
    assert "appears to be RUNNING" in proc.stderr


# ── functional: reset produces a clean world ─────────────────────────────────


def test_reset_clears_world_and_props_and_snapshots_first(tmp_path):
    server_dir = _make_world(tmp_path)

    proc = _run(RESTORE, "--reset", "--yes", server_dir=server_dir)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    # World folders + the generated server.properties are gone, so the next
    # start-server.sh run regenerates a fresh world from world.config.
    assert not (server_dir / "testworld").exists()
    assert not (server_dir / "testworld_nether").exists()
    assert not (server_dir / "server.properties").exists()
    # A pre-reset safety snapshot was taken before wiping.
    pre = list((server_dir / "backups").glob("pre-reset-*.tar.gz"))
    assert len(pre) == 1, f"expected a pre-reset snapshot, got {pre}"


def test_reset_refuses_while_server_appears_running(tmp_path):
    server_dir = _make_world(tmp_path)
    pid_file = server_dir / "logs" / "supervise-child.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    proc = _run(RESTORE, "--reset", "--yes", server_dir=server_dir)
    assert proc.returncode == 4
    assert "appears to be RUNNING" in proc.stderr
    assert (server_dir / "testworld").is_dir(), "world must be untouched"


def test_destructive_actions_refuse_without_yes_and_no_tty(tmp_path):
    """No --yes and no TTY (subprocess pipes) → refuse, do not guess."""
    server_dir = _make_world(tmp_path)
    proc = _run(RESTORE, "--reset", server_dir=server_dir)
    assert proc.returncode == 3
    assert "without confirmation" in proc.stderr
    assert (server_dir / "testworld").is_dir(), "world must be untouched"


# ── functional: retention prunes the periodic series ─────────────────────────


def test_retention_prunes_world_series_beyond_keep(tmp_path):
    """Pre-seed distinct-timestamp world- archives (no sleeps), then a real
    backup with BACKUP_KEEP=3 must leave only the 3 newest world- archives,
    and must NOT touch a pre-restore- safety snapshot."""
    server_dir = _make_world(tmp_path)
    backup_dir = server_dir / "backups"
    backup_dir.mkdir(parents=True)
    for ts in (
        "20260101T000000Z",
        "20260102T000000Z",
        "20260103T000000Z",
        "20260104T000000Z",
    ):
        (backup_dir / f"world-{ts}.tar.gz").write_text("old")
    keep_me = backup_dir / "pre-restore-20250101T000000Z.tar.gz"
    keep_me.write_text("safety-net")

    proc = _run(
        BACKUP, server_dir=server_dir, env={"BACKUP_KEEP": "3"}
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout

    world_archives = sorted(p.name for p in backup_dir.glob("world-*.tar.gz"))
    assert len(world_archives) == 3, world_archives
    # The 4 pre-seeded + 1 new = 5; oldest 2 pre-seeded pruned, newest kept.
    assert "world-20260101T000000Z.tar.gz" not in world_archives
    assert "world-20260104T000000Z.tar.gz" in world_archives
    # The safety snapshot (different prefix) is never touched by a world run.
    assert keep_me.is_file()

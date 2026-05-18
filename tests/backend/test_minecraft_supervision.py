"""Tests for 24/7 supervision (issue #529, epic E2-4).

Covers both deliverables:

* ``scripts/minecraft/minecraft.service`` — the systemd unit for the Linux
  24/7 host. Statically validated here (and, where ``systemd-analyze`` is
  available, syntax-verified on a sanitised copy so it doesn't depend on the
  template's placeholder host paths/user).
* ``scripts/minecraft/supervise.sh`` — the portable, dependency-free
  supervisor for hosts without systemd. Exercised via its ``--self-test``
  mode with a fast fake "server" so the kill->restart behaviour is
  verifiable with no Java and no network.

Acceptance criterion under test: *killing the server process auto-restarts
it within a documented window; an operator-requested stop does not loop;
logs are retained.*
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "supervise.sh"
SERVICE = REPO_ROOT / "scripts" / "minecraft" / "minecraft.service"
START_SERVER = REPO_ROOT / "scripts" / "minecraft" / "start-server.sh"


def _wait_until(predicate, timeout: float, *, what: str):
    """Poll ``predicate`` every 50ms until true or ``timeout`` seconds pass.

    Polling (not a fixed sleep) keeps the test fast on quick machines and
    non-flaky on slow CI.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout}s waiting for: {what}")


# ── supervise.sh: static / smoke checks (mirror test_minecraft_start_server) ──


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "supervise.sh must be chmod +x"


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
    assert "--self-test" in proc.stdout
    assert "RESTART_DELAY" in proc.stdout
    # Help must print only the comment header — never leak script source.
    assert "set -euo pipefail" not in proc.stdout
    assert "trap on_signal" not in proc.stdout


def test_unknown_argument_is_rejected():
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--nope"], capture_output=True, text=True
    )
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


def test_self_test_requires_an_injected_server_cmd():
    """--self-test must refuse to run without an explicit SERVER_CMD so a
    test can never accidentally launch the real Minecraft server."""
    env = {k: v for k, v in os.environ.items() if k != "SERVER_CMD"}
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--self-test"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 2
    assert "requires SERVER_CMD" in proc.stderr


# ── minecraft.service: static validation ─────────────────────────────────────


def test_service_unit_has_crash_recovery_directives():
    assert SERVICE.is_file(), f"missing {SERVICE}"
    text = SERVICE.read_text()

    # Sections present.
    assert "[Unit]" in text and "[Service]" in text and "[Install]" in text

    # Auto-restart on crash, with the documented restart window.
    assert "Restart=on-failure" in text
    assert "RestartSec=10" in text

    # Supervises the E2-1 start script (foreground exec → systemd tracks the
    # JVM directly and SIGTERM reaches Paper for a clean save).
    assert "ExecStart=" in text
    assert "scripts/minecraft/start-server.sh" in text
    assert "Type=simple" in text
    assert "KillSignal=SIGTERM" in text

    # Crash-loop guard (mirrors supervise.sh CRASH_LOOP_*).
    assert "StartLimitBurst=" in text
    assert "StartLimitIntervalSec=" in text

    # Logs retained in the journal.
    assert "StandardOutput=journal" in text
    assert "StandardError=journal" in text

    # Boots on host reboot.
    assert "WantedBy=multi-user.target" in text


@pytest.mark.skipif(
    shutil.which("systemd-analyze") is None,
    reason="systemd-analyze not available (non-Linux host)",
)
def test_service_unit_passes_systemd_analyze(tmp_path):
    """Syntax-verify the unit on a sanitised copy.

    The committed unit uses placeholder host paths/user (``/opt/...``,
    ``User=minecraft``) that don't exist on CI, which ``systemd-analyze
    verify`` would (correctly) flag. Substituting a real ExecStart and
    dropping User= isolates the check to the *directives/sections* being
    syntactically valid.
    """
    sanitized = []
    for line in SERVICE.read_text().splitlines():
        if line.startswith("ExecStart="):
            sanitized.append("ExecStart=/bin/true")
        elif line.startswith(("User=", "WorkingDirectory=")):
            continue
        else:
            sanitized.append(line)
    unit = tmp_path / "minecraft.service"
    unit.write_text("\n".join(sanitized) + "\n")

    proc = subprocess.run(
        ["systemd-analyze", "verify", str(unit)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── supervise.sh: functional crash-recovery ──────────────────────────────────


def _fake_server(path: Path, launches: Path) -> Path:
    """A fast stand-in for the Minecraft server: records each launch, then
    runs until signalled (so it only exits when killed/stopped)."""
    path.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$$" >> "{launches}"\n'
        "trap 'exit 0' TERM INT\n"
        "while :; do sleep 0.1; done\n"
    )
    path.chmod(0o755)
    return path


def test_crash_recovery_restarts_within_window_and_stop_does_not_loop(
    tmp_path,
):
    """The acceptance criterion, end to end with no Java/network:

    1. supervise.sh launches the (fake) server,
    2. SIGKILLing it auto-restarts within the documented window,
    3. the supervisor log file is retained with the restart recorded,
    4. an operator stop (SIGTERM) exits cleanly and does NOT relaunch.
    """
    server_dir = tmp_path / "mc"
    launches = tmp_path / "launches.txt"
    sup_log = server_dir / "logs" / "supervisor.log"
    pid_file = server_dir / "logs" / "child.pid"
    fake = _fake_server(tmp_path / "fake-server.sh", launches)

    restart_delay = 1  # the documented window, shortened for the test
    env = {
        **os.environ,
        "SERVER_DIR": str(server_dir),
        "SERVER_CMD": str(fake),
        "RESTART_DELAY": str(restart_delay),
        "SUPERVISOR_LOG": str(sup_log),
        "CHILD_PID_FILE": str(pid_file),
    }
    proc = subprocess.Popen(
        ["bash", str(SCRIPT), "--self-test"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    try:
        # (1) First launch happened and the PID file is populated.
        _wait_until(
            lambda: launches.exists()
            and len(launches.read_text().split()) >= 1
            and pid_file.exists()
            and pid_file.read_text().strip().isdigit(),
            timeout=15,
            what="first server launch + pid file",
        )
        first_pid = int(pid_file.read_text().strip())

        # (2) Simulate a crash; expect an auto-restart within the window.
        os.kill(first_pid, signal.SIGKILL)
        killed_at = time.monotonic()
        _wait_until(
            lambda: len(launches.read_text().split()) >= 2,
            timeout=15,
            what="auto-restart after crash",
        )
        relaunch_after = time.monotonic() - killed_at
        # Within the documented window + a generous margin for slow CI.
        assert relaunch_after < restart_delay + 10, (
            f"relaunch took {relaunch_after:.1f}s"
        )
        second_pid = int(pid_file.read_text().strip())
        assert second_pid != first_pid

        # (3) Log retained, with the crash + restart recorded.
        assert sup_log.is_file()
        log_text = sup_log.read_text()
        assert "exited unexpectedly" in log_text
        assert "restarting in" in log_text
        assert "attempt 2" in log_text

        # (4) Operator stop → clean exit, signal forwarded, NO relaunch.
        launches_at_stop = len(launches.read_text().split())
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=15)
        assert proc.returncode == 0
        stop_log = sup_log.read_text()
        assert "stop requested" in stop_log
        assert "not restarting" in stop_log
        # The supervisor has exited, so no further launch is possible.
        assert len(launches.read_text().split()) == launches_at_stop
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

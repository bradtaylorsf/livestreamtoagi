"""Tests for E13-5 livestream 24/7 resilience supervision.

The real stream command owns capture, ffmpeg encoding, and RTMP push. These
tests exercise the supervisor around a fake command so CI never needs ffmpeg,
Twitch, YouTube, or network access.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "livestream" / "supervise-stream.sh"
SERVICE = REPO_ROOT / "scripts" / "livestream" / "livestream.service"

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="livestream supervisor is a bash/unix process supervisor",
)


def _wait_until(predicate, timeout: float, *, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout}s waiting for: {what}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text()


def _launch_count(path: Path) -> int:
    return len(_read_text(path).splitlines())


def _pid_from_file(path: Path) -> int:
    text = path.read_text().strip()
    assert text.isdigit(), f"PID file did not contain a PID: {text!r}"
    return int(text)


def _write_running_fake(path: Path, launches: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$$" >> "{launches}"\n'
        "trap 'exit 0' TERM INT\n"
        "while :; do sleep 0.1; done\n"
    )
    path.chmod(0o755)
    return path


def _write_exiting_fake(path: Path, launches: Path, exit_code: int = 1) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$$" >> "{launches}"\n'
        f"exit {exit_code}\n"
    )
    path.chmod(0o755)
    return path


def _env_for(
    tmp_path: Path,
    stream_cmd: Path,
    *,
    restart_delay: int = 1,
    crash_loop_limit: int = 5,
    crash_loop_window: int = 30,
) -> tuple[dict[str, str], Path, Path, Path]:
    log_dir = tmp_path / "logs"
    supervisor_log = log_dir / "livestream-supervisor.log"
    child_log = log_dir / "livestream-child.log"
    pid_file = log_dir / "child.pid"
    env = {
        **os.environ,
        "LOG_DIR": str(log_dir),
        "STREAM_CMD": str(stream_cmd),
        "RESTART_DELAY": str(restart_delay),
        "CRASH_LOOP_LIMIT": str(crash_loop_limit),
        "CRASH_LOOP_WINDOW": str(crash_loop_window),
        "SUPERVISOR_LOG": str(supervisor_log),
        "CHILD_LOG": str(child_log),
        "CHILD_PID_FILE": str(pid_file),
    }
    return env, supervisor_log, pid_file, child_log


def _start_supervisor(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["bash", str(SCRIPT), "--self-test"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def _terminate_supervisor(proc: subprocess.Popen[str], pid_file: Path) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if pid_file.exists():
            try:
                os.kill(_pid_from_file(pid_file), signal.SIGTERM)
            except ProcessLookupError:
                pass
        proc.kill()
        proc.wait(timeout=10)


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "supervise-stream.sh must be chmod +x"


def test_bash_syntax_is_valid() -> None:
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(
    shutil.which("shellcheck") is None, reason="shellcheck not installed"
)
def test_shellcheck_clean() -> None:
    proc = subprocess.run(
        ["shellcheck", str(SCRIPT)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_service_unit_has_crash_recovery_directives() -> None:
    assert SERVICE.is_file(), f"missing {SERVICE}"
    text = SERVICE.read_text()

    assert "[Unit]" in text and "[Service]" in text and "[Install]" in text
    assert "Type=simple" in text
    assert "ExecStart=/opt/livestreamtoagi/scripts/livestream/stream-push.sh" in text
    assert "Restart=on-failure" in text
    assert "RestartSec=10" in text
    assert "StartLimitIntervalSec=300" in text
    assert "StartLimitBurst=5" in text
    assert "KillSignal=SIGTERM" in text
    assert "TimeoutStopSec=30" in text
    assert "TWITCH_STREAM_KEY=EDIT_ON_HOST" in text
    assert "YOUTUBE_STREAM_KEY=EDIT_ON_HOST" in text
    assert "docs/livestream/resilience.md" in text


@pytest.mark.skipif(
    shutil.which("systemd-analyze") is None,
    reason="systemd-analyze not available on this host",
)
def test_service_unit_passes_systemd_analyze(tmp_path: Path) -> None:
    sanitized: list[str] = []
    for line in SERVICE.read_text().splitlines():
        if line.startswith("ExecStart="):
            sanitized.append("ExecStart=/bin/true")
        elif line.startswith(("User=", "WorkingDirectory=")):
            continue
        else:
            sanitized.append(line)

    unit = tmp_path / "livestream.service"
    unit.write_text("\n".join(sanitized) + "\n")
    proc = subprocess.run(
        ["systemd-analyze", "verify", str(unit)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_self_test_requires_stream_cmd() -> None:
    env = {key: value for key, value in os.environ.items() if key != "STREAM_CMD"}
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--self-test"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert proc.returncode == 2
    assert "requires STREAM_CMD" in proc.stderr


def test_supervise_help_does_not_run_child(tmp_path: Path) -> None:
    launches = tmp_path / "launches.txt"
    fake = _write_running_fake(tmp_path / "fake-stream.sh", launches)
    env, _supervisor_log, pid_file, _child_log = _env_for(tmp_path, fake)

    proc = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert proc.returncode == 0
    assert "--self-test" in proc.stdout
    assert "RESTART_DELAY" in proc.stdout
    assert "set -euo pipefail" not in proc.stdout
    assert "trap on_signal" not in proc.stdout
    assert not launches.exists()
    assert not pid_file.exists()


def test_supervisor_restarts_child_after_crash(tmp_path: Path) -> None:
    launches = tmp_path / "launches.txt"
    fake = _write_running_fake(tmp_path / "fake-stream.sh", launches)
    restart_delay = 1
    env, supervisor_log, pid_file, _child_log = _env_for(
        tmp_path, fake, restart_delay=restart_delay
    )
    proc = _start_supervisor(env)

    try:
        _wait_until(
            lambda: _launch_count(launches) == 1
            and pid_file.exists()
            and pid_file.read_text().strip().isdigit(),
            timeout=10,
            what="first stream child launch",
        )
        first_pid = _pid_from_file(pid_file)

        os.kill(first_pid, signal.SIGKILL)
        killed_at = time.monotonic()

        _wait_until(
            lambda: _launch_count(launches) >= 2
            and pid_file.exists()
            and _pid_from_file(pid_file) != first_pid,
            timeout=10,
            what="stream child restart",
        )

        relaunch_after = time.monotonic() - killed_at
        assert relaunch_after < restart_delay + 5
        assert _pid_from_file(pid_file) != first_pid

        log_text = supervisor_log.read_text()
        assert re.search(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ child-exited exit_code=\d+ uptime_seconds=\d+",
            log_text,
        )
        assert "restarting attempt=2 gap_seconds=" in log_text
    finally:
        _terminate_supervisor(proc, pid_file)


def test_supervisor_logs_downtime_gap(tmp_path: Path) -> None:
    launches = tmp_path / "launches.txt"
    fake = _write_exiting_fake(tmp_path / "fake-stream.sh", launches)
    restart_delay = 1
    env, supervisor_log, pid_file, _child_log = _env_for(
        tmp_path, fake, restart_delay=restart_delay
    )
    proc = _start_supervisor(env)

    try:
        _wait_until(
            lambda: "restarting attempt=2" in _read_text(supervisor_log),
            timeout=10,
            what="first logged restart",
        )
        log_text = supervisor_log.read_text()
        match = re.search(r"restarting attempt=2 gap_seconds=(\d+)", log_text)
        assert match is not None, log_text
        assert int(match.group(1)) >= restart_delay
    finally:
        _terminate_supervisor(proc, pid_file)


def test_supervisor_crash_loop_guard_aborts(tmp_path: Path) -> None:
    launches = tmp_path / "launches.txt"
    fake = _write_exiting_fake(tmp_path / "fake-stream.sh", launches)
    env, supervisor_log, _pid_file, _child_log = _env_for(
        tmp_path,
        fake,
        restart_delay=0,
        crash_loop_limit=2,
        crash_loop_window=30,
    )

    proc = subprocess.run(
        ["bash", str(SCRIPT), "--self-test"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )

    assert proc.returncode == 1
    assert _launch_count(launches) == 2
    log_text = supervisor_log.read_text()
    assert log_text.count("restarting attempt=") == 1
    assert (
        "crash-loop-abort restarts=2 window_seconds=30 limit=2 "
        "failed_launches=2"
    ) in log_text


def test_supervisor_captures_child_output_without_leaking_to_terminal(
    tmp_path: Path,
) -> None:
    launches = tmp_path / "launches.txt"
    fake = tmp_path / "fake-stream.sh"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$$" >> "{launches}"\n'
        "echo fake-stream-up\n"
        "exit 1\n"
    )
    fake.chmod(0o755)
    env, supervisor_log, _pid_file, child_log = _env_for(
        tmp_path,
        fake,
        restart_delay=0,
        crash_loop_limit=3,
        crash_loop_window=30,
    )

    proc = subprocess.run(
        ["bash", str(SCRIPT), "--self-test"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )

    assert proc.returncode == 1
    assert "fake-stream-up" not in proc.stdout
    assert "fake-stream-up" not in proc.stderr
    assert child_log.read_text().splitlines() == [
        "fake-stream-up",
        "fake-stream-up",
        "fake-stream-up",
    ]
    assert _launch_count(launches) == 3
    assert "starting-child attempt=4" not in supervisor_log.read_text()


def test_supervisor_defaults_companion_files_beside_supervisor_log(
    tmp_path: Path,
) -> None:
    launches = tmp_path / "launches.txt"
    fake = tmp_path / "fake-stream.sh"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$$" >> "{launches}"\n'
        "echo fake-stream-up\n"
        "exit 1\n"
    )
    fake.chmod(0o755)
    supervisor_log = tmp_path / "sup.log"
    child_log = tmp_path / "livestream-child.log"
    pid_file = tmp_path / "supervise-stream-child.pid"
    env = {
        **os.environ,
        "STREAM_CMD": str(fake),
        "SUPERVISOR_LOG": str(supervisor_log),
        "RESTART_DELAY": "0",
        "CRASH_LOOP_LIMIT": "1",
        "CRASH_LOOP_WINDOW": "30",
    }
    for key in ("LOG_DIR", "CHILD_LOG", "CHILD_PID_FILE"):
        env.pop(key, None)

    proc = subprocess.run(
        ["bash", str(SCRIPT), "--self-test"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )

    assert proc.returncode == 1
    assert "fake-stream-up" not in proc.stdout
    assert "fake-stream-up" not in proc.stderr
    assert child_log.read_text().splitlines() == ["fake-stream-up"]
    assert not pid_file.exists()
    log_text = supervisor_log.read_text()
    assert f"child_log={child_log}" in log_text
    assert f"child_pid_file={pid_file}" in log_text
    assert "child_log=./logs/livestream" not in log_text


def test_supervisor_clean_stop_does_not_restart(tmp_path: Path) -> None:
    launches = tmp_path / "launches.txt"
    fake = _write_running_fake(tmp_path / "fake-stream.sh", launches)
    env, supervisor_log, pid_file, _child_log = _env_for(tmp_path, fake)
    proc = _start_supervisor(env)

    _wait_until(
        lambda: _launch_count(launches) == 1
        and pid_file.exists()
        and pid_file.read_text().strip().isdigit(),
        timeout=10,
        what="first stream child launch",
    )

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)

    assert proc.returncode == 0
    assert _launch_count(launches) == 1
    log_text = supervisor_log.read_text()
    assert "stop-requested reason=operator" in log_text
    assert "reason=operator-stop" in log_text
    assert "restarting attempt=" not in log_text
    assert not pid_file.exists()

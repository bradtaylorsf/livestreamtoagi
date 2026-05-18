"""Tests for the server health check + status endpoint (issue #531, epic E2-6).

Covers both deliverables:

* ``scripts/minecraft/health.sh`` — a dependency-free TCP liveness probe
  with human / ``--json`` / ``--quiet`` / ``--self-test`` modes. Exercised
  against a *real* loopback socket (no Java, no Minecraft, no real network)
  so up/down, exit codes, the JSON status line, and port autodetect from
  ``server.properties`` are all verified offline.
* The opt-in addition to ``scripts/check-services.sh`` — gated on
  ``CHECK_MINECRAFT=1`` so the default 5-service dev/CI gate is unaffected.

Acceptance criterion under test: *a single command reports server up/down;
it integrates with the existing scripts/check-services.sh pattern.*

Mirrors the static-check style of ``test_minecraft_supervision.py``.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "health.sh"
CHECK_SERVICES = REPO_ROOT / "scripts" / "check-services.sh"


def _run(*args: str, env: dict | None = None, timeout: float = 30):
    full_env = {**os.environ}
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=REPO_ROOT,
        timeout=timeout,
    )


@contextlib.contextmanager
def _tcp_listener() -> Iterator[int]:
    """Bind a real loopback TCP listener that accepts+closes connections in a
    background thread (so repeated probes don't exhaust a tiny backlog — a
    real server calls ``accept()``). Yields the bound port; closes on exit.
    """
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    port = srv.getsockname()[1]

    stop = threading.Event()

    def _serve() -> None:
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                conn.close()
            except TimeoutError:
                continue
            except OSError:
                break

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    try:
        yield port
    finally:
        stop.set()
        srv.close()
        t.join(timeout=2)


def _free_port() -> int:
    """A port number with nothing listening (bound then immediately freed)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── static / smoke checks (mirror test_minecraft_supervision) ────────────────


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "health.sh must be chmod +x"


def test_bash_syntax_is_valid():
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean():
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_exits_zero_and_describes_usage():
    proc = _run("--help")
    assert proc.returncode == 0
    assert "--json" in proc.stdout
    assert "--self-test" in proc.stdout
    assert "SERVER_PORT" in proc.stdout
    # Help must print only the comment header — never leak script source.
    assert "set -euo pipefail" not in proc.stdout
    assert "probe_tcp()" not in proc.stdout


def test_unknown_argument_is_rejected():
    proc = _run("--nope")
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


# ── functional: up / down against a real loopback socket ─────────────────────


def test_human_mode_reports_up_and_exits_zero():
    with _tcp_listener() as port:
        proc = _run(env={"SERVER_HOST": "127.0.0.1", "SERVER_PORT": str(port)})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "✓" in proc.stdout
    assert f"127.0.0.1:{port}" in proc.stdout


def test_json_mode_emits_valid_status_when_up():
    with _tcp_listener() as port:
        proc = _run("--json", env={"SERVER_HOST": "127.0.0.1", "SERVER_PORT": str(port)})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["up"] is True
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == port  # a JSON number, not a string
    assert payload["checked_at"].endswith("Z")  # UTC ISO-8601


def test_quiet_mode_is_silent_but_sets_exit_code():
    with _tcp_listener() as port:
        up = _run(
            "--quiet",
            env={"SERVER_HOST": "127.0.0.1", "SERVER_PORT": str(port)},
        )
    assert up.returncode == 0
    assert up.stdout == "" and up.stderr == ""

    down = _run(
        "--quiet",
        env={"SERVER_HOST": "127.0.0.1", "SERVER_PORT": str(_free_port())},
    )
    assert down.returncode == 1
    assert down.stdout == ""


def test_reports_down_when_nothing_is_listening():
    port = _free_port()
    env = {"SERVER_HOST": "127.0.0.1", "SERVER_PORT": str(port)}

    human = _run(env=env)
    assert human.returncode == 1
    assert "✗" in human.stderr

    js = _run("--json", env=env)
    assert js.returncode == 1
    payload = json.loads(js.stdout)
    assert payload["up"] is False
    assert payload["port"] == port


def test_connect_timeout_is_bounded_for_an_unreachable_host():
    """A filtered/unroutable host must not hang for the OS default (~75s);
    the watchdog caps it at CONNECT_TIMEOUT and reports down."""
    proc = _run(
        "--quiet",
        env={
            "SERVER_HOST": "10.255.255.1",  # RFC5737-style unroutable
            "SERVER_PORT": "25565",
            "CONNECT_TIMEOUT": "2",
        },
        timeout=20,
    )
    assert proc.returncode == 1


def test_port_is_autodetected_from_server_properties(tmp_path):
    """With SERVER_PORT unset, the port is read from server.properties via
    the same allow-list reader start-server.sh uses (CRLF tolerated)."""
    with _tcp_listener() as port:
        server_dir = tmp_path / "mc"
        server_dir.mkdir()
        (server_dir / "server.properties").write_text(
            f"motd=x\r\nserver-port={port}\r\ndifficulty=normal\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "SERVER_PORT"}
        env.update({"SERVER_HOST": "127.0.0.1", "SERVER_DIR": str(server_dir)})
        proc = _run("--json", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["up"] is True
    assert payload["port"] == port


def test_invalid_port_is_a_usage_error():
    proc = _run(env={"SERVER_PORT": "not-a-number"})
    assert proc.returncode == 2
    assert "Invalid server port" in proc.stderr


def test_self_test_passes_with_no_java_or_network():
    """--self-test is the single self-contained verification (mirrors
    supervise.sh --self-test): it binds a throwaway listener, proves the
    probe says up then down, with no Java and no real network."""
    if shutil.which("python3") is None:
        pytest.skip("python3 required for --self-test's throwaway listener")
    proc = _run("--self-test", timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "self-test passed" in proc.stdout


# ── check-services.sh integration: opt-in, default flow unaffected ───────────


def test_check_services_minecraft_check_is_opt_in():
    """Static guard: the Minecraft check exists, is gated on CHECK_MINECRAFT,
    and invokes health.sh --quiet — without changing the default 5 checks."""
    text = CHECK_SERVICES.read_text()
    assert 'CHECK_MINECRAFT:-0}" = "1"' in text
    assert "minecraft/health.sh" in text
    assert "--quiet" in text
    # bash -n must still pass after the addition.
    proc = subprocess.run(["bash", "-n", str(CHECK_SERVICES)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def _run_check_services(env: dict):
    try:
        return subprocess.run(
            ["bash", str(CHECK_SERVICES)],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
            cwd=REPO_ROOT,
            timeout=90,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover - env-dependent
        pytest.skip("check-services.sh did not finish (docker env unavailable)")


def test_check_services_default_run_has_no_minecraft_line():
    """With CHECK_MINECRAFT unset the Minecraft probe is absent — the default
    dev/CI gate is unaffected (it runs with no Minecraft server present)."""
    proc = _run_check_services({})
    assert "Minecraft" not in (proc.stdout + proc.stderr)


def test_check_services_opt_in_invokes_health_probe():
    """CHECK_MINECRAFT=1 routes through health.sh: a live server shows the
    Minecraft check passing in the same report as the other services."""
    with _tcp_listener() as port:
        proc = _run_check_services(
            {
                "CHECK_MINECRAFT": "1",
                "SERVER_HOST": "127.0.0.1",
                "SERVER_PORT": str(port),
            }
        )
    assert f"✓ Minecraft server (127.0.0.1:{port})" in proc.stdout

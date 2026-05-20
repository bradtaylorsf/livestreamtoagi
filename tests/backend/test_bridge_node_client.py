"""Tests for the Node bridge client in the fork (issue #543 E4-4 + #544 E4-5
— epic #506).

Acceptance bar (issue #543): *in-game a bot invokes the ping action and logs
the Python response; the failure path is logged, not crashed.* That has two
testable halves, and this module covers both:

* **(a) Static contract of the committed JS** — ``./mindcraft`` is git-ignored,
  so ``scripts/minecraft/fork-src/...`` is the reviewed source of truth. These
  assertions pin the envelope field set, the ``Authorization: Bearer`` /
  ``MINECRAFT_BRIDGE_TOKEN`` auth, the ``/api/minecraft/bridge/ws`` endpoint,
  the local deadline timeout, the structured-error type, the never-crash
  wrapping of ``!bridgePing``, that the JSON Schema is treated as *reference*
  (no validator dependency — the lockfile is frozen), and that nothing points
  at ``openrouter`` (local-only validation).

* **(b) Live round-trip** — boot the real E4-3 ``bridge_router`` under uvicorn
  on an ephemeral port (a minimal app, so the heavy ``core.main`` lifespan /
  Docker services never run — this stays the dependency-free local smoke path),
  then drive the *committed* ``python_bridge.js`` from a Node subprocess. The
  happy path returns ``payload.pong == message`` with an echoed ``request_id``;
  the failure paths (wrong token, server ``ok:false``, deadline timeout, no
  token) all surface as a typed ``BridgeClientError`` the process handles — not
  an uncaught throw / crash.

This issue's local runtime path is exactly this Node↔Python round-trip; there
is no LLM model call in the bridge client, so no LM Studio spend is required.
The integration half skips cleanly when ``node`` is unavailable.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from tests.integration.bridge_harness import copy_bridge_client_with_header_ws


def _strip_js_comments(src: str) -> str:
    """Drop `//` line and `/* */` block comments so a token assertion checks
    executable code, not prose in a docstring/comment."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
BRIDGE_CLIENT = FORK_SRC / "agent" / "bridge" / "python_bridge.js"
BRIDGE_ACTION = FORK_SRC / "agent" / "commands" / "bridge_ping_action.js"
CONNECT_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
BRIDGE_PROFILE = REPO_ROOT / "scripts" / "minecraft" / "profiles" / "bridge-bot.json"
CLIENT_DOC = REPO_ROOT / "docs" / "minecraft" / "mindcraft-bridge-client.md"
PACKAGE_JSON = REPO_ROOT / "package.json"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SCHEMA_FILE = REPO_ROOT / "core" / "bridge" / "schemas" / "bridge-protocol.schema.json"

TOKEN = "test-bridge-node-secret"  # noqa: S105 — test-only shared secret
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _node_has_global_websocket() -> bool:
    if NODE is None:
        return False
    res = subprocess.run(
        [NODE, "-e", "process.exit(globalThis.WebSocket ? 0 : 1)"],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


requires_global_websocket = pytest.mark.skipif(
    not _node_has_global_websocket(),
    reason="node runtime does not expose globalThis.WebSocket",
)


# ── (a) Static contract of the committed JS ─────────────────────────────────


def test_committed_bridge_files_exist() -> None:
    assert BRIDGE_CLIENT.is_file(), f"missing {BRIDGE_CLIENT}"
    assert BRIDGE_ACTION.is_file(), f"missing {BRIDGE_ACTION}"
    # Layout must mirror the clone so `../bridge/python_bridge.js` resolves both
    # staged-in-the-clone and when driven directly by this test.
    assert BRIDGE_CLIENT.parent.name == "bridge"
    assert BRIDGE_ACTION.parent.name == "commands"


def test_client_carries_the_full_request_envelope() -> None:
    src = BRIDGE_CLIENT.read_text()
    # ADR §2 request envelope — every field must be present (decision 0010).
    for field in (
        "version",
        "request_id",
        "agent_id",
        "run_id",
        "simulation_id",
        "service",
        "method",
        "payload",
        "deadline_ms",
        "cost_context",
    ):
        assert field in src, f"client envelope missing {field!r}"
    # cost_context shape the contract's CostContext model requires.
    assert "agent_tier" in src and "conversation" in src
    assert "budget_bucket" in src and "'bridge'" in src
    assert "estimated_cost_usd" in src
    # 1.5: E7-2 (#566) added errand.poll — a minor
    # bump (ADR §3), still wire-compatible with earlier 1.x peers.
    assert "PROTOCOL_VERSION = '1.5'" in src, "protocol version must be 1.5"


def test_client_uses_bearer_auth_and_the_bridge_endpoint() -> None:
    src = BRIDGE_CLIENT.read_text()
    assert "/api/minecraft/bridge/ws" in src, "client must target the ADR §1 endpoint"
    assert "MINECRAFT_BRIDGE_TOKEN" in src, "client must read the shared-secret env"
    assert "MINECRAFT_BRIDGE_URL" in src, "client must honor the URL override env"
    assert "Bearer" in src and "Authorization" in src, "ADR §4 bearer header"
    # Fail closed when the secret is absent — no anonymous path (ADR §4).
    assert "bridge_no_token" in src


def test_client_enforces_a_local_deadline_and_structured_errors() -> None:
    src = BRIDGE_CLIENT.read_text()
    assert "setTimeout" in src and "deadlineMs" in src, "local timeout == deadline_ms"
    assert "class BridgeClientError" in src, "typed structured error required"
    assert "bridge_timeout" in src
    assert "bridge_auth_refused" in src
    # Response is structurally validated (ok boolean / request_id echo / typed
    # error) WITHOUT a JSON-Schema validator dependency (frozen lockfile).
    assert "request_id" in src and "echo" in src.lower()
    assert "ajv" not in src.lower(), "no ajv — JSON Schema is reference only"
    assert "jsonschema" not in src.lower(), "no jsonschema — schema is reference only"
    assert "bridge-protocol.schema.json" in src, "schema referenced as reference"


def test_client_is_local_only_no_external_spend() -> None:
    assert "openrouter" not in BRIDGE_CLIENT.read_text().lower()
    assert "openrouter" not in BRIDGE_ACTION.read_text().lower()


def test_ping_action_matches_mindcraft_shape_and_never_crashes() -> None:
    src = BRIDGE_ACTION.read_text()
    assert "'!bridgePing'" in src, "action name must be !bridgePing (ADR first proof)"
    assert "params" in src and "message" in src, "declares the message param"
    assert "perform" in src and "async function" in src, "Mindcraft actionsList shape"
    assert "callBridge" in src, "action round-trips through the bridge client"
    assert "service: 'bridge'" in src and "method: 'ping'" in src
    # Wrapped so a bridge failure is logged with the structured code, never
    # thrown out of perform (issue #543 acceptance: "not crashed").
    assert "try {" in src and "catch" in src
    assert "err.code" in src, "failure path logs the structured error.code"
    # perform must not re-throw — no `throw` statement in the executable code
    # (comments mentioning the word are stripped first).
    assert not re.search(r"\bthrow\b", _strip_js_comments(src)), (
        "action must never throw (no crash)"
    )


# ── (a) Static wiring: launch script / profile / docs / package.json ────────


def test_connect_script_is_executable_and_bash_clean() -> None:
    assert CONNECT_SCRIPT.is_file()
    assert os.access(CONNECT_SCRIPT, os.X_OK), "connect-bridge-bot.sh must be executable"
    res = subprocess.run(["bash", "-n", str(CONNECT_SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("mode", ["--help", "--verify", "--dry-run"])
def test_connect_script_static_modes_do_not_clone(mode: str, tmp_path: Path) -> None:
    res = subprocess.run(
        ["bash", str(CONNECT_SCRIPT), mode],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert res.returncode == 0, f"{mode} failed: {res.stderr}"
    assert not (tmp_path / "mindcraft").exists(), f"{mode} must not create a clone"


def test_connect_script_fails_closed_without_a_bridge_token() -> None:
    """A real run with no MINECRAFT_BRIDGE_TOKEN must refuse (decision 0010 §4)."""
    src = CONNECT_SCRIPT.read_text()
    assert "MINECRAFT_BRIDGE_TOKEN is not set" in src
    assert "no unauthenticated path" in src.lower() or "no anonymous" in src.lower()
    # The token is a secret: never printed.
    assert "bridge token: set (value hidden)" in src


def test_connect_script_stages_the_committed_assets() -> None:
    src = CONNECT_SCRIPT.read_text()
    assert "fork-src" in src, "stages from the committed fork-src tree"
    assert "src/agent/bridge/python_bridge.js" in src
    assert "src/agent/commands/bridge_ping_action.js" in src
    assert "src/agent/commands/actions.js" in src
    assert "LTAG E4-4 bridge ping action" in src, "anchored injection marker"
    assert "restore_clone_patches" in src, "restore-on-exit trap (mcdata pattern)"
    assert "trap restore_clone_patches EXIT" in src


def test_bridge_profile_is_lmstudio_local_only() -> None:
    profile = json.loads(BRIDGE_PROFILE.read_text())
    assert profile["name"] == "BridgeBot"
    assert profile["model"].startswith("lmstudio/"), "no external spend"
    assert profile["code_model"].startswith("lmstudio/")
    assert "openrouter/" not in BRIDGE_PROFILE.read_text()


def test_package_json_wires_verify_and_connect_scripts() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]
    assert (
        scripts.get("verify:bridge-node-client")
        == ".venv/bin/pytest tests/backend/test_bridge_node_client.py -v"
    )
    assert scripts.get("mc:connect-bridge") == "scripts/minecraft/connect-bridge-bot.sh"


def test_env_example_documents_bridge_vars() -> None:
    env = ENV_EXAMPLE.read_text()
    assert "MINECRAFT_BRIDGE_TOKEN" in env
    assert "MINECRAFT_BRIDGE_URL" in env
    assert "MINECRAFT_BRIDGE_ALLOW_QUERY_TOKEN" in env


def test_client_doc_records_envvars_and_the_spike() -> None:
    doc = CLIENT_DOC.read_text()
    assert "MINECRAFT_BRIDGE_TOKEN" in doc
    assert "MINECRAFT_BRIDGE_URL" in doc
    assert "MINECRAFT_BRIDGE_ALLOW_QUERY_TOKEN" in doc
    assert "!bridgePing" in doc
    assert "connect-bridge-bot.sh" in doc


def test_committed_schema_is_reference_only() -> None:
    """Sanity: the schema exists and the client never imports a validator."""
    assert SCHEMA_FILE.is_file(), "the contract schema must exist (E4-2)"
    assert "do not edit by hand" in SCHEMA_FILE.read_text()


# ── (b) Live Node↔Python round-trip ─────────────────────────────────────────


_HARNESS = r"""
import { pathToFileURL } from 'node:url';

// Any leak of an uncaught error/rejection is a CRASH (the issue's anti-case).
process.on('uncaughtException', (e) => {
    process.stdout.write(JSON.stringify({ status: 'crash', where: 'uncaught', message: String((e && e.message) || e) }) + '\n');
    process.exit(3);
});
process.on('unhandledRejection', (e) => {
    process.stdout.write(JSON.stringify({ status: 'crash', where: 'unhandledRejection', message: String((e && e.message) || e) }) + '\n');
    process.exit(3);
});

const mod = await import(pathToFileURL(process.env.BRIDGE_MODULE).href);
const { callBridge, BridgeClientError } = mod;

try {
    const response = await callBridge({
        service: process.env.BR_SERVICE,
        method: process.env.BR_METHOD,
        payload: { message: process.env.BR_MESSAGE },
        deadlineMs: Number(process.env.BR_DEADLINE_MS || '5000'),
        agentId: process.env.BR_AGENT_ID || 'test-bot',
    });
    process.stdout.write(JSON.stringify({ status: 'ok', response }) + '\n');
    process.exit(0);
} catch (err) {
    process.stdout.write(JSON.stringify({
        status: 'error',
        isBridgeClientError: err instanceof BridgeClientError,
        code: err && err.code,
        message: err && err.message,
        retryable: !!(err && err.retryable),
    }) + '\n');
    process.exit(0);
}
"""


class _ThreadedUvicorn:
    """Run the bridge router under uvicorn in a daemon thread."""

    def __init__(self, port: int) -> None:
        import uvicorn
        from fastapi import FastAPI

        from core.bridge.server import bridge_router

        app = FastAPI()
        app.include_router(bridge_router)

        class _Server(uvicorn.Server):
            def install_signal_handlers(self) -> None:  # not in main thread
                pass

        self._server = _Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> _ThreadedUvicorn:
        self._thread.start()
        deadline = time.time() + 20
        while not self._server.started and time.time() < deadline:
            time.sleep(0.05)
        if not self._server.started:
            raise RuntimeError("bridge test server did not start in time")
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def harness(tmp_path: Path) -> Path:
    path = tmp_path / "harness.mjs"
    path.write_text(_HARNESS)
    return path


def _run_client(
    harness: Path,
    *,
    url: str,
    service: str,
    method: str,
    message: str,
    token: str | None,
    deadline_ms: int = 5000,
    tmp_cwd: Path,
    bridge_module: Path = BRIDGE_CLIENT,
) -> dict:
    """Drive the committed python_bridge.js from a Node subprocess.

    By default this uses the committed module in-place. Tests that need the
    primary Authorization-header path pass a temp copy beside a tiny `ws` shim;
    tests that need the constrained-client fallback pass the in-place module,
    where no Mindcraft node_modules exist and the global WebSocket path is used.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "BRIDGE_MODULE": str(bridge_module),
        "MINECRAFT_BRIDGE_URL": url,
        "BR_SERVICE": service,
        "BR_METHOD": method,
        "BR_MESSAGE": message,
        "BR_DEADLINE_MS": str(deadline_ms),
    }
    if token is not None:
        env["MINECRAFT_BRIDGE_TOKEN"] = token
    proc = subprocess.run(
        [NODE, str(harness)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_cwd,
        timeout=30,
    )
    # The client must never crash the process: structured outcomes exit 0.
    assert proc.returncode == 0, (
        f"node exited {proc.returncode} (a crash, not a structured error)\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


@requires_node
def test_happy_path_round_trips_a_pong_over_bearer_header(
    harness: Path, tmp_path: Path
) -> None:
    port = _free_port()
    from core.bridge.server import BRIDGE_TOKEN_ENV

    os.environ[BRIDGE_TOKEN_ENV] = TOKEN
    try:
        with _ThreadedUvicorn(port):
            url = f"ws://127.0.0.1:{port}/api/minecraft/bridge/ws"
            bridge_module = copy_bridge_client_with_header_ws(tmp_path)
            result = _run_client(
                harness,
                url=url,
                service="bridge",
                method="ping",
                message="hello-bridge",
                token=TOKEN,
                tmp_cwd=tmp_path,
                bridge_module=bridge_module,
            )
    finally:
        os.environ.pop(BRIDGE_TOKEN_ENV, None)
    assert result["status"] == "ok", result
    response = result["response"]
    assert response["ok"] is True
    assert response["payload"]["pong"] == "hello-bridge"
    # request_id echo proves the client correlated the response (it rejects a
    # mismatch as a protocol error, so a success inherently confirms it).
    assert response["request_id"].startswith("bridge-")


@requires_node
@requires_global_websocket
def test_query_param_fallback_round_trips_when_explicitly_enabled(
    harness: Path, tmp_path: Path
) -> None:
    """The constrained-client ?token= path works only when the server opts in."""
    port = _free_port()
    from core.bridge.server import BRIDGE_QUERY_TOKEN_ENV, BRIDGE_TOKEN_ENV

    os.environ[BRIDGE_TOKEN_ENV] = TOKEN
    os.environ[BRIDGE_QUERY_TOKEN_ENV] = "1"
    try:
        with _ThreadedUvicorn(port):
            url = f"ws://127.0.0.1:{port}/api/minecraft/bridge/ws"
            result = _run_client(
                harness,
                url=url,
                service="bridge",
                method="ping",
                message="fallback-bridge",
                token=TOKEN,
                tmp_cwd=tmp_path,
            )
    finally:
        os.environ.pop(BRIDGE_TOKEN_ENV, None)
        os.environ.pop(BRIDGE_QUERY_TOKEN_ENV, None)
    assert result["status"] == "ok", result
    assert result["response"]["payload"]["pong"] == "fallback-bridge"


@requires_node
def test_wrong_token_is_a_structured_error_not_a_crash(harness: Path, tmp_path: Path) -> None:
    port = _free_port()
    from core.bridge.server import BRIDGE_TOKEN_ENV

    os.environ[BRIDGE_TOKEN_ENV] = TOKEN
    try:
        with _ThreadedUvicorn(port):
            url = f"ws://127.0.0.1:{port}/api/minecraft/bridge/ws"
            bridge_module = copy_bridge_client_with_header_ws(tmp_path)
            result = _run_client(
                harness,
                url=url,
                service="bridge",
                method="ping",
                message="nope",
                token="the-wrong-secret",
                tmp_cwd=tmp_path,
                bridge_module=bridge_module,
            )
    finally:
        os.environ.pop(BRIDGE_TOKEN_ENV, None)
    assert result["status"] == "error", result
    assert result["isBridgeClientError"] is True
    # Fail-closed handshake → auth-refused or a connection failure, never a crash.
    assert result["code"] in {"bridge_auth_refused", "bridge_connect_failed"}, result


@requires_node
def test_server_ok_false_passes_through_the_typed_error(harness: Path, tmp_path: Path) -> None:
    port = _free_port()
    from core.bridge.server import BRIDGE_TOKEN_ENV

    os.environ[BRIDGE_TOKEN_ENV] = TOKEN
    try:
        with _ThreadedUvicorn(port):
            url = f"ws://127.0.0.1:{port}/api/minecraft/bridge/ws"
            bridge_module = copy_bridge_client_with_header_ws(tmp_path)
            result = _run_client(
                harness,
                url=url,
                service="filesystem",  # not in the ADR §6 closed registry
                method="delete",
                message="x",
                token=TOKEN,
                tmp_cwd=tmp_path,
                bridge_module=bridge_module,
            )
    finally:
        os.environ.pop(BRIDGE_TOKEN_ENV, None)
    assert result["status"] == "error", result
    assert result["isBridgeClientError"] is True
    # The server's typed error.code is passed straight through (ADR §2/§6).
    assert result["code"] == "unsupported_service", result


@requires_node
def test_deadline_timeout_is_structured(harness: Path, tmp_path: Path) -> None:
    """A server that accepts TCP but never completes the handshake must hit the
    local deadline and surface a structured ``bridge_timeout`` — not hang."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    hung_port = listener.getsockname()[1]
    held: list[socket.socket] = []

    def _accept_and_hold() -> None:
        try:
            conn, _ = listener.accept()
            held.append(conn)  # keep it open, never reply to the WS upgrade
        except OSError:
            pass

    t = threading.Thread(target=_accept_and_hold, daemon=True)
    t.start()
    try:
        bridge_module = copy_bridge_client_with_header_ws(tmp_path)
        result = _run_client(
            harness,
            url=f"ws://127.0.0.1:{hung_port}/api/minecraft/bridge/ws",
            service="bridge",
            method="ping",
            message="slow",
            token=TOKEN,
            deadline_ms=800,
            tmp_cwd=tmp_path,
            bridge_module=bridge_module,
        )
    finally:
        for c in held:
            c.close()
        listener.close()
        t.join(timeout=5)
    assert result["status"] == "error", result
    assert result["isBridgeClientError"] is True
    assert result["code"] == "bridge_timeout", result


@requires_node
def test_missing_token_fails_closed_before_connecting(harness: Path, tmp_path: Path) -> None:
    """No MINECRAFT_BRIDGE_TOKEN → typed error, no socket opened (ADR §4)."""
    result = _run_client(
        harness,
        url="ws://127.0.0.1:1/api/minecraft/bridge/ws",  # never dialed
        service="bridge",
        method="ping",
        message="hi",
        token=None,
        tmp_cwd=tmp_path,
    )
    assert result["status"] == "error", result
    assert result["isBridgeClientError"] is True
    assert result["code"] == "bridge_no_token", result


# ── (a) Static contract of the E4-5 resilience layer (#544) ─────────────────


def test_client_declares_the_e4_5_resilience_layer() -> None:
    """The reconnect / backpressure / circuit machinery is present in the
    committed client, the E4-4 one-shot is preserved as the base call
    mechanism, and no new dependency / JSON-Schema validator / external-spend
    path crept in (the Mindcraft lockfile is frozen — it must be hand-rolled)."""
    src = BRIDGE_CLIENT.read_text()
    code = _strip_js_comments(src)

    # New typed, retryable error codes (kept alongside the E4-4 codes).
    assert "bridge_unreachable" in code, "circuit-open fail-fast code"
    assert "bridge_overloaded" in code, "bounded-in-flight backpressure code"
    for kept in ("bridge_timeout", "bridge_auth_refused", "bridge_no_token"):
        assert kept in code, f"E4-4 code {kept!r} must stay intact"

    # The four tuning env vars (defaults live in code, documented in .env.example).
    for env in (
        "MINECRAFT_BRIDGE_MAX_INFLIGHT",
        "MINECRAFT_BRIDGE_RECONNECT_BASE_MS",
        "MINECRAFT_BRIDGE_RECONNECT_MAX_MS",
        "MINECRAFT_BRIDGE_CIRCUIT_THRESHOLD",
    ):
        assert env in code, f"missing tuning env constant {env!r}"

    # The one-shot E4-4 round-trip is preserved as the base mechanism, with the
    # circuit / backoff+jitter / bounded-in-flight layer wrapped around it.
    assert "_callBridgeOnce" in code, "E4-4 one-shot preserved as the base call"
    assert re.search(r"\bcircuit\b", code), "circuit-breaker state machine"
    assert re.search(r"backoff", code), "exponential reconnect backoff"
    assert re.search(r"_jitter|Math\.random", code), "jittered reconnect"
    assert "_inflight" in code, "hand-rolled bounded in-flight counter (semaphore)"
    assert re.search(r"probe", code), "background reconnect probe"

    # Public reachability accessor so the action layer can choose to safe-idle.
    assert "export function bridgeStatus" in code
    assert "export function bridgeIsReachable" in code

    # Still reference-only schema / local-only / no new dep. The ONLY top-level
    # import stays node:crypto — backoff/jitter/semaphore are hand-rolled.
    assert "ajv" not in code.lower(), "no ajv — JSON Schema stays reference only"
    assert "jsonschema" not in code.lower(), "no jsonschema dependency"
    assert "openrouter" not in src.lower(), "local-only, no external spend"
    top_imports = re.findall(r"(?m)^import\b.*$", src)
    assert top_imports == ["import { randomUUID } from 'node:crypto';"], (
        f"no new static dependency may be added (frozen lockfile): {top_imports}"
    )


def test_ping_action_safe_idles_on_the_new_codes_and_still_never_throws() -> None:
    src = BRIDGE_ACTION.read_text()
    code = _strip_js_comments(src)
    assert "bridge_unreachable" in code and "bridge_overloaded" in code, (
        "the action must branch the catch on the E4-5 codes"
    )
    assert "safe-idling" in code, "down/saturated bridge → an explicit SAFE-IDLE line"
    assert "err.code" in code, "still branches on the structured error.code (#543)"
    # The #543 never-crash contract is unchanged: no throw in executable code.
    assert not re.search(r"\bthrow\b", code), "action must never throw (no crash)"


# ── (b) Live ACCEPTANCE: kill the server mid-run → safe-idle → auto-recover ──

_LOOP_HARNESS = r"""
import { pathToFileURL } from 'node:url';

// Any uncaught error/rejection is a CRASH (the acceptance anti-case).
process.on('uncaughtException', (e) => {
    process.stdout.write(JSON.stringify({ ev: 'crash', where: 'uncaught', message: String((e && e.message) || e) }) + '\n');
    process.exit(3);
});
process.on('unhandledRejection', (e) => {
    process.stdout.write(JSON.stringify({ ev: 'crash', where: 'unhandledRejection', message: String((e && e.message) || e) }) + '\n');
    process.exit(3);
});

const mod = await import(pathToFileURL(process.env.BRIDGE_MODULE).href);
const { callBridge, BridgeClientError } = mod;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const loopSleepMs = Number(process.env.BR_LOOP_SLEEP_MS || '250');
const deadlineMs = Number(process.env.BR_DEADLINE_MS || '700');
const maxIters = Number(process.env.BR_MAX_ITERS || '240');

const emit = (o) => process.stdout.write(JSON.stringify(o) + '\n');

// One long-lived process so the module-level circuit / reconnect state
// actually accumulates across calls. Python orchestrates the server stop/start;
// this phase machine only decides when the full arc has been observed so the
// process can self-exit 0 (a structured-error/safe-idle run is never a crash).
let phase = 'await_up';

for (let i = 1; i <= maxIters; i++) {
    let line;
    try {
        const response = await callBridge({
            service: 'bridge',
            method: 'ping',
            payload: { message: `loop-${i}` },
            deadlineMs,
            agentId: 'loop-bot',
        });
        line = { i, status: 'ok', pong: response && response.payload && response.payload.pong };
    } catch (err) {
        line = {
            i,
            status: 'error',
            isBridgeClientError: err instanceof BridgeClientError,
            code: err && err.code,
            retryable: !!(err && err.retryable),
        };
    }
    emit(line);

    if (phase === 'await_up' && line.status === 'ok') {
        phase = 'await_unreachable';
    } else if (phase === 'await_unreachable' && line.code === 'bridge_unreachable') {
        phase = 'await_recover';
    } else if (phase === 'await_recover' && line.status === 'ok') {
        emit({ ev: 'recovered', i });
        process.exit(0); // clean exit even with an unref'd probe timer pending
    }
    await sleep(loopSleepMs);
}
emit({ ev: 'incomplete', phase });
process.exit(0);
"""


def _wait_for(events, lock, predicate, *, timeout, what):
    """Poll the streamed-event list until ``predicate(snapshot)`` is true."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with lock:
            snapshot = list(events)
        if predicate(snapshot):
            return snapshot
        time.sleep(0.05)
    with lock:
        snapshot = list(events)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}; events={snapshot}")


@requires_node
def test_server_kill_safe_idles_then_auto_recovers(tmp_path: Path) -> None:
    """ACCEPTANCE (#544): killing the Python server mid-run makes the bot
    fail-fast / **safe-idle** — a *structured* ``bridge_unreachable`` (retryable,
    no in-world action, exit 0, never a crash) rather than a hang — and a fresh
    server on the same port **auto-recovers** the client within the backoff
    window, all in ONE long-lived Node process so the circuit/reconnect state
    accumulates. Small circuit/backoff env values keep it fast; skips without
    ``node`` like the other live tests."""
    from core.bridge.server import BRIDGE_TOKEN_ENV

    port = _free_port()
    url = f"ws://127.0.0.1:{port}/api/minecraft/bridge/ws"
    harness = tmp_path / "loop_harness.mjs"
    harness.write_text(_LOOP_HARNESS)
    bridge_module = copy_bridge_client_with_header_ws(tmp_path)

    env = {
        "PATH": os.environ.get("PATH", ""),
        "BRIDGE_MODULE": str(bridge_module),
        "MINECRAFT_BRIDGE_URL": url,
        "MINECRAFT_BRIDGE_TOKEN": TOKEN,
        # Small values so the policy is fast to drive (defaults are big).
        "MINECRAFT_BRIDGE_CIRCUIT_THRESHOLD": "2",
        "MINECRAFT_BRIDGE_RECONNECT_BASE_MS": "150",
        "MINECRAFT_BRIDGE_RECONNECT_MAX_MS": "600",
        "BR_DEADLINE_MS": "700",
        "BR_LOOP_SLEEP_MS": "250",
        "BR_MAX_ITERS": "240",
    }

    events: list[dict] = []
    lock = threading.Lock()

    def _reader(stream: object) -> None:
        for raw in stream:  # type: ignore[attr-defined]
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                obj = {"ev": "nonjson", "raw": raw}
            with lock:
                events.append(obj)

    os.environ[BRIDGE_TOKEN_ENV] = TOKEN
    proc: subprocess.Popen | None = None
    active = _ThreadedUvicorn(port)
    active.__enter__()
    try:
        proc = subprocess.Popen(
            [NODE, str(harness)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            cwd=tmp_path,
        )
        threading.Thread(target=_reader, args=(proc.stdout,), daemon=True).start()

        # 1. Healthy: at least one successful round-trip while the server is up.
        before = _wait_for(
            events,
            lock,
            lambda evs: any(e.get("status") == "ok" for e in evs),
            timeout=20,
            what="an initial successful call (server up)",
        )
        ok_before = max(e["i"] for e in before if e.get("status") == "ok")

        # 2. Kill the Python server mid-run.
        active.__exit__()
        active = None

        # 3. The bot must fail-fast as a STRUCTURED bridge_unreachable (the
        #    circuit opened) — safe-idle, not a hang, not a crash.
        _wait_for(
            events,
            lock,
            lambda evs: any(
                e.get("code") == "bridge_unreachable"
                and e.get("isBridgeClientError") is True
                and e.get("retryable") is True
                and e.get("i", 0) > ok_before
                for e in evs
            ),
            timeout=20,
            what="a structured bridge_unreachable after the server was killed",
        )
        with lock:
            mid = list(events)
        unreachable_at = min(
            e["i"] for e in mid if e.get("code") == "bridge_unreachable" and e["i"] > ok_before
        )
        # Never a crash, and never an unsafe success while the bridge was down.
        assert not any(e.get("ev") == "crash" for e in mid), mid
        assert not any(e.get("status") == "ok" and e.get("i", 0) >= unreachable_at for e in mid), (
            "a call succeeded while the bridge was down (unsafe action)"
        )

        # 4. Bring a FRESH server back on the SAME port.
        active = _ThreadedUvicorn(port)
        active.__enter__()

        # 5. The background probe must auto-recover the circuit → a later call
        #    succeeds again, within the backoff window.
        _wait_for(
            events,
            lock,
            lambda evs: any(
                e.get("status") == "ok" and e.get("i", 0) > unreachable_at for e in evs
            ),
            timeout=25,
            what="auto-recovery (a successful call after the server restart)",
        )

        # 6. The harness self-exits 0 once it has observed the full arc.
        try:
            rc = proc.wait(timeout=20)
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - failure path
            raise AssertionError("the bot process did not exit after recovery") from exc
        stderr = proc.stderr.read() if proc.stderr else ""
        assert rc == 0, (
            f"node exited {rc} (a crash, not a clean safe-idle/recover); stderr={stderr}"
        )
        with lock:
            final = list(events)
        assert not any(e.get("ev") == "crash" for e in final), final
        assert any(e.get("ev") == "recovered" for e in final), final
    finally:
        if active is not None:
            active.__exit__()
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        os.environ.pop(BRIDGE_TOKEN_ENV, None)


# ── (c) Live ACCEPTANCE: bounded in-flight → fail-closed backpressure ───────

_BACKPRESSURE_HARNESS = r"""
import { pathToFileURL } from 'node:url';

// Any uncaught error/rejection is a CRASH — backpressure must never crash.
process.on('uncaughtException', (e) => {
    process.stdout.write(JSON.stringify({ ev: 'crash', message: String((e && e.message) || e) }) + '\n');
    process.exit(3);
});
process.on('unhandledRejection', (e) => {
    process.stdout.write(JSON.stringify({ ev: 'crash', message: String((e && e.message) || e) }) + '\n');
    process.exit(3);
});

const mod = await import(pathToFileURL(process.env.BRIDGE_MODULE).href);
const { callBridge, BridgeClientError } = mod;

const fanout = Number(process.env.BR_FANOUT || '6');

// Fire the whole burst synchronously: every callBridge runs to its first
// `await` (past the semaphore check + increment) before any yields, so the
// in-flight cap is exercised deterministically with no sleep/race.
const settled = await Promise.allSettled(
    Array.from({ length: fanout }, (_, k) =>
        callBridge({
            service: 'bridge',
            method: 'ping',
            payload: { message: `burst-${k}` },
            deadlineMs: 5000,
            agentId: 'burst-bot',
        }),
    ),
);

const results = settled.map((s) =>
    s.status === 'fulfilled'
        ? { status: 'ok' }
        : {
              status: 'error',
              isBridgeClientError: s.reason instanceof BridgeClientError,
              code: s.reason && s.reason.code,
              retryable: !!(s.reason && s.reason.retryable),
          },
);
process.stdout.write(JSON.stringify({ ev: 'done', results }) + '\n');
process.exit(0);
"""


@requires_node
def test_bounded_in_flight_sheds_excess_as_retryable_backpressure(tmp_path: Path) -> None:
    """ACCEPTANCE (#544, scope: bounded in-flight): with a small
    ``MINECRAFT_BRIDGE_MAX_INFLIGHT`` and a synchronous burst of more
    concurrent ``callBridge`` calls than the cap, the excess reject
    *immediately* with a structured, retryable ``bridge_overloaded`` (never an
    unbounded queue, never more concurrent sockets than the cap), at most
    ``MAX_INFLIGHT`` succeed, and the process never crashes."""
    from core.bridge.server import BRIDGE_TOKEN_ENV

    port = _free_port()
    url = f"ws://127.0.0.1:{port}/api/minecraft/bridge/ws"
    harness = tmp_path / "backpressure_harness.mjs"
    harness.write_text(_BACKPRESSURE_HARNESS)
    bridge_module = copy_bridge_client_with_header_ws(tmp_path)

    max_inflight = 2
    fanout = 6
    env = {
        "PATH": os.environ.get("PATH", ""),
        "BRIDGE_MODULE": str(bridge_module),
        "MINECRAFT_BRIDGE_URL": url,
        "MINECRAFT_BRIDGE_TOKEN": TOKEN,
        "MINECRAFT_BRIDGE_MAX_INFLIGHT": str(max_inflight),
        "BR_FANOUT": str(fanout),
    }

    os.environ[BRIDGE_TOKEN_ENV] = TOKEN
    try:
        with _ThreadedUvicorn(port):
            proc = subprocess.run(
                [NODE, str(harness)],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmp_path,
                timeout=30,
            )
    finally:
        os.environ.pop(BRIDGE_TOKEN_ENV, None)

    assert proc.returncode == 0, (
        f"node exited {proc.returncode} (backpressure must never crash)\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ev"] == "done", payload
    results = payload["results"]
    assert len(results) == fanout, results

    oks = [r for r in results if r["status"] == "ok"]
    overloaded = [r for r in results if r.get("code") == "bridge_overloaded"]

    # The semaphore must bound concurrency: never more than the cap proceed.
    assert len(oks) <= max_inflight, (
        f"more calls proceeded than MAX_INFLIGHT={max_inflight}: {results}"
    )
    # The excess must shed as fail-closed backpressure, and every shed call
    # must be a structured, retryable bridge_overloaded (so callers safe-idle).
    assert len(overloaded) >= fanout - max_inflight, results
    for r in overloaded:
        assert r["isBridgeClientError"] is True, r
        assert r["retryable"] is True, r
    # No other error class, and definitely no crash.
    assert not any(e.get("ev") == "crash" for e in [payload]), payload
    assert all(r["status"] == "ok" or r.get("code") == "bridge_overloaded" for r in results), (
        f"unexpected non-overloaded failure during a healthy burst: {results}"
    )

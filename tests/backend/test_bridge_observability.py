"""Tests for bridge observability — trace ids, structured logs, metrics
(issue #546, E4-7; epic #506).

Acceptance bar: *a single request is traceable end-to-end via one trace ID in
both logs.* This module proves that on three levels, mirroring the established
in-process-server + Node-subprocess harness pattern from
``test_bridge_node_client.py``:

* **Units** — the structured-log helper emits the fixed ``key=value`` line
  (``trace_id`` first, INFO on success / WARNING on failure) and the
  in-process metrics registry counts calls/errors/latency and resets cleanly.
* **Server integration** — the real E4-3 endpoint (mounted on ``core.main:app``
  over an in-process Starlette ``TestClient`` WebSocket, lifespan never run, no
  Docker/network/LLM) echoes the caller's ``trace_id`` (or mints one when the
  additive field is absent), logs exactly one ``bridge_event`` per settled
  frame with that id, records the metrics, and threads the id into the E4-6
  inbound emit — while the fail-closed handshake rejection still logs **no**
  identity (ADR §4).
* **Live ACCEPTANCE** — boot the real ``bridge_router`` under uvicorn on an
  ephemeral port, drive the *committed* ``python_bridge.js`` from a Node
  subprocess, and assert **one** trace id appears in BOTH the Node stderr logs
  and the Python server logs for the same request — the literal acceptance
  criterion. Skips cleanly when ``node`` is unavailable.

This issue has **no LLM runtime path**: it is pure logging/metrics plumbing
with no model calls. The nearest local smoke path is exactly this
dependency-free test (``pnpm verify:bridge-observability``); the Node↔Python
round-trip uses no model so no LM Studio spend is required.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.bridge import contract as c
from core.bridge import inbound, observability
from core.bridge.server import BRIDGE_TOKEN_ENV, BRIDGE_WS_PATH
from core.event_bus import EventType, event_bus
from core.main import app

TOKEN = "test-bridge-obs-secret"  # noqa: S105 — test-only shared secret
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "backend" / "fixtures" / "bridge"
BRIDGE_CLIENT = (
    REPO_ROOT / "scripts" / "minecraft" / "fork-src" / "agent" / "bridge" / "python_bridge.js"
)

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _fixture(verb: str, name: str = "request.valid.json") -> dict[str, Any]:
    return json.loads((FIXTURES / verb / name).read_text())


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    return TOKEN


@pytest.fixture
def client() -> TestClient:
    # No `with TestClient(app)`: lifespan/bootstrap must not run (dependency-free).
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_metrics() -> Iterator[None]:
    """Every test starts and ends with a zeroed in-process registry."""
    observability.reset_metrics()
    yield
    observability.reset_metrics()


class _ListHandler(logging.Handler):
    """Collects emitted ``LogRecord``s (works across the uvicorn daemon thread —
    logging is process-global and thread-safe)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def capture_logs(*logger_names: str) -> Iterator[_ListHandler]:
    handler = _ListHandler()
    loggers = [logging.getLogger(n) for n in logger_names]
    saved = [(lg, lg.level) for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        for lg, level in saved:
            lg.removeHandler(handler)
            lg.setLevel(level)


def _bridge_event_lines(handler: _ListHandler) -> list[logging.LogRecord]:
    return [
        r for r in handler.records if r.getMessage().startswith(observability.BRIDGE_EVENT_PREFIX)
    ]


# ── Units: the structured-log helper ────────────────────────────────────────


def test_log_bridge_event_line_shape_and_extra() -> None:
    log = logging.getLogger("test.bridge.obs.unit")
    with capture_logs("test.bridge.obs.unit") as h:
        observability.log_bridge_event(
            log,
            trace_id="trace-unit-1",
            request_id="req-1",
            agent_id="vera",
            service="bridge",
            method="ping",
            ok=True,
            latency_ms=1.2345,
            direction="inbound",
        )
        observability.log_bridge_event(
            log,
            trace_id="trace-unit-2",
            request_id="req-2",
            agent_id="vera",
            service="memory",
            method="recall",
            ok=False,
            latency_ms=7.0,
            error_code=c.ERR_INVALID_PAYLOAD,
            direction="inbound",
        )

    ok_rec, fail_rec = h.records
    msg = ok_rec.getMessage()
    # trace_id is first so a single grep lines both languages up; fixed shape.
    assert msg.startswith(f"{observability.BRIDGE_EVENT_PREFIX} trace_id=trace-unit-1 ")
    assert "request_id=req-1" in msg
    assert "service=bridge method=ping" in msg
    assert "ok=true" in msg and "latency_ms=1.234" in msg
    assert "error_code=-" in msg  # None renders explicitly, never an empty token
    assert ok_rec.levelno == logging.INFO
    # Structured fields are also attached under a single non-reserved key.
    assert ok_rec.bridge["trace_id"] == "trace-unit-1"
    assert ok_rec.bridge["ok"] is True

    # A handled failure logs at WARNING and carries the typed code.
    assert fail_rec.levelno == logging.WARNING
    assert f"error_code={c.ERR_INVALID_PAYLOAD}" in fail_rec.getMessage()
    assert "ok=false" in fail_rec.getMessage()


def test_log_bridge_inbound_event_carries_trace_id() -> None:
    log = logging.getLogger("test.bridge.obs.inbound")
    with capture_logs("test.bridge.obs.inbound") as h:
        observability.log_bridge_inbound_event(
            log,
            trace_id="trace-evt-9",
            request_id="req-9",
            agent_id="rex",
            event_type=EventType.BRIDGE_PERCEPTION.value,
        )
    rec = h.records[0]
    assert rec.getMessage().startswith(
        f"{observability.BRIDGE_INBOUND_EVENT_PREFIX} trace_id=trace-evt-9 "
    )
    assert f"event_type={EventType.BRIDGE_PERCEPTION.value}" in rec.getMessage()
    assert rec.levelno == logging.INFO


def test_caller_controlled_field_cannot_break_the_line_or_forge_a_record() -> None:
    """The acceptance bar is *one trace id greps cleanly across both logs*.
    A caller-controlled field (``trace_id``/``request_id``/``agent_id``) is an
    authenticated peer's input; an embedded newline/space would split the
    single-line ``key=value`` shape and let it forge a second ``bridge_event``
    record. Such characters must be neutralised and an oversized id capped."""
    log = logging.getLogger("test.bridge.obs.inject")
    forged = "real\nbridge_event trace_id=forged ok=true latency_ms=0"
    with capture_logs("test.bridge.obs.inject") as h:
        observability.log_bridge_event(
            log,
            trace_id=forged,
            request_id="req with space",
            agent_id="x" * 5000,  # hostile/oversized → must be capped
            service="bridge",
            method="ping",
            ok=True,
            latency_ms=1.0,
        )
    rec = h.records[0]
    msg = rec.getMessage()
    tokens = msg.split(" ")
    # One physical line; the prefix appears once as a *standalone* token (a
    # forged record would need a fresh `bridge_event ` at a token boundary —
    # an inert substring inside a sanitised value does not parse as one).
    assert "\n" not in msg
    assert tokens.count(observability.BRIDGE_EVENT_PREFIX) == 1
    # The whole forged payload collapsed into the single trace_id token: no
    # whitespace survived to fake `ok=`/`latency_ms=` fields or a new record.
    trace_tok = next(t for t in tokens if t.startswith("trace_id="))
    assert trace_tok == "trace_id=real_bridge_event_trace_id=forged_ok=true_latency_ms=0"
    # The space in another value cannot be confused for the field delimiter.
    assert "request_id=req_with_space" in tokens
    # Oversized value is bounded (cap + truncation marker), not unbounded.
    agent_tok = next(t for t in tokens if t.startswith("agent_id="))
    assert len(agent_tok) <= len("agent_id=") + observability._MAX_LOG_VALUE_LEN + 1
    assert agent_tok.endswith("~")
    # A normal hyphenated id is untouched (the range op is not a literal '-').
    with capture_logs("test.bridge.obs.inject") as h2:
        observability.log_bridge_event(
            log,
            trace_id="trace-e2e-acceptance-001",
            request_id="r",
            agent_id="vera",
            service="bridge",
            method="ping",
            ok=True,
            latency_ms=1.0,
        )
    assert "trace_id=trace-e2e-acceptance-001 " in h2.records[0].getMessage()


# ── Units: the in-process metrics registry ──────────────────────────────────


def test_record_call_counts_calls_errors_and_latency() -> None:
    observability.record_call(verb="bridge.ping", ok=True, latency_ms=3.0)
    observability.record_call(verb="bridge.ping", ok=True, latency_ms=30.0)
    observability.record_call(
        verb="memory.recall", ok=False, latency_ms=1500.0, error_code="invalid_payload"
    )

    snap = observability.bridge_metrics_snapshot()
    assert snap["calls"] == {"bridge.ping": 2, "memory.recall": 1}
    assert snap["calls_total"] == 3
    assert snap["errors"] == {"invalid_payload": 1}
    assert snap["errors_total"] == 1
    lat = snap["latency_ms"]
    assert lat["count"] == 3
    assert lat["sum"] == pytest.approx(1533.0)
    assert lat["max"] == pytest.approx(1500.0)
    # 3.0 → <=5, 30.0 → <=100, 1500.0 → <=5000; buckets sum to the call count.
    assert lat["buckets"]["<=5"] == 1
    assert lat["buckets"]["<=100"] == 1
    assert lat["buckets"]["<=5000"] == 1
    assert sum(lat["buckets"].values()) == 3

    # A failure with no explicit code is bucketed under "unknown".
    observability.record_call(verb="x.y", ok=False, latency_ms=1.0)
    assert observability.bridge_metrics_snapshot()["errors"]["unknown"] == 1


def test_reset_metrics_zeroes_everything() -> None:
    observability.record_call(verb="bridge.ping", ok=True, latency_ms=1.0)
    observability.reset_metrics()
    snap = observability.bridge_metrics_snapshot()
    assert snap["calls_total"] == 0
    assert snap["errors_total"] == 0
    assert snap["latency_ms"]["count"] == 0
    assert all(v == 0 for v in snap["latency_ms"]["buckets"].values())


def test_snapshot_is_a_defensive_copy() -> None:
    observability.record_call(verb="bridge.ping", ok=True, latency_ms=1.0)
    snap = observability.bridge_metrics_snapshot()
    snap["calls"]["bridge.ping"] = 999
    snap["latency_ms"]["buckets"]["<=5"] = 999
    # Mutating the snapshot must not corrupt the live registry.
    fresh = observability.bridge_metrics_snapshot()
    assert fresh["calls"]["bridge.ping"] == 1
    assert fresh["latency_ms"]["buckets"]["<=5"] == 1


# ── Server integration: real endpoint, in-process WebSocket ─────────────────


def test_response_echoes_caller_trace_id_and_logs_it_once(
    token_env: str, client: TestClient
) -> None:
    request = _fixture("bridge.ping") | {"trace_id": "trace-caller-abc"}
    with capture_logs("core.bridge.server") as h:
        with client.websocket_connect(
            BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.send_json(request)
            response = ws.receive_json()

    # The wire response carries the caller's id back (additive field).
    assert response["ok"] is True
    assert response["trace_id"] == "trace-caller-abc"

    events = _bridge_event_lines(h)
    assert len(events) == 1, "exactly one structured log per settled frame"
    line = events[0].getMessage()
    assert "trace_id=trace-caller-abc" in line
    assert "service=bridge method=ping ok=true" in line
    assert events[0].levelno == logging.INFO

    snap = observability.bridge_metrics_snapshot()
    assert snap["calls"]["bridge.ping"] == 1
    assert snap["calls_total"] == 1
    assert snap["errors_total"] == 0


def test_server_mints_trace_id_when_request_omits_it(token_env: str, client: TestClient) -> None:
    request = _fixture("bridge.ping")
    assert "trace_id" not in request  # the additive field is absent
    with capture_logs("core.bridge.server") as h:
        with client.websocket_connect(
            BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.send_json(request)
            response = ws.receive_json()

    minted = response["trace_id"]
    assert isinstance(minted, str) and minted.startswith("trace-")
    # The minted id is what the server logged — correlation still holds even
    # for a 1.0 peer that never sends the field.
    assert f"trace_id={minted}" in _bridge_event_lines(h)[0].getMessage()


@pytest.mark.parametrize(
    ("mutate", "expected_code", "expected_verb"),
    [
        (
            {"service": "filesystem", "method": "delete"},
            c.ERR_UNSUPPORTED_SERVICE,
            "filesystem.delete",
        ),
        ({"version": "2.0"}, c.ERR_UNSUPPORTED_VERSION, "bridge.ping"),
    ],
)
def test_failed_frame_logs_warning_and_records_error(
    token_env: str,
    client: TestClient,
    mutate: dict[str, str],
    expected_code: str,
    expected_verb: str,
) -> None:
    request = _fixture("bridge.ping") | {"trace_id": "trace-fail-1"} | mutate
    with capture_logs("core.bridge.server") as h:
        with client.websocket_connect(
            BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.send_json(request)
            response = ws.receive_json()

    assert response["ok"] is False
    assert response["error"]["code"] == expected_code
    # The failed response still echoes the trace id so a failure correlates too.
    assert response["trace_id"] == "trace-fail-1"

    rec = _bridge_event_lines(h)[0]
    assert rec.levelno == logging.WARNING
    assert "trace_id=trace-fail-1" in rec.getMessage()
    assert f"error_code={expected_code}" in rec.getMessage()

    snap = observability.bridge_metrics_snapshot()
    # Every settled frame is counted exactly once (honest denominator)…
    assert snap["calls_total"] == 1
    assert snap["calls"][expected_verb] == 1
    # …and the failure is bucketed by its typed code.
    assert snap["errors"][expected_code] == 1
    assert snap["errors_total"] == 1


def test_non_json_frame_is_recorded_as_unparseable(token_env: str, client: TestClient) -> None:
    with capture_logs("core.bridge.server") as h:
        with client.websocket_connect(
            BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.send_text("this is not json {")
            response = ws.receive_json()

    assert response["ok"] is False
    assert response["error"]["code"] == c.ERR_INVALID_PAYLOAD
    # An unparseable frame still gets a minted trace id + a WARNING log…
    assert isinstance(response["trace_id"], str) and response["trace_id"].startswith("trace-")
    rec = _bridge_event_lines(h)[0]
    assert rec.levelno == logging.WARNING
    # …and is counted under the explicit 'unparseable' verb (not dropped).
    snap = observability.bridge_metrics_snapshot()
    assert snap["calls"]["unparseable"] == 1
    assert snap["errors"][c.ERR_INVALID_PAYLOAD] == 1


def test_rejected_handshake_logs_no_trace_and_dispatches_nothing(
    token_env: str, client: TestClient
) -> None:
    """ADR §4: an unauthenticated connection is closed before ``accept()`` —
    no ``bridge_event`` (no identity, no dispatch) is ever logged for it."""
    with capture_logs("core.bridge.server") as h:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(BRIDGE_WS_PATH):  # no token
                pass
    assert _bridge_event_lines(h) == []
    assert observability.bridge_metrics_snapshot()["calls_total"] == 0


# ── Server integration: the E4-6 inbound emit joins the same trace ──────────


@pytest.fixture
def captured_perception() -> Iterator[list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    async def on_perception(event: dict[str, Any]) -> None:
        seen.append(event["data"])

    event_bus.on(EventType.BRIDGE_PERCEPTION, on_perception)
    try:
        yield seen
    finally:
        event_bus.off(EventType.BRIDGE_PERCEPTION, on_perception)


def test_inbound_emit_carries_and_logs_the_frame_trace_id(
    token_env: str, client: TestClient, captured_perception: list[dict[str, Any]]
) -> None:
    request = _fixture("perception.report") | {"trace_id": "trace-inbound-7"}
    with capture_logs("core.bridge.server", "core.bridge.inbound") as h:
        with client.websocket_connect(
            BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            ws.send_json(request)
            assert ws.receive_json()["ok"] is True

    # The bus event carries the SAME id the server resolved for the frame…
    assert len(captured_perception) == 1
    assert captured_perception[0]["trace_id"] == "trace-inbound-7"

    # …the server logged the frame with it, and the inbound emit logged it too,
    # so a report is followable from the send through the Python bus by one id.
    server_lines = [
        r for r in h.records if r.getMessage().startswith(observability.BRIDGE_EVENT_PREFIX)
    ]
    inbound_lines = [
        r for r in h.records if r.getMessage().startswith(observability.BRIDGE_INBOUND_EVENT_PREFIX)
    ]
    assert any("trace_id=trace-inbound-7" in r.getMessage() for r in server_lines)
    assert len(inbound_lines) == 1
    assert "trace_id=trace-inbound-7" in inbound_lines[0].getMessage()
    assert EventType.BRIDGE_PERCEPTION.value in inbound_lines[0].getMessage()


async def test_dispatch_inbound_prefers_passed_trace_over_envelope() -> None:
    """The server passes the trace id it resolved for the frame; it must win
    over the envelope's own ``trace_id`` so the bus event, the server log and
    the wire response all share exactly one id. Absent a passed id, the
    handler falls back to the envelope's, and finally mints one — the emitted
    attribution is therefore always a complete ``dict[str, str]``."""
    seen: list[dict[str, Any]] = []

    async def on_action(event: dict[str, Any]) -> None:
        seen.append(event["data"])

    event_bus.on(EventType.BRIDGE_ACTION_RESULT, on_action)
    try:
        env = c.BridgeRequest.model_validate(_fixture("action.result") | {"trace_id": "trace-env"})
        # Passed id wins over the envelope's own.
        await inbound.dispatch_inbound(env, trace_id="trace-frame")
        # No passed id → fall back to the envelope's trace_id.
        await inbound.dispatch_inbound(env)
        # Neither present → a non-empty id is minted (never None).
        env_no_trace = c.BridgeRequest.model_validate(_fixture("action.result"))
        assert env_no_trace.trace_id is None
        await inbound.dispatch_inbound(env_no_trace)
    finally:
        event_bus.off(EventType.BRIDGE_ACTION_RESULT, on_action)

    assert [d["trace_id"] for d in seen[:2]] == ["trace-frame", "trace-env"]
    minted = seen[2]["trace_id"]
    assert isinstance(minted, str) and minted.startswith("trace-")


# ── Live ACCEPTANCE: one trace id in BOTH the Node and Python logs ──────────


class _ThreadedUvicorn:
    """Run the bridge router under uvicorn in a daemon thread (same pattern as
    test_bridge_node_client.py — a minimal app so the heavy core.main lifespan
    never runs; this stays the dependency-free local smoke path)."""

    def __init__(self, port: int) -> None:
        import uvicorn
        from fastapi import FastAPI

        from core.bridge.server import bridge_router

        app_ = FastAPI()
        app_.include_router(bridge_router)

        class _Server(uvicorn.Server):
            def install_signal_handlers(self) -> None:  # not in main thread
                pass

        self._server = _Server(
            uvicorn.Config(app_, host="127.0.0.1", port=port, log_level="warning")
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


# Drives the committed python_bridge.js. The client logs to STDERR; STDOUT is
# kept clean for one JSON result line (it must never be polluted by logs).
_HARNESS = r"""
import { pathToFileURL } from 'node:url';

process.on('uncaughtException', (e) => {
    process.stdout.write(JSON.stringify({ status: 'crash', message: String((e && e.message) || e) }) + '\n');
    process.exit(3);
});
process.on('unhandledRejection', (e) => {
    process.stdout.write(JSON.stringify({ status: 'crash', message: String((e && e.message) || e) }) + '\n');
    process.exit(3);
});

const mod = await import(pathToFileURL(process.env.BRIDGE_MODULE).href);
const { callBridge, bridgeMetrics, BridgeClientError } = mod;

try {
    const response = await callBridge({
        service: process.env.BR_SERVICE,
        method: process.env.BR_METHOD,
        payload: { message: process.env.BR_MESSAGE },
        deadlineMs: Number(process.env.BR_DEADLINE_MS || '5000'),
        traceId: process.env.BR_TRACE_ID || undefined,
        agentId: 'obs-bot',
    });
    process.stdout.write(JSON.stringify({ status: 'ok', response, metrics: bridgeMetrics() }) + '\n');
    process.exit(0);
} catch (err) {
    process.stdout.write(JSON.stringify({
        status: 'error',
        isBridgeClientError: err instanceof BridgeClientError,
        code: err && err.code,
        metrics: bridgeMetrics(),
    }) + '\n');
    process.exit(0);
}
"""


def _run_node(
    harness: Path, *, url: str, trace_id: str, service: str, method: str, tmp_cwd: Path
) -> tuple[dict, str]:
    """Returns (parsed stdout JSON, raw stderr) — stderr carries the client's
    structured `bridge_event` logs."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "BRIDGE_MODULE": str(BRIDGE_CLIENT),
        "MINECRAFT_BRIDGE_URL": url,
        "MINECRAFT_BRIDGE_TOKEN": TOKEN,
        "BR_SERVICE": service,
        "BR_METHOD": method,
        "BR_MESSAGE": "trace-correlation",
        "BR_DEADLINE_MS": "5000",
        "BR_TRACE_ID": trace_id,
    }
    proc = subprocess.run(
        [NODE, str(harness)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_cwd,  # empty dir → global WebSocket + ?token= (the CI path)
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode} (a crash, not a structured result)\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1]), proc.stderr


@requires_node
def test_one_trace_id_correlates_node_and_python_logs(tmp_path: Path) -> None:
    """ACCEPTANCE (#546): a single request is traceable end-to-end via ONE
    trace id present in BOTH logs — the Node client's stderr and the Python
    server's logs — driving the real endpoint with the committed client."""
    trace_id = "trace-e2e-acceptance-001"
    port = _free_port()
    url = f"ws://127.0.0.1:{port}/api/minecraft/bridge/ws"
    harness = tmp_path / "obs_harness.mjs"
    harness.write_text(_HARNESS)

    os.environ[BRIDGE_TOKEN_ENV] = TOKEN
    try:
        with _ThreadedUvicorn(port):
            # Attach the capture AFTER uvicorn applied its logging config so
            # the handler is not affected by it.
            with capture_logs("core.bridge.server") as srv_logs:
                result, node_stderr = _run_node(
                    harness,
                    url=url,
                    trace_id=trace_id,
                    service="bridge",
                    method="ping",
                    tmp_cwd=tmp_path,
                )
                # Give the server thread a beat to flush its log record.
                deadline = time.time() + 5
                while time.time() < deadline and not any(
                    trace_id in r.getMessage() for r in srv_logs.records
                ):
                    time.sleep(0.05)
                python_msgs = [r.getMessage() for r in srv_logs.records]
    finally:
        os.environ.pop(BRIDGE_TOKEN_ENV, None)

    # 1. The round-trip succeeded and the response echoed OUR trace id.
    assert result["status"] == "ok", result
    assert result["response"]["ok"] is True
    assert result["response"]["trace_id"] == trace_id

    # 2. The Node client logged it to STDERR (start + settle), never STDOUT.
    node_event_lines = [
        ln for ln in node_stderr.splitlines() if ln.startswith(observability.BRIDGE_EVENT_PREFIX)
    ]
    assert len(node_event_lines) >= 2, node_stderr
    assert all(f"trace_id={trace_id}" in ln for ln in node_event_lines), node_stderr
    assert any("phase=start" in ln for ln in node_event_lines), node_stderr
    settle = [ln for ln in node_event_lines if "phase=settle" in ln]
    assert settle and "ok=true" in settle[0] and "outcome=ok" in settle[0], node_stderr
    assert "echoed_trace_id=" + trace_id in settle[0], node_stderr

    # 3. The Python server logged the SAME id for the same request — the
    #    acceptance bar: one trace id, both logs.
    py_event_lines = [m for m in python_msgs if m.startswith(observability.BRIDGE_EVENT_PREFIX)]
    assert any(f"trace_id={trace_id}" in m for m in py_event_lines), python_msgs

    # 4. The Node client's in-process metrics counted the call exactly once.
    metrics = result["metrics"]
    assert metrics["callsTotal"] == 1
    assert metrics["calls"]["bridge.ping"] == 1
    assert metrics["errorsTotal"] == 0
    assert metrics["latencyMs"]["count"] == 1


@requires_node
def test_trace_id_correlates_an_error_path_too(tmp_path: Path) -> None:
    """A failed call (server ``ok:false`` → typed error passed through) is
    correlated on BOTH sides by the same id, and both sides count the error."""
    trace_id = "trace-e2e-error-002"
    port = _free_port()
    url = f"ws://127.0.0.1:{port}/api/minecraft/bridge/ws"
    harness = tmp_path / "obs_harness.mjs"
    harness.write_text(_HARNESS)

    os.environ[BRIDGE_TOKEN_ENV] = TOKEN
    observability.reset_metrics()
    try:
        with _ThreadedUvicorn(port):
            with capture_logs("core.bridge.server") as srv_logs:
                result, node_stderr = _run_node(
                    harness,
                    url=url,
                    trace_id=trace_id,
                    service="filesystem",  # not in the ADR §6 closed registry
                    method="delete",
                    tmp_cwd=tmp_path,
                )
                deadline = time.time() + 5
                while time.time() < deadline and not any(
                    trace_id in r.getMessage() for r in srv_logs.records
                ):
                    time.sleep(0.05)
                py_snapshot = observability.bridge_metrics_snapshot()
                python_msgs = [r.getMessage() for r in srv_logs.records]
    finally:
        os.environ.pop(BRIDGE_TOKEN_ENV, None)

    assert result["status"] == "error", result
    assert result["code"] == c.ERR_UNSUPPORTED_SERVICE, result

    # Node stderr settle line carries our id + the typed outcome code.
    settle = [
        ln
        for ln in node_stderr.splitlines()
        if ln.startswith(observability.BRIDGE_EVENT_PREFIX) and "phase=settle" in ln
    ]
    assert settle, node_stderr
    assert f"trace_id={trace_id}" in settle[0] and "ok=false" in settle[0]
    assert f"outcome={c.ERR_UNSUPPORTED_SERVICE}" in settle[0], node_stderr

    # Python side logged the same id at WARNING and counted the typed error.
    assert any(
        m.startswith(observability.BRIDGE_EVENT_PREFIX)
        and f"trace_id={trace_id}" in m
        and f"error_code={c.ERR_UNSUPPORTED_SERVICE}" in m
        for m in python_msgs
    ), python_msgs
    assert py_snapshot["errors"][c.ERR_UNSUPPORTED_SERVICE] == 1
    assert py_snapshot["calls"]["filesystem.delete"] == 1

    # Node in-process metrics also recorded the error by its passed-through code.
    assert result["metrics"]["errors"][c.ERR_UNSUPPORTED_SERVICE] == 1
    assert result["metrics"]["errorsTotal"] == 1

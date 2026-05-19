"""Reusable bridge harnesses for Minecraft bridge integration tests.

The E4 bridge sits between Node/Mindcraft and Python/FastAPI. Future epics need
to test both sides without a Minecraft server, so this module provides two
small fakes:

* :class:`FakeNodeBridgeClient` is a Python-side fake Node client. It opens the
  real FastAPI bridge WebSocket through an in-process TestClient and sends
  contract-valid envelopes.
* :class:`FakePythonBridgeServer` is a Node-side fake Python server. It starts
  the real bridge router on an ephemeral local port so a Node subprocess can
  exercise the committed bridge client.

No Docker, database, Redis, LLM, or Minecraft process is required.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from starlette.testclient import TestClient

from core.bridge import contract as c
from core.bridge.server import BRIDGE_TOKEN_ENV, BRIDGE_WS_PATH, bridge_router

DEFAULT_TOKEN = "test-bridge-harness-secret"  # noqa: S105 - test harness only
DEFAULT_AGENT_ID = "fake-node"
DEFAULT_RUN_ID = "run-harness"
DEFAULT_SIMULATION_ID = "00000000-0000-0000-0000-000000000000"

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_CLIENT = (
    REPO_ROOT / "scripts" / "minecraft" / "fork-src" / "agent" / "bridge" / "python_bridge.js"
)


def make_bridge_request(
    *,
    service: str = "bridge",
    method: str = "ping",
    payload: dict[str, Any] | None = None,
    agent_id: str = DEFAULT_AGENT_ID,
    run_id: str = DEFAULT_RUN_ID,
    simulation_id: str = DEFAULT_SIMULATION_ID,
    deadline_ms: int = 5000,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Build a contract-valid BridgeRequest dictionary for tests."""

    request = c.BridgeRequest(
        version=c.PROTOCOL_VERSION,
        request_id=request_id or f"harness-{uuid4()}",
        agent_id=agent_id,
        run_id=run_id,
        simulation_id=simulation_id,
        service=service,
        method=method,
        payload=payload or {"message": "hello"},
        deadline_ms=deadline_ms,
        cost_context=c.CostContext(
            agent_tier="conversation",
            budget_bucket="bridge-harness",
            estimated_cost_usd=0.0,
        ),
        trace_id=trace_id or f"trace-{uuid4()}",
    )
    return request.model_dump()


class FakeNodeBridgeClient:
    """Python-side fake for a Node bridge client.

    It uses the real bridge WebSocket endpoint and bearer auth, but it stays
    in-process through Starlette TestClient so future tests can drive bridge
    calls without booting uvicorn or Minecraft.
    """

    def __init__(self, *, token: str = DEFAULT_TOKEN) -> None:
        self.token = token
        self._previous_token: str | None = None
        self._client: TestClient | None = None

    def __enter__(self) -> FakeNodeBridgeClient:
        self._previous_token = os.environ.get(BRIDGE_TOKEN_ENV)
        os.environ[BRIDGE_TOKEN_ENV] = self.token
        app = FastAPI()
        app.include_router(bridge_router)
        self._client = TestClient(app)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._previous_token is None:
            os.environ.pop(BRIDGE_TOKEN_ENV, None)
        else:
            os.environ[BRIDGE_TOKEN_ENV] = self._previous_token

    @property
    def client(self) -> TestClient:
        if self._client is None:
            raise RuntimeError("FakeNodeBridgeClient must be used as a context manager")
        return self._client

    def call(
        self,
        *,
        service: str = "bridge",
        method: str = "ping",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one valid bridge envelope and return the raw JSON response."""

        request = make_bridge_request(service=service, method=method, payload=payload)
        return self.call_raw(request)

    def call_raw(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Send one raw JSON frame over an authenticated fake Node socket."""

        with self.client.websocket_connect(
            BRIDGE_WS_PATH,
            headers={"Authorization": f"Bearer {self.token}"},
        ) as ws:
            ws.send_json(frame)
            return ws.receive_json()


def free_local_port() -> int:
    """Return an available localhost TCP port."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class FakePythonBridgeServer:
    """Node-side fake for the Python bridge server.

    Starts a minimal FastAPI app with only the bridge router mounted. The URL
    and token can be fed directly into a Node subprocess.
    """

    def __init__(self, *, token: str = DEFAULT_TOKEN, port: int | None = None) -> None:
        self.token = token
        self.port = port or free_local_port()
        self.url = f"ws://127.0.0.1:{self.port}{BRIDGE_WS_PATH}"
        self._previous_token: str | None = None
        self._server: Any = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> FakePythonBridgeServer:
        import uvicorn

        self._previous_token = os.environ.get(BRIDGE_TOKEN_ENV)
        os.environ[BRIDGE_TOKEN_ENV] = self.token

        app = FastAPI()
        app.include_router(bridge_router)

        class _Server(uvicorn.Server):
            def install_signal_handlers(self) -> None:
                pass

        self._server = _Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        deadline = time.time() + 20
        while not self._server.started and time.time() < deadline:
            time.sleep(0.05)
        if not self._server.started:
            raise RuntimeError("fake Python bridge server did not start in time")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
        if self._previous_token is None:
            os.environ.pop(BRIDGE_TOKEN_ENV, None)
        else:
            os.environ[BRIDGE_TOKEN_ENV] = self._previous_token

    def node_env(self) -> dict[str, str]:
        """Environment values a Node bridge client needs to reach this fake."""

        return {
            "MINECRAFT_BRIDGE_URL": self.url,
            "MINECRAFT_BRIDGE_TOKEN": self.token,
        }


_HEADER_WS_MODULE = r"""
const { EventEmitter } = require('node:events');
const http = require('node:http');
const crypto = require('node:crypto');

function encodeClientTextFrame(text) {
    const payload = Buffer.from(text);
    let header;
    if (payload.length < 126) {
        header = Buffer.alloc(2);
        header[1] = 0x80 | payload.length;
    } else if (payload.length < 65536) {
        header = Buffer.alloc(4);
        header[1] = 0x80 | 126;
        header.writeUInt16BE(payload.length, 2);
    } else {
        throw new Error('test WebSocket payload too large');
    }
    header[0] = 0x81;
    const mask = crypto.randomBytes(4);
    const masked = Buffer.alloc(payload.length);
    for (let i = 0; i < payload.length; i += 1) {
        masked[i] = payload[i] ^ mask[i % 4];
    }
    return Buffer.concat([header, mask, masked]);
}

class WebSocket extends EventEmitter {
    constructor(rawUrl, options = {}) {
        super();
        this.url = rawUrl;
        this.readyState = 0;
        this._socket = null;
        this._buffer = Buffer.alloc(0);

        const url = new URL(rawUrl);
        const key = crypto.randomBytes(16).toString('base64');
        this._request = http.request({
            method: 'GET',
            protocol: 'http:',
            hostname: url.hostname,
            port: url.port || '80',
            path: `${url.pathname}${url.search}`,
            headers: {
                Host: url.host,
                Upgrade: 'websocket',
                Connection: 'Upgrade',
                'Sec-WebSocket-Key': key,
                'Sec-WebSocket-Version': '13',
                ...(options.headers || {}),
            },
        });

        this._request.on('upgrade', (res, socket, head) => {
            this.readyState = 1;
            this._socket = socket;
            socket.on('data', (chunk) => this._handleData(chunk));
            socket.on('close', () => this.emit('close', 1006, ''));
            socket.on('error', (err) => this.emit('error', err));
            this.emit('open');
            if (head && head.length > 0) this._handleData(head);
        });
        this._request.on('response', (res) => {
            this.emit('unexpected-response', this._request, res);
            res.resume();
        });
        this._request.on('error', (err) => this.emit('error', err));
        this._request.end();
    }

    send(text) {
        if (!this._socket) throw new Error('test WebSocket is not open');
        this._socket.write(encodeClientTextFrame(String(text)));
    }

    close() {
        if (this._socket) {
            this._socket.end();
            this._socket = null;
        } else if (this._request) {
            this._request.destroy();
        }
    }

    _handleData(chunk) {
        this._buffer = Buffer.concat([this._buffer, chunk]);
        while (this._buffer.length >= 2) {
            const b0 = this._buffer[0];
            const b1 = this._buffer[1];
            const opcode = b0 & 0x0f;
            let length = b1 & 0x7f;
            let offset = 2;
            if (length === 126) {
                if (this._buffer.length < 4) return;
                length = this._buffer.readUInt16BE(2);
                offset = 4;
            } else if (length === 127) {
                throw new Error('test WebSocket does not support 64-bit frames');
            }
            if (this._buffer.length < offset + length) return;
            const payload = this._buffer.subarray(offset, offset + length);
            this._buffer = this._buffer.subarray(offset + length);
            if (opcode === 1) {
                this.emit('message', payload.toString('utf8'));
            } else if (opcode === 8) {
                this.emit('close', 1000, '');
                this.close();
                return;
            }
        }
    }
}

exports.WebSocket = WebSocket;
"""


def copy_bridge_client_with_header_ws(tmp_path: Path, source: Path = BRIDGE_CLIENT) -> Path:
    """Copy the committed Node client beside a tiny header-capable `ws` shim.

    The real Mindcraft clone has `ws`, but this repo's CI path does not. The
    shim lets tests exercise the client's primary Authorization-header path
    without installing dependencies or booting Minecraft.
    """

    root = tmp_path / "node-bridge-client"
    root.mkdir()
    target = root / "python_bridge.js"
    shutil.copy2(source, target)

    ws_dir = root / "node_modules" / "ws"
    ws_dir.mkdir(parents=True)
    (ws_dir / "package.json").write_text(json.dumps({"main": "index.js"}))
    (ws_dir / "index.js").write_text(_HEADER_WS_MODULE)
    return target


_NODE_CALL_HARNESS = r"""
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
const { callBridge, BridgeClientError } = mod;

try {
    const response = await callBridge({
        service: process.env.BR_SERVICE || 'bridge',
        method: process.env.BR_METHOD || 'ping',
        payload: { message: process.env.BR_MESSAGE || 'hello' },
        deadlineMs: Number(process.env.BR_DEADLINE_MS || '5000'),
        agentId: process.env.BR_AGENT_ID || 'fake-node',
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


def run_node_bridge_call(
    tmp_path: Path,
    *,
    bridge_module: Path,
    env: dict[str, str],
    service: str = "bridge",
    method: str = "ping",
    message: str = "hello",
    deadline_ms: int = 5000,
) -> dict[str, Any]:
    """Run the committed Node bridge client once and return its JSON result."""

    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not available")

    harness = tmp_path / "node_call_harness.mjs"
    harness.write_text(_NODE_CALL_HARNESS)
    proc_env = {
        "PATH": os.environ.get("PATH", ""),
        "BRIDGE_MODULE": str(bridge_module),
        "BR_SERVICE": service,
        "BR_METHOD": method,
        "BR_MESSAGE": message,
        "BR_DEADLINE_MS": str(deadline_ms),
        **env,
    }
    proc = subprocess.run(
        [node, str(harness)],
        capture_output=True,
        text=True,
        env=proc_env,
        cwd=tmp_path,
        timeout=30,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}; stdout={proc.stdout}; stderr={proc.stderr}"
        )
    return json.loads(proc.stdout.strip().splitlines()[-1])

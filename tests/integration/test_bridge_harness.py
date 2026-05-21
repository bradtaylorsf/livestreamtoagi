"""Example tests for the reusable E4 bridge harness."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.integration.bridge_harness import (
    FakeNodeBridgeClient,
    FakePythonBridgeServer,
    copy_bridge_client_with_header_ws,
    run_node_bridge_call,
)

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


def test_fake_node_client_round_trips_without_uvicorn_or_minecraft() -> None:
    """Python tests can fake the Node side and drive the real bridge endpoint."""

    with FakeNodeBridgeClient() as client:
        response = client.call(payload={"message": "from-python-fake-node"})

    assert response["ok"] is True
    assert response["payload"] == {"pong": "from-python-fake-node"}
    assert response["trace_id"].startswith("trace-")


@requires_node
def test_fake_python_server_accepts_the_committed_node_client(tmp_path: Path) -> None:
    """Node tests can fake the Python side without a Minecraft server."""

    bridge_module = copy_bridge_client_with_header_ws(tmp_path)
    with FakePythonBridgeServer() as server:
        result = run_node_bridge_call(
            tmp_path,
            bridge_module=bridge_module,
            env=server.node_env(),
            message="from-node-client",
        )

    assert result["status"] == "ok", result
    assert result["response"]["payload"] == {"pong": "from-node-client"}


_KILL_WATCH_HARNESS = r"""
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
const {
    BridgeClientError,
    bridgeIsKillActive,
    callBridge,
    startKillSwitchWatch,
    stopKillSwitchWatch,
} = mod;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pollMs = Number(process.env.MINECRAFT_BRIDGE_KILL_POLL_MS || '100');
const started = Date.now();

startKillSwitchWatch();
while (!bridgeIsKillActive() && Date.now() - started <= pollMs * 2) {
    await sleep(10);
}

let line;
let code = null;
try {
    await callBridge({
        service: 'action',
        method: 'result',
        payload: {
            action_id: 'kill-window-action',
            status: 'success',
            detail: 'should be locally gated',
        },
        deadlineMs: 1000,
        agentId: 'kill-window-node',
    });
    line = 'action unexpectedly proceeded';
} catch (err) {
    code = err && err.code;
    line = err instanceof BridgeClientError && code === 'kill_switch_active'
        ? `safe-idling [${code}]`
        : `unexpected error [${code || 'unknown'}]`;
}
stopKillSwitchWatch();
process.stdout.write(JSON.stringify({
    status: 'done',
    killActive: bridgeIsKillActive(),
    elapsedMs: Date.now() - started,
    code,
    line,
}) + '\n');
"""


@requires_node
def test_kill_switch_halts_node_bot_within_window(tmp_path: Path) -> None:
    """Activating kill makes the Node-side cache safe-idle action verbs."""

    poll_ms = 500
    bridge_module = copy_bridge_client_with_header_ws(tmp_path)
    action_payload = {
        "action_id": "pre-kill-action",
        "status": "success",
        "detail": "before kill",
    }

    with FakePythonBridgeServer(kill_switch_active=False) as server:
        before = run_node_bridge_call(
            tmp_path,
            bridge_module=bridge_module,
            env=server.node_env(),
            service="action",
            method="result",
            payload=action_payload,
        )
        assert before["status"] == "ok", before
        assert before["response"]["payload"] == {"accepted": True}

        server.activate_kill_switch(ttl_seconds=60)
        harness = tmp_path / "kill_watch_harness.mjs"
        harness.write_text(_KILL_WATCH_HARNESS)
        proc_env = {
            "PATH": os.environ.get("PATH", ""),
            "BRIDGE_MODULE": str(bridge_module),
            "MINECRAFT_BRIDGE_KILL_POLL_MS": str(poll_ms),
            **server.node_env(),
        }
        proc = subprocess.run(
            [shutil.which("node"), str(harness)],
            capture_output=True,
            text=True,
            env=proc_env,
            cwd=tmp_path,
            timeout=30,
        )

    assert proc.returncode == 0, (
        f"node exited {proc.returncode}; stdout={proc.stdout}; stderr={proc.stderr}"
    )
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["status"] == "done", result
    assert result["killActive"] is True, result
    assert result["code"] == "kill_switch_active", result
    assert result["line"] == "safe-idling [kill_switch_active]", result
    assert result["elapsedMs"] <= poll_ms * 2, result

"""Tests for E6-5 bridge-routed code execution (#560).

No live Minecraft server is required. Python-side tests drive the real bridge
dispatch with fake initialized services and a mocked Docker client; Node-side
tests exercise the committed Mindcraft action source with a stub bridge module.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bridge import contract as c
from core.bridge.server import (
    CODE_EXECUTE_VERBS,
    ERR_CODE_SERVICE_UNAVAILABLE,
    build_bridge_response,
    build_bridge_response_with_services,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
EXECUTE_CODE_ACTION = FORK_SRC / "agent" / "commands" / "execute_code_action.js"
CONNECT_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


@dataclass
class FakeServices:
    event_bus: AsyncMock
    docker_client: MagicMock | None = None


def _code_request(agent_id: str = "rex") -> dict[str, Any]:
    return c.BridgeRequest(
        version=c.PROTOCOL_VERSION,
        request_id=f"req-code-{agent_id}",
        agent_id=agent_id,
        run_id="run-code-test",
        simulation_id="00000000-0000-0000-0000-000000000560",
        service="code",
        method="execute",
        payload={"language": "python", "code": "print(2 + 2)", "timeout": 5},
        deadline_ms=10000,
        cost_context=c.CostContext(
            agent_tier="building",
            budget_bucket="bridge-code-test",
            estimated_cost_usd=0.0,
        ),
    ).model_dump()


def _docker_client(stdout: bytes = b"4\n", stderr: bytes = b"") -> MagicMock:
    client = MagicMock()
    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.side_effect = [stdout, stderr]
    client.containers.create.return_value = container
    return client


async def test_allowed_agent_runs_code_via_bridge_and_returns_sandbox_result() -> None:
    docker_client = _docker_client()
    services = FakeServices(event_bus=AsyncMock(), docker_client=docker_client)

    response = await build_bridge_response_with_services(_code_request("rex"), services)

    assert response.ok is True
    assert response.payload is not None
    assert response.payload["status"] == "ok"
    assert response.payload["stdout"] == "4\n"
    assert response.payload["exit_code"] == 0
    docker_client.containers.create.assert_called_once()
    container = docker_client.containers.create.return_value
    container.wait.assert_called_once_with(timeout=5)
    c.validate_response(response, service="code", method="execute")


async def test_non_allowed_agent_gets_tool_rejection_not_bridge_error() -> None:
    docker_client = _docker_client()
    services = FakeServices(event_bus=AsyncMock(), docker_client=docker_client)

    response = await build_bridge_response_with_services(_code_request("aurora"), services)

    assert response.ok is True
    assert response.error is None
    assert response.payload is not None
    assert response.payload["status"] == "rejected"
    assert "not authorized" in response.payload["reason"]
    docker_client.containers.create.assert_not_called()
    c.validate_response(response, service="code", method="execute")


def test_pure_bridge_response_reports_code_service_unavailable() -> None:
    response = build_bridge_response(_code_request("rex"))

    assert response.ok is False
    assert response.payload is None
    assert response.error is not None
    assert response.error.code == ERR_CODE_SERVICE_UNAVAILABLE
    assert response.retryable is True
    c.validate_response(response, service="code", method="execute")


async def test_missing_event_bus_reports_code_service_unavailable() -> None:
    services = type("Services", (), {"event_bus": None, "docker_client": _docker_client()})()

    response = await build_bridge_response_with_services(_code_request("rex"), services)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == ERR_CODE_SERVICE_UNAVAILABLE
    assert response.retryable is True


async def test_unreachable_docker_daemon_degrades_to_error_payload_not_a_crash() -> None:
    """Regression: ``ExecuteCodeTool`` acquires its Docker client outside its
    own try/except, so an unreachable daemon raises. The bridge dispatch path
    and shared WebSocket loop only catch ``WebSocketDisconnect``; an uncaught
    exception here would kill the connection for every verb. The handler must
    fail-closed to a contract-valid error payload instead.
    """
    import unittest.mock

    services = FakeServices(event_bus=AsyncMock(), docker_client=None)

    with unittest.mock.patch(
        "tools.code_execution.ExecuteCodeTool._get_docker",
        side_effect=RuntimeError("Error while fetching server API version"),
    ):
        response = await build_bridge_response_with_services(_code_request("rex"), services)

    assert response.ok is True
    assert response.payload is not None
    assert response.payload["status"] == "error"
    assert "sandbox unavailable" in response.payload["reason"]
    c.validate_response(response, service="code", method="execute")


def test_code_execute_is_a_real_service_not_a_stub() -> None:
    assert frozenset({"code.execute"}) == CODE_EXECUTE_VERBS
    assert EXECUTE_CODE_ACTION.is_file()
    src = EXECUTE_CODE_ACTION.read_text()
    assert "'!executeCode'" in src
    assert "service: 'code'" in src and "method: 'execute'" in src
    assert "safe-idling" in src
    assert "openrouter" not in src.lower()


def test_connect_script_stages_and_injects_execute_code_action() -> None:
    src = CONNECT_SCRIPT.read_text()
    for token in (
        "EXECUTE_CODE_ACTION_REL",
        "LTAG E6-5 execute-code action",
        "executeCodeAction",
        "!executeCode",
    ):
        assert token in src


def test_package_json_wires_embodiment_code_execution_verifier() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]

    assert (
        scripts.get("verify:embodiment-code-execution")
        == ".venv/bin/pytest tests/backend/test_embodiment_code_execution.py -v"
    )


def _run_node_harness(tmp_path: Path, source: str, env: dict[str, str] | None = None) -> dict:
    harness = tmp_path / "code_harness.mjs"
    harness.write_text(source)
    proc = subprocess.run(
        [NODE, str(harness)],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), **(env or {})},
        cwd=tmp_path,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _stage_action_with_stub_bridge(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fork-src"
    commands = root / "agent" / "commands"
    bridge = root / "agent" / "bridge"
    commands.mkdir(parents=True)
    bridge.mkdir(parents=True)
    shutil.copy2(EXECUTE_CODE_ACTION, commands / "execute_code_action.js")
    calls_path = tmp_path / "bridge_calls.jsonl"
    (bridge / "python_bridge.js").write_text(
        """
import { appendFileSync } from 'node:fs';

export class BridgeClientError extends Error {
    constructor(code, message) {
        super(message);
        this.name = 'BridgeClientError';
        this.code = code;
    }
}

export async function callBridge(opts = {}) {
    appendFileSync(process.env.BRIDGE_CALLS_PATH, JSON.stringify(opts) + '\\n');
    if (process.env.BRIDGE_THROW_CODE) {
        throw new BridgeClientError(process.env.BRIDGE_THROW_CODE, 'stub outage');
    }
    return {
        request_id: 'stub-request',
        ok: true,
        payload: {
            status: 'ok',
            stdout: '4\\n',
            stderr: '',
            exit_code: 0,
            execution_time_ms: 1,
        },
        retryable: false,
        trace_id: opts.traceId || 'trace-stub',
    };
}
""".lstrip()
    )
    return commands / "execute_code_action.js", calls_path


@requires_node
def test_execute_code_action_calls_bridge_code_execute(tmp_path: Path) -> None:
    action_path, calls_path = _stage_action_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

process.on('uncaughtException', (e) => {{
    process.stdout.write(JSON.stringify({{ status: 'crash', message: String((e && e.message) || e) }}) + '\\n');
    process.exit(3);
}});
process.on('unhandledRejection', (e) => {{
    process.stdout.write(JSON.stringify({{ status: 'crash', message: String((e && e.message) || e) }}) + '\\n');
    process.exit(3);
}});

const mod = await import(pathToFileURL({json.dumps(str(action_path))}).href);
const logs = [];
const result = await mod.executeCodeAction.perform(
    {{ name: 'rex', openChat: (line) => logs.push(line) }},
    'python',
    'print(2 + 2)',
    7,
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, logs }}) + '\\n');
"""
    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(calls_path)},
    )
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]

    assert result["status"] == "ok"
    assert "code execution ok" in result["result"]
    assert calls == [
        {
            "service": "code",
            "method": "execute",
            "payload": {"language": "python", "code": "print(2 + 2)", "timeout": 7},
            "deadlineMs": 12000,
            "agentId": "rex",
            "traceId": calls[0]["traceId"],
        }
    ]
    assert calls[0]["traceId"].startswith("trace-")


@requires_node
def test_execute_code_action_safe_idles_on_bridge_client_outage(tmp_path: Path) -> None:
    action_path, calls_path = _stage_action_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

process.on('uncaughtException', (e) => {{
    process.stdout.write(JSON.stringify({{ status: 'crash', message: String((e && e.message) || e) }}) + '\\n');
    process.exit(3);
}});
process.on('unhandledRejection', (e) => {{
    process.stdout.write(JSON.stringify({{ status: 'crash', message: String((e && e.message) || e) }}) + '\\n');
    process.exit(3);
}});

const mod = await import(pathToFileURL({json.dumps(str(action_path))}).href);
const result = await mod.executeCodeAction.perform(
    {{ name: 'rex' }},
    'python',
    'print(2 + 2)',
    7,
);
process.stdout.write(JSON.stringify({{ status: 'ok', result }}) + '\\n');
"""
    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "BRIDGE_THROW_CODE": "bridge_unreachable",
        },
    )

    assert result["status"] == "ok"
    assert "safe-idling [bridge_unreachable]" in result["result"]
    assert calls_path.read_text().strip()

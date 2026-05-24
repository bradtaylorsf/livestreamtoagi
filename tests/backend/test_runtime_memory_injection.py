"""Runtime Python-memory context injection for Mindcraft decisions (#708)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.bridge import contract as c
from core.bridge.server import BRIDGE_TOKEN_ENV, BRIDGE_WS_PATH, bridge_router

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
MEMORY_CONTEXT = FORK_SRC / "agent" / "skills" / "memory_context.js"
DIRECTOR_GATE = FORK_SRC / "agent" / "skills" / "director_gate.js"
HEARTBEAT = FORK_SRC / "agent" / "skills" / "heartbeat.js"

TOKEN = "test-runtime-memory-context-secret"  # noqa: S105 - test-only shared secret
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


@dataclass
class RuntimeCoreMemory:
    rows: dict[tuple[str, uuid.UUID | None], str] = field(default_factory=dict)

    async def get_core_memory(
        self,
        agent_id: str,
        simulation_id: uuid.UUID | None = None,
    ) -> str | None:
        return self.rows.get((agent_id, simulation_id))


@dataclass
class RuntimeRecallMemory:
    rows: dict[tuple[str, uuid.UUID | None], list[str]] = field(default_factory=dict)
    calls: list[tuple[str, str, int, uuid.UUID | None]] = field(default_factory=list)

    async def retrieve_recall_memories(
        self,
        agent_id: str,
        query_text: str,
        limit: int = 3,
        simulation_id: uuid.UUID | None = None,
    ) -> str:
        self.calls.append((agent_id, query_text, limit, simulation_id))
        memories = self.rows.get((agent_id, simulation_id), [])
        return "\n".join(f"- {memory}" for memory in memories[:limit])


@dataclass
class RuntimeServices:
    core_memory: RuntimeCoreMemory
    recall_memory: RuntimeRecallMemory


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    return TOKEN


def _client(services: RuntimeServices) -> TestClient:
    app = FastAPI()
    app.include_router(bridge_router)
    app.state.services = services
    return TestClient(app)


def _memory_request(
    *,
    agent_id: str,
    simulation_id: uuid.UUID,
    tier: str,
    query: str,
    limit: int = 3,
    request_id: str | None = None,
) -> dict[str, Any]:
    return c.BridgeRequest(
        version=c.PROTOCOL_VERSION,
        request_id=request_id or f"req-runtime-memory-{tier}",
        agent_id=agent_id,
        run_id="run-runtime-memory-test",
        simulation_id=str(simulation_id),
        service="memory",
        method="recall",
        payload={"query": query, "tier": tier, "limit": limit},
        deadline_ms=5000,
        cost_context=c.CostContext(
            agent_tier="conversation",
            budget_bucket="runtime-memory-test",
            estimated_cost_usd=0.0,
        ),
    ).model_dump()


def _send_memory_request(client: TestClient, request: dict[str, Any]) -> c.BridgeResponse:
    with client.websocket_connect(
        BRIDGE_WS_PATH,
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as ws:
        ws.send_json(request)
        raw_response = ws.receive_json()
    return c.BridgeResponse.model_validate(raw_response)


def test_runtime_memory_recall_is_scoped_and_logs_no_content(
    token_env: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    target_simulation_id = uuid.uuid4()
    other_simulation_id = uuid.uuid4()
    core_memory = "Vera core: never log this seeded core phrase."
    services = RuntimeServices(
        core_memory=RuntimeCoreMemory(
            rows={
                ("vera", target_simulation_id): core_memory,
                ("vera", other_simulation_id): "Other sim core should stay isolated.",
            }
        ),
        recall_memory=RuntimeRecallMemory(
            rows={
                ("vera", target_simulation_id): [
                    "Vera learned Rex hid torches near the starter oak."
                ],
                ("vera", other_simulation_id): ["Other sim recall should stay isolated."],
            }
        ),
    )
    client = _client(services)
    caplog.set_level(logging.INFO, logger="core.bridge.handlers.memory")

    core_response = _send_memory_request(
        client,
        _memory_request(
            agent_id="vera",
            simulation_id=target_simulation_id,
            tier="core",
            query="current goal",
        ),
    )
    recall_response = _send_memory_request(
        client,
        _memory_request(
            agent_id="vera",
            simulation_id=target_simulation_id,
            tier="recall",
            query="torches starter oak",
            request_id="req-runtime-memory-recall",
        ),
    )
    scoped_response = _send_memory_request(
        client,
        _memory_request(
            agent_id="vera",
            simulation_id=uuid.uuid4(),
            tier="recall",
            query="torches starter oak",
            request_id="req-runtime-memory-other-sim",
        ),
    )

    core_payload = c.validate_response(core_response, service="memory", method="recall")
    recall_payload = c.validate_response(recall_response, service="memory", method="recall")
    scoped_payload = c.validate_response(scoped_response, service="memory", method="recall")

    assert isinstance(core_payload, c.MemoryRecallResponse)
    assert isinstance(recall_payload, c.MemoryRecallResponse)
    assert isinstance(scoped_payload, c.MemoryRecallResponse)
    assert core_payload.core_memory == core_memory
    assert "Rex hid torches" in (recall_payload.formatted or "")
    assert scoped_payload.formatted == ""
    assert services.recall_memory.calls[-2][0:3] == ("vera", "torches starter oak", 3)
    assert services.recall_memory.calls[-2][3] == target_simulation_id
    assert services.recall_memory.calls[-1][0:3] == ("vera", "torches starter oak", 3)
    assert services.recall_memory.calls[-1][3] not in {target_simulation_id, other_simulation_id}

    memory_records = [
        record.bridge_memory for record in caplog.records if hasattr(record, "bridge_memory")
    ]
    assert {
        "agent_id": "vera",
        "tier": "core",
        "simulation_id": str(target_simulation_id),
        "result_size": len(core_memory),
    } in memory_records
    assert any(
        record["tier"] == "recall" and record["result_size"] > 0 for record in memory_records
    )
    assert "never log this seeded core phrase" not in caplog.text
    assert "Rex hid torches" not in caplog.text


def _stage_node_runtime(tmp_path: Path) -> Path:
    root = tmp_path / "fork-src"
    (root / "agent" / "skills").mkdir(parents=True)
    (root / "agent" / "bridge").mkdir(parents=True)
    shutil.copy2(MEMORY_CONTEXT, root / "agent" / "skills" / "memory_context.js")
    shutil.copy2(DIRECTOR_GATE, root / "agent" / "skills" / "director_gate.js")
    shutil.copy2(HEARTBEAT, root / "agent" / "skills" / "heartbeat.js")
    (root / "agent" / "bridge" / "timeline_emitter.js").write_text(
        """
export const events = [];
export function emitTimelineEvent(event = {}) {
    events.push(event);
}
export default { emitTimelineEvent };
""",
        encoding="utf-8",
    )
    (root / "agent" / "bridge" / "python_bridge.js").write_text(
        """
export const calls = [];
export async function callBridge(opts = {}) {
    calls.push(JSON.parse(JSON.stringify(opts)));
    if (opts.service === 'director' && opts.method === 'gate') {
        return {
            ok: true,
            trace_id: opts.traceId,
            payload: {
                selected: true,
                turn_kind: 'speaker',
                reason: 'selected',
                scene_id: 'scene-runtime-memory',
                scene_digest: 'camp marker beside the starter oak',
                role: 'builder',
                local_observations: { biome: 'plains' },
                granted_tools: ['!inventory', '!placeHere'],
                queue_depth: 0,
                suppressed_agents: [],
            },
        };
    }
    if (opts.service === 'shared_state' && opts.method === 'read') {
        return {
            ok: true,
            trace_id: opts.traceId,
            payload: {
                formatted: '**Agent claims:**\\n  - rex: builder on camp (claimed by rex)',
            },
        };
    }
    if (opts.service === 'memory' && opts.method === 'recall' && opts.payload?.tier === 'core') {
        return {
            ok: true,
            trace_id: opts.traceId,
            payload: {
                results: [],
                core_memory: 'Vera remembers Rex stored torches under the oak.',
            },
        };
    }
    if (opts.service === 'memory' && opts.method === 'recall') {
        return {
            ok: true,
            trace_id: opts.traceId,
            payload: {
                results: [],
                formatted: '- Recall: Rex asked Vera to use torches for the camp marker.',
            },
        };
    }
    throw new Error(`unexpected bridge call ${opts.service}.${opts.method}`);
}
export const sharedState = Object.freeze({
    read: async (opts = {}) => {
        const response = await callBridge({ ...opts, service: 'shared_state', method: 'read', payload: {} });
        return response.payload || {};
    },
});
export class BridgeClientError extends Error {}
""",
        encoding="utf-8",
    )
    return root


def _run_node_harness(tmp_path: Path, source: str) -> dict[str, Any]:
    harness = tmp_path / "runtime_memory_harness.mjs"
    harness.write_text(source, encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(harness)],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


@requires_node
def test_director_selected_prompt_gets_python_memory_context(tmp_path: Path) -> None:
    root = _stage_node_runtime(tmp_path)
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.DIRECTOR_V2_GATE = '1';
process.env.LTAG_RUN_ID = 'run-runtime-memory-node';
process.env.LTAG_SIMULATION_ID = '11111111-1111-1111-1111-111111111111';
process.env.MC_SIM_MEMORY_RECALL_LIMIT = '2';

const director = await import(pathToFileURL({json.dumps(str(root / "agent" / "skills" / "director_gate.js"))}).href);
const bridge = await import(pathToFileURL({json.dumps(str(root / "agent" / "bridge" / "python_bridge.js"))}).href);
const timeline = await import(pathToFileURL({json.dumps(str(root / "agent" / "bridge" / "timeline_emitter.js"))}).href);

const handled = [];
const agent = {{
    name: 'vera',
    bot: {{ entity: {{ position: {{ x: 1, y: 64, z: 2 }} }} }},
    actions: {{ actions: ['inventory', 'placeHere'] }},
    async handleMessage(source, message, maxResponses) {{
        handled.push({{ source, message, maxResponses }});
        return message;
    }},
}};

director.installDirectorGate(agent, {{ enabled: true, deadlineMs: 25 }});
await agent.handleMessage('viewer', 'Please use torch memory near the camp.', 1);

process.stdout.write(JSON.stringify({{
    handled,
    calls: bridge.calls.map((call) => ({{
        service: call.service,
        method: call.method,
        tier: call.payload?.tier,
        query: call.payload?.query,
        limit: call.payload?.limit,
        traceId: call.traceId,
    }})),
    events: timeline.events,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    message = result["handled"][0]["message"]
    assert message.startswith("[Python memory context]")
    assert message.index("[Python memory context]") < message.index("[Director V2 context]")
    assert "Run: run-runtime-memory-node" in message
    assert "Simulation: 11111111-1111-1111-1111-111111111111" in message
    assert "Vera remembers Rex stored torches under the oak." in message
    assert "Rex asked Vera to use torches for the camp marker" in message
    assert [call["service"] + "." + call["method"] for call in result["calls"]] == [
        "director.gate",
        "memory.recall",
        "memory.recall",
    ]
    assert [call["tier"] for call in result["calls"][1:]] == ["core", "recall"]
    assert result["calls"][2]["limit"] == 2
    assert "torch memory" in result["calls"][2]["query"]
    assert len({call["traceId"] for call in result["calls"]}) == 1
    assert "memory_context.fetched" in [event["type"] for event in result["events"]]
    assert "torches under the oak" not in json.dumps(result["events"])


@requires_node
def test_memory_context_includes_shared_blackboard_when_enabled(tmp_path: Path) -> None:
    root = _stage_node_runtime(tmp_path)
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.LTAG_RUN_ID = 'run-shared-context';
process.env.LTAG_SIMULATION_ID = '33333333-3333-3333-3333-333333333333';
process.env.MC_SIM_SHARED_STATE_ENABLED = '1';

const memory = await import(pathToFileURL({json.dumps(str(root / "agent" / "skills" / "memory_context.js"))}).href);
const bridge = await import(pathToFileURL({json.dumps(str(root / "agent" / "bridge" / "python_bridge.js"))}).href);
const timeline = await import(pathToFileURL({json.dumps(str(root / "agent" / "bridge" / "timeline_emitter.js"))}).href);

const context = await memory.fetchMemoryContext({{ agent: {{ name: 'vera' }}, query: 'camp coordination' }});

process.stdout.write(JSON.stringify({{
    context,
    calls: bridge.calls.map((call) => call.service + '.' + call.method),
    events: timeline.events.map((event) => event.type),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert "Shared embodied blackboard" in result["context"]
    assert "rex: builder on camp" in result["context"]
    assert result["calls"] == ["memory.recall", "memory.recall", "shared_state.read"]
    assert "shared_state_context.fetched" in result["events"]


@requires_node
def test_heartbeat_fetches_startup_and_legacy_prompt_memory_context(tmp_path: Path) -> None:
    root = _stage_node_runtime(tmp_path)
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.LTAG_RUN_ID = 'run-heartbeat-memory';
process.env.LTAG_SIMULATION_ID = '22222222-2222-2222-2222-222222222222';

const heartbeatMod = await import(pathToFileURL({json.dumps(str(root / "agent" / "skills" / "heartbeat.js"))}).href);
const bridge = await import(pathToFileURL({json.dumps(str(root / "agent" / "bridge" / "python_bridge.js"))}).href);
const timeline = await import(pathToFileURL({json.dumps(str(root / "agent" / "bridge" / "timeline_emitter.js"))}).href);

let now = 1;
const handled = [];
const events = [];
const agent = {{
    name: 'rex',
    async handleMessage(source, message, maxResponses) {{
        handled.push({{ source, message, maxResponses }});
        return '!inventory';
    }},
    actions: {{}},
}};

const controller = heartbeatMod.installHeartbeat(agent, {{
    autoStart: true,
    now: () => now,
    emit: (event) => events.push(event),
    tickMs: 1000000,
    idleMs: 0,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 3,
}});
await new Promise((resolve) => setTimeout(resolve, 10));
now = 2;
await controller.tick();
controller.stop();

process.stdout.write(JSON.stringify({{
    handled,
    memoryCalls: bridge.calls.filter((call) => call.service === 'memory').map((call) => call.payload.tier),
    heartbeatEvents: events.map((event) => event.type),
    timelineEvents: timeline.events.map((event) => event.type),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["memoryCalls"] == ["core", "recall", "core", "recall"]
    assert result["handled"][0]["message"].startswith("[Python memory context]")
    assert "Autonomous heartbeat" in result["handled"][0]["message"]
    assert "memory_context.startup" in result["heartbeatEvents"]
    assert result["timelineEvents"].count("memory_context.fetched") == 2


@requires_node
def test_memory_context_skips_alpha_and_management_without_bridge_calls(
    tmp_path: Path,
) -> None:
    root = _stage_node_runtime(tmp_path)
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const memory = await import(pathToFileURL({json.dumps(str(root / "agent" / "skills" / "memory_context.js"))}).href);
const bridge = await import(pathToFileURL({json.dumps(str(root / "agent" / "bridge" / "python_bridge.js"))}).href);
const timeline = await import(pathToFileURL({json.dumps(str(root / "agent" / "bridge" / "timeline_emitter.js"))}).href);

const alpha = await memory.fetchMemoryContext({{ agent: {{ name: 'alpha' }}, query: 'build camp' }});
const management = await memory.fetchMemoryContext({{ agent: {{ name: 'Management' }}, query: 'review chat' }});

process.stdout.write(JSON.stringify({{
    alpha,
    management,
    calls: bridge.calls,
    events: timeline.events,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["alpha"] == ""
    assert result["management"] == ""
    assert result["calls"] == []
    assert [event["type"] for event in result["events"]] == [
        "memory_context.skipped",
        "memory_context.skipped",
    ]

"""Tests for Alpha executing a verified structured errand (E7-3, #567).

No live Minecraft server is required. The Node harness runs the committed
fork-src action files with a fake bot and a stub bridge, proving a known
navigate+place errand reports a verified `errand.complete` result with Alpha's
✓/✗/? symbol semantics.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from core.bridge import contract as c

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
RUN_ERRAND_ACTION = FORK_SRC / "agent" / "commands" / "run_errand_action.js"
NAVIGATE_ACTION = FORK_SRC / "agent" / "commands" / "navigate_action.js"
PLACE_ACTION = FORK_SRC / "agent" / "commands" / "place_action.js"
ERRAND_PLAN = FORK_SRC / "agent" / "skills" / "errand_plan.js"
MOVEMENT_HELPERS = FORK_SRC / "agent" / "skills" / "movement.js"
BUILDING_HELPERS = FORK_SRC / "agent" / "skills" / "building.js"
ACTION_INTERRUPTION = FORK_SRC / "agent" / "skills" / "action_interruption.js"
BRIDGE_CLIENT = FORK_SRC / "agent" / "bridge" / "python_bridge.js"
CONNECT_ALPHA = REPO_ROOT / "scripts" / "minecraft" / "connect-alpha-bot.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node_harness(tmp_path: Path, source: str, env: dict[str, str] | None = None) -> dict:
    harness = tmp_path / "alpha_errand_harness.mjs"
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


def _stage_run_errand_with_stub_bridge(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fork-src"
    commands = root / "agent" / "commands"
    skills = root / "agent" / "skills"
    bridge = root / "agent" / "bridge"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)

    for src in (RUN_ERRAND_ACTION, NAVIGATE_ACTION, PLACE_ACTION):
        shutil.copy2(src, commands / src.name)
    for src in (ERRAND_PLAN, MOVEMENT_HELPERS, BUILDING_HELPERS, ACTION_INTERRUPTION):
        shutil.copy2(src, skills / src.name)

    calls_path = tmp_path / "bridge_calls.jsonl"
    (bridge / "python_bridge.js").write_text(
        """
import { appendFileSync } from 'node:fs';

let pollCount = 0;

export class BridgeClientError extends Error {
    constructor(code, message) {
        super(message);
        this.name = 'BridgeClientError';
        this.code = code;
    }
}

export function startKillSwitchWatch() {}
export function bridgeIsKillActive() {
    return process.env.BRIDGE_KILL_ACTIVE === '1';
}

export async function callBridge(opts = {}) {
    appendFileSync(process.env.BRIDGE_CALLS_PATH, JSON.stringify(opts) + '\\n');
    if (opts.service === 'errand' && opts.method === 'poll') {
        pollCount += 1;
        return {
            request_id: 'stub-poll',
            ok: true,
            payload: pollCount === 1
                ? {
                    task_id: 'alpha-known-errand',
                    task: process.env.ERRAND_TASK,
                    from_agent: 'vera',
                    dispatched_at_ms: 1710000000000,
                    urgency: 'now',
                }
                : {
                    task_id: null,
                    task: null,
                    from_agent: null,
                    dispatched_at_ms: null,
                    urgency: null,
                },
            retryable: false,
            trace_id: opts.traceId || 'trace-stub',
        };
    }
    if (opts.service === 'bridge') {
        return {
            request_id: 'stub-ping',
            ok: true,
            payload: { pong: opts.payload && opts.payload.message },
            retryable: false,
            trace_id: opts.traceId || 'trace-stub',
        };
    }
    return {
        request_id: 'stub-ack',
        ok: true,
        payload: { accepted: true },
        retryable: false,
        trace_id: opts.traceId || 'trace-stub',
    };
}
""".lstrip()
    )
    return commands / "run_errand_action.js", calls_path


def test_run_errand_action_is_non_verbal_and_bridge_backed() -> None:
    src = RUN_ERRAND_ACTION.read_text()
    assert "'!runErrand'" in src
    assert "service: 'errand'" in src
    assert "method: 'poll'" in src
    assert "method: 'complete'" in src
    assert "parseErrandPlan" in src
    assert "deriveOverallStatus" in src
    assert "'✓'" in src and "'✗'" in src and "'?'" in src
    assert "console.log" in src and "console.error" in src
    assert "openChat" not in src
    assert "openrouter" not in src.lower()


@requires_node
def test_errand_plan_parser_and_symbol_reducer(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(ERRAND_PLAN))}).href);
const plan = mod.parseErrandPlan(JSON.stringify({{
    kind: 'place',
    steps: [{{
        action_id: 'place-1',
        place: {{
            block_type: 'dirt',
            position: {{ x: 1, y: 64, z: 2 }},
            face: 'up',
            source_slot: 1,
        }},
    }}],
}}));
const malformed = mod.parseErrandPlan('not json');
process.stdout.write(JSON.stringify({{
    plan,
    success: mod.deriveOverallStatus([{{ action_id: 'a', status: 'success', detail: '' }}]),
    failure: mod.deriveOverallStatus([
        {{ action_id: 'a', status: 'success', detail: '' }},
        {{ action_id: 'b', status: 'failure', detail: 'blocked' }},
    ]),
    unknown: mod.deriveOverallStatus([]),
    malformed,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["plan"]["kind"] == "place"
    assert result["plan"]["steps"][0]["action"] == "place"
    assert result["plan"]["steps"][0]["place"]["block_type"] == "dirt"
    assert result["success"] == {"status": "success", "symbol": "✓"}
    assert result["failure"] == {"status": "failure", "symbol": "✗"}
    assert result["unknown"] == {"status": "failure", "symbol": "?"}
    assert result["malformed"]["error"].startswith("task JSON parse failed")


@requires_node
def test_run_errand_executes_known_navigate_place_errand_and_reports_completion(
    tmp_path: Path,
) -> None:
    run_action, calls_path = _stage_run_errand_with_stub_bridge(tmp_path)
    task = {
        "kind": "fetch_place",
        "steps": [
            {
                "action_id": "nav-1",
                "navigate": {
                    "target": {"x": 2, "y": 64, "z": 0},
                    "arrive_within_blocks": 1,
                    "timeout_ms": 1000,
                },
            },
            {
                "action_id": "place-1",
                "place": {
                    "block_type": "dirt",
                    "position": {"x": 2, "y": 64, "z": 0},
                    "face": "up",
                    "source_slot": 1,
                },
            },
        ],
    }
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(run_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const position = {{ x: 0, y: 64, z: 0 }};
const world = new Map([
    ['2,63,0', 'stone'],
    ['2,64,0', 'air'],
]);
const bot = {{
    username: 'Alpha',
    entity: {{ position, yaw: 0 }},
    pathfinder: {{
        async goto(goal) {{
            position.x = Number(goal.x);
            position.y = Number(goal.y);
            position.z = Number(goal.z);
            bot.entity.position = position;
        }},
        stop() {{}},
    }},
    inventory: {{
        slots: [null, {{ name: 'dirt' }}],
        items() {{ return this.slots.filter(Boolean); }},
    }},
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return block(world.get(key(cell)) || 'air', cell);
    }},
    async equip(item) {{
        this.heldItem = item;
    }},
    async placeBlock(referenceBlock, faceVector) {{
        const target = {{
            x: referenceBlock.position.x + faceVector.x,
            y: referenceBlock.position.y + faceVector.y,
            z: referenceBlock.position.z + faceVector.z,
        }};
        world.set(key(target), this.heldItem.name);
    }},
}};
const result = await mod.runErrandAction.perform({{
    name: 'Alpha',
    bot,
    openChat: () => {{ throw new Error('chat should not be used'); }},
}});
process.stdout.write(JSON.stringify({{
    result,
    position,
    finalBlock: world.get('2,64,0'),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        source,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "ERRAND_TASK": json.dumps(task),
        },
    )
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    complete_call = next(
        call for call in calls if call["service"] == "errand" and call["method"] == "complete"
    )
    action_results = [
        call for call in calls if call["service"] == "action" and call["method"] == "result"
    ]

    assert result["position"] == {"x": 2, "y": 64, "z": 0}
    assert result["finalBlock"] == "dirt"
    assert "✓ success" in result["result"]
    assert {call["agentId"] for call in calls} == {"alpha"}
    assert complete_call["deadlineMs"] == 20000
    assert [call["payload"]["status"] for call in action_results] == ["success", "success"]
    assert complete_call["payload"] == {
        "task_id": "alpha-known-errand",
        "status": "success",
        "symbol": "✓",
        "detail": "2/2 steps finished",
        "step_results": [
            {
                "action_id": "nav-1",
                "status": "success",
                "detail": complete_call["payload"]["step_results"][0]["detail"],
            },
            {
                "action_id": "place-1",
                "status": "success",
                "detail": complete_call["payload"]["step_results"][1]["detail"],
            },
        ],
    }
    assert "reached:" in complete_call["payload"]["step_results"][0]["detail"]
    assert "placed:" in complete_call["payload"]["step_results"][1]["detail"]


def test_connect_alpha_stages_and_injects_run_errand_action(tmp_path: Path) -> None:
    src = CONNECT_ALPHA.read_text()
    for token in (
        "RUN_ERRAND_ACTION_REL",
        "ERRAND_PLAN_SKILL_REL",
        "RUN_ERRAND_ACTION_SRC",
        "ERRAND_PLAN_SKILL_SRC",
        "LTAG E7-3 run errand action",
        "runErrandAction",
        "src/agent/commands/run_errand_action.js",
        "src/agent/skills/errand_plan.js",
    ):
        assert token in src

    proc = subprocess.run(
        ["bash", str(CONNECT_ALPHA), "--verify"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "Errand smoke: Alpha !runErrand()" in proc.stdout


def test_protocol_version_bumped_on_python_and_node_sides() -> None:
    assert c.PROTOCOL_VERSION == "1.9"
    assert "PROTOCOL_VERSION = '1.9'" in BRIDGE_CLIENT.read_text()


def test_package_json_wires_alpha_errand_verifiers() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]
    assert (
        scripts.get("mc:run-errand-smoke")
        == ".venv/bin/pytest tests/backend/test_minecraft_alpha_errand_execution.py -v"
    )
    assert (
        scripts.get("verify:alpha-errand")
        == ".venv/bin/pytest tests/backend/test_minecraft_alpha_errand_execution.py tests/backend/test_bridge_errand.py -v"
    )

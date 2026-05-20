"""Tests for E6-2 verified movement/navigation outcomes (#557).

No live Minecraft server is required. The Node helper tests exercise the
committed fork source directly, and the bridge smoke test uses the existing
Python bridge endpoint with a fake bot/pathfinder so the resulting
``perception.report`` and ``action.result`` are observable on the Python event
bus.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from core.bridge import contract as c
from core.bridge import inbound
from core.embodiment import verify_movement
from core.event_bus import EventType, event_bus

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
MOVEMENT_HELPERS = FORK_SRC / "agent" / "skills" / "movement.js"
MOVE_ACTION = FORK_SRC / "agent" / "commands" / "move_action.js"
NAVIGATE_ACTION = FORK_SRC / "agent" / "commands" / "navigate_action.js"
CONNECT_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node_harness(tmp_path: Path, source: str, env: dict[str, str] | None = None) -> dict:
    harness = tmp_path / "movement_harness.mjs"
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


def _stage_action_with_stub_bridge(
    tmp_path: Path, action_src: Path, action_filename: str
) -> tuple[Path, Path]:
    root = tmp_path / "fork-src"
    commands = root / "agent" / "commands"
    skills = root / "agent" / "skills"
    bridge = root / "agent" / "bridge"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)
    shutil.copy2(action_src, commands / action_filename)
    shutil.copy2(MOVEMENT_HELPERS, skills / "movement.js")
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
    return {
        request_id: 'stub-request',
        ok: true,
        payload: opts.service === 'bridge' ? { pong: opts.payload && opts.payload.message } : { accepted: true },
        retryable: false,
        trace_id: opts.traceId || 'trace-stub',
    };
}
""".lstrip()
    )
    return commands / action_filename, calls_path


def _write_pathfinder_default_export_stub(tmp_path: Path) -> None:
    package = tmp_path / "node_modules" / "mineflayer-pathfinder"
    package.mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"type": "module", "main": "index.js"})
    )
    (package / "index.js").write_text(
        """
class GoalNear {
    constructor(x, y, z, range) {
        this.x = x;
        this.y = y;
        this.z = z;
        this.range = range;
    }

    isValid() {
        return true;
    }
}

export const pathfinder = {};
export default { pathfinder, goals: { GoalNear } };
""".lstrip()
    )


async def _dispatch_recorded_inbound_calls(calls_path: Path) -> None:
    for idx, raw in enumerate(calls_path.read_text().splitlines()):
        call = json.loads(raw)
        if c.service_key(call["service"], call["method"]) not in inbound.INBOUND_VERBS:
            continue
        env = c.BridgeRequest(
            version=c.PROTOCOL_VERSION,
            request_id=f"movement-stub-{idx}",
            agent_id="vera",
            run_id="run-movement-test",
            simulation_id="00000000-0000-0000-0000-000000000557",
            service=call["service"],
            method=call["method"],
            payload=call["payload"],
            deadline_ms=call.get("deadlineMs", 5000),
            cost_context=c.CostContext(
                agent_tier="conversation",
                budget_bucket="bridge-test",
                estimated_cost_usd=0.0,
            ),
            trace_id=call.get("traceId") or "trace-movement-test",
        )
        await inbound.dispatch_inbound(env, env.trace_id)


@pytest.fixture
def captured_bridge_events() -> Iterator[dict[str, list[dict[str, Any]]]]:
    seen: dict[str, list[dict[str, Any]]] = {"perception": [], "action": []}

    async def on_perception(event: dict[str, Any]) -> None:
        seen["perception"].append(event["data"])

    async def on_action(event: dict[str, Any]) -> None:
        seen["action"].append(event["data"])

    event_bus.on(EventType.BRIDGE_PERCEPTION, on_perception)
    event_bus.on(EventType.BRIDGE_ACTION_RESULT, on_action)
    try:
        yield seen
    finally:
        event_bus.off(EventType.BRIDGE_PERCEPTION, on_perception)
        event_bus.off(EventType.BRIDGE_ACTION_RESULT, on_action)


def test_python_verifies_reached_from_final_pose() -> None:
    observation = {
        "type": "pose",
        "after": {"x": 10.2, "y": 64, "z": -4.9},
        "target": {"x": 10, "y": 64, "z": -5},
        "tolerance": 0.5,
        "class": "reached",
    }

    result = verify_movement(observation)

    assert result["verified"] is True
    assert result["class"] == "reached"
    assert result["distance"] == pytest.approx(0.2236, rel=1e-3)


def test_python_does_not_trust_false_reached_claim() -> None:
    observation = {
        "type": "pose",
        "after": {"x": 0, "y": 64, "z": 0},
        "target": {"x": 0, "y": 64, "z": 5},
        "tolerance": 0.5,
        "class": "reached",
    }

    result = verify_movement(observation)

    assert result == {"verified": False, "class": "partial", "distance": 5.0}


def test_python_preserves_reported_failure_class_when_not_reached() -> None:
    observation = {
        "type": "pose",
        "after": {"x": 1, "y": 64, "z": 0},
        "target": {"x": 8, "y": 64, "z": 0},
        "tolerance": 0.5,
        "class": "blocked",
    }

    result = verify_movement(observation)

    assert result["verified"] is False
    assert result["class"] == "blocked"
    assert result["distance"] == pytest.approx(7.0)


def test_python_marks_malformed_pose_observation_invalid() -> None:
    result = verify_movement({"type": "pose", "after": {"x": 1}, "target": {"x": 1}})

    assert result["verified"] is False
    assert result["class"] == "invalid"


@requires_node
def test_node_movement_helpers_classify_verified_outcomes(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(MOVEMENT_HELPERS))}).href);
await import(pathToFileURL({json.dumps(str(MOVE_ACTION))}).href);
await import(pathToFileURL({json.dumps(str(NAVIGATE_ACTION))}).href);
const target = mod.targetFromMove({{ x: 0, y: 64, z: 0 }}, 'north', 3, 0);
const reached = mod.classifyMovement({{
    before: {{ x: 0, y: 64, z: 0 }},
    after: {{ x: 0, y: 64, z: -2.7 }},
    target,
    tolerance: 0.5,
}});
const blocked = mod.classifyMovement({{
    before: {{ x: 0, y: 64, z: 0 }},
    after: {{ x: 0.01, y: 64, z: 0 }},
    target,
    tolerance: 0.5,
}});
const partial = mod.classifyMovement({{
    before: {{ x: 0, y: 64, z: 0 }},
    after: {{ x: 0, y: 64, z: -1.0 }},
    target,
    tolerance: 0.5,
}});
process.stdout.write(JSON.stringify({{
    target,
    reached,
    blocked,
    partial,
    status: mod.statusForMovementClass(partial),
}}) + '\\n');
"""
    result = _run_node_harness(tmp_path, source)

    assert result["target"] == {"x": 0, "y": 64, "z": -3}
    assert result["reached"] == "reached"
    assert result["blocked"] == "blocked"
    assert result["partial"] == "partial"
    assert result["status"] == "partial"


def test_committed_movement_action_files_match_contract() -> None:
    assert MOVEMENT_HELPERS.is_file()
    assert MOVE_ACTION.is_file()
    assert NAVIGATE_ACTION.is_file()

    helper_src = MOVEMENT_HELPERS.read_text()
    assert "classifyMovement" in helper_src
    assert "targetFromMove" in helper_src
    assert "callBridge" not in helper_src

    for path, action_name in ((MOVE_ACTION, "!move"), (NAVIGATE_ACTION, "!navigate")):
        src = path.read_text()
        assert f"'{action_name}'" in src
        assert "service: 'perception'" in src and "method: 'report'" in src
        assert "service: 'action'" in src and "method: 'result'" in src
        assert "classifyMovement" in src
        assert "safe-idling" in src
        assert "openrouter" not in src.lower()

    move_src = MOVE_ACTION.read_text()
    assert "timeout_ms: {" not in move_src
    assert "type: 'float'" in move_src
    assert "type: 'number'" not in move_src
    assert "MINECRAFT_SUPPRESS_ACTION_CHAT" in move_src
    assert "perform: async function (agent, action_id, direction, distance_blocks, timeout_ms)" in move_src


@requires_node
def test_navigate_action_uses_pathfinder_default_export_goals(tmp_path: Path) -> None:
    """mineflayer-pathfinder exposes ``goals`` via the default export under ESM.

    Passing the fallback plain object into a real pathfinder crashes later in
    the physics tick because it lacks ``isValid``; this catches that live shape.
    """
    navigate_action, calls_path = _stage_action_with_stub_bridge(
        tmp_path, NAVIGATE_ACTION, "navigate_action.js"
    )
    _write_pathfinder_default_export_stub(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(navigate_action))}).href);
const position = {{ x: 0, y: 64, z: 0 }};
const bot = {{
    username: 'NavHarnessBot',
    entity: {{ position, yaw: 0 }},
    pathfinder: {{
        async goto(goal) {{
            if (typeof goal.isValid !== 'function') {{
                throw new Error('goal must expose isValid');
            }}
            position.x = Number(goal.x);
            position.y = Number(goal.y);
            position.z = Number(goal.z);
            bot.entity.position = position;
        }},
        stop() {{}},
    }},
}};
const result = await mod.navigateAction.perform(
    {{ name: 'vera', bot, openChat: () => {{}} }},
    'navigate-action-default-export',
    {{ x: 6, y: 64, z: -3 }},
    1.0,
    1000,
);
process.stdout.write(JSON.stringify({{ result, position }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "vera",
            "LTAG_RUN_ID": "run-movement-test",
            "LTAG_SIMULATION_ID": "00000000-0000-0000-0000-000000000557",
        },
    )

    assert result["position"] == {"x": 6, "y": 64, "z": -3}
    assert "reached:" in result["result"]


def test_connect_script_stages_and_injects_movement_actions() -> None:
    src = CONNECT_SCRIPT.read_text()
    for token in (
        "MOVE_ACTION_REL",
        "NAVIGATE_ACTION_REL",
        "MOVEMENT_SKILL_REL",
        "LTAG E6-2 move action",
        "LTAG E6-2 navigate action",
        "moveAction",
        "navigateAction",
    ):
        assert token in src


def test_package_json_wires_embodiment_movement_verifier() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]

    assert (
        scripts.get("verify:embodiment-movement")
        == ".venv/bin/pytest tests/backend/test_embodiment_movement.py -v"
    )


@requires_node
async def test_move_action_reports_verified_success_observable_on_python_side(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    move_action, calls_path = _stage_action_with_stub_bridge(
        tmp_path, MOVE_ACTION, "move_action.js"
    )
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

const mod = await import(pathToFileURL({json.dumps(str(move_action))}).href);
const position = {{ x: 0, y: 64, z: 0 }};
const bot = {{
    username: 'MoveHarnessBot',
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
}};
const logs = [];
const result = await mod.moveAction.perform(
    {{ name: 'vera', bot, openChat: (line) => logs.push(line) }},
    'move-action-1',
    'south',
    2,
    1000,
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, position, logs }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "vera",
            "LTAG_RUN_ID": "run-movement-test",
            "LTAG_SIMULATION_ID": "00000000-0000-0000-0000-000000000557",
        },
    )
    await _dispatch_recorded_inbound_calls(calls_path)

    assert result["status"] == "ok"
    assert result["position"] == {"x": 0, "y": 64, "z": 2}
    assert len(captured_bridge_events["perception"]) == 1
    assert len(captured_bridge_events["action"]) == 1

    perception = captured_bridge_events["perception"][0]
    action = captured_bridge_events["action"][0]
    observation = perception["observations"][0]

    assert observation["type"] == "pose"
    assert observation["action"] == "move"
    assert observation["action_id"] == "move-action-1"
    assert observation["class"] == "reached"
    assert observation["after"] == {"x": 0, "y": 64, "z": 2}
    assert action["action_id"] == "move-action-1"
    assert action["status"] == "success"
    assert "reached:" in action["detail"]
    assert verify_movement(observation)["verified"] is True


@requires_node
async def test_navigate_action_reports_verified_success_observable_on_python_side(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    """The acceptance criterion names navigate explicitly: a navigate action
    must report a verified success/failure observable on the Python side. This
    exercises ``navigateAction.perform`` (including coordinate ``resolveTarget``)
    end-to-end with a fake bot/pathfinder and confirms the resulting
    ``perception.report``/``action.result`` reach the Python event bus and that
    Python independently verifies the final pose against the target.
    """
    navigate_action, calls_path = _stage_action_with_stub_bridge(
        tmp_path, NAVIGATE_ACTION, "navigate_action.js"
    )
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

const mod = await import(pathToFileURL({json.dumps(str(navigate_action))}).href);
const position = {{ x: 0, y: 64, z: 0 }};
const bot = {{
    username: 'NavHarnessBot',
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
}};
const logs = [];
const result = await mod.navigateAction.perform(
    {{ name: 'vera', bot, openChat: (line) => logs.push(line) }},
    'navigate-action-1',
    {{ x: 6, y: 64, z: -3 }},
    1.0,
    1000,
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, position, logs }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "vera",
            "LTAG_RUN_ID": "run-movement-test",
            "LTAG_SIMULATION_ID": "00000000-0000-0000-0000-000000000557",
        },
    )
    await _dispatch_recorded_inbound_calls(calls_path)

    assert result["status"] == "ok"
    assert result["position"] == {"x": 6, "y": 64, "z": -3}
    assert len(captured_bridge_events["perception"]) == 1
    assert len(captured_bridge_events["action"]) == 1

    perception = captured_bridge_events["perception"][0]
    action = captured_bridge_events["action"][0]
    observation = perception["observations"][0]

    assert observation["type"] == "pose"
    assert observation["action"] == "navigate"
    assert observation["action_id"] == "navigate-action-1"
    assert observation["class"] == "reached"
    assert observation["after"] == {"x": 6, "y": 64, "z": -3}
    assert action["action_id"] == "navigate-action-1"
    assert action["status"] == "success"
    assert "reached:" in action["detail"]
    assert verify_movement(observation)["verified"] is True

"""Tests for E6-3 verified block placement/break outcomes (#558).

No live Minecraft server is required. The Node helper tests exercise the
committed fork source directly, and the bridge smoke tests use the existing
Python bridge endpoint with fake bots so the resulting ``perception.report``
and ``action.result`` are observable on the Python event bus.
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
from core.embodiment import verify_break, verify_place
from core.event_bus import EventType, event_bus

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
BUILDING_HELPERS = FORK_SRC / "agent" / "skills" / "building.js"
PLACE_ACTION = FORK_SRC / "agent" / "commands" / "place_action.js"
BREAK_ACTION = FORK_SRC / "agent" / "commands" / "break_action.js"
CONNECT_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node_harness(tmp_path: Path, source: str, env: dict[str, str] | None = None) -> dict:
    harness = tmp_path / "building_harness.mjs"
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
    shutil.copy2(BUILDING_HELPERS, skills / "building.js")
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


async def _dispatch_recorded_inbound_calls(calls_path: Path) -> None:
    for idx, raw in enumerate(calls_path.read_text().splitlines()):
        call = json.loads(raw)
        if c.service_key(call["service"], call["method"]) not in inbound.INBOUND_VERBS:
            continue
        env = c.BridgeRequest(
            version=c.PROTOCOL_VERSION,
            request_id=f"building-stub-{idx}",
            agent_id="vera",
            run_id="run-building-test",
            simulation_id="00000000-0000-0000-0000-000000000558",
            service=call["service"],
            method=call["method"],
            payload=call["payload"],
            deadline_ms=call.get("deadlineMs", 5000),
            cost_context=c.CostContext(
                agent_tier="conversation",
                budget_bucket="bridge-test",
                estimated_cost_usd=0.0,
            ),
            trace_id=call.get("traceId") or "trace-building-test",
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


def test_python_verifies_placed_from_post_action_block() -> None:
    observation = {
        "type": "block",
        "position": {"x": 1, "y": 64, "z": 2},
        "before_block": "air",
        "after_block": "minecraft:oak_planks",
        "expected_block_type": "oak_planks",
        "class": "placed",
    }

    result = verify_place(observation)

    assert result == {"verified": True, "class": "placed"}


def test_python_does_not_trust_false_placed_claim() -> None:
    observation = {
        "type": "block",
        "after_block": "air",
        "expected_block_type": "dirt",
        "class": "placed",
    }

    result = verify_place(observation)

    assert result == {"verified": False, "class": "partial"}


def test_python_marks_malformed_place_observation_invalid() -> None:
    result = verify_place({"type": "block", "expected_block_type": "stone"})

    assert result == {"verified": False, "class": "invalid"}


def test_python_verifies_removed_from_post_action_block() -> None:
    observation = {
        "type": "block",
        "position": {"x": 1, "y": 64, "z": 2},
        "before_block": "stone",
        "after_block": "air",
        "expected_block_type": "minecraft:stone",
        "class": "removed",
    }

    result = verify_break(observation)

    assert result == {"verified": True, "class": "removed"}


def test_python_does_not_trust_false_removed_claim() -> None:
    observation = {
        "type": "block",
        "before_block": "stone",
        "after_block": "stone",
        "expected_block_type": "stone",
        "class": "removed",
    }

    result = verify_break(observation)

    assert result == {"verified": False, "class": "partial"}


def test_python_marks_malformed_break_observation_invalid() -> None:
    result = verify_break({"type": "block", "before_block": "stone"})

    assert result == {"verified": False, "class": "invalid"}


@requires_node
def test_node_building_helpers_classify_verified_outcomes(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(BUILDING_HELPERS))}).href);
await import(pathToFileURL({json.dumps(str(PLACE_ACTION))}).href);
await import(pathToFileURL({json.dumps(str(BREAK_ACTION))}).href);

const placed = mod.classifyPlace({{
    afterBlock: 'minecraft:dirt',
    blockType: 'dirt',
}});
const blockedPlace = mod.classifyPlace({{
    afterBlock: 'air',
    blockType: 'dirt',
}});
const removed = mod.classifyBreak({{
    beforeBlock: 'stone',
    afterBlock: 'air',
    expectedBlockType: 'stone',
}});
const blockedBreak = mod.classifyBreak({{
    beforeBlock: 'stone',
    afterBlock: 'stone',
    expectedBlockType: 'stone',
}});
const partialBreak = mod.classifyBreak({{
    beforeBlock: 'stone',
    afterBlock: 'dirt',
    expectedBlockType: 'stone',
}});
process.stdout.write(JSON.stringify({{
    cell: mod.positionFrom({{ x: 1.9, y: 64.2, z: -2.1 }}),
    normalized: mod.normalizeBlockType('minecraft:Oak Planks'),
    placed,
    blockedPlace,
    removed,
    blockedBreak,
    partialBreak,
    status: mod.statusForBuildClass(removed),
}}) + '\\n');
"""
    result = _run_node_harness(tmp_path, source)

    assert result["cell"] == {"x": 1, "y": 64, "z": -3}
    assert result["normalized"] == "oak_planks"
    assert result["placed"] == "placed"
    assert result["blockedPlace"] == "blocked"
    assert result["removed"] == "removed"
    assert result["blockedBreak"] == "blocked"
    assert result["partialBreak"] == "partial"
    assert result["status"] == "success"


def test_committed_building_action_files_match_contract() -> None:
    assert BUILDING_HELPERS.is_file()
    assert PLACE_ACTION.is_file()
    assert BREAK_ACTION.is_file()

    helper_src = BUILDING_HELPERS.read_text()
    assert "classifyPlace" in helper_src
    assert "classifyBreak" in helper_src
    assert "callBridge" not in helper_src

    for path, action_name, classifier in (
        (PLACE_ACTION, "!place", "classifyPlace"),
        (BREAK_ACTION, "!break", "classifyBreak"),
    ):
        src = path.read_text()
        assert f"'{action_name}'" in src
        assert "service: 'perception'" in src and "method: 'report'" in src
        assert "service: 'action'" in src and "method: 'result'" in src
        assert classifier in src
        assert "safe-idling" in src
        assert "openrouter" not in src.lower()


def test_connect_script_stages_and_injects_building_actions() -> None:
    src = CONNECT_SCRIPT.read_text()
    for token in (
        "PLACE_ACTION_REL",
        "BREAK_ACTION_REL",
        "BUILDING_SKILL_REL",
        "LTAG E6-3 place action",
        "LTAG E6-3 break action",
        "placeAction",
        "breakAction",
    ):
        assert token in src


def test_package_json_wires_embodiment_building_verifier() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]

    assert (
        scripts.get("verify:embodiment-building")
        == ".venv/bin/pytest tests/backend/test_embodiment_building.py -v"
    )


@requires_node
async def test_place_action_reports_success_only_when_post_action_block_matches(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    place_action, calls_path = _stage_action_with_stub_bridge(
        tmp_path, PLACE_ACTION, "place_action.js"
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

const mod = await import(pathToFileURL({json.dumps(str(place_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'stone'],
    ['0,64,0', 'air'],
]);
const bot = {{
    username: 'PlaceHarnessBot',
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
const logs = [];
const result = await mod.placeAction.perform(
    {{ name: 'vera', bot, openChat: (line) => logs.push(line) }},
    'place-action-1',
    'minecraft:dirt',
    {{ x: 0, y: 64, z: 0 }},
    'up',
    1,
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, finalBlock: world.get('0,64,0'), logs }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "vera",
            "LTAG_RUN_ID": "run-building-test",
            "LTAG_SIMULATION_ID": "00000000-0000-0000-0000-000000000558",
        },
    )
    await _dispatch_recorded_inbound_calls(calls_path)

    assert result["status"] == "ok"
    assert result["finalBlock"] == "dirt"
    assert len(captured_bridge_events["perception"]) == 1
    assert len(captured_bridge_events["action"]) == 1

    perception = captured_bridge_events["perception"][0]
    action = captured_bridge_events["action"][0]
    observation = perception["observations"][0]

    assert observation["type"] == "block"
    assert observation["action"] == "place"
    assert observation["action_id"] == "place-action-1"
    assert observation["class"] == "placed"
    assert observation["after_block"] == "dirt"
    assert action["action_id"] == "place-action-1"
    assert action["status"] == "success"
    assert "placed:" in action["detail"]
    assert verify_place(observation)["verified"] is True


@requires_node
async def test_place_action_reports_failure_when_post_action_block_is_missing(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    place_action, calls_path = _stage_action_with_stub_bridge(
        tmp_path, PLACE_ACTION, "place_action.js"
    )
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(place_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'stone'],
    ['0,64,0', 'air'],
]);
const bot = {{
    username: 'PlaceNoopHarnessBot',
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
    async placeBlock() {{
        // Deliberately no-op: command acceptance alone must not become success.
    }},
}};
const result = await mod.placeAction.perform(
    {{ name: 'vera', bot }},
    'place-action-2',
    'dirt',
    {{ x: 0, y: 64, z: 0 }},
    'up',
    1,
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, finalBlock: world.get('0,64,0') }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(calls_path)},
    )
    await _dispatch_recorded_inbound_calls(calls_path)

    assert result["status"] == "ok"
    assert result["finalBlock"] == "air"
    action = captured_bridge_events["action"][0]
    observation = captured_bridge_events["perception"][0]["observations"][0]

    assert observation["class"] == "blocked"
    assert observation["after_block"] == "air"
    assert action["status"] == "failure"
    assert verify_place(observation)["verified"] is False


@requires_node
async def test_break_action_reports_verified_success_observable_on_python_side(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    break_action, calls_path = _stage_action_with_stub_bridge(
        tmp_path, BREAK_ACTION, "break_action.js"
    )
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(break_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([['2,64,0', 'stone']]);
const bot = {{
    username: 'BreakHarnessBot',
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return block(world.get(key(cell)) || 'air', cell);
    }},
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const result = await mod.breakAction.perform(
    {{ name: 'vera', bot }},
    'break-action-1',
    {{ x: 2, y: 64, z: 0 }},
    'stone',
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, finalBlock: world.get('2,64,0') }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(calls_path)},
    )
    await _dispatch_recorded_inbound_calls(calls_path)

    assert result["status"] == "ok"
    assert result["finalBlock"] == "air"
    assert len(captured_bridge_events["perception"]) == 1
    assert len(captured_bridge_events["action"]) == 1

    perception = captured_bridge_events["perception"][0]
    action = captured_bridge_events["action"][0]
    observation = perception["observations"][0]

    assert observation["type"] == "block"
    assert observation["action"] == "break"
    assert observation["action_id"] == "break-action-1"
    assert observation["class"] == "removed"
    assert observation["after_block"] == "air"
    assert action["action_id"] == "break-action-1"
    assert action["status"] == "success"
    assert "removed:" in action["detail"]
    assert verify_break(observation)["verified"] is True


@requires_node
async def test_break_action_reports_failure_when_post_action_block_remains(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    break_action, calls_path = _stage_action_with_stub_bridge(
        tmp_path, BREAK_ACTION, "break_action.js"
    )
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(break_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([['2,64,0', 'stone']]);
const bot = {{
    username: 'BreakNoopHarnessBot',
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return block(world.get(key(cell)) || 'air', cell);
    }},
    async dig() {{
        // Deliberately no-op: command acceptance alone must not become success.
    }},
}};
const result = await mod.breakAction.perform(
    {{ name: 'vera', bot }},
    'break-action-2',
    {{ x: 2, y: 64, z: 0 }},
    'stone',
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, finalBlock: world.get('2,64,0') }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(calls_path)},
    )
    await _dispatch_recorded_inbound_calls(calls_path)

    assert result["status"] == "ok"
    assert result["finalBlock"] == "stone"
    action = captured_bridge_events["action"][0]
    observation = captured_bridge_events["perception"][0]["observations"][0]

    assert observation["class"] == "blocked"
    assert observation["after_block"] == "stone"
    assert action["status"] == "failure"
    assert verify_break(observation)["verified"] is False

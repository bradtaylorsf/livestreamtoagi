"""Tests for E6-6 perception snapshots (#561).

No live Minecraft server is required. Python-side tests validate the typed
snapshot schema and inbound event enrichment; Node-side tests exercise the
committed fork source with a fake bot and a stub bridge so ``!observe`` emits a
schema-valid ``perception.report`` and no ``action.result``.
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
from core.embodiment import build_perception_snapshot, is_schema_valid_snapshot
from core.event_bus import EventType, event_bus

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
PERCEPTION_HELPERS = FORK_SRC / "agent" / "skills" / "perception.js"
BUILDING_HELPERS = FORK_SRC / "agent" / "skills" / "building.js"
MOVEMENT_HELPERS = FORK_SRC / "agent" / "skills" / "movement.js"
OBSERVE_ACTION = FORK_SRC / "agent" / "commands" / "observe_action.js"
CONNECT_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _snapshot_observation() -> dict[str, Any]:
    return {
        "type": "perception_snapshot",
        "pose": {
            "position": {"x": 1, "y": 64, "z": -2},
            "yaw": 1.25,
            "pitch": -0.2,
            "on_ground": True,
            "dimension": "minecraft:overworld",
        },
        "nearby_blocks": [
            {"position": {"x": 1, "y": 64, "z": -1}, "block_type": "Minecraft:Oak Planks"}
        ],
        "entities": [
            {
                "entity_id": "mob-1",
                "kind": "MOB",
                "name": "minecraft:Zombie",
                "position": {"x": 1, "y": 64, "z": 0},
                "distance": 2,
            }
        ],
        "inventory": {
            "items": [{"slot": 3, "item_id": "minecraft:Stone", "count": 12}],
            "equipment": {"hand": "minecraft:Diamond Sword", "head": None},
            "used_slots": 1,
            "total_slots": 46,
        },
        "radius_blocks": 8,
        "scope": "ALL",
        "include_air": False,
        "captured_tick": 42,
    }


def _envelope(observations: list[dict[str, Any]]) -> c.BridgeRequest:
    return c.BridgeRequest(
        version=c.PROTOCOL_VERSION,
        request_id="req-perception-snapshot",
        agent_id="vera",
        run_id="run-perception-test",
        simulation_id="00000000-0000-0000-0000-000000000561",
        service="perception",
        method="report",
        payload={"observations": observations},
        deadline_ms=5000,
        cost_context=c.CostContext(
            agent_tier="conversation",
            budget_bucket="bridge-test",
            estimated_cost_usd=0.0,
        ),
        trace_id="trace-perception-test",
    )


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


def _run_node_harness(tmp_path: Path, source: str, env: dict[str, str] | None = None) -> dict:
    harness = tmp_path / "perception_harness.mjs"
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


def _stage_observe_with_stub_bridge(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fork-src"
    commands = root / "agent" / "commands"
    skills = root / "agent" / "skills"
    bridge = root / "agent" / "bridge"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)
    shutil.copy2(OBSERVE_ACTION, commands / "observe_action.js")
    shutil.copy2(PERCEPTION_HELPERS, skills / "perception.js")
    shutil.copy2(BUILDING_HELPERS, skills / "building.js")
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
    return commands / "observe_action.js", calls_path


async def _dispatch_recorded_inbound_calls(calls_path: Path) -> None:
    for idx, raw in enumerate(calls_path.read_text().splitlines()):
        call = json.loads(raw)
        if c.service_key(call["service"], call["method"]) not in inbound.INBOUND_VERBS:
            continue
        env = c.BridgeRequest(
            version=c.PROTOCOL_VERSION,
            request_id=f"perception-stub-{idx}",
            agent_id="vera",
            run_id="run-perception-test",
            simulation_id="00000000-0000-0000-0000-000000000561",
            service=call["service"],
            method=call["method"],
            payload=call["payload"],
            deadline_ms=call.get("deadlineMs", 5000),
            cost_context=c.CostContext(
                agent_tier="conversation",
                budget_bucket="bridge-test",
                estimated_cost_usd=0.0,
            ),
            trace_id=call.get("traceId") or "trace-perception-test",
        )
        await inbound.dispatch_inbound(env, env.trace_id)


def test_python_builds_schema_valid_snapshot_and_normalizes_ids() -> None:
    snapshot = build_perception_snapshot([{"type": "pose"}, _snapshot_observation()])

    assert snapshot is not None
    assert snapshot.type == "perception_snapshot"
    assert snapshot.pose.dimension == "overworld"
    assert snapshot.scope == "all"
    assert snapshot.nearby_blocks[0].block_type == "oak_planks"
    assert snapshot.entities[0].kind == "mob"
    assert snapshot.entities[0].name == "zombie"
    assert snapshot.inventory.items[0].item_id == "stone"
    assert snapshot.inventory.equipment["hand"] == "diamond_sword"
    assert is_schema_valid_snapshot(_snapshot_observation()) is True


def test_python_returns_none_when_snapshot_is_absent_or_invalid() -> None:
    assert build_perception_snapshot([{"type": "pose"}]) is None
    invalid = _snapshot_observation()
    invalid["nearby_blocks"][0]["block_type"] = ""

    assert build_perception_snapshot([invalid]) is None
    assert is_schema_valid_snapshot(invalid) is False


async def test_inbound_perception_event_includes_typed_snapshot_additively(
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    raw_snapshot = _snapshot_observation()
    env = _envelope([{"type": "pose"}, raw_snapshot])

    ack = await inbound.handle_perception_report(env)

    assert ack == {"accepted": True}
    assert len(captured_bridge_events["perception"]) == 1
    assert captured_bridge_events["action"] == []
    event = captured_bridge_events["perception"][0]
    assert event["observations"] == env.payload["observations"]
    assert event["snapshot"]["nearby_blocks"][0]["block_type"] == "oak_planks"
    assert event["snapshot"]["inventory"]["equipment"]["hand"] == "diamond_sword"
    c.PerceptionSnapshot.model_validate(event["snapshot"])


async def test_inbound_omits_snapshot_key_when_snapshot_observation_is_invalid(
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    invalid = _snapshot_observation()
    invalid["entities"][0]["kind"] = "vehicle"

    await inbound.handle_perception_report(_envelope([invalid]))

    assert len(captured_bridge_events["perception"]) == 1
    assert "snapshot" not in captured_bridge_events["perception"][0]


@requires_node
def test_node_perception_helpers_capture_known_setup(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(PERCEPTION_HELPERS))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const world = new Map([
    ['0,64,0', 'minecraft:Stone'],
    ['1,64,0', 'Minecraft:Oak Planks'],
]);
const bot = {{
    username: 'ObserveHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }}, yaw: 1.25, pitch: -0.25, onGround: true }},
    game: {{ dimension: 'minecraft:overworld' }},
    time: {{ age: 99 }},
    heldItem: {{ name: 'minecraft:Stone Pickaxe', count: 1 }},
    entities: {{
        zombie: {{ id: 7, type: 'mob', name: 'minecraft:Zombie', position: {{ x: 0, y: 64, z: 1 }} }},
        far: {{ id: 8, type: 'player', username: 'Alex', position: {{ x: 10, y: 64, z: 0 }} }},
    }},
    inventory: {{
        slots: [null, {{ name: 'minecraft:Oak Planks', count: 4, slot: 1 }}],
        items() {{ return this.slots.map((item, slot) => item ? {{ ...item, slot }} : null).filter(Boolean); }},
    }},
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return {{ name: world.get(key(cell)) || 'air', position: cell }};
    }},
}};
const blocks = await mod.nearbyBlocks(bot, 1.5, false);
const entities = mod.nearbyEntities(bot, 1.5);
const inventory = mod.inventorySnapshot(bot, null, true);
const observation = mod.perceptionObservation({{
    pose: mod.poseFrom(bot),
    blocks,
    entities,
    inventory,
    radius: 1.5,
    scope: 'all',
    includeAir: false,
    tick: bot.time.age,
}});
process.stdout.write(JSON.stringify({{ observation }}) + '\\n');
"""
    result = _run_node_harness(tmp_path, source)
    observation = result["observation"]

    assert observation["type"] == "perception_snapshot"
    assert observation["pose"]["dimension"] == "overworld"
    assert observation["captured_tick"] == 99
    assert {block["block_type"] for block in observation["nearby_blocks"]} == {
        "stone",
        "oak_planks",
    }
    assert observation["entities"] == [
        {
            "entity_id": "7",
            "kind": "mob",
            "name": "zombie",
            "position": {"x": 0, "y": 64, "z": 1},
            "distance": 1,
        }
    ]
    assert observation["inventory"]["items"][0] == {
        "slot": 1,
        "item_id": "oak_planks",
        "count": 4,
    }
    assert observation["inventory"]["equipment"]["hand"] == "stone_pickaxe"
    assert build_perception_snapshot([observation]) is not None


def test_committed_perception_files_match_contract() -> None:
    assert PERCEPTION_HELPERS.is_file()
    assert OBSERVE_ACTION.is_file()

    helper_src = PERCEPTION_HELPERS.read_text()
    assert "perceptionObservation" in helper_src
    assert "nearbyBlocks" in helper_src
    assert "nearbyEntities" in helper_src
    assert "inventorySnapshot" in helper_src
    assert "callBridge" not in helper_src

    action_src = OBSERVE_ACTION.read_text()
    assert "'!observe'" in action_src
    assert "service: 'perception'" in action_src and "method: 'report'" in action_src
    assert "perceptionObservation" in action_src
    assert "safe-idling" in action_src
    assert "service: 'action'" not in action_src
    assert "openrouter" not in action_src.lower()


def test_connect_script_stages_and_injects_observe_action() -> None:
    src = CONNECT_SCRIPT.read_text()
    for token in (
        "OBSERVE_ACTION_REL",
        "PERCEPTION_SKILL_REL",
        "LTAG E6-6 observe action",
        "observeAction",
        "!observe",
    ):
        assert token in src


def test_package_json_wires_embodiment_perception_verifier() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]

    assert (
        scripts.get("verify:embodiment-perception")
        == ".venv/bin/pytest tests/backend/test_embodiment_perception.py -v"
    )


@requires_node
async def test_observe_action_reports_schema_valid_snapshot_without_action_result(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    observe_action, calls_path = _stage_observe_with_stub_bridge(tmp_path)
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

const mod = await import(pathToFileURL({json.dumps(str(observe_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const world = new Map([
    ['0,64,0', 'minecraft:Stone'],
    ['1,64,0', 'Minecraft:Oak Planks'],
]);
const bot = {{
    username: 'ObserveActionHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }}, yaw: 0.5, pitch: 0.1, onGround: true }},
    game: {{ dimension: 'minecraft:overworld' }},
    time: {{ age: 123 }},
    heldItem: {{ name: 'minecraft:Stone Pickaxe', count: 1 }},
    entities: {{
        zombie: {{ id: 7, type: 'mob', name: 'minecraft:Zombie', position: {{ x: 0, y: 64, z: 1 }} }},
        alex: {{ id: 8, type: 'player', username: 'Alex', position: {{ x: 10, y: 64, z: 0 }} }},
    }},
    inventory: {{
        slots: [null, {{ name: 'minecraft:Oak Planks', count: 4, slot: 1 }}],
        items() {{ return this.slots.map((item, slot) => item ? {{ ...item, slot }} : null).filter(Boolean); }},
    }},
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return {{ name: world.get(key(cell)) || 'air', position: cell }};
    }},
}};
const logs = [];
const result = await mod.observeAction.perform(
    {{ name: 'vera', bot, openChat: (line) => logs.push(line) }},
    1.5,
    'all',
    false,
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, logs }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "vera",
            "LTAG_RUN_ID": "run-perception-test",
            "LTAG_SIMULATION_ID": "00000000-0000-0000-0000-000000000561",
        },
    )
    await _dispatch_recorded_inbound_calls(calls_path)

    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    assert result["status"] == "ok"
    assert "observe all:" in result["result"]
    assert [c.service_key(call["service"], call["method"]) for call in calls] == [
        "bridge.ping",
        "perception.report",
    ]
    assert len(captured_bridge_events["perception"]) == 1
    assert captured_bridge_events["action"] == []

    event = captured_bridge_events["perception"][0]
    observation = event["observations"][0]
    snapshot = c.PerceptionSnapshot.model_validate(event["snapshot"])
    assert observation["type"] == "perception_snapshot"
    assert snapshot.pose.position.x == 0
    assert snapshot.pose.dimension == "overworld"
    assert snapshot.captured_tick == 123
    assert {block.block_type for block in snapshot.nearby_blocks} == {"stone", "oak_planks"}
    assert snapshot.entities[0].name == "zombie"
    assert snapshot.inventory.items[0].item_id == "oak_planks"
    assert build_perception_snapshot(event["observations"]) is not None

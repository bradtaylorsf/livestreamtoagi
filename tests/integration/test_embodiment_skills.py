"""No-server integration tests for E6 embodiment skills (#563).

This module intentionally does not use the ``integration`` marker or the
Docker-backed fixtures from ``tests/integration/conftest.py``. It exercises the
embodiment verifier APIs, the E4 bridge harness, and the committed Node command
modules with fake bots only.
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
from core.bridge.server import ERR_CODE_SERVICE_UNAVAILABLE
from core.embodiment import (
    RetryBudget,
    build_perception_snapshot,
    classify,
    decide_safe_fail,
    is_schema_valid_snapshot,
    verify_break,
    verify_build_plan,
    verify_movement,
    verify_place,
)
from core.event_bus import EventType, event_bus
from tests.integration.bridge_harness import (
    FakeNodeBridgeClient,
    FakePythonBridgeServer,
    copy_bridge_client_with_header_ws,
    free_local_port,
    make_bridge_request,
    run_node_bridge_call,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
COMMAND_SRC = FORK_SRC / "agent" / "commands"
SKILL_SRC = FORK_SRC / "agent" / "skills"
BRIDGE_CLIENT_SRC = FORK_SRC / "agent" / "bridge" / "python_bridge.js"

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


def _structure_observation(
    *,
    steps: list[dict[str, Any]],
    final_blocks: list[dict[str, Any]],
    outcome_class: str = "success",
) -> dict[str, Any]:
    return {
        "type": "structure",
        "action": "build-from-plan",
        "action_id": "build-plan-python",
        "origin": {"x": 0, "y": 64, "z": 0},
        "steps": steps,
        "final_blocks": final_blocks,
        "class": outcome_class,
    }


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


def test_python_verifier_path_covers_embodied_skills_with_mocked_perception() -> None:
    move_result = verify_movement(
        {
            "type": "pose",
            "action": "move",
            "after": {"x": 0, "y": 64, "z": 2},
            "target": {"x": 0, "y": 64, "z": 2},
            "tolerance": 0.5,
            "class": "reached",
        }
    )
    short_navigation = verify_movement(
        {
            "type": "pose",
            "action": "navigate",
            "after": {"x": 3, "y": 64, "z": 0},
            "target": {"x": 6, "y": 64, "z": 0},
            "tolerance": 0.5,
            "class": "reached",
        }
    )

    assert move_result == {"verified": True, "class": "reached", "distance": 0.0}
    assert short_navigation == {"verified": False, "class": "partial", "distance": 3.0}

    assert verify_place(
        {
            "type": "block",
            "after_block": "minecraft:oak_planks",
            "expected_block_type": "Oak Planks",
            "class": "placed",
        }
    ) == {"verified": True, "class": "placed"}
    assert verify_place(
        {
            "type": "block",
            "after_block": "air",
            "expected_block_type": "stone",
            "class": "placed",
        }
    ) == {"verified": False, "class": "partial"}

    assert verify_break(
        {
            "type": "block",
            "before_block": "minecraft:stone",
            "after_block": "air",
            "expected_block_type": "stone",
            "class": "removed",
        }
    ) == {"verified": True, "class": "removed"}
    assert verify_break(
        {
            "type": "block",
            "before_block": "stone",
            "after_block": "stone",
            "expected_block_type": "stone",
            "class": "removed",
        }
    ) == {"verified": False, "class": "partial"}

    full_plan = _structure_observation(
        steps=[
            {
                "index": 0,
                "action": "place",
                "position": {"x": 0, "y": 64, "z": 0},
                "block_type": "stone",
                "final_block": "stone",
            },
            {
                "index": 1,
                "action": "place",
                "position": {"x": 1, "y": 64, "z": 0},
                "block_type": "stone",
                "final_block": "stone",
            },
        ],
        final_blocks=[
            {"position": {"x": 0, "y": 64, "z": 0}, "block_type": "stone"},
            {"position": {"x": 1, "y": 64, "z": 0}, "block_type": "stone"},
        ],
    )
    partial_plan = _structure_observation(
        steps=[
            {
                "index": 0,
                "action": "place",
                "position": {"x": 0, "y": 64, "z": 0},
                "block_type": "stone",
                "final_block": "stone",
            },
            {
                "index": 1,
                "action": "place",
                "position": {"x": 1, "y": 64, "z": 0},
                "block_type": "stone",
                "final_block": "air",
            },
        ],
        final_blocks=[
            {"position": {"x": 0, "y": 64, "z": 0}, "block_type": "stone"},
            {"position": {"x": 1, "y": 64, "z": 0}, "block_type": "air"},
        ],
        outcome_class="success",
    )

    assert verify_build_plan(full_plan)["verified"] is True
    partial_result = verify_build_plan(partial_plan)
    assert partial_result["verified"] is False
    assert partial_result["class"] == "partial"
    assert partial_result["completion"] == 0.5

    observation = _snapshot_observation()
    snapshot = build_perception_snapshot([{"type": "pose"}, observation])
    assert snapshot is not None
    assert snapshot.pose.dimension == "overworld"
    assert snapshot.nearby_blocks[0].block_type == "oak_planks"
    assert is_schema_valid_snapshot(observation) is True

    budget = RetryBudget(max_attempts=2)
    assert classify({"error": {"code": "bridge_timeout"}}, source="bridge") == "timeout"
    assert decide_safe_fail("blocked", attempt=1, budget=budget)["action"] == "idle"
    assert decide_safe_fail("timeout", attempt=1, budget=budget)["action"] == "retry"
    assert decide_safe_fail("timeout", attempt=2, budget=budget)["next_backoff_ms"] == 1000
    assert decide_safe_fail("timeout", attempt=3, budget=budget)["action"] == "abandon"
    assert decide_safe_fail("bridge_connect_failed", attempt=1, budget=budget)["action"] == "abandon"


def test_fake_node_bridge_routes_embodiment_services_without_live_server() -> None:
    ping_request = make_bridge_request(payload={"message": "embodiment"})
    ping_env = c.BridgeRequest.model_validate(ping_request)
    assert ping_env.cost_context.estimated_cost_usd == 0.0

    perception_request = make_bridge_request(
        service="perception",
        method="report",
        payload={"observations": [_snapshot_observation()]},
    )
    perception_env = c.BridgeRequest.model_validate(perception_request)
    assert perception_env.cost_context.estimated_cost_usd == 0.0

    code_request = make_bridge_request(
        service="code",
        method="execute",
        payload={"language": "python", "code": "print(2 + 2)", "timeout": 5},
    )
    code_env = c.BridgeRequest.model_validate(code_request)
    assert code_env.cost_context.estimated_cost_usd == 0.0

    with FakeNodeBridgeClient() as client:
        ping = c.BridgeResponse.model_validate(client.call_raw(ping_request))
        perception = c.BridgeResponse.model_validate(client.call_raw(perception_request))
        code = c.BridgeResponse.model_validate(client.call_raw(code_request))

    assert c.validate_response(ping, service="bridge", method="ping").pong == "embodiment"
    assert c.validate_response(perception, service="perception", method="report").accepted is True
    assert code.ok is False
    assert code.error is not None
    assert code.error.code == ERR_CODE_SERVICE_UNAVAILABLE
    assert code.retryable is True
    assert c.validate_response(code, service="code", method="execute") is None


def test_package_json_wires_no_server_embodiment_integration_verifier() -> None:
    scripts = json.loads((REPO_ROOT / "package.json").read_text())["scripts"]

    assert (
        scripts.get("verify:embodiment-integration")
        == ".venv/bin/pytest tests/integration/test_embodiment_skills.py -v"
    )


def _stage_fork_with_real_bridge(tmp_path: Path) -> Path:
    root = tmp_path / "fork-src"
    commands = root / "agent" / "commands"
    skills = root / "agent" / "skills"
    bridge = root / "agent" / "bridge"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)

    (root / "package.json").write_text(json.dumps({"type": "module"}))
    for source in COMMAND_SRC.glob("*.js"):
        shutil.copy2(source, commands / source.name)
    for source in SKILL_SRC.glob("*.js"):
        shutil.copy2(source, skills / source.name)

    copied_bridge = copy_bridge_client_with_header_ws(tmp_path)
    shutil.copy2(copied_bridge, bridge / "python_bridge.js")
    shutil.copytree(copied_bridge.parent / "node_modules", bridge / "node_modules")
    assert (bridge / "python_bridge.js").read_text() == BRIDGE_CLIENT_SRC.read_text()
    return root


def _run_node_harness(tmp_path: Path, source: str, env: dict[str, str]) -> dict[str, Any]:
    if NODE is None:
        raise RuntimeError("node is not available")

    harness = tmp_path / "embodiment_skill_harness.mjs"
    harness.write_text(source)
    proc = subprocess.run(
        [NODE, str(harness)],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), **env},
        cwd=tmp_path,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"node exited {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _fake_python_bridge_server_or_skip() -> FakePythonBridgeServer:
    try:
        port = free_local_port()
    except PermissionError as exc:
        pytest.skip(f"local sandbox forbids loopback sockets: {exc}")
    return FakePythonBridgeServer(port=port)


@requires_node
def test_committed_node_bridge_client_reaches_fake_python_server(tmp_path: Path) -> None:
    bridge_module = copy_bridge_client_with_header_ws(tmp_path)
    with _fake_python_bridge_server_or_skip() as server:
        result = run_node_bridge_call(
            tmp_path,
            bridge_module=bridge_module,
            env=server.node_env(),
            message="embodiment-ping",
        )

    assert result["status"] == "ok", result
    assert result["response"]["payload"] == {"pong": "embodiment-ping"}
    assert result["response"]["trace_id"].startswith("trace-")


@requires_node
def test_node_embodiment_commands_emit_schema_valid_bridge_frames_without_minecraft(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    staged = _stage_fork_with_real_bridge(tmp_path)
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

const root = {json.dumps(str(staged))};
const command = async (name) => import(pathToFileURL(`${{root}}/agent/commands/${{name}}`).href);
const skill = async (name) => import(pathToFileURL(`${{root}}/agent/skills/${{name}}`).href);

const moveMod = await command('move_action.js');
const navigateMod = await command('navigate_action.js');
const placeMod = await command('place_action.js');
const breakMod = await command('break_action.js');
const buildMod = await command('build_from_plan_action.js');
const observeMod = await command('observe_action.js');
const codeMod = await command('execute_code_action.js');

const movement = await skill('movement.js');
const building = await skill('building.js');
const buildPlan = await skill('build_plan.js');
const perception = await skill('perception.js');
const safeFail = await skill('safe_fail.js');

const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{
    name,
    position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }},
}});
const world = new Map([
    ['0,63,0', 'stone'],
    ['1,63,0', 'stone'],
    ['2,64,0', 'stone'],
    ['4,63,0', 'stone'],
    ['4,64,0', 'air'],
    ['5,63,0', 'stone'],
    ['5,64,0', 'air'],
]);
const position = {{ x: 0, y: 64, z: 0 }};
const bot = {{
    username: 'EmbodimentHarnessBot',
    entity: {{ position, yaw: 0, pitch: 0.1, onGround: true }},
    game: {{ dimension: 'minecraft:overworld' }},
    time: {{ age: 321 }},
    heldItem: {{ name: 'minecraft:Stone Pickaxe', count: 1 }},
    entities: {{
        zombie: {{ id: 7, type: 'mob', name: 'minecraft:Zombie', position: {{ x: 0, y: 64, z: 1 }} }},
    }},
    inventory: {{
        slots: [
            {{ name: 'oak_planks', count: 16, slot: 0 }},
            {{ name: 'stone_pickaxe', count: 1, slot: 1 }},
        ],
        items() {{ return this.slots.map((item, slot) => item ? {{ ...item, slot }} : null).filter(Boolean); }},
    }},
    pathfinder: {{
        async goto(goal) {{
            position.x = Number(goal.x);
            position.y = Number(goal.y);
            position.z = Number(goal.z);
            bot.entity.position = position;
        }},
        stop() {{}},
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{ name: 'vera', bot }};

const helperProbe = {{
    movement: movement.classifyMovement({{
        before: {{ x: 0, y: 64, z: 0 }},
        after: {{ x: 0, y: 64, z: 1 }},
        target: {{ x: 0, y: 64, z: 1 }},
        tolerance: 0.5,
    }}),
    place: building.classifyPlace({{ afterBlock: 'oak_planks', blockType: 'minecraft:oak_planks' }}),
    plan: buildPlan.classifyPlan({{
        metric: {{
            intended_count: 1,
            blocks_present: 1,
            blocks_missing: 0,
            blocks_unexpected: 0,
            steps_verified: 1,
            steps_abandoned: 0,
            completion_ratio: 1,
        }},
    }}),
    perception: perception.perceptionObservation({{
        pose: perception.poseFrom(bot),
        blocks: [],
        entities: [],
        inventory: perception.inventorySnapshot(bot, null, true),
        radius: 1,
        scope: 'all',
        includeAir: false,
        tick: bot.time.age,
    }}).type,
    safeFail: safeFail.decideSafeFail('bridge_unreachable', 1).action,
}};

const results = {{}};
results.move = await moveMod.moveAction.perform(agent, 'move-it', 'south', 2, 1000);
results.navigate = await navigateMod.navigateAction.perform(agent, 'nav-it', {{ x: 6, y: 64, z: -3 }}, 1, 1000);
results.place = await placeMod.placeAction.perform(agent, 'place-it', 'oak_planks', {{ x: 4, y: 64, z: 0 }}, 'up', 0);
results.break = await breakMod.breakAction.perform(agent, 'break-it', {{ x: 2, y: 64, z: 0 }}, 'stone', 1);
results.build = await buildMod.buildFromPlanAction.perform(
    agent,
    'build-it',
    {{ x: 4, y: 64, z: 0 }},
    {{
        palette: {{ wall: 'minecraft:oak_planks' }},
        blocks: [
            {{ dx: 0, dy: 0, dz: 0, block_type: 'wall' }},
            {{ dx: 1, dy: 0, dz: 0, block_type: 'wall' }},
        ],
    }},
    2,
    10000,
);
results.observe = await observeMod.observeAction.perform(agent, 2, 'all', false);
results.code = await codeMod.executeCodeAction.perform(
    {{ name: 'rex' }},
    'python',
    'print(2 + 2)',
    5,
);

process.stdout.write(JSON.stringify({{
    status: 'ok',
    helperProbe,
    results,
    finalWorld: {{
        placed: world.get('4,64,0'),
        built: world.get('5,64,0'),
        broken: world.get('2,64,0'),
    }},
}}) + '\\n');
"""

    with _fake_python_bridge_server_or_skip() as server:
        result = _run_node_harness(
            tmp_path,
            harness,
            {
                **server.node_env(),
                "LTAG_AGENT_ID": "vera",
                "LTAG_RUN_ID": "run-embodiment-integration",
                "LTAG_SIMULATION_ID": "00000000-0000-0000-0000-000000000563",
                "MINECRAFT_BRIDGE_CIRCUIT_THRESHOLD": "10",
                "MINECRAFT_BRIDGE_RECONNECT_BASE_MS": "10",
                "MINECRAFT_BRIDGE_RECONNECT_MAX_MS": "50",
            },
        )

    assert result["status"] == "ok"
    assert result["helperProbe"] == {
        "movement": "reached",
        "place": "placed",
        "plan": "success",
        "perception": "perception_snapshot",
        "safeFail": "idle",
    }
    assert result["finalWorld"] == {
        "placed": "oak_planks",
        "built": "oak_planks",
        "broken": "air",
    }
    assert "reached:" in result["results"]["move"]
    assert "reached:" in result["results"]["navigate"]
    assert "placed:" in result["results"]["place"]
    assert "removed:" in result["results"]["break"]
    assert "success:" in result["results"]["build"]
    assert "observe all:" in result["results"]["observe"]
    assert result["results"]["code"].startswith("code execution failed [")

    action_by_id = {event["action_id"]: event for event in captured_bridge_events["action"]}
    assert action_by_id["move-it"]["status"] == "success"
    assert action_by_id["nav-it"]["status"] == "success"
    assert action_by_id["place-it"]["status"] == "success"
    assert action_by_id["break-it"]["status"] == "success"
    assert action_by_id["build-it"]["status"] == "success"

    observations = [
        observation
        for event in captured_bridge_events["perception"]
        for observation in event["observations"]
    ]
    by_action = {
        observation.get("action_id"): observation
        for observation in observations
        if observation.get("action_id")
    }

    assert verify_movement(by_action["move-it"])["verified"] is True
    assert verify_movement(by_action["nav-it"])["verified"] is True
    assert verify_place(by_action["place-it"])["verified"] is True
    assert verify_break(by_action["break-it"])["verified"] is True
    assert verify_build_plan(by_action["build-it"])["verified"] is True

    snapshots = [obs for obs in observations if obs.get("type") == "perception_snapshot"]
    assert snapshots
    assert any(is_schema_valid_snapshot(snapshot) for snapshot in snapshots)
    c.PerceptionSnapshot.model_validate(
        next(event["snapshot"] for event in captured_bridge_events["perception"] if "snapshot" in event)
    )

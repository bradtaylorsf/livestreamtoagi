"""Regression tests for E8-14 Mindcraft action interruption recovery (#720)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
ACTION_INTERRUPTION = FORK_SRC / "agent" / "skills" / "action_interruption.js"
MOVEMENT_HELPERS = FORK_SRC / "agent" / "skills" / "movement.js"
BUILDING_HELPERS = FORK_SRC / "agent" / "skills" / "building.js"
MOVE_ACTION = FORK_SRC / "agent" / "commands" / "move_action.js"
NAVIGATE_ACTION = FORK_SRC / "agent" / "commands" / "navigate_action.js"
PLACE_ACTION = FORK_SRC / "agent" / "commands" / "place_action.js"
PLACE_HERE_GUARD = FORK_SRC / "agent" / "commands" / "place_here_guard.js"
CONNECT_BRIDGE_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
CONNECT_ALPHA_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-alpha-bot.sh"
CONNECT_COHORT_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-cohort-bot.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")

PATH_STOPPED = "PathStopped: Path was stopped before it could be completed"


def _run_node_harness(tmp_path: Path, source: str, env: dict[str, str] | None = None) -> dict:
    harness = tmp_path / "interruption_harness.mjs"
    harness.write_text(source, encoding="utf-8")
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


def _stage_stub_bridge(root: Path) -> Path:
    bridge = root / "bridge"
    bridge.mkdir(parents=True)
    calls_path = root.parent.parent / "bridge_calls.jsonl"
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
""".lstrip(),
        encoding="utf-8",
    )
    return calls_path


def _stage_action(tmp_path: Path, action_src: Path, action_filename: str, helper_src: Path) -> tuple[Path, Path]:
    root = tmp_path / "fork-src" / "agent"
    commands = root / "commands"
    skills = root / "skills"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    shutil.copy2(action_src, commands / action_filename)
    shutil.copy2(helper_src, skills / helper_src.name)
    shutil.copy2(ACTION_INTERRUPTION, skills / "action_interruption.js")
    calls_path = _stage_stub_bridge(root)
    return commands / action_filename, calls_path


def _read_calls(calls_path: Path) -> list[dict]:
    return [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]


def test_interruption_classifier_covers_alpha_pathstopped_signature() -> None:
    assert ACTION_INTERRUPTION.is_file()
    src = ACTION_INTERRUPTION.read_text(encoding="utf-8")
    assert "PathStopped" in src
    assert "path was stopped before it could be completed" in src
    assert "mode:unstuck" in src
    assert "interrupted" in src


@requires_node
@pytest.mark.parametrize(
    ("action_src", "action_filename", "export_name", "perform_args"),
    [
        (
            MOVE_ACTION,
            "move_action.js",
            "moveAction",
            "'move-pathstopped', 'south', 2, 1000",
        ),
        (
            NAVIGATE_ACTION,
            "navigate_action.js",
            "navigateAction",
            "'navigate-pathstopped', { x: 2, y: 64, z: 0 }, 1.0, 1000",
        ),
    ],
)
def test_pathstopped_movement_actions_report_interrupted_without_crashing(
    tmp_path: Path,
    action_src: Path,
    action_filename: str,
    export_name: str,
    perform_args: str,
) -> None:
    action_path, calls_path = _stage_action(
        tmp_path, action_src, action_filename, MOVEMENT_HELPERS
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

const mod = await import(pathToFileURL({json.dumps(str(action_path))}).href);
let stopCount = 0;
const position = {{ x: 0, y: 64, z: 0 }};
const bot = {{
    username: 'InterruptHarnessBot',
    entity: {{ position, yaw: 0 }},
    pathfinder: {{
        async goto() {{
            throw new Error({json.dumps(PATH_STOPPED)});
        }},
        stop() {{
            stopCount += 1;
        }},
    }},
}};
const result = await mod.{export_name}.perform(
    {{ name: 'alpha', bot, openChat: () => {{}} }},
    {perform_args},
);
process.stdout.write(JSON.stringify({{ status: 'ok', result, stopCount }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(calls_path), "LTAG_AGENT_ID": "alpha"},
    )
    calls = _read_calls(calls_path)
    action_call = next(call for call in calls if call["service"] == "action")
    perception_call = next(call for call in calls if call["service"] == "perception")
    observation = perception_call["payload"]["observations"][0]

    assert result["status"] == "ok"
    assert result["stopCount"] == 1
    assert "interrupted:" in result["result"]
    assert observation["class"] == "interrupted"
    assert action_call["payload"]["status"] == "failure"
    assert action_call["payload"]["outcome_class"] == "interrupted"
    assert "interrupted:" in action_call["payload"]["detail"]
    assert PATH_STOPPED in action_call["payload"]["detail"]


@requires_node
def test_pathstopped_place_action_reports_interrupted_without_crashing(tmp_path: Path) -> None:
    action_path, calls_path = _stage_action(tmp_path, PLACE_ACTION, "place_action.js", BUILDING_HELPERS)
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
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'stone'],
    ['0,64,0', 'air'],
]);
const bot = {{
    username: 'PlaceInterruptHarnessBot',
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
        throw new Error({json.dumps(PATH_STOPPED)});
    }},
}};
const result = await mod.placeAction.perform(
    {{ name: 'alpha', bot, openChat: () => {{}} }},
    'place-pathstopped',
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
        {"BRIDGE_CALLS_PATH": str(calls_path), "LTAG_AGENT_ID": "alpha"},
    )
    calls = _read_calls(calls_path)
    action_call = next(call for call in calls if call["service"] == "action")
    perception_call = next(call for call in calls if call["service"] == "perception")
    observation = perception_call["payload"]["observations"][0]

    assert result["status"] == "ok"
    assert result["finalBlock"] == "air"
    assert "interrupted:" in result["result"]
    assert observation["class"] == "interrupted"
    assert action_call["payload"]["status"] == "failure"
    assert action_call["payload"]["outcome_class"] == "interrupted"
    assert PATH_STOPPED in action_call["payload"]["detail"]


@requires_node
def test_place_here_guard_converts_upstream_pathstopped_to_action_result(tmp_path: Path) -> None:
    root = tmp_path / "fork-src" / "agent"
    commands = root / "commands"
    skills = root / "skills"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    shutil.copy2(PLACE_HERE_GUARD, commands / "place_here_guard.js")
    shutil.copy2(ACTION_INTERRUPTION, skills / "action_interruption.js")
    calls_path = _stage_stub_bridge(root)
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

const mod = await import(pathToFileURL({json.dumps(str(commands / "place_here_guard.js"))}).href);
const guarded = mod.wrapPlaceHere(async () => {{
    throw new Error({json.dumps(PATH_STOPPED)});
}});
const result = await guarded({{ name: 'alpha', bot: {{ username: 'Alpha' }} }}, 'oak_log');
process.stdout.write(JSON.stringify({{ status: 'ok', result }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(calls_path), "LTAG_AGENT_ID": "alpha"},
    )
    calls = _read_calls(calls_path)
    action_call = next(call for call in calls if call["service"] == "action")

    assert result["status"] == "ok"
    assert "!placeHere" in result["result"]
    assert "interrupted:" in result["result"]
    assert action_call["payload"]["status"] == "failure"
    assert action_call["payload"]["outcome_class"] == "interrupted"
    assert "interrupted:" in action_call["payload"]["detail"]
    assert PATH_STOPPED in action_call["payload"]["detail"]


@requires_node
def test_place_here_guard_flags_repeated_failed_target(tmp_path: Path) -> None:
    root = tmp_path / "fork-src" / "agent"
    commands = root / "commands"
    skills = root / "skills"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    shutil.copy2(PLACE_HERE_GUARD, commands / "place_here_guard.js")
    shutil.copy2(ACTION_INTERRUPTION, skills / "action_interruption.js")
    _stage_stub_bridge(root)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(commands / "place_here_guard.js"))}).href);
const guarded = mod.wrapPlaceHere(async () => 'Action output:\\nFailed to place cobblestone at (1, 65, 2).');
const agent = {{ name: 'rex', bot: {{ username: 'Rex' }} }};
const first = await guarded(agent, 'cobblestone');
const second = await guarded(agent, 'cobblestone');
process.stdout.write(JSON.stringify({{ first, second }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(tmp_path / "bridge_calls.jsonl"), "LTAG_AGENT_ID": "rex"},
    )

    assert "repeated_failure" not in result["first"]
    assert "repeated_failure" in result["second"]
    assert "choose a different target" in result["second"]


def test_launchers_stage_interruption_guard_and_clean_exit_gate() -> None:
    for script in (CONNECT_BRIDGE_SCRIPT, CONNECT_ALPHA_SCRIPT, CONNECT_COHORT_SCRIPT):
        src = script.read_text(encoding="utf-8")
        assert "ACTION_INTERRUPTION_SKILL_REL" in src
        assert "PLACE_HERE_GUARD_REL" in src
        assert "wrapInterruptedActions" in src
        assert "LTAG E8-14 action interruption guard" in src
        assert "const actionName = actionObj && typeof actionObj.name === 'string'" in src
        assert "interrupted before completion" in src
        assert "MINECRAFT_CLEAN_EXIT" in src
        assert "this.bot.chat(code > 1 ? 'Restarting.': 'Exiting.')" in src
        assert "clean exit chat gate" in src
        assert "MODES_UNSTUCK_PATCH_MARKER" in src
        assert "effectiveMaxStuckTime" in src
        assert "/action:(placeHere|collectBlocks|followPlayer)/" in src
        assert "unstuck timed out before recovery" in src
        assert "interrupted: unstuck-failed: timed out before recovery" in src
        assert "Promise.race([skills.moveAway(bot, 5), unstuckTimeout])" in src
        assert "ACTION_MANAGER_NO_KILL_PATCH_MARKER" in src
        assert "action-stop-timeout" in src
        assert "forcing idle without process exit" in src
        assert "action-manager no-kill patch" in src
        assert "[behavior-status]" in src


def test_package_json_exposes_action_interruption_verifier() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]
    assert scripts["verify:embodiment-action-interruption"] == (
        ".venv/bin/pytest tests/backend/test_embodiment_action_interruption.py -v"
    )

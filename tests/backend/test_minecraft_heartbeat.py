"""Tests for E8-15 autonomous Mindcraft heartbeat idle recovery."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
HEARTBEAT = FORK_SRC / "agent" / "skills" / "heartbeat.js"
CONNECT_BRIDGE = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
CONNECT_ALPHA = REPO_ROOT / "scripts" / "minecraft" / "connect-alpha-bot.sh"
CONNECT_VERA = REPO_ROOT / "scripts" / "minecraft" / "connect-vera-bot.sh"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node_harness(tmp_path: Path, source: str) -> dict:
    harness = tmp_path / "heartbeat_harness.mjs"
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


def test_heartbeat_skill_exports_bounded_runtime_contract() -> None:
    src = HEARTBEAT.read_text(encoding="utf-8")
    assert "installHeartbeat" in src
    assert "MC_HEARTBEAT_IDLE_MS" in src
    assert "MC_HEARTBEAT_COOLDOWN_MS" in src
    assert "MC_HEARTBEAT_MAX_NO_COMMAND" in src
    for event_type in (
        "heartbeat.fired",
        "heartbeat.skipped",
        "heartbeat.outcome",
        "heartbeat.halted",
    ):
        assert event_type in src
    assert "per-tick movement" in src


@requires_node
def test_idle_detection_fires_next_action_prompt_after_threshold(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 0;
const events = [];
const calls = [];
const routed = [];
const agent = {{
    name: 'vera',
    async handleMessage(source, message, maxResponses) {{
        calls.push({{ source, message, maxResponses }});
        return this.routeResponse(null, '!move("heartbeat-scout", "forward", 2)');
    }},
    async routeResponse(_toPlayer, message) {{
        routed.push(message);
        return message;
    }},
    openChat() {{}},
    actions: {{}},
}};

const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: (event) => events.push(event),
    idleMs: 100,
    cooldownMs: 50,
    staleActionMs: 1000,
    maxNoCommand: 3,
}});

now = 99;
const before = await heartbeat.tick();
now = 100;
const after = await heartbeat.tick();

process.stdout.write(JSON.stringify({{
    before,
    after,
    calls,
    routed,
    eventTypes: events.map((event) => event.type),
    outcome: events.find((event) => event.type === 'heartbeat.outcome')?.payload,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["before"]["fired"] is False
    assert result["after"]["fired"] is True
    assert result["after"]["reason"] == "idle"
    assert result["calls"][0]["source"] == "system"
    assert result["calls"][0]["maxResponses"] == 1
    assert "visible high-level next action" in result["calls"][0]["message"]
    assert result["routed"] == ['!move("heartbeat-scout", "forward", 2)']
    assert result["eventTypes"] == ["heartbeat.fired", "heartbeat.outcome"]
    assert result["outcome"]["had_command"] is True
    assert result["outcome"]["no_command_streak"] == 0


@requires_node
def test_plan_mode_heartbeat_prompt_avoids_standalone_place_commands(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.MC_SIM_BUILD_MODE = 'plan';
const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 1000;
const calls = [];
const agent = {{
    name: 'rex',
    async handleMessage(source, message, maxResponses) {{
        calls.push({{ source, message, maxResponses }});
        return 'Checking inventory before the cabin plan. !inventory';
    }},
    actions: {{}},
}};

const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: () => {{}},
    idleMs: 0,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 3,
}});
await heartbeat.tick();

process.stdout.write(JSON.stringify({{ calls }}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    prompt = result["calls"][0]["message"]
    assert "If you are the build owner and !planAndBuild is available" in prompt
    assert "!placeHere" not in prompt
    assert "standalone block placement" in prompt


@requires_node
def test_settlement_mode_heartbeat_prompt_prefers_plan_build_owner_command(
    tmp_path: Path,
) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.MC_SIM_BUILD_MODE = 'settlement';
const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 1000;
const calls = [];
const agent = {{
    name: 'rex',
    async handleMessage(source, message, maxResponses) {{
        calls.push({{ source, message, maxResponses }});
        return 'Starting the active build. !planAndBuild("Team Ember crafting shelter")';
    }},
    actions: {{}},
}};

const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: () => {{}},
    idleMs: 0,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 3,
}});
await heartbeat.tick();

process.stdout.write(JSON.stringify({{ calls }}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    prompt = result["calls"][0]["message"]
    assert "If you are the build owner and !planAndBuild is available" in prompt
    assert "!placeHere" not in prompt
    assert "standalone block placement" in prompt


@requires_node
def test_plan_mode_chat_response_satisfies_heartbeat_without_command(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.MC_SIM_BUILD_MODE = 'plan';
const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 1;
const events = [];
const agent = {{
    name: 'fork',
    async handleMessage() {{
        await this.routeResponse(null, 'I can support Rex from here and keep watching the cabin.');
        return undefined;
    }},
    async routeResponse() {{
        return undefined;
    }},
    self_prompter: {{
        async stop() {{
            throw new Error('plan-mode support chat should not halt');
        }},
    }},
    actions: {{}},
}};
const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: (event) => events.push(event),
    idleMs: 0,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 2,
}});
heartbeat.state.consecutiveNoCommand = 1;

const result = await heartbeat.tick();

process.stdout.write(JSON.stringify({{
    result,
    halted: heartbeat.state.halted,
    noCommandStreak: heartbeat.state.consecutiveNoCommand,
    eventTypes: events.map((event) => event.type),
    outcome: events.find((event) => event.type === 'heartbeat.outcome')?.payload,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["result"]["fired"] is True
    assert result["result"]["hadCommand"] is False
    assert result["halted"] is False
    assert result["noCommandStreak"] == 0
    assert result["eventTypes"] == ["heartbeat.fired", "heartbeat.outcome"]
    assert result["outcome"]["outcome"] == "chat"
    assert result["outcome"]["chat_satisfied_heartbeat"] is True
    assert result["outcome"]["no_command_streak"] == 0


@requires_node
def test_settlement_mode_support_chat_satisfies_heartbeat_without_command(
    tmp_path: Path,
) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.MC_SIM_BUILD_MODE = 'settlement';
const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 1;
const events = [];
const agent = {{
    name: 'sentinel',
    async handleMessage() {{
        await this.routeResponse(null, 'I can scout the route and report hazards while Rex builds.');
        return undefined;
    }},
    async routeResponse() {{
        return undefined;
    }},
    self_prompter: {{
        async stop() {{
            throw new Error('settlement support chat should not halt');
        }},
    }},
    actions: {{}},
}};
const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: (event) => events.push(event),
    idleMs: 0,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 2,
}});
heartbeat.state.consecutiveNoCommand = 1;

const result = await heartbeat.tick();

process.stdout.write(JSON.stringify({{
    result,
    halted: heartbeat.state.halted,
    noCommandStreak: heartbeat.state.consecutiveNoCommand,
    eventTypes: events.map((event) => event.type),
    outcome: events.find((event) => event.type === 'heartbeat.outcome')?.payload,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["result"]["fired"] is True
    assert result["result"]["hadCommand"] is False
    assert result["halted"] is False
    assert result["noCommandStreak"] == 0
    assert result["eventTypes"] == ["heartbeat.fired", "heartbeat.outcome"]
    assert result["outcome"]["outcome"] == "chat"
    assert result["outcome"]["chat_satisfied_heartbeat"] is True
    assert result["outcome"]["no_command_streak"] == 0


@requires_node
def test_heartbeat_cooldown_suppresses_double_fire(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 1;
const events = [];
let calls = 0;
const agent = {{
    name: 'rex',
    async handleMessage() {{
        calls += 1;
        return '!inventory';
    }},
    actions: {{}},
}};
const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: (event) => events.push(event),
    idleMs: 0,
    cooldownMs: 100,
    staleActionMs: 1000,
    maxNoCommand: 3,
}});

const first = await heartbeat.tick();
now = 50;
const second = await heartbeat.tick();

process.stdout.write(JSON.stringify({{
    first,
    second,
    calls,
    eventTypes: events.map((event) => event.type),
    skipped: events.find((event) => event.type === 'heartbeat.skipped')?.payload,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["first"]["fired"] is True
    assert result["second"]["fired"] is False
    assert result["second"]["reason"] == "cooldown"
    assert result["calls"] == 1
    assert result["eventTypes"] == ["heartbeat.fired", "heartbeat.outcome", "heartbeat.skipped"]
    assert result["skipped"]["reason"] == "cooldown"
    assert result["skipped"]["cooldown_remaining_ms"] == 51


@requires_node
def test_director_suppressed_heartbeat_does_not_increment_no_command_streak(
    tmp_path: Path,
) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 1;
const events = [];
const agent = {{
    name: 'aurora',
    __ltagDirectorGate: {{
        sequence: 0,
        latestSequence: 0,
        lastOutcome: null,
    }},
    async handleMessage() {{
        this.__ltagDirectorGate.sequence += 1;
        this.__ltagDirectorGate.lastOutcome = {{
            sequence: this.__ltagDirectorGate.sequence,
            selected: false,
            outcome: 'director_suppressed',
        }};
        return false;
    }},
    actions: {{}},
}};
const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: (event) => events.push(event),
    idleMs: 0,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 1,
}});

const first = await heartbeat.tick();
now = 2;
const second = await heartbeat.tick();

process.stdout.write(JSON.stringify({{
    first,
    second,
    halted: heartbeat.state.halted,
    noCommandStreak: heartbeat.state.consecutiveNoCommand,
    eventTypes: events.map((event) => event.type),
    outcomes: events
        .filter((event) => event.type === 'heartbeat.outcome')
        .map((event) => event.payload),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["first"]["fired"] is True
    assert result["first"]["hadCommand"] is False
    assert result["first"]["noCommandStreak"] == 0
    assert result["second"]["fired"] is True
    assert result["halted"] is False
    assert result["noCommandStreak"] == 0
    assert "heartbeat.halted" not in result["eventTypes"]
    assert [outcome["outcome"] for outcome in result["outcomes"]] == [
        "director-suppressed",
        "director-suppressed",
    ]
    assert all(outcome["director_suppressed"] is True for outcome in result["outcomes"])


@requires_node
def test_mindcraft_boolean_true_counts_as_command_without_true_excerpt(
    tmp_path: Path,
) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 1;
const events = [];
const agent = {{
    name: 'rex',
    async handleMessage() {{
        return true;
    }},
    actions: {{}},
}};
const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: (event) => events.push(event),
    idleMs: 0,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 3,
}});
heartbeat.state.consecutiveNoCommand = 2;

const result = await heartbeat.tick();

process.stdout.write(JSON.stringify({{
    result,
    noCommandStreak: heartbeat.state.consecutiveNoCommand,
    outcome: events.find((event) => event.type === 'heartbeat.outcome')?.payload,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["result"]["fired"] is True
    assert result["result"]["hadCommand"] is True
    assert result["noCommandStreak"] == 0
    assert result["outcome"]["outcome"] == "command"
    assert result["outcome"]["response_empty"] is True
    assert result["outcome"]["response_excerpt"] == ""


@requires_node
def test_active_action_suppresses_until_stale_timeout(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 500;
const events = [];
let calls = 0;
const agent = {{
    name: 'aurora',
    async handleMessage() {{
        calls += 1;
        return '!placeHere("cobblestone")';
    }},
    actions: {{ active: true, currentActionLabel: 'build-marker' }},
}};
const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: (event) => events.push(event),
    idleMs: 100,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 3,
}});
heartbeat.state.lastResponseTs = 0;
heartbeat.state.lastChatTs = 0;
heartbeat.state.lastCommandTs = 0;
heartbeat.state.lastCommandIssuedTs = 0;

const active = await heartbeat.tick();
now = 1200;
const stale = await heartbeat.tick();

process.stdout.write(JSON.stringify({{
    active,
    stale,
    calls,
    events: events.map((event) => ({{ type: event.type, payload: event.payload }})),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["active"]["fired"] is False
    assert result["active"]["reason"] == "active-action"
    assert result["stale"]["fired"] is True
    assert result["stale"]["reason"] == "stale-action"
    assert result["calls"] == 1
    assert result["events"][0]["type"] == "heartbeat.skipped"
    assert result["events"][0]["payload"]["reason"] == "active-action"
    assert result["events"][1]["type"] == "heartbeat.fired"


@requires_node
def test_max_no_command_halts_heartbeat_and_stops_self_prompter(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const {{ installHeartbeat }} = await import(pathToFileURL({json.dumps(str(HEARTBEAT))}).href);
let now = 1;
const events = [];
const stopCalls = [];
const agent = {{
    name: 'pixel',
    async handleMessage() {{
        return 'I am still deciding.';
    }},
    self_prompter: {{
        async stop(stopAction) {{
            stopCalls.push(stopAction);
        }},
    }},
    actions: {{}},
}};
const heartbeat = installHeartbeat(agent, {{
    autoStart: false,
    now: () => now,
    emit: (event) => events.push(event),
    idleMs: 0,
    cooldownMs: 0,
    staleActionMs: 1000,
    maxNoCommand: 2,
}});

const first = await heartbeat.tick();
now = 2;
const second = await heartbeat.tick();
now = 3;
const third = await heartbeat.tick();

process.stdout.write(JSON.stringify({{
    first,
    second,
    third,
    halted: heartbeat.state.halted,
    stopCalls,
    eventTypes: events.map((event) => event.type),
    haltedPayload: events.find((event) => event.type === 'heartbeat.halted')?.payload,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["first"]["fired"] is True
    assert result["first"]["hadCommand"] is False
    assert result["second"]["fired"] is True
    assert result["second"]["noCommandStreak"] == 2
    assert result["halted"] is True
    assert result["stopCalls"] == [False]
    assert result["third"]["fired"] is False
    assert result["third"]["reason"] == "halted"
    assert result["eventTypes"].count("heartbeat.outcome") == 2
    assert "heartbeat.halted" in result["eventTypes"]
    assert result["haltedPayload"]["reason"] == "max-no-command"
    assert result["haltedPayload"]["no_command_streak"] == 2


def test_connect_launchers_stage_and_install_heartbeat() -> None:
    for script in (CONNECT_BRIDGE, CONNECT_ALPHA, CONNECT_VERA):
        proc = subprocess.run(
            ["bash", str(script), "--verify"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    for script in (CONNECT_BRIDGE, CONNECT_ALPHA, REPO_ROOT / "scripts" / "minecraft" / "connect-cohort-bot.sh"):
        text = script.read_text(encoding="utf-8")
        assert "HEARTBEAT_SKILL_REL" in text
        assert "src/agent/skills/heartbeat.js" in text
        assert "LTAG E8-15 autonomous heartbeat" in text
        assert "installHeartbeat(this)" in text

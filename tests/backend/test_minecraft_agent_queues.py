"""Node harness tests for staged Minecraft multi-agent queues."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
ACTION_QUEUE = FORK_SRC / "agent" / "skills" / "action_queue.js"
INBOX_QUEUE = FORK_SRC / "agent" / "skills" / "inbox_queue.js"
DIRECTOR_GATE = FORK_SRC / "agent" / "skills" / "director_gate.js"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node_harness(tmp_path: Path, source: str) -> dict:
    harness = tmp_path / "queue_harness.mjs"
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


def _stage_skill_tree(tmp_path: Path, skill_path: Path) -> Path:
    root = tmp_path / "fork-src"
    agent = root / "agent"
    skills = agent / "skills"
    bridge = agent / "bridge"
    commands = agent / "commands"
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)
    commands.mkdir(parents=True)
    (root / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    shutil.copy2(skill_path, skills / skill_path.name)
    (bridge / "timeline_emitter.js").write_text(
        """
export function emitTimelineEvent(event = {}) {
    globalThis.__timelineEvents = globalThis.__timelineEvents || [];
    globalThis.__timelineEvents.push(event);
}
""".lstrip(),
        encoding="utf-8",
    )
    (commands / "index.js").write_text(
        """
export function containsCommand(message = '') {
    const match = String(message).match(/!\\w+/);
    return match ? match[0] : null;
}
""".lstrip(),
        encoding="utf-8",
    )
    (agent / "conversation.js").write_text(
        "export default { isOtherAgent() { return true; } };\n",
        encoding="utf-8",
    )
    return skills / skill_path.name


@requires_node
def test_action_queue_serializes_second_action_instead_of_interrupting(tmp_path: Path) -> None:
    action_queue = _stage_skill_tree(tmp_path, ACTION_QUEUE)
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(action_queue))}).href);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
globalThis.__timelineEvents = [];

const order = [];
const manager = {{
    agent: {{ name: 'rex' }},
    executing: false,
    currentActionLabel: null,
    async _executeAction(label, fn) {{
        if (this.executing) throw new Error(`unexpected interrupt for ${{label}}`);
        this.executing = true;
        this.currentActionLabel = label;
        try {{
            return await fn();
        }} finally {{
            this.executing = false;
            this.currentActionLabel = null;
        }}
    }},
}};

mod.installActionQueue(manager, {{ maxQueue: 4 }});
const first = manager._executeAction('action:first', async () => {{
    order.push('first-start');
    await sleep(40);
    order.push('first-end');
    return {{ success: true }};
}});
await sleep(5);
const second = manager._executeAction('action:second', async () => {{
    order.push('second-start');
    return {{ success: true }};
}});
const results = await Promise.all([first, second]);

process.stdout.write(JSON.stringify({{
    order,
    results,
    events: globalThis.__timelineEvents.map((event) => event.type),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["order"] == ["first-start", "first-end", "second-start"]
    assert [item["success"] for item in result["results"]] == [True, True]
    assert "action.queued" in result["events"]
    assert result["events"].count("action.started") == 2
    assert result["events"].count("action.completed") == 2


@requires_node
def test_inbox_queue_batches_and_defers_messages_arriving_during_generation(
    tmp_path: Path,
) -> None:
    inbox_queue = _stage_skill_tree(tmp_path, INBOX_QUEUE)
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(inbox_queue))}).href);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
globalThis.__timelineEvents = [];

const calls = [];
const agent = {{
    name: 'aurora',
    async handleMessage(source, message, maxResponses = null) {{
        calls.push({{ source, message, maxResponses }});
        if (calls.length <= 2) await sleep(35);
        return `handled-${{calls.length}}`;
    }},
}};

mod.installInboxQueue(agent, {{
    debounceMs: 5,
    maxBatch: 8,
    maxMessageChars: 120,
    maxBatchChars: 600,
}});

const batchA = agent.handleMessage('Vera', 'first batch message');
const batchB = agent.handleMessage('Rex', 'second batch message');
const batchResults = await Promise.all([batchA, batchB]);

const duringFirst = agent.handleMessage('Pixel', 'message before long turn');
await sleep(10);
const duringSecond = agent.handleMessage('Fork', 'message while model is generating');
const deferredResults = await Promise.all([duringFirst, duringSecond]);

process.stdout.write(JSON.stringify({{
    calls,
    batchResults,
    deferredResults,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert len(result["calls"]) == 3
    assert result["batchResults"] == ["handled-1", "handled-1"]
    assert (
        "Incoming message batch since your last turn (2 messages):" in result["calls"][0]["message"]
    )
    assert "first batch message" in result["calls"][0]["message"]
    assert "second batch message" in result["calls"][0]["message"]
    assert result["deferredResults"] == ["handled-2", "handled-3"]
    assert result["calls"][1]["message"] == "message before long turn"
    assert result["calls"][2]["message"] == "message while model is generating"
    event_types = [event["type"] for event in result["events"]]
    running_queue_events = [
        event
        for event in result["events"]
        if event["type"] == "inbox.queued" and event["payload"].get("running")
    ]
    assert event_types.count("inbox.turn_started") == 3
    assert event_types.count("inbox.turn_completed") == 3
    assert running_queue_events


@requires_node
def test_inbox_queue_ignores_mindcraft_command_echo_telemetry(
    tmp_path: Path,
) -> None:
    inbox_queue = _stage_skill_tree(tmp_path, INBOX_QUEUE)
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(inbox_queue))}).href);
globalThis.__timelineEvents = [];

const calls = [];
const agent = {{
    name: 'grok',
    async handleMessage(source, message, maxResponses = null) {{
        calls.push({{ source, message, maxResponses }});
        return 'handled';
    }},
}};

mod.installInboxQueue(agent, {{ debounceMs: 5 }});

const results = await Promise.all([
    agent.handleMessage('Sentinel', '*Pixel used break*'),
    agent.handleMessage('Sentinel', 'Command !break was given 0 args, but requires 4 args.'),
    agent.handleMessage('Pixel', '!break'),
]);

process.stdout.write(JSON.stringify({{
    calls,
    results,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["calls"] == []
    assert result["results"] == [False, False, False]
    telemetry_events = [
        event for event in result["events"] if event["type"] == "inbox.telemetry_ignored"
    ]
    assert len(telemetry_events) == 3
    assert {event["payload"]["message"] for event in telemetry_events} == {
        "*Pixel used break*",
        "Command !break was given 0 args, but requires 4 args.",
        "!break",
    }


@requires_node
def test_inbox_queue_keeps_human_commands_immediate(tmp_path: Path) -> None:
    inbox_queue = _stage_skill_tree(tmp_path, INBOX_QUEUE)
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(inbox_queue))}).href);
globalThis.__timelineEvents = [];

const calls = [];
const agent = {{
    name: 'vera',
    async handleMessage(source, message, maxResponses = null) {{
        calls.push({{ source, message, maxResponses }});
        return 'handled';
    }},
}};

mod.installInboxQueue(agent, {{
    debounceMs: 5,
    isOtherAgent() {{ return false; }},
}});

const result = await agent.handleMessage('Viewer', 'please !stop');

process.stdout.write(JSON.stringify({{
    calls,
    result,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["result"] == "handled"
    assert result["calls"] == [
        {"source": "Viewer", "message": "please !stop", "maxResponses": None}
    ]
    immediate_events = [
        event for event in result["events"] if event["type"] == "inbox.immediate_command"
    ]
    assert len(immediate_events) == 1
    assert immediate_events[0]["payload"]["source"] == "Viewer"
    assert immediate_events[0]["payload"]["command"] == "!stop"


@requires_node
def test_director_gate_suppresses_unselected_inbox_turns_before_llm(
    tmp_path: Path,
) -> None:
    inbox_queue = _stage_skill_tree(tmp_path, INBOX_QUEUE)
    skills = inbox_queue.parent
    shutil.copy2(DIRECTOR_GATE, skills / DIRECTOR_GATE.name)
    bridge = skills.parent / "bridge"
    (bridge / "python_bridge.js").write_text(
        """
export async function callBridge(opts = {}) {
    globalThis.__bridgeCalls = globalThis.__bridgeCalls || [];
    globalThis.__bridgeCalls.push(opts);
    const verdict = globalThis.__directorVerdicts.shift();
    return { ok: true, payload: verdict };
}
""".lstrip(),
        encoding="utf-8",
    )
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const inbox = await import(pathToFileURL({json.dumps(str(inbox_queue))}).href);
const gate = await import(pathToFileURL({json.dumps(str(skills / DIRECTOR_GATE.name))}).href);
globalThis.__timelineEvents = [];
globalThis.__bridgeCalls = [];
globalThis.__directorVerdicts = [
    {{
        selected: true,
        turn_kind: 'speaker',
        reason: 'weighted_scene_fit',
        scene_id: 'scene-1',
        scene_digest: 'viewer asked for one camp marker',
        role: 'host facilitator',
        local_observations: {{ scene_participants: ['vera', 'rex'] }},
        granted_tools: ['!placeHere'],
        queue_depth: 1,
        suppressed_agents: ['rex'],
    }},
    {{
        selected: false,
        turn_kind: null,
        reason: 'suppressed',
        suppression_reason: 'fanout_capped',
        scene_id: 'scene-1',
        scene_digest: 'viewer asked for one camp marker',
        role: 'builder',
        local_observations: {{}},
        granted_tools: [],
        queue_depth: 1,
        suppressed_agents: ['rex'],
    }},
];

const calls = [];
function makeAgent(name) {{
    return {{
        name,
        bot: {{ entity: {{ position: {{ x: 0, y: 64, z: 0 }} }} }},
        actions: {{
            actionList: ['!break', '!observe', '!place', '!placeHere', '!searchForBlock'],
        }},
        async handleMessage(source, message, maxResponses = null) {{
            calls.push({{ agent: name, source, message, maxResponses }});
            return `${{name}}-handled`;
        }},
    }};
}}

const vera = makeAgent('vera');
const rex = makeAgent('rex');
for (const agent of [vera, rex]) {{
    inbox.installInboxQueue(agent, {{ debounceMs: 5, maxBatch: 4 }});
    gate.installDirectorGate(agent, {{ enabled: true, deadlineMs: 100 }});
}}

const results = await Promise.all([
    vera.handleMessage('Viewer', 'Please place one shared camp marker.'),
    rex.handleMessage('Viewer', 'Please place one shared camp marker.'),
]);

process.stdout.write(JSON.stringify({{
    results,
    calls,
    bridgeCalls: globalThis.__bridgeCalls,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        agent: event.agent,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert result["results"] == ["vera-handled", False]
    assert len(result["calls"]) == 1
    assert result["calls"][0]["agent"] == "vera"
    assert result["calls"][0]["source"] == "system"
    assert "[Director V2 context]" in result["calls"][0]["message"]
    assert len(result["bridgeCalls"]) == 2
    assert {call["service"] for call in result["bridgeCalls"]} == {"director"}
    assert {call["method"] for call in result["bridgeCalls"]} == {"gate"}
    for call in result["bridgeCalls"]:
        tools = call["payload"]["available_tools"]
        assert "!placeHere" in tools
        assert "!searchForBlock" in tools
        assert "!break" not in tools
        assert "!observe" not in tools
        assert "!place" not in tools
    event_types = [event["type"] for event in result["events"]]
    assert "director_gate.selected" in event_types
    assert "director_gate.suppressed" in event_types
    canonical_decisions = [
        event for event in result["events"] if event["type"] == "director.gate.decision"
    ]
    assert [event["payload"]["selected"] for event in canonical_decisions] == [True, False]
    assert canonical_decisions[0]["payload"]["llm_prompt_count"] == 1
    assert canonical_decisions[1]["payload"]["avoided_prompt_count"] == 1
    assert {
        event["payload"].get("outcome")
        for event in result["events"]
        if event["type"] == "inbox.turn_completed"
    } >= {"ok", "director_suppressed"}


@requires_node
def test_director_gate_plan_mode_enrichment_avoids_standalone_place_commands(
    tmp_path: Path,
) -> None:
    director_gate = _stage_skill_tree(tmp_path, DIRECTOR_GATE)
    bridge = director_gate.parent.parent / "bridge"
    (bridge / "python_bridge.js").write_text(
        """
export async function callBridge(opts = {}) {
    globalThis.__bridgeCalls = globalThis.__bridgeCalls || [];
    globalThis.__bridgeCalls.push(opts);
    return {
        ok: true,
        payload: {
            selected: true,
            turn_kind: 'speaker',
            reason: 'support',
            scene_id: 'scene-cabin',
            scene_digest: 'one full log cabin house',
            role: 'support',
            local_observations: {},
            granted_tools: ['!placeHere', '!inventory', '!planAndBuild'],
            build_macro: {
                role: 'support',
                owner: 'rex',
                plan_id: 'plan-cabin',
                support_task: 'inventory check',
            },
            queue_depth: 1,
            suppressed_agents: [],
        },
    };
}
""".lstrip(),
        encoding="utf-8",
    )
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.MC_SIM_BUILD_MODE = 'plan';
const gate = await import(pathToFileURL({json.dumps(str(director_gate))}).href);
const calls = [];
const agent = {{
    name: 'vera',
    bot: {{ entity: {{ position: {{ x: 0, y: 64, z: 0 }} }} }},
    actions: {{
        actionList: ['!placeHere', '!inventory', '!planAndBuild'],
    }},
    async handleMessage(source, message, maxResponses = null) {{
        calls.push({{ source, message, maxResponses }});
        return 'supporting';
    }},
}};

gate.installDirectorGate(agent, {{ enabled: true, deadlineMs: 100 }});
await agent.handleMessage('system', 'Coordinate the cabin build.');

process.stdout.write(JSON.stringify({{
    calls,
    bridgeCalls: globalThis.__bridgeCalls,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    message = result["calls"][0]["message"]
    assert "Support role only" in message
    assert "Do not use plan/build commands" in message
    assert "Available tools: !inventory" in message
    assert "Available tools: !inventory, !placeHere" not in message
    assert "prefer one visible safe command" not in message
    assert "!placeHere" not in result["bridgeCalls"][0]["payload"]["available_tools"]
    assert "!buildFromPlan" not in result["bridgeCalls"][0]["payload"]["available_tools"]


@requires_node
def test_director_gate_settlement_mode_reads_active_objective_from_shared_state(
    tmp_path: Path,
) -> None:
    director_gate = _stage_skill_tree(tmp_path, DIRECTOR_GATE)
    bridge = director_gate.parent.parent / "bridge"
    (bridge / "python_bridge.js").write_text(
        """
export async function callBridge(opts = {}) {
    globalThis.__bridgeCalls = globalThis.__bridgeCalls || [];
    globalThis.__bridgeCalls.push(opts);
    if (opts.service === 'shared_state') {
        return {
            ok: true,
            payload: {
                active_objective: {
                    objective_id: 'phase-workshop',
                    phase_index: 2,
                    description: 'workshop station',
                    owner_agent_id: 'vera',
                    status: 'pending',
                },
            },
        };
    }
    return {
        ok: true,
        payload: {
            selected: true,
            turn_kind: 'planner',
            reason: 'settlement_phase_owner',
            scene_id: 'scene-workshop',
            scene_digest: 'build the next settlement phase',
            role: 'builder',
            local_observations: {},
            granted_tools: ['!inventory', '!planAndBuild'],
            build_macro: {
                role: 'planner_owner',
                owner: 'vera',
                plan_id: 'plan-workshop',
                granted: true,
                objective_id: 'phase-workshop',
                phase_index: 2,
                phase_owner: 'vera',
            },
            queue_depth: 1,
            suppressed_agents: [],
        },
    };
}
""".lstrip(),
        encoding="utf-8",
    )
    source = f"""
import {{ pathToFileURL }} from 'node:url';

process.env.MC_SIM_BUILD_MODE = 'settlement';
process.env.MC_SIM_SHARED_STATE_ENABLED = '1';
const gate = await import(pathToFileURL({json.dumps(str(director_gate))}).href);
const calls = [];
const agent = {{
    name: 'vera',
    bot: {{ entity: {{ position: {{ x: 0, y: 64, z: 0 }} }} }},
    actions: {{
        actionList: ['!inventory', '!planAndBuild'],
    }},
    async handleMessage(source, message, maxResponses = null) {{
        calls.push({{ source, message, maxResponses }});
        return 'planning';
    }},
}};

gate.installDirectorGate(agent, {{ enabled: true, deadlineMs: 100 }});
await agent.handleMessage('system', 'Autonomous heartbeat: you have been quiet.');

process.stdout.write(JSON.stringify({{
    calls,
    bridgeCalls: globalThis.__bridgeCalls,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, source)

    assert [call["service"] for call in result["bridgeCalls"]] == ["shared_state", "director"]
    director_payload = result["bridgeCalls"][1]["payload"]
    assert director_payload["active_objective"]["objective_id"] == "phase-workshop"
    assert director_payload["active_objective"]["phase_index"] == 2
    assert director_payload["event_text"].startswith(
        'Build the active settlement phase "workshop station".'
    )
    assert "!planAndBuild" in director_payload["available_tools"]
    assert "Build macro: planner_owner owner=vera" in result["calls"][0]["message"]
    assert (
        'Include exactly one concise !planAndBuild("...") command' in result["calls"][0]["message"]
    )
    fetched = [
        event for event in result["events"] if event["type"] == "settlement_objective.fetched"
    ]
    assert fetched and fetched[0]["payload"]["objective_id"] == "phase-workshop"

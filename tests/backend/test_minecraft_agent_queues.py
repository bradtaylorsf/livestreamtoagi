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
    assert "[Director V2 context]" in result["calls"][0]["message"]
    assert len(result["bridgeCalls"]) == 2
    assert {call["service"] for call in result["bridgeCalls"]} == {"director"}
    assert {call["method"] for call in result["bridgeCalls"]} == {"gate"}
    event_types = [event["type"] for event in result["events"]]
    assert "director_gate.selected" in event_types
    assert "director_gate.suppressed" in event_types
    assert {
        event["payload"].get("outcome")
        for event in result["events"]
        if event["type"] == "inbox.turn_completed"
    } >= {"ok", "director_suppressed"}

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
    assert "Incoming message batch since your last turn (2 messages):" in result["calls"][0]["message"]
    assert "first batch message" in result["calls"][0]["message"]
    assert "second batch message" in result["calls"][0]["message"]
    assert result["deferredResults"] == ["handled-2", "handled-3"]
    assert result["calls"][1]["message"] == "message before long turn"
    assert result["calls"][2]["message"] == "message while model is generating"
    event_types = [event["type"] for event in result["events"]]
    running_queue_events = [
        event for event in result["events"] if event["type"] == "inbox.queued" and event["payload"].get("running")
    ]
    assert event_types.count("inbox.turn_started") == 3
    assert event_types.count("inbox.turn_completed") == 3
    assert running_queue_events

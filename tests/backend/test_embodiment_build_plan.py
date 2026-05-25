"""Tests for E6-4 verified build-from-plan outcomes (#559).

No live Minecraft server is required. The Node helper tests exercise the
committed fork source directly, and the bridge smoke test uses a fake bot plus
the existing Python inbound dispatch so the emitted ``perception.report`` and
``action.result`` records are observable on the Python event bus.
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
from core.embodiment import verify_build_plan
from core.event_bus import EventType, event_bus

REPO_ROOT = Path(__file__).resolve().parents[2]
FORK_SRC = REPO_ROOT / "scripts" / "minecraft" / "fork-src"
BUILDING_HELPERS = FORK_SRC / "agent" / "skills" / "building.js"
BUILD_PLAN_HELPERS = FORK_SRC / "agent" / "skills" / "build_plan.js"
BUILDER_PROVIDER_HELPERS = FORK_SRC / "agent" / "skills" / "builder_provider.js"
BUILD_PLAN_GOVERNOR_HELPERS = FORK_SRC / "agent" / "skills" / "build_plan_governor.js"
DISTRESS_MONITOR_HELPERS = FORK_SRC / "agent" / "skills" / "distress_monitor.js"
BUILD_FROM_PLAN_ACTION = FORK_SRC / "agent" / "commands" / "build_from_plan_action.js"
PLAN_AND_BUILD_ACTION = FORK_SRC / "agent" / "commands" / "plan_and_build_action.js"
CONNECT_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-bridge-bot.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _run_node_harness(tmp_path: Path, source: str, env: dict[str, str] | None = None) -> dict:
    harness = tmp_path / "build_plan_harness.mjs"
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


@requires_node
def test_build_plan_governor_ignores_zone_stride_in_confined_easy_spawn(tmp_path: Path) -> None:
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const governor = await import(pathToFileURL({json.dumps(str(BUILD_PLAN_GOVERNOR_HELPERS))}).href);
const shifted = governor.applyBuildZoneOffset('alpha', {{ x: -4, y: 64, z: -4 }});
process.stdout.write(JSON.stringify({{ shifted }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "SOAK_EASY_SPAWN": "1",
            "EASY_SETUP_BOUNDARY": "glass",
            "EASY_SETUP_MEADOW_RADIUS": "23",
            "MC_SIM_BUILD_ZONE_STRIDE": "24",
        },
    )

    assert result["shifted"] == {"x": -4, "y": 64, "z": -4}


@requires_node
def test_build_plan_governor_applies_zone_stride_in_open_easy_meadow(tmp_path: Path) -> None:
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const governor = await import(pathToFileURL({json.dumps(str(BUILD_PLAN_GOVERNOR_HELPERS))}).href);
const shifted = governor.applyBuildZoneOffset('alpha', {{ x: -4, y: 64, z: -4 }});
process.stdout.write(JSON.stringify({{ shifted }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "SOAK_EASY_SPAWN": "1",
            "EASY_SETUP_BOUNDARY": "none",
            "EASY_SETUP_MEADOW_RADIUS": "64",
            "MC_SIM_BUILD_ZONE_STRIDE": "24",
        },
    )

    assert result["shifted"] == {"x": -28, "y": 64, "z": 44}


@requires_node
def test_build_plan_governor_clamps_open_easy_meadow_zone_offset(tmp_path: Path) -> None:
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const governor = await import(pathToFileURL({json.dumps(str(BUILD_PLAN_GOVERNOR_HELPERS))}).href);
const shifted = governor.applyBuildZoneOffset('grok', {{ x: 70, y: 64, z: -14 }});
process.stdout.write(JSON.stringify({{ shifted }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "SOAK_EASY_SPAWN": "1",
            "EASY_SETUP_BOUNDARY": "none",
            "EASY_SETUP_MEADOW_RADIUS": "96",
            "MC_SIM_BUILD_ZONE_STRIDE": "24",
        },
    )

    assert abs(result["shifted"]["x"]) <= 88
    assert abs(result["shifted"]["z"]) <= 88


@requires_node
def test_scene_build_origin_uses_objective_slot_for_repeated_owner(tmp_path: Path) -> None:
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const governor = await import(pathToFileURL({json.dumps(str(BUILD_PLAN_GOVERNOR_HELPERS))}).href);
governor.resetBuildPlanGovernor();
const agent = {{ name: 'alpha', bot: {{ username: 'Alpha' }} }};
const origin = {{ x: 0, y: 64, z: 0 }};
const settings = {{ max_steps: 32, planner_max_steps: 32 }};
const first = governor.tryAcquireSceneBuild('settlement', agent, 'crafting hall', origin, settings, {{
    ownerAgentId: 'alpha',
    phaseOwner: 'alpha',
    objectiveId: 'phase-1-crafting-hall',
}});
governor.recordBuildCompleted(agent, first.plan_id, 'success: intended=4; verified=4');
const second = governor.tryAcquireSceneBuild('settlement', agent, 'tool workshop', origin, settings, {{
    ownerAgentId: 'alpha',
    phaseOwner: 'alpha',
    objectiveId: 'phase-9-tool-workshop',
}});
process.stdout.write(JSON.stringify({{ first: first.origin, second: second.origin }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "SOAK_EASY_SPAWN": "1",
            "EASY_SETUP_BOUNDARY": "none",
            "EASY_SETUP_MEADOW_RADIUS": "96",
            "MC_SIM_BUILD_ZONE_STRIDE": "24",
        },
    )

    assert result["first"] != result["second"]


@requires_node
def test_settlement_phase_slots_are_unique_across_objective_roster(tmp_path: Path) -> None:
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const governor = await import(pathToFileURL({json.dumps(str(BUILD_PLAN_GOVERNOR_HELPERS))}).href);
governor.resetBuildPlanGovernor();
const agent = {{ name: 'alpha', bot: {{ username: 'Alpha' }} }};
const origin = {{ x: 0, y: 64, z: 0 }};
const settings = {{ max_steps: 32, planner_max_steps: 32 }};
const origins = [];
for (let index = 0; index < 12; index += 1) {{
    const objectiveId = `phase-${{index + 1}}-objective`;
    const acquired = governor.tryAcquireSceneBuild('settlement', agent, objectiveId, origin, settings, {{
        ownerAgentId: 'alpha',
        phaseOwner: 'alpha',
        objectiveId,
        phaseIndex: index,
    }});
    origins.push(acquired.origin);
    governor.recordBuildCompleted(agent, acquired.plan_id, 'success: intended=4; verified=4');
}}
process.stdout.write(JSON.stringify({{
    origins,
    unique: new Set(origins.map((item) => `${{item.x}},${{item.y}},${{item.z}}`)).size,
    phase2: origins[1],
    phase10: origins[9],
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "SOAK_EASY_SPAWN": "1",
            "EASY_SETUP_BOUNDARY": "none",
            "EASY_SETUP_MEADOW_RADIUS": "96",
            "MC_SIM_BUILD_ZONE_STRIDE": "24",
            "MC_SIM_BUILD_COOLDOWN_SEC": "0",
        },
    )

    assert result["unique"] == 12
    assert result["phase2"] != result["phase10"]
    assert all(abs(origin["x"]) <= 88 and abs(origin["z"]) <= 88 for origin in result["origins"])


@requires_node
def test_building_helper_normalizes_wall_torch_as_torch(tmp_path: Path) -> None:
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const building = await import(pathToFileURL({json.dumps(str(BUILDING_HELPERS))}).href);
process.stdout.write(JSON.stringify({{
    wallTorch: building.normalizeBlockType('wall_torch'),
    torch: building.normalizeBlockType('torch'),
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, harness)

    assert result == {"wallTorch": "torch", "torch": "torch"}


def _stage_action_with_stub_bridge(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fork-src"
    commands = root / "agent" / "commands"
    skills = root / "agent" / "skills"
    bridge = root / "agent" / "bridge"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)
    shutil.copy2(BUILD_FROM_PLAN_ACTION, commands / "build_from_plan_action.js")
    shutil.copy2(BUILDING_HELPERS, skills / "building.js")
    shutil.copy2(BUILD_PLAN_HELPERS, skills / "build_plan.js")
    shutil.copy2(BUILDER_PROVIDER_HELPERS, skills / "builder_provider.js")
    shutil.copy2(BUILD_PLAN_GOVERNOR_HELPERS, skills / "build_plan_governor.js")
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

export function startKillSwitchWatch() {}
export function bridgeIsKillActive() {
    return process.env.BRIDGE_KILL_ACTIVE === '1';
}

export async function callBridge(opts = {}) {
    appendFileSync(process.env.BRIDGE_CALLS_PATH, JSON.stringify(opts) + '\\n');
    const failOnce = process.env.STUB_FAIL_BRIDGE_ONCE || '';
    const failKey = `${opts.service}.${opts.method}`;
    if (failOnce === failKey && !globalThis.__stubBridgeFailedOnce) {
        globalThis.__stubBridgeFailedOnce = true;
        throw new BridgeClientError('bridge_unreachable', 'stub bridge report outage');
    }
    if (
        opts.service === 'shared_state' &&
        opts.method === 'read' &&
        process.env.STUB_ACTIVE_OBJECTIVE_JSON
    ) {
        return {
            request_id: 'stub-request',
            ok: true,
            payload: { active_objective: JSON.parse(process.env.STUB_ACTIVE_OBJECTIVE_JSON) },
            retryable: false,
            trace_id: opts.traceId || 'trace-stub',
        };
    }
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
    return commands / "build_from_plan_action.js", calls_path


def _stage_plan_and_build_with_stub_bridge(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fork-src"
    commands = root / "agent" / "commands"
    skills = root / "agent" / "skills"
    bridge = root / "agent" / "bridge"
    commands.mkdir(parents=True)
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)
    (root / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    shutil.copy2(BUILD_FROM_PLAN_ACTION, commands / "build_from_plan_action.js")
    shutil.copy2(PLAN_AND_BUILD_ACTION, commands / "plan_and_build_action.js")
    shutil.copy2(BUILDING_HELPERS, skills / "building.js")
    shutil.copy2(BUILD_PLAN_HELPERS, skills / "build_plan.js")
    shutil.copy2(BUILDER_PROVIDER_HELPERS, skills / "builder_provider.js")
    shutil.copy2(BUILD_PLAN_GOVERNOR_HELPERS, skills / "build_plan_governor.js")
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

export function startKillSwitchWatch() {}
export function bridgeIsKillActive() {
    return false;
}

export async function callBridge(opts = {}) {
    appendFileSync(process.env.BRIDGE_CALLS_PATH, JSON.stringify(opts) + '\\n');
    if (
        opts.service === 'shared_state' &&
        opts.method === 'read' &&
        process.env.STUB_ACTIVE_OBJECTIVE_JSON
    ) {
        return {
            request_id: 'stub-request',
            ok: true,
            payload: { active_objective: JSON.parse(process.env.STUB_ACTIVE_OBJECTIVE_JSON) },
            retryable: false,
            trace_id: opts.traceId || 'trace-stub',
        };
    }
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
    (bridge / "timeline_emitter.js").write_text(
        """
export function emitTimelineEvent(event = {}) {
    globalThis.__timelineEvents = globalThis.__timelineEvents || [];
    globalThis.__timelineEvents.push(event);
}
""".lstrip(),
        encoding="utf-8",
    )
    return commands / "plan_and_build_action.js", calls_path


def _stage_distress_monitor_with_stub_bridge(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fork-src"
    skills = root / "agent" / "skills"
    bridge = root / "agent" / "bridge"
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)
    (root / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    shutil.copy2(DISTRESS_MONITOR_HELPERS, skills / "distress_monitor.js")
    calls_path = tmp_path / "bridge_calls.jsonl"
    (bridge / "python_bridge.js").write_text(
        """
import { appendFileSync } from 'node:fs';

export async function callBridge(opts = {}) {
    appendFileSync(process.env.BRIDGE_CALLS_PATH, JSON.stringify(opts) + '\\n');
    return {
        request_id: 'stub-request',
        ok: true,
        payload: { accepted: true },
        retryable: false,
        trace_id: opts.traceId || 'trace-stub',
    };
}
""".lstrip(),
        encoding="utf-8",
    )
    (bridge / "timeline_emitter.js").write_text(
        """
export function emitTimelineEvent(event = {}) {
    globalThis.__timelineEvents = globalThis.__timelineEvents || [];
    globalThis.__timelineEvents.push(event);
}
""".lstrip(),
        encoding="utf-8",
    )
    return skills / "distress_monitor.js", calls_path


def _stage_builder_provider_with_stub_timeline(tmp_path: Path) -> Path:
    root = tmp_path / "fork-src"
    skills = root / "agent" / "skills"
    bridge = root / "agent" / "bridge"
    skills.mkdir(parents=True)
    bridge.mkdir(parents=True)
    (root / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    shutil.copy2(BUILDER_PROVIDER_HELPERS, skills / "builder_provider.js")
    (bridge / "timeline_emitter.js").write_text(
        """
export function emitTimelineEvent(event = {}) {
    globalThis.__timelineEvents = globalThis.__timelineEvents || [];
    globalThis.__timelineEvents.push(event);
}
""".lstrip(),
        encoding="utf-8",
    )
    return skills / "builder_provider.js"


async def _dispatch_recorded_inbound_calls(calls_path: Path) -> None:
    for idx, raw in enumerate(calls_path.read_text().splitlines()):
        call = json.loads(raw)
        if c.service_key(call["service"], call["method"]) not in inbound.INBOUND_VERBS:
            continue
        env = c.BridgeRequest(
            version=c.PROTOCOL_VERSION,
            request_id=f"build-plan-stub-{idx}",
            agent_id="vera",
            run_id="run-build-plan-test",
            simulation_id="00000000-0000-0000-0000-000000000559",
            service=call["service"],
            method=call["method"],
            payload=call["payload"],
            deadline_ms=call.get("deadlineMs", 5000),
            cost_context=c.CostContext(
                agent_tier="conversation",
                budget_bucket="bridge-test",
                estimated_cost_usd=0.0,
            ),
            trace_id=call.get("traceId") or "trace-build-plan-test",
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


@requires_node
def test_distress_monitor_ignores_zero_oxygen_when_agent_is_not_in_water(tmp_path: Path) -> None:
    monitor_path, calls_path = _stage_distress_monitor_with_stub_bridge(tmp_path)
    harness = f"""
import {{ existsSync, readFileSync }} from 'node:fs';
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(monitor_path))}).href);
const agent = {{
    name: 'pixel',
    bot: {{
        username: 'PixelHarnessBot',
        health: 20,
        oxygen: 0,
        entity: {{
            position: {{ x: 0, y: 64, z: 0 }},
            isInWater: false,
        }},
    }},
}};
mod.installDistressMonitor(agent, {{ pollMs: 5, minIntervalMs: 1 }});
await new Promise((resolve) => setTimeout(resolve, 30));
clearInterval(agent.__ltagDistressMonitor.timer);
process.stdout.write(JSON.stringify({{
    events: globalThis.__timelineEvents,
    bridgeCalls: existsSync(process.env.BRIDGE_CALLS_PATH)
        ? readFileSync(process.env.BRIDGE_CALLS_PATH, 'utf8').trim().split('\\n').filter(Boolean)
        : [],
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
        },
    )

    assert result["events"] == []
    assert result["bridgeCalls"] == []


@requires_node
def test_distress_monitor_reports_zero_oxygen_when_agent_is_in_water(tmp_path: Path) -> None:
    monitor_path, calls_path = _stage_distress_monitor_with_stub_bridge(tmp_path)
    harness = f"""
import {{ readFileSync }} from 'node:fs';
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(monitor_path))}).href);
const agent = {{
    name: 'pixel',
    bot: {{
        username: 'PixelHarnessBot',
        health: 20,
        oxygen: 0,
        entity: {{
            position: {{ x: 0, y: 64, z: 0 }},
            isInWater: true,
        }},
    }},
}};
mod.installDistressMonitor(agent, {{ pollMs: 5, minIntervalMs: 1 }});
await new Promise((resolve) => setTimeout(resolve, 30));
clearInterval(agent.__ltagDistressMonitor.timer);
process.stdout.write(JSON.stringify({{
    events: globalThis.__timelineEvents,
    bridgeCalls: readFileSync(process.env.BRIDGE_CALLS_PATH, 'utf8').trim().split('\\n').filter(Boolean),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
        },
    )

    assert any(event["type"] == "distress.reported" for event in result["events"])
    assert result["bridgeCalls"]


@requires_node
def test_builder_provider_run_cap_is_shared_across_agent_processes(tmp_path: Path) -> None:
    provider_path = _stage_builder_provider_with_stub_timeline(tmp_path)
    shared_run_dir = tmp_path / "shared-run"
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
globalThis.fetch = async () => ({{
    ok: true,
    async text() {{
        return JSON.stringify({{
            choices: [{{ message: {{ content: '{{"blocks":[{{"dx":0,"dy":0,"dz":0,"block_type":"oak_log"}}]}}' }} }}],
            usage: {{ prompt_tokens: 4, completion_tokens: 5, total_tokens: 9 }},
        }});
    }},
}});

const providerUrl = pathToFileURL({json.dumps(str(provider_path))}).href;
async function callBuilder(agentName, instance) {{
    const provider = await import(`${{providerUrl}}?instance=${{instance}}`);
    const resolved = provider.resolveBuilderModel({{ name: agentName }});
    await resolved.sendRequest(
        [{{ role: 'user', content: 'make one block' }}],
        'system',
        {{ purpose: 'plan_generation', traceId: `trace-${{agentName}}` }},
    );
    return resolved.lastMetadata.request_count_run;
}}

const first = await callBuilder('rex', 1);
const second = await callBuilder('fork', 2);
let thirdError = null;
try {{
    await callBuilder('pixel', 3);
}} catch (error) {{
    thirdError = {{
        name: error.name,
        code: error.code,
        reason: error.reason,
        message: error.message,
    }};
}}
process.stdout.write(JSON.stringify({{
    first,
    second,
    thirdError,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        agent: event.agent,
        request_count_run: event.payload && event.payload.request_count_run,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "MC_RUN_DIR": str(shared_run_dir),
            "MC_SIM_BUILDER_PROVIDER": "openrouter",
            "MC_SIM_BUILDER_OPENROUTER_API_KEY": "test-key",
            "MC_SIM_BUILDER_OPENROUTER_MODEL": "openrouter/test-builder",
            "MC_SIM_BUILDER_MAX_CALLS_PER_RUN": "2",
            "MC_SIM_BUILDER_MAX_CALLS_PER_AGENT": "2",
        },
    )

    assert result["first"] == 1
    assert result["second"] == 2
    assert result["thirdError"]["name"] == "BuilderBudgetError"
    assert result["thirdError"]["reason"] == "run_call_cap"
    assert [
        event["request_count_run"] for event in result["events"] if event["type"] == "llm.request"
    ] == [
        1,
        2,
    ]


@requires_node
def test_build_plan_governor_invalidates_cached_plan_after_failed_execution(
    tmp_path: Path,
) -> None:
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const governor = await import(pathToFileURL({json.dumps(str(BUILD_PLAN_GOVERNOR_HELPERS))}).href);
governor.resetBuildPlanGovernor();
const agent = {{ name: 'pixel', bot: {{ username: 'Pixel' }} }};
const origin = {{ x: 0, y: 64, z: 0 }};
const settings = {{ max_steps: 32, planner_max_steps: 32 }};

const first = governor.tryAcquireBuild(agent, 'garden shed', origin, settings);
governor.recordPlanGenerated(agent, first, {{
    blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }}],
}});
const afterPlan = governor.governorSnapshot(agent);
governor.recordBuildFailed(agent, first.plan_id, 'partial: intended=9; verified=7');
const afterFailure = governor.governorSnapshot(agent);
const second = governor.tryAcquireBuild(agent, 'garden shed', origin, settings);
process.stdout.write(JSON.stringify({{
    firstCacheHit: first.cache_hit,
    afterPlanCacheSize: afterPlan.cache_size,
    afterFailureCacheSize: afterFailure.cache_size,
    secondCacheHit: second.cache_hit,
    secondReason: second.reason,
}}) + '\\n');
"""

    result = _run_node_harness(tmp_path, harness)

    assert result["firstCacheHit"] is False
    assert result["afterPlanCacheSize"] == 1
    assert result["afterFailureCacheSize"] == 0
    assert result["secondCacheHit"] is False
    assert result["secondReason"] == "cache_miss"


@requires_node
def test_build_plan_governor_releases_scene_after_failed_execution(
    tmp_path: Path,
) -> None:
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const governor = await import(pathToFileURL({json.dumps(str(BUILD_PLAN_GOVERNOR_HELPERS))}).href);
governor.resetBuildPlanGovernor();
const agent = {{ name: 'alpha', bot: {{ username: 'Alpha' }} }};
const origin = {{ x: 0, y: 64, z: 0 }};
const settings = {{ max_steps: 32, planner_max_steps: 32 }};

const first = governor.tryAcquireSceneBuild('settlement-phase-1', agent, 'crafting hall', origin, settings, {{
    ownerAgentId: 'alpha',
    phaseOwner: 'alpha',
    objectiveId: 'phase-1-crafting-hall',
}});
governor.recordPlanGenerated(agent, first, {{
    blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }}],
}});
const failed = governor.recordBuildFailed(
    agent,
    first.plan_id,
    'partial: intended=6; present=0; missing=6; unexpected=5; verified=5',
);
const afterFailure = governor.governorSnapshot(agent);
const second = governor.tryAcquireSceneBuild('settlement-phase-1', agent, 'crafting workshop', origin, settings, {{
    ownerAgentId: 'alpha',
    phaseOwner: 'alpha',
    objectiveId: 'phase-1-crafting-hall',
}});
process.stdout.write(JSON.stringify({{
    failedActive: failed.active_build,
    snapshotActive: afterFailure.active_build,
    secondAllowed: second.allowed,
    secondReason: second.reason,
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"MC_SIM_BUILD_COOLDOWN_SEC": "900"},
    )

    assert result["failedActive"] is None
    assert result["snapshotActive"] is None
    assert result["secondAllowed"] is True
    assert result["secondReason"] == "cache_miss"


@requires_node
def test_plan_and_build_rejects_duplicate_cells_and_uses_blueprint_fallback(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = -1; x <= 3; x += 1) {{
    for (let z = -1; z <= 3; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
const bot = {{
    username: 'DuplicatePlanHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'oak_planks' }},
            {{ name: 'crafting_table' }},
            {{ name: 'torch' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'alpha',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'cobblestone' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'crafting hall');
process.stdout.write(JSON.stringify({{
    result,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "alpha",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "12",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "plan-and-build" in result["result"]
    rejected = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.rejected"
    )
    assert "duplicates target" in rejected["payload"]["error"]
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"
    executed = next(
        event for event in result["events"] if event["type"] == "build_plan.execution.completed"
    )
    assert executed["payload"]["verified_blocks"] > 0


@requires_node
def test_plan_and_build_rejects_unavailable_glass_and_uses_tower_blueprint(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = 0; x <= 3; x += 1) {{
    for (let z = 0; z <= 3; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
let systemMessage = '';
const bot = {{
    username: 'TowerFallbackHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'oak_log' }},
            {{ name: 'oak_planks' }},
            {{ name: 'torch' }},
            {{ name: 'glass' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'aurora',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest(_messages, prompt) {{
                systemMessage = prompt;
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 1, dy: 0, dz: 1, block_type: 'glass' }},
                        {{ dx: 1, dy: 1, dz: 1, block_type: 'glass' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'watch tower');
process.stdout.write(JSON.stringify({{
    result,
    systemMessage,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
    placed: {{
        base: world.get('1,64,1') || null,
        platform: world.get('1,67,1') || null,
        torch: world.get('1,68,1') || null,
        glass: [...world.values()].filter((value) => value === 'glass').length,
    }},
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "aurora",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "24",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert (
        "glass"
        not in result["systemMessage"].split("Allowed block_type values:", 1)[1].split("\n", 1)[0]
    )
    rejected = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.rejected"
    )
    assert "glass is not allowed" in rejected["payload"]["error"]
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"
    assert result["placed"] == {
        "base": "oak_log",
        "platform": "oak_planks",
        "torch": "torch",
        "glass": 0,
    }


def test_python_verifies_full_build_plan_match() -> None:
    steps = [
        {
            "index": 0,
            "action": "place",
            "position": {"x": 0, "y": 64, "z": 0},
            "block_type": "minecraft:stone",
            "final_block": "stone",
        },
        {
            "index": 1,
            "action": "place",
            "position": {"x": 1, "y": 64, "z": 0},
            "block_type": "stone",
            "final_block": "minecraft:stone",
        },
    ]
    observation = _structure_observation(
        steps=steps,
        final_blocks=[
            {"position": {"x": 0, "y": 64, "z": 0}, "block_type": "stone"},
            {"position": {"x": 1, "y": 64, "z": 0}, "block_type": "minecraft:stone"},
        ],
    )

    result = verify_build_plan(observation)

    assert result == {
        "verified": True,
        "class": "success",
        "intended": 2,
        "present": 2,
        "missing": 0,
        "unexpected": 0,
        "steps_verified": 2,
        "steps_abandoned": 0,
        "completion": 1.0,
    }


def test_python_marks_missing_blocks_partial() -> None:
    observation = _structure_observation(
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
        outcome_class="partial",
    )

    result = verify_build_plan(observation)

    assert result["verified"] is False
    assert result["class"] == "partial"
    assert result["intended"] == 2
    assert result["present"] == 1
    assert result["missing"] == 1
    assert result["completion"] == 0.5


def test_python_counts_unexpected_final_blocks() -> None:
    observation = _structure_observation(
        steps=[
            {
                "index": 0,
                "action": "break",
                "source": "clear",
                "position": {"x": 2, "y": 64, "z": 0},
                "final_block": "dirt",
            },
            {
                "index": 1,
                "action": "place",
                "position": {"x": 0, "y": 64, "z": 0},
                "block_type": "stone",
                "final_block": "stone",
            },
        ],
        final_blocks=[
            {"position": {"x": 2, "y": 64, "z": 0}, "block_type": "dirt"},
            {"position": {"x": 0, "y": 64, "z": 0}, "block_type": "stone"},
        ],
        outcome_class="partial",
    )

    result = verify_build_plan(observation)

    assert result["class"] == "partial"
    assert result["present"] == 1
    assert result["missing"] == 0
    assert result["unexpected"] == 1
    assert result["steps_verified"] == 1


def test_python_marks_invalid_plan_invalid() -> None:
    observation = _structure_observation(
        steps=[],
        final_blocks=[],
        outcome_class="invalid",
    )

    result = verify_build_plan(
        observation,
        plan={
            "origin": {"x": 0, "y": 64, "z": 0},
            "plan": {"blocks": [{"dx": 0, "dy": 0, "dz": 0, "block_type": "air"}]},
        },
    )

    assert result == {
        "verified": False,
        "class": "invalid",
        "intended": 0,
        "present": 0,
        "missing": 0,
        "unexpected": 0,
        "steps_verified": 0,
        "steps_abandoned": 0,
        "completion": 0.0,
    }


def test_python_downgrades_false_node_success_label() -> None:
    observation = _structure_observation(
        steps=[
            {
                "index": 0,
                "action": "place",
                "position": {"x": 0, "y": 64, "z": 0},
                "block_type": "stone",
                "final_block": "air",
                "class": "placed",
            }
        ],
        final_blocks=[{"position": {"x": 0, "y": 64, "z": 0}, "block_type": "air"}],
        outcome_class="success",
    )

    result = verify_build_plan(observation)

    assert result["verified"] is False
    assert result["class"] == "partial"
    assert result["missing"] == 1


@requires_node
def test_node_build_plan_helpers_expand_and_score_plan(tmp_path: Path) -> None:
    source = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(BUILD_PLAN_HELPERS))}).href);
const normalized = mod.normalizePlan({{
    origin: {{ x: 10.9, y: 64, z: -2.1 }},
    plan: {{
        palette: {{ wall: 'minecraft:Oak Planks' }},
        clear: [{{ dx: 0, dy: 0, dz: 0 }}],
        blocks: [
            {{ dx: 0, dy: 0, dz: 0, block_type: 'wall' }},
            {{ dx: 1, dy: 0, dz: 0, block_type: 'stone' }},
        ],
    }},
}});
const metric = mod.completionMetric({{
    steps: normalized.steps,
    finalBlocks: [
        {{ position: {{ x: 10, y: 64, z: -3 }}, block_type: 'oak_planks' }},
        {{ position: {{ x: 11, y: 64, z: -3 }}, block_type: 'air' }},
        {{ position: {{ x: 12, y: 64, z: -3 }}, block_type: 'dirt' }},
    ],
}});
const partial = mod.classifyPlan({{ metric, failureClass: 'blocked' }});
const fullMetric = mod.completionMetric({{
    steps: normalized.steps,
    finalBlocks: [
        {{ position: {{ x: 10, y: 64, z: -3 }}, block_type: 'oak_planks' }},
        {{ position: {{ x: 11, y: 64, z: -3 }}, block_type: 'stone' }},
    ],
}});
process.stdout.write(JSON.stringify({{
    origin: normalized.origin,
    actions: normalized.steps.map((step) => step.action),
    blockTypes: normalized.steps.map((step) => step.block_type || null),
    firstPosition: normalized.steps[0].position,
    metric,
    partial,
    success: mod.classifyPlan({{ metric: fullMetric }}),
    status: mod.statusForPlanClass('partial'),
    observationType: mod.structureObservation({{
        actionId: 'node-helper',
        origin: normalized.origin,
        steps: normalized.steps,
        metric: fullMetric,
        outcomeClass: 'success',
    }}).type,
}}) + '\\n');
"""
    result = _run_node_harness(tmp_path, source)

    assert result["origin"] == {"x": 10, "y": 64, "z": -3}
    assert result["actions"] == ["break", "place", "place"]
    assert result["blockTypes"] == [None, "oak_planks", "stone"]
    assert result["firstPosition"] == {"x": 10, "y": 64, "z": -3}
    assert result["metric"]["intended_count"] == 2
    assert result["metric"]["blocks_present"] == 1
    assert result["metric"]["blocks_missing"] == 1
    assert result["metric"]["blocks_unexpected"] == 1
    assert result["metric"]["completion_ratio"] == 0.5
    assert result["partial"] == "partial"
    assert result["success"] == "success"
    assert result["status"] == "partial"
    assert result["observationType"] == "structure"


def test_committed_build_plan_files_match_contract() -> None:
    assert BUILD_PLAN_HELPERS.is_file()
    assert BUILD_FROM_PLAN_ACTION.is_file()
    assert PLAN_AND_BUILD_ACTION.is_file()
    assert BUILDER_PROVIDER_HELPERS.is_file()
    assert BUILD_PLAN_GOVERNOR_HELPERS.is_file()

    helper_src = BUILD_PLAN_HELPERS.read_text()
    assert "normalizePlan" in helper_src
    assert "completionMetric" in helper_src
    assert "structureObservation" in helper_src
    assert "callBridge" not in helper_src

    action_src = BUILD_FROM_PLAN_ACTION.read_text()
    assert "'!buildFromPlan'" in action_src
    assert "service: 'perception'" in action_src and "method: 'report'" in action_src
    assert "service: 'action'" in action_src and "method: 'result'" in action_src
    assert "completionMetric" in action_src
    assert "safe-idling" in action_src
    assert "openrouter" not in action_src.lower()

    plan_action_src = PLAN_AND_BUILD_ACTION.read_text()
    assert "'!planAndBuild'" in plan_action_src
    assert "LOCAL_LLM_MODEL_BUILDING" not in plan_action_src
    assert "code_model" in plan_action_src
    assert "validateGeneratedPlan" in plan_action_src
    assert "performBuildFromPlan" in plan_action_src
    assert "build_plan.generation.completed" in plan_action_src
    provider_src = BUILDER_PROVIDER_HELPERS.read_text()
    assert "MC_SIM_BUILDER_PROVIDER" in provider_src
    assert "plan_generation" in provider_src
    assert "OpenRouter" in provider_src
    governor_src = BUILD_PLAN_GOVERNOR_HELPERS.read_text()
    assert "active_build_exists" in governor_src
    assert "MC_SIM_BUILD_COOLDOWN_SEC" in governor_src


def test_connect_script_stages_and_injects_build_plan_action() -> None:
    src = CONNECT_SCRIPT.read_text()
    for token in (
        "BUILD_FROM_PLAN_ACTION_REL",
        "BUILD_PLAN_SKILL_REL",
        "LTAG E6-4 build-from-plan action",
        "buildFromPlanAction",
        "!buildFromPlan",
        "PLAN_AND_BUILD_ACTION_REL",
        "planAndBuildAction",
        "!planAndBuild",
    ):
        assert token in src


@requires_node
def test_plan_and_build_valid_builder_json_executes_bounded_plan(tmp_path: Path) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'stone'],
    ['1,63,0', 'stone'],
]);
let plannerEnv = null;
const bot = {{
    username: 'PlanBuildHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_log' }}, {{ name: 'torch' }}],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'rex',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest(messages, systemMessage) {{
                plannerEnv = {{
                    purpose: process.env.MC_LLM_REQUEST_PURPOSE,
                    reason: process.env.MC_LLM_REQUEST_REASON,
                    message: messages[0].content,
                    systemMessage,
                }};
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 1, dy: 0, dz: 0, block_type: 'torch' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'tiny marker');
process.stdout.write(JSON.stringify({{
    result,
    plannerEnv,
    finalBlocks: {{ a: world.get('0,64,0'), b: world.get('1,64,0') }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert result["finalBlocks"] == {"a": "oak_log", "b": "torch"}
    assert "plan-and-build" in result["result"]
    assert "success" in result["result"]
    assert result["plannerEnv"]["purpose"] == "plan_generation"
    assert result["plannerEnv"]["reason"] == "planAndBuild"
    assert "strict JSON" in result["plannerEnv"]["systemMessage"]
    event_types = [event["type"] for event in result["events"]]
    assert event_types == [
        "build_plan.generation.started",
        "build_plan.generation.completed",
        "build_plan.execution.started",
        "build_plan.execution.completed",
    ]
    completed = result["events"][1]["payload"]
    assert completed["source"] == "builder_model"
    assert completed["plan_json"]
    assert len(completed["plan"]["blocks"]) == 2


@requires_node
def test_plan_and_build_flattens_lighting_torches_to_ground_level(tmp_path: Path) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (const [x, z] of [[-2, -2], [2, -2], [-2, 2], [2, 2]]) {{
    world.set(`${{x}},63,${{z}}`, 'grass_block');
}}
const bot = {{
    username: 'LightingHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'torch', count: 8 }}, {{ name: 'cobblestone', count: 4 }}, {{ name: 'oak_log', count: 4 }}],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'rex',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: -2, dy: 0, dz: -2, block_type: 'cobblestone' }},
                        {{ dx: 2, dy: 0, dz: -2, block_type: 'cobblestone' }},
                        {{ dx: -2, dy: 0, dz: 2, block_type: 'cobblestone' }},
                        {{ dx: 2, dy: 0, dz: 2, block_type: 'cobblestone' }},
                        {{ dx: -2, dy: 1, dz: -2, block_type: 'oak_log' }},
                        {{ dx: 2, dy: 1, dz: -2, block_type: 'oak_log' }},
                        {{ dx: -2, dy: 1, dz: 2, block_type: 'oak_log' }},
                        {{ dx: 2, dy: 1, dz: 2, block_type: 'oak_log' }},
                        {{ dx: -2, dy: 2, dz: -2, block_type: 'torch' }},
                        {{ dx: 2, dy: 2, dz: -2, block_type: 'torch' }},
                        {{ dx: -2, dy: 2, dz: 2, block_type: 'torch' }},
                        {{ dx: 2, dy: 2, dz: 2, block_type: 'torch' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'lighting perimeter');
const completed = globalThis.__timelineEvents.find((event) => event.type === 'build_plan.generation.completed').payload;
process.stdout.write(JSON.stringify({{
    result,
    planBlocks: completed.plan.blocks,
    finalBlocks: {{
        nw: world.get('-2,64,-2'),
        ne: world.get('2,64,-2'),
        sw: world.get('-2,64,2'),
        se: world.get('2,64,2'),
    }},
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "16",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "nw": "torch",
        "ne": "torch",
        "sw": "torch",
        "se": "torch",
    }
    assert result["planBlocks"] == [
        {"dx": -2, "dy": 0, "dz": -2, "block_type": "torch"},
        {"dx": 2, "dy": 0, "dz": -2, "block_type": "torch"},
        {"dx": -2, "dy": 0, "dz": 2, "block_type": "torch"},
        {"dx": 2, "dy": 0, "dz": 2, "block_type": "torch"},
    ]


@requires_node
def test_plan_and_build_uses_current_inventory_budget_for_fallback(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['1,63,1', 'grass_block'],
    ['2,63,1', 'grass_block'],
    ['2,63,2', 'grass_block'],
]);
let systemMessage = '';
const bot = {{
    username: 'InventoryBudgetHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'oak_planks', count: 4 }},
            {{ name: 'torch', count: 1 }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'alpha',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest(_messages, prompt) {{
                systemMessage = prompt;
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 1, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 2, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 3, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 4, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 5, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 1, dy: 0, dz: 2, block_type: 'crafting_table' }},
                    ],
                    clear: [],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'basic workbench setup');
process.stdout.write(JSON.stringify({{
    result,
    systemMessage,
    finalBlocks: {{
        plankA: world.get('1,64,1') || null,
        plankB: world.get('2,64,1') || null,
        table: world.get('1,64,2') || null,
        torchBase: world.get('2,64,2') || null,
        torch: world.get('2,65,2') || null,
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "alpha",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "20",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert "4 oak_planks" in result["systemMessage"]
    assert "0 crafting_table" in result["systemMessage"]
    assert result["finalBlocks"] == {
        "plankA": "oak_planks",
        "plankB": "oak_planks",
        "table": None,
        "torchBase": "oak_planks",
        "torch": "torch",
    }
    rejected = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.rejected"
    )
    assert "current inventory" in rejected["payload"]["error"]
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"
    assert len(completed["payload"]["plan"]["blocks"]) == 4


@requires_node
def test_plan_and_build_repairs_elevated_floor_utility_blocks(tmp_path: Path) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['1,63,0', 'stone'],
    ['2,63,0', 'stone'],
    ['3,63,0', 'stone'],
]);
const bot = {{
    username: 'PlanBuildHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'cobblestone' }},
            {{ name: 'crafting_table' }},
            {{ name: 'chest' }},
            {{ name: 'oak_log' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'vera',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 1, dy: 0, dz: 0, block_type: 'cobblestone' }},
                        {{ dx: 1, dy: 1, dz: 0, block_type: 'crafting_table' }},
                        {{ dx: 2, dy: 0, dz: 0, block_type: 'cobblestone' }},
                        {{ dx: 2, dy: 1, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 3, dy: 0, dz: 0, block_type: 'cobblestone' }},
                        {{ dx: 3, dy: 1, dz: 0, block_type: 'chest' }},
                    ],
                    clear: [],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'crafting station');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        table: world.get('1,64,0'),
        support: world.get('2,64,0'),
        post: world.get('2,65,0'),
        chest: world.get('3,64,0'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "vera",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "table": "crafting_table",
        "support": "cobblestone",
        "post": "oak_log",
        "chest": "chest",
    }
    event_types = [event["type"] for event in result["events"]]
    assert "build_plan.generation.rejected" not in event_types
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "builder_model"
    plan_blocks = completed["payload"]["plan"]["blocks"]
    assert {"dx": 1, "dy": 0, "dz": 0, "block_type": "crafting_table"} in plan_blocks
    assert {"dx": 3, "dy": 0, "dz": 0, "block_type": "chest"} in plan_blocks
    assert {"dx": 1, "dy": 0, "dz": 0, "block_type": "cobblestone"} not in plan_blocks


@requires_node
def test_plan_and_build_uses_nearby_ground_origin_when_agent_is_elevated(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = 5; x <= 11; x += 1) {{
    for (let z = -3; z <= 3; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
world.set('7,64,0', 'cobblestone');
let plannerMessage = null;
const bot = {{
    username: 'ElevatedPlanBuildHarnessBot',
    entity: {{ position: {{ x: 7.4, y: 65, z: 0.6 }} }},
    inventory: {{
        slots: [{{ name: 'cobblestone' }}, {{ name: 'oak_planks' }}],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'rex',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest(messages) {{
                plannerMessage = messages[0].content;
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 1, dy: 0, dz: 1, block_type: 'cobblestone' }},
                        {{ dx: 2, dy: 0, dz: 1, block_type: 'oak_planks' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'mine staging yard');
const started = globalThis.__timelineEvents.find((event) => event.type === 'build_plan.generation.started');
process.stdout.write(JSON.stringify({{
    result,
    plannerMessage,
    origin: started.payload.origin,
    baseOrigin: started.payload.base_origin,
    finalBlocks: {{
        groundA: world.get('8,64,1'),
        groundB: world.get('9,64,1'),
        elevatedA: world.get('8,65,1') || null,
        elevatedB: world.get('9,65,1') || null,
    }},
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert result["origin"] == {"x": 7, "y": 64, "z": 0}
    assert result["baseOrigin"] == {"x": 7, "y": 64, "z": 0}
    assert '"y":64' in result["plannerMessage"]
    assert result["finalBlocks"] == {
        "groundA": "cobblestone",
        "groundB": "oak_planks",
        "elevatedA": None,
        "elevatedB": None,
    }
    assert "success" in result["result"]


@requires_node
def test_plan_and_build_uses_configured_settlement_origin_instead_of_roaming_agent(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = -2; x <= 2; x += 1) {{
    for (let z = -2; z <= 2; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
let plannerMessage = null;
const bot = {{
    username: 'SettlementAnchorHarnessBot',
    entity: {{ position: {{ x: 70, y: 71, z: -14 }} }},
    inventory: {{
        slots: [{{ name: 'cobblestone' }}],
        items() {{ return this.slots.filter(Boolean); }},
    }},
    pathfinder: {{
        async goto(goal) {{
            bot.entity.position = {{ x: goal.x, y: goal.y, z: goal.z }};
        }},
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
const agent = {{
    name: 'grok',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest(messages) {{
                plannerMessage = messages[0].content;
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'cobblestone' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'scout outpost');
const started = globalThis.__timelineEvents.find((event) => event.type === 'build_plan.generation.started');
process.stdout.write(JSON.stringify({{
    result,
    plannerMessage,
    origin: started.payload.origin,
    baseOrigin: started.payload.base_origin,
    anchoredBlock: world.get('0,64,0') || null,
    roamingBlock: world.get('70,71,-14') || null,
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "grok",
            "MC_SIM_BUILD_MODE": "settlement",
            "MC_SIM_SETTLEMENT_ORIGIN": "0,64,0",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert result["baseOrigin"] == {"x": 0, "y": 64, "z": 0}
    assert result["origin"] == {"x": 0, "y": 64, "z": 0}
    assert '"y":64' in result["plannerMessage"]
    assert result["anchoredBlock"] == "cobblestone"
    assert result["roamingBlock"] is None
    assert "success" in result["result"]


@requires_node
def test_plan_and_build_adjusts_shifted_open_meadow_origin_to_target_ground(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = -31; x <= -24; x += 1) {{
    for (let z = 41; z <= 48; z += 1) {{
        world.set(`${{x}},64,${{z}}`, 'grass_block');
    }}
}}
let plannerMessage = null;
const bot = {{
    username: 'ShiftedOriginHarnessBot',
    entity: {{ position: {{ x: -4, y: 64, z: -4 }} }},
    inventory: {{
        slots: [{{ name: 'cobblestone' }}, {{ name: 'oak_planks' }}],
        items() {{ return this.slots.filter(Boolean); }},
    }},
    pathfinder: {{
        setMovements(movements) {{
            this.movements = movements;
        }},
        async goto(goal) {{
            bot.entity.position = {{ x: goal.x, y: goal.y, z: goal.z - 2 }};
        }},
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
const agent = {{
    name: 'alpha',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest(messages) {{
                plannerMessage = messages[0].content;
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 1, dy: 0, dz: 1, block_type: 'cobblestone' }},
                        {{ dx: 2, dy: 0, dz: 1, block_type: 'oak_planks' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'shared storage depot');
const started = globalThis.__timelineEvents.find((event) => event.type === 'build_plan.generation.started');
process.stdout.write(JSON.stringify({{
    result,
    plannerMessage,
    origin: started.payload.origin,
    baseOrigin: started.payload.base_origin,
    placedA: world.get('-27,65,45'),
    placedB: world.get('-26,65,45'),
    untouchedGroundA: world.get('-27,64,45'),
    untouchedGroundB: world.get('-26,64,45'),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "alpha",
            "MINECRAFT_ALLOW_DESTRUCTIVE_PATHS": "0",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_ZONE_STRIDE": "24",
            "SOAK_EASY_SPAWN": "1",
            "EASY_SETUP_BOUNDARY": "none",
            "EASY_SETUP_MEADOW_RADIUS": "64",
        },
    )

    assert result["baseOrigin"] == {"x": -4, "y": 64, "z": -4}
    assert result["origin"] == {"x": -28, "y": 65, "z": 44}
    assert '"y":65' in result["plannerMessage"]
    assert result["placedA"] == "cobblestone"
    assert result["placedB"] == "oak_planks"
    assert result["untouchedGroundA"] == "grass_block"
    assert result["untouchedGroundB"] == "grass_block"
    assert "success" in result["result"]


@requires_node
def test_plan_and_build_updates_settlement_objective_shared_state(tmp_path: Path) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = 1; x <= 2; x += 1) {{
    for (let z = -2; z <= -1; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'stone');
    }}
}}
const bot = {{
    username: 'SettlementHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_log' }}, {{ name: 'oak_planks' }}],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'rex',
    bot,
    __ltagDirectorContext: {{
        scene_id: 'scene-settlement',
        build_macro: {{
            scene_id: 'scene-settlement',
            plan_id: 'director-plan-settlement',
            owner: 'rex',
            role: 'planner_owner',
            granted: true,
            objective_id: 'phase-1-starter-cabin',
            phase_index: 0,
            phase_owner: 'rex',
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'starter cabin');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        floorNW: world.get('1,64,-2'),
        postNW: world.get('1,65,-2'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_MODE": "settlement",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert result["finalBlocks"] == {"floorNW": "oak_planks", "postNW": "oak_log"}
    assert "success" in result["result"]
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    objective_writes = [
        call
        for call in calls
        if call["service"] == "shared_state"
        and call["method"] == "write"
        and call["payload"]["operation"].startswith("settlement_objective_")
    ]
    assert [call["payload"]["operation"] for call in objective_writes] == [
        "settlement_objective_assign",
        "settlement_objective_advance",
    ]
    assigned = objective_writes[0]["payload"]["settlement_objective"]
    completed = objective_writes[1]["payload"]["settlement_objective"]
    assert assigned["objective_id"] == "phase-1-starter-cabin"
    assert assigned["status"] == "in_progress"
    assert completed["status"] == "completed"
    assert completed["verified_blocks"] == 8
    assert completed["completion_ratio"] == 1
    assert [
        event["type"]
        for event in result["events"]
        if event["type"] == "settlement_objective.updated"
    ] == ["settlement_objective.updated", "settlement_objective.updated"]


@requires_node
def test_plan_and_build_skips_stale_settlement_objective_context(tmp_path: Path) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const agent = {{
    name: 'fork',
    bot: {{
        username: 'ForkHarnessBot',
        entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    }},
    __ltagDirectorContext: {{
        scene_id: 'settlement-phase-1',
        build_macro: {{
            scene_id: 'settlement-phase-1',
            plan_id: 'phase-one-plan',
            owner: 'fork',
            role: 'planner_owner',
            granted: true,
            objective_id: 'phase-1-starter-cabin',
            phase_index: 0,
            phase_owner: 'fork',
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest() {{
                throw new Error('stale settlement command must not call builder model');
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'simple wall');
process.stdout.write(JSON.stringify({{
    result,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    active_objective = {
        "objective_id": "phase-2-perimeter-wall",
        "phase_index": 1,
        "description": "perimeter wall",
        "owner_agent_id": "rex",
        "status": "pending",
    }
    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "fork",
            "MC_SIM_BUILD_MODE": "settlement",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
            "STUB_ACTIVE_OBJECTIVE_JSON": json.dumps(active_objective),
        },
    )

    assert result["result"] == "plan-and-build skipped: stale_settlement_objective"
    event_types = [event["type"] for event in result["events"]]
    assert "build_plan.generation.skipped" in event_types
    assert "build_plan.generation.completed" not in event_types
    assert "build_plan.execution.completed" not in event_types
    skipped = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.skipped"
    )
    assert skipped["payload"]["reason"] == "stale_settlement_objective"
    assert skipped["payload"]["active_objective_id"] == "phase-2-perimeter-wall"
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    assert [(call["service"], call["method"]) for call in calls] == [("shared_state", "read")]


@requires_node
def test_plan_and_build_marks_settlement_owner_cap_for_reassignment(tmp_path: Path) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const agent = {{
    name: 'rex',
    bot: {{
        username: 'RexCapHarnessBot',
        entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    }},
    __ltagDirectorContext: {{
        scene_id: 'settlement-phase-5',
        build_macro: {{
            scene_id: 'settlement-phase-5',
            plan_id: 'phase-five-plan',
            owner: 'rex',
            role: 'planner_owner',
            granted: true,
            objective_id: 'phase-5-hunting-lodge',
            phase_index: 4,
            phase_owner: 'rex',
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest() {{
                throw new Error('per-agent cap should prevent builder call');
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'hunting prep lodge');
process.stdout.write(JSON.stringify({{
    result,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    active_objective = {
        "objective_id": "phase-5-hunting-lodge",
        "phase_index": 4,
        "description": "hunting prep lodge",
        "owner_agent_id": "rex",
        "status": "pending",
    }
    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MC_SIM_BUILD_MODE": "settlement",
            "MC_SIM_BUILD_MAX_PER_AGENT": "0",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
            "STUB_ACTIVE_OBJECTIVE_JSON": json.dumps(active_objective),
        },
    )

    assert result["result"] == "plan-and-build skipped: per_agent_cap"
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    objective_advances = [
        call["payload"]["settlement_objective"]
        for call in calls
        if call["service"] == "shared_state"
        and call["method"] == "write"
        and call["payload"]["operation"] == "settlement_objective_advance"
    ]
    assert len(objective_advances) == 1
    capped = objective_advances[0]
    assert capped["objective_id"] == "phase-5-hunting-lodge"
    assert capped["owner_agent_id"] == "rex"
    assert capped["status"] == "owner_cap_reached"
    assert capped["evidence"]["skipped_reason"] == "per_agent_cap"
    updated = [
        event for event in result["events"] if event["type"] == "settlement_objective.updated"
    ]
    assert updated[0]["payload"]["status"] == "owner_cap_reached"


@requires_node
@pytest.mark.parametrize("objective_status", ["blocked", "pending"])
def test_plan_and_build_allows_director_reassigned_settlement_owner(
    tmp_path: Path,
    objective_status: str,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = -1; x <= 1; x += 1) {{
    for (let z = -1; z <= 1; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
const bot = {{
    username: 'ForkReassignHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_planks' }}],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'fork',
    bot,
    __ltagDirectorContext: {{
        scene_id: 'settlement-phase-3',
        build_macro: {{
            scene_id: 'settlement-phase-3',
            plan_id: 'phase-three-reassigned-plan',
            owner: 'fork',
            role: 'planner_owner',
            granted: true,
            objective_id: 'phase-3-workshop-station',
            phase_index: 2,
            phase_owner: 'fork',
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'workshop station');
process.stdout.write(JSON.stringify({{
    result,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    active_objective = {
        "objective_id": "phase-3-workshop-station",
        "phase_index": 2,
        "description": "workshop station",
        "owner_agent_id": "pixel",
        "status": objective_status,
    }
    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "fork",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "2",
            "MC_SIM_BUILD_MODE": "settlement",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
            "STUB_ACTIVE_OBJECTIVE_JSON": json.dumps(active_objective),
        },
    )

    assert "settlement_owner_mismatch" not in result["result"]
    assert "plan-and-build" in result["result"]
    event_types = [event["type"] for event in result["events"]]
    assert "build_plan.generation.completed" in event_types
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    objective_writes = [
        call
        for call in calls
        if call["service"] == "shared_state"
        and call["method"] == "write"
        and call["payload"]["operation"].startswith("settlement_objective_")
    ]
    assert objective_writes
    assigned = objective_writes[0]["payload"]["settlement_objective"]
    assert assigned["objective_id"] == "phase-3-workshop-station"
    assert assigned["owner_agent_id"] == "fork"
    assert assigned["status"] == "in_progress"


@requires_node
def test_plan_and_build_uses_active_objective_description_for_settlement_fallback(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = -2; x <= 2; x += 1) {{
    world.set(`${{x}},63,0`, 'grass_block');
}}
let builderPrompt = '';
const bot = {{
    username: 'RexActiveObjectiveHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'cobblestone' }},
            {{ name: 'torch' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'rex',
    bot,
    __ltagDirectorContext: {{
        scene_id: 'settlement-phase-2',
        build_macro: {{
            scene_id: 'settlement-phase-2',
            plan_id: 'phase-two-plan',
            owner: 'rex',
            role: 'planner_owner',
            granted: true,
            objective_id: 'phase-2-perimeter-wall',
            phase_index: 1,
            phase_owner: 'rex',
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest(messages) {{
                builderPrompt = messages[0].content;
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }},
                        {{ dx: 1, dy: 0, dz: 0, block_type: 'chest' }},
                        {{ dx: -1, dy: 0, dz: 0, block_type: 'crafting_table' }},
                        {{ dx: 0, dy: 1, dz: 1, block_type: 'torch' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(
    agent,
    'Reinforce the perimeter gate and plan for storage sheds inside.',
);
process.stdout.write(JSON.stringify({{
    result,
    builderPrompt,
    finalBlocks: {{
        left: world.get('-2,64,0'),
        center: world.get('0,64,0'),
        right: world.get('2,64,0'),
        leftTorch: world.get('-2,65,0'),
        rightTorch: world.get('2,65,0'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    active_objective = {
        "objective_id": "phase-2-perimeter-wall",
        "phase_index": 1,
        "description": "perimeter wall",
        "owner_agent_id": "rex",
        "status": "pending",
    }
    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "20",
            "MC_SIM_BUILD_MODE": "settlement",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
            "STUB_ACTIVE_OBJECTIVE_JSON": json.dumps(active_objective),
        },
    )

    assert "Build request: perimeter wall" in result["builderPrompt"]
    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "left": "cobblestone",
        "center": "cobblestone",
        "right": "cobblestone",
        "leftTorch": "torch",
        "rightTorch": "torch",
    }
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["description"] == "perimeter wall"
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"


@requires_node
def test_plan_and_build_scene_lock_suppresses_duplicate_and_reuses_cache(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'stone'],
    ['1,63,0', 'stone'],
]);
let plannerCalls = 0;
let releaseBuilder;
const builderStarted = new Promise((resolve) => {{
    releaseBuilder = () => {{}};
    globalThis.__resolveBuilderStarted = resolve;
}});
const waitForRelease = new Promise((resolve) => {{
    releaseBuilder = resolve;
}});

function makeBot(username) {{
    return {{
        username,
        entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
        inventory: {{
            slots: [{{ name: 'oak_log' }}, {{ name: 'torch' }}],
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
        async dig(targetBlock) {{
            world.set(key(targetBlock.position), 'air');
        }},
    }};
}}

const rex = {{
    name: 'rex',
    bot: makeBot('RexHarnessBot'),
    __ltagDirectorContext: {{
        scene_id: 'scene-build-cache',
        build_macro: {{
            scene_id: 'scene-build-cache',
            plan_id: 'director-plan-cache',
            owner: 'rex',
            role: 'planner_owner',
            granted: true,
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest() {{
                plannerCalls += 1;
                globalThis.__resolveBuilderStarted();
                await waitForRelease;
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 1, dy: 0, dz: 0, block_type: 'torch' }},
                    ],
                }});
            }},
        }},
    }},
}};
const vera = {{
    name: 'vera',
    bot: makeBot('VeraHarnessBot'),
    __ltagDirectorContext: {{
        scene_id: 'scene-build-cache',
        build_macro: {{
            scene_id: 'scene-build-cache',
            plan_id: 'director-plan-cache',
            owner: 'rex',
            role: 'support',
            support_task: 'Gather oak logs for Rex.',
            granted: false,
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest() {{
                throw new Error('support agent must not invoke builder model');
            }},
        }},
    }},
}};

const firstPromise = mod.planAndBuildAction.perform(rex, 'shared marker');
await builderStarted;
const second = await mod.planAndBuildAction.perform(vera, 'shared marker');
releaseBuilder();
const first = await firstPromise;
const third = await mod.planAndBuildAction.perform(rex, 'shared marker');

process.stdout.write(JSON.stringify({{
    first,
    second,
    third,
    plannerCalls,
    finalBlocks: {{ a: world.get('0,64,0'), b: world.get('1,64,0') }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
            "MC_SIM_BUILD_COOLDOWN_SEC": "0",
        },
    )

    assert result["plannerCalls"] == 1
    assert "success" in result["first"]
    assert result["second"] == "plan-and-build skipped: scene_locked"
    assert "success" in result["third"]
    assert result["finalBlocks"] == {"a": "oak_log", "b": "torch"}
    skipped = [
        event["payload"]
        for event in result["events"]
        if event["type"] == "build_plan.generation.skipped"
    ]
    assert any(
        payload["reason"] == "scene_locked" and payload["owner"] == "rex" for payload in skipped
    )
    assert any(payload["reason"] == "cache_hit" for payload in skipped)
    completed = [
        event["payload"]
        for event in result["events"]
        if event["type"] == "build_plan.generation.completed"
    ]
    assert completed[0]["scene_id"] == "scene-build-cache"
    assert completed[0]["owner"] == "rex"
    assert completed[-1]["source"] == "plan_cache"
    execution_completed = [
        event["payload"]
        for event in result["events"]
        if event["type"] == "build_plan.execution.completed"
    ]
    assert execution_completed[-1]["verified_blocks"] == 2


@requires_node
def test_plan_and_build_provider_metadata_for_local_and_openrouter_modes(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    provider_path = plan_action.parents[1] / "skills" / "builder_provider.js"
    governor_path = plan_action.parents[1] / "skills" / "build_plan_governor.js"
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const provider = await import(pathToFileURL({json.dumps(str(provider_path))}).href);
const governor = await import(pathToFileURL({json.dumps(str(governor_path))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});

function makeAgent(name, sceneId, model) {{
    const world = new Map([['0,63,0', 'stone']]);
    return {{
        name,
        bot: {{
            username: `${{name}}ProviderHarnessBot`,
            entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
            inventory: {{
                slots: [{{ name: 'oak_log' }}],
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
            async dig(targetBlock) {{
                world.set(key(targetBlock.position), 'air');
            }},
        }},
        __ltagDirectorContext: {{
            scene_id: sceneId,
            build_macro: {{
                scene_id: sceneId,
                plan_id: `${{sceneId}}-plan`,
                owner: name,
                role: 'planner_owner',
                granted: true,
            }},
        }},
        prompter: {{
            code_model: model,
        }},
    }};
}}

async function runLocal() {{
    globalThis.__timelineEvents = [];
    provider.resetBuilderProviderState();
    governor.resetBuildPlanGovernor();
    process.env.MC_SIM_BUILDER_PROVIDER = 'local';
    const agent = makeAgent('rex', 'scene-local-provider', {{
        model_name: 'local/build-json',
        async sendRequest() {{
            return JSON.stringify({{ blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }}] }});
        }},
    }});
    await mod.planAndBuildAction.perform(agent, 'local marker');
    return globalThis.__timelineEvents.find((event) => event.type === 'build_plan.generation.completed').payload;
}}

async function runOpenRouter() {{
    globalThis.__timelineEvents = [];
    provider.resetBuilderProviderState();
    governor.resetBuildPlanGovernor();
    process.env.MC_SIM_BUILDER_PROVIDER = 'openrouter';
    process.env.MC_SIM_BUILDER_OPENROUTER_MODEL = 'openrouter/test-builder';
    process.env.MC_SIM_BUILDER_OPENROUTER_API_KEY = 'test-key';
    process.env.MC_SIM_BUILDER_USD_PER_1K_INPUT = '0.001';
    process.env.MC_SIM_BUILDER_USD_PER_1K_OUTPUT = '0.002';
    globalThis.fetch = async () => ({{
        ok: true,
        status: 200,
        async text() {{
            return JSON.stringify({{
                choices: [
                    {{
                        message: {{
                            content: JSON.stringify({{
                                blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }}],
                            }}),
                        }},
                    }},
                ],
                usage: {{ prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 }},
            }});
        }},
    }});
    const agent = makeAgent('fork', 'scene-openrouter-provider', null);
    await mod.planAndBuildAction.perform(agent, 'openrouter marker');
    return globalThis.__timelineEvents.find((event) => event.type === 'build_plan.generation.completed').payload;
}}

const localPayload = await runLocal();
const openrouterPayload = await runOpenRouter();
process.stdout.write(JSON.stringify({{ localPayload, openrouterPayload }}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
            "MC_SIM_BUILD_COOLDOWN_SEC": "0",
        },
    )

    assert result["localPayload"]["builder_provider"] == "local"
    assert result["localPayload"]["builder_model"] == "local/build-json"
    assert result["localPayload"]["paid"] is False
    assert result["localPayload"]["request_count_run"] == 0
    assert result["openrouterPayload"]["builder_provider"] == "openrouter"
    assert result["openrouterPayload"]["builder_model"] == "openrouter/test-builder"
    assert result["openrouterPayload"]["paid"] is True
    assert result["openrouterPayload"]["request_count_run"] == 1
    assert result["openrouterPayload"]["request_count_agent"] == 1
    assert result["openrouterPayload"]["estimated_usd"] > 0


@requires_node
def test_plan_and_build_rejects_invalid_model_plan_and_uses_starter_blueprint(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['-1,63,0', 'stone'],
    ['0,63,0', 'stone'],
    ['1,63,0', 'stone'],
]);
const bot = {{
    username: 'PlanBuildFallbackHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_log' }}, {{ name: 'cobblestone' }}, {{ name: 'torch' }}],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'pixel',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [{{ dx: 99, dy: 0, dz: 0, block_type: 'bedrock' }}],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'marker camp');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        center0: world.get('0,64,0'),
        center1: world.get('0,65,0'),
        center2: world.get('0,66,0'),
        left: world.get('-1,64,0'),
        right: world.get('1,64,0'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "pixel",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert result["finalBlocks"] == {
        "center0": "oak_log",
        "center1": "oak_log",
        "center2": "torch",
        "left": "cobblestone",
        "right": "cobblestone",
    }
    event_types = [event["type"] for event in result["events"]]
    assert "build_plan.generation.rejected" in event_types
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"
    assert "plan_json" in completed["payload"]
    rejected = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.rejected"
    )
    assert "exceeds horizontal build bounds" in rejected["payload"]["error"]


@requires_node
def test_plan_and_build_does_not_fallback_to_marker_for_unknown_non_cabin(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([['0,63,0', 'grass_block']]);
const bot = {{
    username: 'NoFallbackHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_log' }}, {{ name: 'cobblestone' }}, {{ name: 'torch' }}],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'fork',
    bot,
    __ltagDirectorContext: {{
        scene_id: 'settlement-phase-2',
        build_macro: {{
            scene_id: 'settlement-phase-2',
            plan_id: 'phase-two-plan',
            owner: 'fork',
            role: 'planner_owner',
            granted: true,
            objective_id: 'phase-two',
            phase_index: 2,
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [{{ dx: 99, dy: 0, dz: 0, block_type: 'bedrock' }}],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'decorative statue balcony');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        markerBase: world.get('0,64,0') || null,
        markerTop: world.get('0,66,0') || null,
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "fork",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "8",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert result["result"] == "plan-and-build skipped: no_starter_blueprint"
    assert result["finalBlocks"] == {"markerBase": None, "markerTop": None}
    event_types = [event["type"] for event in result["events"]]
    assert "build_plan.generation.rejected" in event_types
    assert "build_plan.generation.skipped" in event_types
    assert "build_plan.generation.completed" not in event_types
    skipped = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.skipped"
    )
    assert skipped["payload"]["reason"] == "no_starter_blueprint"
    assert skipped["payload"]["objective_id"] == "phase-two"


@requires_node
def test_plan_and_build_rejects_tiny_cabin_plan_and_uses_cabin_blueprint(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = -2; x <= 2; x += 1) {{
    for (let z = -2; z <= 2; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
const bot = {{
    username: 'RexHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'oak_log' }},
            {{ name: 'oak_planks' }},
            {{ name: 'cobblestone' }},
            {{ name: 'torch' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'rex',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 1, dy: 0, dz: 1, block_type: 'oak_planks' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(
    agent,
    'full log cabin house with oak-log corners, oak-plank walls, cobblestone foundation, torch-lit interior, doorway, and simple roof',
);
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        nwBase: world.get('-1,64,-1'),
        seTop: world.get('1,66,1'),
        threshold: world.get('0,64,-1'),
        doorwayTorch: world.get('0,65,-1'),
        sideWall: world.get('-1,65,0'),
        roof: world.get('-1,67,0'),
        ridge: world.get('-1,68,0'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "64",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "nwBase": "oak_log",
        "seTop": "oak_log",
        "threshold": "cobblestone",
        "doorwayTorch": "torch",
        "sideWall": "oak_planks",
        "roof": "oak_planks",
        "ridge": "oak_planks",
    }
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"
    assert len(completed["payload"]["plan"]["blocks"]) >= 32
    rejected = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.rejected"
    )
    assert "cabin plan too small" in rejected["payload"]["error"]


@requires_node
def test_plan_and_build_uses_ordered_compact_cabin_when_step_cap_is_low(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = 0; x <= 4; x += 1) {{
    for (let z = -4; z <= 1; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
const bot = {{
    username: 'ForkHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'oak_log' }},
            {{ name: 'oak_planks' }},
            {{ name: 'cobblestone' }},
            {{ name: 'torch' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'fork',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 1, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 1, dy: 1, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 2, dy: 1, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }},
                        {{ dx: 1, dy: 0, dz: 0, block_type: 'oak_planks' }},
                        {{ dx: 2, dy: 0, dz: 0, block_type: 'oak_planks' }},
                        {{ dx: 0, dy: 1, dz: 1, block_type: 'oak_log' }},
                        {{ dx: 1, dy: 1, dz: 1, block_type: 'oak_log' }},
                        {{ dx: 2, dy: 1, dz: 1, block_type: 'oak_log' }},
                        {{ dx: 0, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 1, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 2, dy: 0, dz: 1, block_type: 'oak_planks' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'small shared cabin');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        floorNW: world.get('0,64,0'),
        floorSE: world.get('2,64,1'),
        postNW: world.get('0,65,0'),
        postSE: world.get('2,65,1'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "fork",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "12",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "floorNW": "oak_planks",
        "floorSE": "oak_planks",
        "postNW": "oak_log",
        "postSE": "oak_log",
    }
    event_types = [event["type"] for event in result["events"]]
    assert "build_plan.generation.rejected" not in event_types
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "builder_model"
    assert len(completed["payload"]["plan"]["blocks"]) == 12
    assert [block["dy"] for block in completed["payload"]["plan"]["blocks"][:6]] == [0] * 6
    assert [block["dy"] for block in completed["payload"]["plan"]["blocks"][6:]] == [1] * 6


@requires_node
def test_plan_and_build_rejects_line_cabin_and_uses_compact_blueprint(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = 0; x <= 4; x += 1) {{
    for (let z = -4; z <= 1; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
const bot = {{
    username: 'ForkLineCabinHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'oak_log' }},
            {{ name: 'oak_planks' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'fork',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 1, dy: 0, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 2, dy: 0, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 3, dy: 0, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 4, dy: 0, dz: 0, block_type: 'oak_log' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'small shared cabin');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        floorNW: world.get('1,64,-2'),
        floorSE: world.get('2,64,-1'),
        postNW: world.get('1,65,-2'),
        postSE: world.get('2,65,-1'),
        roofNW: world.get('1,66,-2'),
        roofSE: world.get('2,66,-1'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "fork",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "20",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "floorNW": "oak_planks",
        "floorSE": "oak_planks",
        "postNW": "oak_log",
        "postSE": "oak_log",
        "roofNW": "oak_planks",
        "roofSE": "oak_planks",
    }
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"
    assert len(completed["payload"]["plan"]["blocks"]) == 12
    rejected = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.rejected"
    )
    assert "recognizable footprint" in rejected["payload"]["error"]


@requires_node
def test_plan_and_build_rejects_stone_wall_and_uses_cobblestone_blueprint(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = -2; x <= 2; x += 1) {{
    world.set(`${{x}},63,0`, 'grass_block');
}}
const bot = {{
    username: 'RexWallHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'cobblestone' }},
            {{ name: 'torch' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'rex',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 0, dz: 0, block_type: 'stone' }},
                        {{ dx: 1, dy: 0, dz: 0, block_type: 'stone' }},
                        {{ dx: 2, dy: 0, dz: 0, block_type: 'stone' }},
                        {{ dx: 3, dy: 0, dz: 0, block_type: 'stone' }},
                        {{ dx: 4, dy: 0, dz: 0, block_type: 'stone' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'a simple 5x3 stone perimeter wall');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        left: world.get('-2,64,0'),
        center: world.get('0,64,0'),
        right: world.get('2,64,0'),
        leftTorch: world.get('-2,65,0'),
        rightTorch: world.get('2,65,0'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "rex",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "20",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "left": "cobblestone",
        "center": "cobblestone",
        "right": "cobblestone",
        "leftTorch": "torch",
        "rightTorch": "torch",
    }
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"
    assert len(completed["payload"]["plan"]["blocks"]) == 7
    rejected = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.rejected"
    )
    assert "easy starter kit" in rejected["payload"]["error"]


@requires_node
def test_plan_and_build_rejects_unsupported_workbench_and_uses_workshop_blueprint(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = 1; x <= 2; x += 1) {{
    for (let z = 1; z <= 2; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
const bot = {{
    username: 'PixelWorkbenchHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'oak_log' }},
            {{ name: 'oak_planks' }},
            {{ name: 'crafting_table' }},
            {{ name: 'torch' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'pixel',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 0, dy: 1, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 1, dy: 1, dz: 0, block_type: 'oak_log' }},
                        {{ dx: 2, dy: 1, dz: 0, block_type: 'oak_log' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'basic workbench setup');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        plankA: world.get('1,64,1'),
        plankB: world.get('2,64,1'),
        table: world.get('1,64,2'),
        torchBase: world.get('2,64,2'),
        torch: world.get('2,65,2'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "pixel",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "20",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "plankA": "oak_planks",
        "plankB": "oak_planks",
        "table": "crafting_table",
        "torchBase": "oak_planks",
        "torch": "torch",
    }
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "starter_blueprint_after_rejection"
    assert len(completed["payload"]["plan"]["blocks"]) == 5
    rejected = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.rejected"
    )
    assert "unsupported upper blocks" in rejected["payload"]["error"]


@requires_node
def test_plan_and_build_repairs_elevated_utility_blocks_without_blueprint_fallback(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = 1; x <= 2; x += 1) {{
    for (let z = 1; z <= 2; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
const bot = {{
    username: 'UtilityFloorHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [
            {{ name: 'oak_planks' }},
            {{ name: 'crafting_table' }},
            {{ name: 'chest' }},
            {{ name: 'torch' }},
        ],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'alpha',
    bot,
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 1, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 2, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 1, dy: 1, dz: 1, block_type: 'crafting_table' }},
                        {{ dx: 2, dy: 1, dz: 1, block_type: 'chest' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'crafting hall');
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        table: world.get('1,64,1'),
        chest: world.get('2,64,1'),
    }},
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "alpha",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "20",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "success" in result["result"]
    assert result["finalBlocks"] == {
        "table": "crafting_table",
        "chest": "chest",
    }
    event_types = [event["type"] for event in result["events"]]
    assert "build_plan.generation.rejected" not in event_types
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.generation.completed"
    )
    assert completed["payload"]["source"] == "builder_model"
    plan_blocks = completed["payload"]["plan"]["blocks"]
    assert {"dx": 1, "dy": 0, "dz": 1, "block_type": "crafting_table"} in plan_blocks
    assert {"dx": 2, "dy": 0, "dz": 1, "block_type": "chest"} in plan_blocks
    assert {"dx": 1, "dy": 0, "dz": 1, "block_type": "oak_planks"} not in plan_blocks
    assert {"dx": 2, "dy": 0, "dz": 1, "block_type": "oak_planks"} not in plan_blocks


@requires_node
def test_plan_and_build_treats_high_completion_partial_as_completed(
    tmp_path: Path,
) -> None:
    plan_action, calls_path = _stage_plan_and_build_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

globalThis.__timelineEvents = [];
const mod = await import(pathToFileURL({json.dumps(str(plan_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map();
for (let x = 0; x <= 4; x += 1) {{
    for (let z = 0; z <= 4; z += 1) {{
        world.set(`${{x}},63,${{z}}`, 'grass_block');
    }}
}}
const bot = {{
    username: 'PartialHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_log' }}, {{ name: 'oak_planks' }}],
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
        if (key(target) === '2,65,1') return;
        world.set(key(target), this.heldItem.name);
    }},
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const agent = {{
    name: 'fork',
    bot,
    __ltagDirectorContext: {{
        scene_id: 'settlement-phase-1',
        build_macro: {{
            scene_id: 'settlement-phase-1',
            plan_id: 'partial-plan',
            owner: 'fork',
            role: 'planner_owner',
            granted: true,
            objective_id: 'phase-1-starter-cabin',
            phase_index: 0,
            phase_owner: 'fork',
        }},
    }},
    prompter: {{
        code_model: {{
            async sendRequest() {{
                return JSON.stringify({{
                    blocks: [
                        {{ dx: 1, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 2, dy: 0, dz: 1, block_type: 'oak_planks' }},
                        {{ dx: 1, dy: 0, dz: 2, block_type: 'oak_planks' }},
                        {{ dx: 2, dy: 0, dz: 2, block_type: 'oak_planks' }},
                        {{ dx: 1, dy: 1, dz: 1, block_type: 'oak_log' }},
                        {{ dx: 2, dy: 1, dz: 1, block_type: 'oak_log' }},
                    ],
                }});
            }},
        }},
    }},
}};
const result = await mod.planAndBuildAction.perform(agent, 'small shared cabin');
process.stdout.write(JSON.stringify({{
    result,
    events: globalThis.__timelineEvents.map((event) => ({{
        type: event.type,
        payload: event.payload,
    }})),
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "fork",
            "MINECRAFT_PLAN_BUILD_MAX_STEPS": "12",
            "MC_SIM_BUILD_MODE": "settlement",
            "MC_SIM_BUILD_ZONE_STRIDE": "0",
        },
    )

    assert "partial" in result["result"]
    completed = next(
        event for event in result["events"] if event["type"] == "build_plan.execution.completed"
    )
    assert completed["payload"]["status"] == "completed"
    assert completed["payload"]["metric"]["completion_ratio"] == pytest.approx(5 / 6, abs=0.001)
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    objective_advances = [
        call["payload"]["settlement_objective"]
        for call in calls
        if call["service"] == "shared_state"
        and call["method"] == "write"
        and call["payload"]["operation"] == "settlement_objective_advance"
    ]
    assert objective_advances[0]["status"] == "completed"
    assert objective_advances[0]["completion_ratio"] == pytest.approx(5 / 6, abs=0.001)


def test_package_json_wires_embodiment_build_plan_verifier() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]

    assert (
        scripts.get("verify:embodiment-build-plan")
        == ".venv/bin/pytest tests/backend/test_embodiment_build_plan.py -v"
    )


@requires_node
async def test_build_from_plan_action_reports_actual_vs_intended_structure(
    tmp_path: Path,
    captured_bridge_events: dict[str, list[dict[str, Any]]],
) -> None:
    build_action, calls_path = _stage_action_with_stub_bridge(tmp_path)
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

const mod = await import(pathToFileURL({json.dumps(str(build_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'stone'],
    ['1,63,0', 'stone'],
]);
const bot = {{
    username: 'BuildPlanHarnessBot',
    inventory: {{
        slots: [{{ name: 'oak_planks' }}],
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
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const plan = {{
    palette: {{ wall: 'minecraft:oak_planks' }},
    blocks: [
        {{ dx: 0, dy: 0, dz: 0, block_type: 'wall' }},
        {{ dx: 1, dy: 0, dz: 0, block_type: 'wall' }},
        {{ dx: 0, dy: 1, dz: 0, block_type: 'wall' }},
        {{ dx: 1, dy: 1, dz: 0, block_type: 'wall' }},
    ],
}};
const result = await mod.buildFromPlanAction.perform(
    {{ name: 'vera', bot }},
    'build-plan-1',
    {{ x: 0, y: 64, z: 0 }},
    plan,
    10,
    10000,
);
process.stdout.write(JSON.stringify({{
    status: 'ok',
    result,
    finalBlocks: {{
        a: world.get('0,64,0'),
        b: world.get('1,64,0'),
        c: world.get('0,65,0'),
        d: world.get('1,65,0'),
    }},
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "LTAG_AGENT_ID": "vera",
            "LTAG_RUN_ID": "run-build-plan-test",
            "LTAG_SIMULATION_ID": "00000000-0000-0000-0000-000000000559",
        },
    )
    await _dispatch_recorded_inbound_calls(calls_path)

    assert result["status"] == "ok"
    assert result["finalBlocks"] == {
        "a": "oak_planks",
        "b": "oak_planks",
        "c": "oak_planks",
        "d": "oak_planks",
    }

    step_actions = [
        action
        for action in captured_bridge_events["action"]
        if action["action_id"].startswith("build-plan-1#")
    ]
    terminal_actions = [
        action
        for action in captured_bridge_events["action"]
        if action["action_id"] == "build-plan-1"
    ]
    structure_observations = [
        observation
        for event in captured_bridge_events["perception"]
        for observation in event["observations"]
        if observation.get("type") == "structure"
    ]

    assert [action["action_id"] for action in step_actions] == [
        "build-plan-1#1",
        "build-plan-1#2",
        "build-plan-1#3",
        "build-plan-1#4",
    ]
    assert all(action["status"] == "success" for action in step_actions)
    assert len(terminal_actions) == 1
    assert terminal_actions[0]["status"] == "success"
    assert len(structure_observations) == 1

    structure = structure_observations[0]
    assert structure["metric"] == {
        "intended_count": 4,
        "blocks_present": 4,
        "blocks_missing": 0,
        "blocks_unexpected": 0,
        "steps_verified": 4,
        "steps_abandoned": 0,
        "completion_ratio": 1,
    }
    assert "intended=4" in terminal_actions[0]["detail"]
    assert "present=4" in terminal_actions[0]["detail"]
    assert verify_build_plan(structure) == {
        "verified": True,
        "class": "success",
        "intended": 4,
        "present": 4,
        "missing": 0,
        "unexpected": 0,
        "steps_verified": 4,
        "steps_abandoned": 0,
        "completion": 1.0,
    }


@requires_node
def test_build_from_plan_pathfinds_to_distant_origin_before_placing(tmp_path: Path) -> None:
    build_action, calls_path = _stage_action_with_stub_bridge(tmp_path)
    pathfinder_pkg = tmp_path / "node_modules" / "mineflayer-pathfinder"
    pathfinder_pkg.mkdir(parents=True)
    (pathfinder_pkg / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    (pathfinder_pkg / "index.js").write_text(
        """
export class Movements {
    constructor(bot) {
        this.bot = bot;
        this.canDig = true;
        this.allow1by1towers = true;
    }
}
export const goals = {
    GoalNear: class GoalNear {
        constructor(x, y, z, range) {
            this.x = x;
            this.y = y;
            this.z = z;
            this.range = range;
        }
    },
};
export const pathfinder = {};
export default { Movements, goals, pathfinder };
""".lstrip(),
        encoding="utf-8",
    )
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(build_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([['10,63,0', 'stone']]);
const gotoCalls = [];
const bot = {{
    username: 'BuildPathfindHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_planks' }}],
        items() {{ return this.slots.filter(Boolean); }},
    }},
    pathfinder: {{
        setMovements(movements) {{
            this.movements = movements;
        }},
        async goto(goal) {{
            gotoCalls.push({{ x: goal.x, y: goal.y, z: goal.z, range: goal.range }});
            await new Promise((resolve) => setTimeout(resolve, 25));
            bot.entity.position = {{ x: goal.x, y: goal.y, z: goal.z - 2 }};
        }},
    }},
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return block(world.get(key(cell)) || 'air', cell);
    }},
    async equip(item) {{
        this.heldItem = item;
    }},
    async placeBlock(referenceBlock, faceVector) {{
        const dx = referenceBlock.position.x - this.entity.position.x;
        const dy = referenceBlock.position.y - this.entity.position.y;
        const dz = referenceBlock.position.z - this.entity.position.z;
        if ((dx * dx + dy * dy + dz * dz) > 25) {{
            throw new Error('too far away');
        }}
        const target = {{
            x: referenceBlock.position.x + faceVector.x,
            y: referenceBlock.position.y + faceVector.y,
            z: referenceBlock.position.z + faceVector.z,
        }};
        world.set(key(target), this.heldItem.name);
    }},
}};
const result = await mod.buildFromPlanAction.perform(
    {{ name: 'rex', bot }},
    'build-plan-pathfind',
    {{ x: 10, y: 64, z: 0 }},
    {{ blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }}] }},
    10,
    10000,
);
process.stdout.write(JSON.stringify({{
    result,
    placed: world.get('10,64,0'),
    gotoCalls,
    movementsCanDig: bot.pathfinder.movements && bot.pathfinder.movements.canDig,
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "MINECRAFT_ALLOW_DESTRUCTIVE_PATHS": "0",
            "MINECRAFT_BUILD_FROM_PLAN_NAVIGATION_TIMEOUT_MS": "1",
            "MINECRAFT_BUILD_FROM_PLAN_NAVIGATION_MS_PER_BLOCK": "50",
        },
    )

    assert "success" in result["result"]
    assert result["placed"] == "oak_planks"
    assert result["gotoCalls"] == [{"x": 10, "y": 64, "z": 0, "range": 1}]
    assert result["movementsCanDig"] is False


@requires_node
def test_build_from_plan_continues_after_step_bridge_report_outage(tmp_path: Path) -> None:
    build_action, calls_path = _stage_action_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(build_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'grass_block'],
    ['1,63,0', 'grass_block'],
]);
const bot = {{
    username: 'BridgeOutageBuildHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_planks' }}],
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
const result = await mod.buildFromPlanAction.perform(
    {{ name: 'fork', bot }},
    'build-plan-bridge-outage',
    {{ x: 0, y: 64, z: 0 }},
    {{ blocks: [
        {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }},
        {{ dx: 1, dy: 0, dz: 0, block_type: 'oak_planks' }},
    ] }},
    10,
    10000,
);
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        a: world.get('0,64,0'),
        b: world.get('1,64,0'),
    }},
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "STUB_FAIL_BRIDGE_ONCE": "perception.report",
        },
    )

    calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
    assert "success" in result["result"]
    assert "report warning" in result["result"]
    assert result["finalBlocks"] == {"a": "oak_planks", "b": "oak_planks"}
    assert any(call["service"] == "action" and call["method"] == "result" for call in calls)


@requires_node
def test_build_from_plan_torch_reconcile_preserves_structural_supports(tmp_path: Path) -> None:
    build_action, calls_path = _stage_action_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(build_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([['0,63,0', 'grass_block']]);
const bot = {{
    username: 'TorchRepairHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_log' }}, {{ name: 'torch' }}],
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
        if (this.heldItem.name === 'torch' && target.y === 66) {{
            world.set(`${{target.x}},${{target.y - 2}},${{target.z}}`, 'air');
            world.set(`${{target.x}},${{target.y - 1}},${{target.z}}`, 'wall_torch');
            return;
        }}
        world.set(key(target), this.heldItem.name);
    }},
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
}};
const result = await mod.buildFromPlanAction.perform(
    {{ name: 'vera', bot }},
    'build-plan-torch-repair',
    {{ x: 0, y: 64, z: 0 }},
    {{
        blocks: [
            {{ dx: 0, dy: 0, dz: 0, block_type: 'oak_log' }},
            {{ dx: 0, dy: 1, dz: 0, block_type: 'oak_log' }},
            {{ dx: 0, dy: 2, dz: 0, block_type: 'torch' }},
        ],
    }},
    10,
    10000,
);
process.stdout.write(JSON.stringify({{
    result,
    finalBlocks: {{
        base: world.get('0,64,0'),
        support: world.get('0,65,0'),
        torch: world.get('0,66,0') || 'air',
    }},
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
        },
    )

    assert "partial" in result["result"]
    assert "present=2" in result["result"]
    assert "completion=0.667" in result["result"]
    assert result["finalBlocks"] == {
        "base": "oak_log",
        "support": "oak_log",
        "torch": "air",
    }


@requires_node
def test_build_from_plan_clears_replaceable_vegetation_before_placing(
    tmp_path: Path,
) -> None:
    build_action, calls_path = _stage_action_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(build_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'stone'],
    ['0,64,0', 'short_grass'],
]);
const digCalls = [];
const bot = {{
    username: 'BuildVegetationHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_planks' }}],
        items() {{ return this.slots.filter(Boolean); }},
    }},
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return block(world.get(key(cell)) || 'air', cell);
    }},
    async equip(item) {{
        this.heldItem = item;
    }},
    async dig(targetBlock) {{
        digCalls.push({{ name: targetBlock.name, position: targetBlock.position }});
        world.set(key(targetBlock.position), 'air');
    }},
    async placeBlock(referenceBlock, faceVector) {{
        const target = {{
            x: referenceBlock.position.x + faceVector.x,
            y: referenceBlock.position.y + faceVector.y,
            z: referenceBlock.position.z + faceVector.z,
        }};
        if ((world.get(key(target)) || 'air') !== 'air') {{
            throw new Error('target occupied');
        }}
        world.set(key(target), this.heldItem.name);
    }},
}};
const result = await mod.buildFromPlanAction.perform(
    {{ name: 'rex', bot }},
    'build-plan-vegetation',
    {{ x: 0, y: 64, z: 0 }},
    {{ blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }}] }},
    10,
    10000,
);
process.stdout.write(JSON.stringify({{
    result,
    placed: world.get('0,64,0'),
    digCalls,
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(calls_path)},
    )

    assert "success" in result["result"]
    assert result["placed"] == "oak_planks"
    assert result["digCalls"] == [{"name": "short_grass", "position": {"x": 0, "y": 64, "z": 0}}]


@requires_node
def test_build_from_plan_repairs_wrong_target_block_before_placing(
    tmp_path: Path,
) -> None:
    build_action, calls_path = _stage_action_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(build_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([
    ['0,63,0', 'stone'],
    ['0,64,0', 'cobblestone'],
]);
const digCalls = [];
const bot = {{
    username: 'BuildRepairHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_planks' }}],
        items() {{ return this.slots.filter(Boolean); }},
    }},
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return block(world.get(key(cell)) || 'air', cell);
    }},
    async equip(item) {{
        this.heldItem = item;
    }},
    async dig(targetBlock) {{
        digCalls.push({{ name: targetBlock.name, position: targetBlock.position }});
        world.set(key(targetBlock.position), 'air');
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
const result = await mod.buildFromPlanAction.perform(
    {{ name: 'rex', bot }},
    'build-plan-repair',
    {{ x: 0, y: 64, z: 0 }},
    {{ blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }}] }},
    10,
    10000,
);
process.stdout.write(JSON.stringify({{
    result,
    placed: world.get('0,64,0'),
    digCalls,
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {"BRIDGE_CALLS_PATH": str(calls_path)},
    )

    assert "success" in result["result"]
    assert result["placed"] == "oak_planks"
    assert result["digCalls"] == [{"name": "cobblestone", "position": {"x": 0, "y": 64, "z": 0}}]


@requires_node
def test_build_from_plan_reconciles_missing_target_after_initial_pass(
    tmp_path: Path,
) -> None:
    build_action, calls_path = _stage_action_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(build_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([['0,63,0', 'stone']]);
let placeCalls = 0;
const bot = {{
    username: 'BuildReconcileHarnessBot',
    entity: {{ position: {{ x: 0, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_planks' }}],
        items() {{ return this.slots.filter(Boolean); }},
    }},
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return block(world.get(key(cell)) || 'air', cell);
    }},
    async equip(item) {{
        this.heldItem = item;
    }},
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
    async placeBlock(referenceBlock, faceVector) {{
        placeCalls += 1;
        if (placeCalls === 1) return;
        const target = {{
            x: referenceBlock.position.x + faceVector.x,
            y: referenceBlock.position.y + faceVector.y,
            z: referenceBlock.position.z + faceVector.z,
        }};
        world.set(key(target), this.heldItem.name);
    }},
}};
const result = await mod.buildFromPlanAction.perform(
    {{ name: 'rex', bot }},
    'build-plan-reconcile',
    {{ x: 0, y: 64, z: 0 }},
    {{ blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }}] }},
    10,
    10000,
);
process.stdout.write(JSON.stringify({{
    result,
    placed: world.get('0,64,0'),
    placeCalls,
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "MINECRAFT_BUILD_FROM_PLAN_PLACE_ATTEMPTS": "1",
            "MINECRAFT_BUILD_FROM_PLAN_RECONCILE_PASSES": "1",
        },
    )

    assert "success" in result["result"]
    assert result["placed"] == "oak_planks"
    assert result["placeCalls"] == 2


@requires_node
def test_build_from_plan_reconciles_missing_far_target_after_navigation(
    tmp_path: Path,
) -> None:
    build_action, calls_path = _stage_action_with_stub_bridge(tmp_path)
    harness = f"""
import {{ pathToFileURL }} from 'node:url';

const mod = await import(pathToFileURL({json.dumps(str(build_action))}).href);
const key = (pos) => `${{Math.floor(pos.x)}},${{Math.floor(pos.y)}},${{Math.floor(pos.z)}}`;
const block = (name, pos) => ({{ name, position: {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }} }});
const world = new Map([['0,63,0', 'stone']]);
let placeCalls = 0;
let gotoCalls = 0;
const bot = {{
    username: 'BuildReconcileNavigationHarnessBot',
    entity: {{ position: {{ x: 10, y: 64, z: 0 }} }},
    inventory: {{
        slots: [{{ name: 'oak_planks' }}],
        items() {{ return this.slots.filter(Boolean); }},
    }},
    pathfinder: {{
        async goto(goal) {{
            gotoCalls += 1;
            bot.entity.position = {{ x: goal.x, y: goal.y, z: goal.z }};
        }},
    }},
    blockAt(pos) {{
        const cell = {{ x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) }};
        return block(world.get(key(cell)) || 'air', cell);
    }},
    async equip(item) {{
        this.heldItem = item;
    }},
    async dig(targetBlock) {{
        world.set(key(targetBlock.position), 'air');
    }},
    async placeBlock(referenceBlock, faceVector) {{
        placeCalls += 1;
        if (placeCalls === 1) {{
            bot.entity.position = {{ x: 10, y: 64, z: 0 }};
            return;
        }}
        const target = {{
            x: referenceBlock.position.x + faceVector.x,
            y: referenceBlock.position.y + faceVector.y,
            z: referenceBlock.position.z + faceVector.z,
        }};
        const dx = bot.entity.position.x - target.x;
        const dy = bot.entity.position.y - target.y;
        const dz = bot.entity.position.z - target.z;
        if ((dx * dx + dy * dy + dz * dz) > 9) return;
        world.set(key(target), this.heldItem.name);
    }},
}};
const result = await mod.buildFromPlanAction.perform(
    {{ name: 'rex', bot }},
    'build-plan-reconcile-nav',
    {{ x: 0, y: 64, z: 0 }},
    {{ blocks: [{{ dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' }}] }},
    10,
    10000,
);
process.stdout.write(JSON.stringify({{
    result,
    placed: world.get('0,64,0') || null,
    placeCalls,
    gotoCalls,
}}) + '\\n');
"""

    result = _run_node_harness(
        tmp_path,
        harness,
        {
            "BRIDGE_CALLS_PATH": str(calls_path),
            "MINECRAFT_BUILD_FROM_PLAN_PLACE_ATTEMPTS": "1",
            "MINECRAFT_BUILD_FROM_PLAN_RECONCILE_PASSES": "1",
        },
    )

    assert "success" in result["result"]
    assert result["placed"] == "oak_planks"
    assert result["placeCalls"] == 2
    assert result["gotoCalls"] == 2

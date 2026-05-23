"""Tests for the Minecraft action-command reliability analyzer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYZER = REPO_ROOT / "scripts" / "minecraft" / "analyze_action_reliability.py"
FAILED_SOAK_FIXTURE = REPO_ROOT / "tests" / "backend" / "fixtures" / "minecraft_soak_2026-05-21"


def _load_analyzer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("analyze_action_reliability", ANALYZER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_bot_log(run_dir: Path, agent: str, lines: list[str]) -> Path:
    bots_dir = run_dir / "bots"
    bots_dir.mkdir(parents=True, exist_ok=True)
    path = bots_dir / f"{agent}.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run_cli(run_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ANALYZER), "--run-dir", str(run_dir), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_good_run_computes_per_agent_metrics_and_verified_examples(tmp_path: Path) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "good-run"
    _write_bot_log(
        run_dir,
        "alpha",
        [
            "[CHAT] Alpha: I will place the camp marker now.",
            'assistant command: !place("camp-marker", "oak_log", {"x": 0, "y": 64, "z": 0}, "up")',
            (
                "[place trace=trace-1] place camp-marker placed: position=0,64,0; "
                "expected=oak_log; before=air; after=oak_log; placed against grass_block"
            ),
            "[CHAT] Alpha: I will move two blocks east.",
            'assistant command: !move("scout-1", "east", 2)',
            "[move trace=trace-2] move scout-1 reached: distance_to_target=0.100 blocks; delta=2.000 blocks",
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0.6,
            "min_parse_success": 0.8,
            "min_execution_rate": 0.7,
            "min_verified_success": 0.5,
            "min_intents": 1,
        },
    )

    alpha = data["agents"]["alpha"]
    assert data["acceptable"] is True
    assert alpha["counts"]["intent_utterances"] == 2
    assert alpha["counts"]["emitted_commands"] == 2
    assert alpha["counts"]["parse_successes"] == 2
    assert alpha["counts"]["command_executions"] == 2
    assert alpha["counts"]["verified_actions"] == 2
    assert alpha["metrics"]["intent_to_command_ratio"] == 1.0
    assert alpha["metrics"]["parse_success_rate"] == 1.0
    assert alpha["metrics"]["command_execution_rate"] == 1.0
    assert alpha["metrics"]["verified_success_rate"] == 1.0
    assert len(alpha["examples"]["verified_successes"]) == 2


def test_mindcraft_log_groups_executions_and_ignores_stale_generated_commands(
    tmp_path: Path,
) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "mindcraft-run"
    _write_bot_log(
        run_dir,
        "vera",
        [
            "Awaiting LM Studio response from model local/test",
            'Generated response: !move("stale", "east", 3)',
            "Vera received new message while generating, discarding old response.",
            'Vera full response to Rex: """"',
            "no response",
            "Awaiting LM Studio response from model local/test",
            'Generated response: !placeHere("oak_log")',
            'Vera full response to Rex: ""!placeHere("oak_log")""',
            "parsed command: { commandName: '!placeHere', args: [ 'oak_log' ] }",
            "executing code...",
            "Agent executed: !placeHere and got: Action output:",
            "torch in the way at (-2, 64, 0).",
            "Broke torch at x:-1.5, y:64.0, z:0.5.",
            "Placed oak_log at (-2, 64, 0).",
            "Saved memory to: ./bots/Vera/memory.json",
            "Awaiting LM Studio response from model local/test",
            'Generated response: !move("survey", "east", 2)',
            'Vera full response to Rex: ""!move("survey", "east", 2)""',
            "parsed command: { commandName: '!move', args: [ 'survey', 'east', 2 ] }",
            "executing code...",
            (
                "Agent executed: !move and got: move survey reached: "
                "distance_to_target=0.140 blocks; delta=3.014 blocks"
            ),
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0.6,
            "min_parse_success": 0.8,
            "min_execution_rate": 0.7,
            "min_verified_success": 0.5,
            "min_intents": 1,
        },
    )

    vera = data["agents"]["vera"]
    assert data["acceptable"] is True
    assert vera["counts"]["generated_commands"] == 3
    assert vera["counts"]["discarded_commands"] == 1
    assert vera["counts"]["stale_generations"] == 1
    assert vera["counts"]["emitted_commands"] == 2
    assert vera["counts"]["command_executions"] == 2
    assert vera["counts"]["execution_successes"] == 2
    assert vera["counts"]["verified_actions"] == 2
    assert vera["metrics"]["command_execution_rate"] == 1.0
    assert vera["metrics"]["verified_success_rate"] == 1.0


def test_mindcraft_failures_are_classified_from_execution_blocks(tmp_path: Path) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "mindcraft-failures"
    _write_bot_log(
        run_dir,
        "rex",
        [
            'Rex full response to Vera: ""!placeHere("cobblestone")""',
            "Agent executed: !placeHere and got: Action output:",
            "Failed to place cobblestone at (1, 65, 2).",
            "Saved memory to: ./bots/Rex/memory.json",
            'Rex full response to Vera: ""!craftable("oak planks")""',
            "Agent executed: !craftable and got: Command !craftable was given 1 args, but requires 0 args.",
            'Rex full response to Vera: ""!placeHere("oak_log")""',
            "Agent executed: !placeHere and got: undefined",
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0,
            "min_parse_success": 0,
            "min_execution_rate": 0,
            "min_verified_success": 0,
            "min_intents": 1,
        },
    )

    rex = data["agents"]["rex"]
    classes = {item["class"]: item["count"] for item in rex["execution_failure_classes"]}
    assert rex["counts"]["emitted_commands"] == 3
    assert rex["counts"]["execution_failures"] == 3
    assert classes["placement_blocked"] == 1
    assert classes["wrong_args"] == 1
    assert classes["undefined_result"] == 1


def test_failed_soak_fixture_ignores_incoming_chat_and_groups_execution_blocks(
    tmp_path: Path,
) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "failed-soak"
    fixture_log = FAILED_SOAK_FIXTURE / "bots" / "sentinel.log.txt"
    _write_bot_log(run_dir, "sentinel", fixture_log.read_text(encoding="utf-8").splitlines())

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0,
            "min_parse_success": 0,
            "min_execution_rate": 0,
            "min_verified_success": 0,
            "min_intents": 1,
        },
        top_n=20,
    )

    sentinel = data["agents"]["sentinel"]
    failed_parse_text = "\n".join(item["text"] for item in sentinel["examples"]["failed_parses"])
    classes = {item["class"]: item["count"] for item in sentinel["execution_failure_classes"]}

    assert "received message from Sentinel" not in failed_parse_text
    assert sentinel["counts"]["parse_failures"] == 0
    assert sentinel["counts"]["emitted_commands"] == 9
    assert sentinel["counts"]["command_executions"] == 9
    assert sentinel["counts"]["verified_actions"] == 1
    assert classes["wrong_args"] == 1
    assert classes["unsupported_arg_type"] == 1
    assert classes["interrupted"] == 2
    assert classes["missing_inventory"] == 1
    assert classes["placement_blocked"] == 1
    assert classes["timeout"] == 1
    assert classes["undefined_result"] == 1
    assert sentinel["command_buckets"]["placement"]["accepted"] == 4
    assert sentinel["command_buckets"]["placement"]["verified"] == 1
    assert sentinel["builder_plan_metrics"]["builder_plan_generated"] == 1
    assert sentinel["builder_plan_metrics"]["builder_plan_unique"] == 1
    assert sentinel["builder_plan_metrics"]["builder_plan_skipped_dedupe"] == 1
    assert sentinel["builder_plan_metrics"]["builder_plan_intended_blocks"] == 2
    assert sentinel["builder_plan_metrics"]["builder_plan_verified_blocks"] == 1
    assert sentinel["builder_plan_metrics"]["builder_plan_completion_rate"] == 0.5


def test_agent_executed_without_accepted_response_is_not_emitted_denominator(
    tmp_path: Path,
) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "executed-only"
    _write_bot_log(
        run_dir,
        "sentinel",
        [
            "Agent executed: !placeHere and got: Action output:",
            "Placed oak_log at (1, 64, 1).",
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0,
            "min_parse_success": 0,
            "min_execution_rate": 0,
            "min_verified_success": 0,
            "min_intents": 0,
        },
    )

    sentinel = data["agents"]["sentinel"]
    assert sentinel["counts"]["emitted_commands"] == 0
    assert sentinel["counts"]["command_executions"] == 1
    assert sentinel["counts"]["verified_actions"] == 1


def test_plan_and_raw_build_commands_are_bucketed_separately(tmp_path: Path) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "plan-buckets"
    _write_bot_log(
        run_dir,
        "aurora",
        [
            'Aurora full response to Rex: ""!planAndBuild("tiny hut")""',
            "Agent executed: !planAndBuild and got: plan-and-build plan-1: "
            "build-from-plan plan-1 success: intended=2; present=2; missing=0; "
            "verified=2; abandoned=0; completion=1.000",
            'Aurora full response to Rex: ""!buildFromPlan("raw-only")""',
            "Agent executed: !buildFromPlan and got: wrong_args: origin is required; plan is required",
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0,
            "min_parse_success": 0,
            "min_execution_rate": 0,
            "min_verified_success": 0,
            "min_intents": 1,
        },
    )

    buckets = data["agents"]["aurora"]["command_buckets"]
    assert buckets["planAndBuild"]["accepted"] == 1
    assert buckets["planAndBuild"]["success"] == 1
    assert buckets["planAndBuild"]["verified"] == 1
    assert buckets["buildFromPlan"]["accepted"] == 1
    assert buckets["buildFromPlan"]["failure"] == 1


def test_builder_provider_usage_is_reported_separately(tmp_path: Path) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "builder-provider-usage"
    _write_bot_log(run_dir, "vera", ["Vera started."])
    raw_dir = run_dir / "timeline-raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "ts": "2026-05-21T00:00:00Z",
            "event_type": "build_plan.generation.completed",
            "agent": "vera",
            "trace_id": "trace-builder-paid",
            "payload": {
                "action_id": "plan-paid",
                "provider": "openrouter",
                "builder_provider": "openrouter",
                "builder_model": "openrouter/test-frontier",
                "paid": True,
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
                "estimated_usd": 0.0123,
                "plan": {"blocks": [{"dx": 0, "dy": 0, "dz": 0, "block_type": "oak_log"}]},
            },
        },
        {
            "ts": "2026-05-21T00:00:01Z",
            "event_type": "build_plan.generation.provider_failed",
            "agent": "vera",
            "trace_id": "trace-builder-fallback",
            "payload": {
                "provider": "openrouter",
                "reason": "request_failed",
                "fallback_reason": "local",
            },
        },
        {
            "ts": "2026-05-21T00:00:02Z",
            "event_type": "build_plan.generation.completed",
            "agent": "vera",
            "trace_id": "trace-builder-local",
            "payload": {
                "action_id": "plan-local",
                "provider": "local",
                "builder_provider": "local",
                "builder_model": "local/build",
                "paid": False,
                "fallback_reason": "request_failed",
                "plan": {"blocks": [{"dx": 0, "dy": 0, "dz": 0, "block_type": "torch"}]},
            },
        },
        {
            "ts": "2026-05-21T00:00:03Z",
            "event_type": "build_plan.generation.budget_capped",
            "agent": "vera",
            "trace_id": "trace-builder-cap",
            "payload": {"provider": "openrouter", "reason": "agent_call_cap"},
        },
        {
            "ts": "2026-05-21T00:00:04Z",
            "event_type": "build_plan.generation.skipped",
            "agent": "vera",
            "trace_id": "trace-builder-active-skip",
            "payload": {
                "reason": "active_build_exists",
                "active_build": {"plan_id": "plan-local", "status": "executing"},
                "max_builder_calls_per_agent": 6,
            },
        },
        {
            "ts": "2026-05-21T00:00:05Z",
            "event_type": "build_plan.generation.skipped",
            "agent": "vera",
            "trace_id": "trace-builder-cache-hit",
            "payload": {
                "reason": "cache_hit",
                "cache_hit": True,
                "max_builder_calls_per_agent": 6,
            },
        },
        {
            "ts": "2026-05-21T00:00:06Z",
            "event_type": "build_plan.generation.skipped",
            "agent": "vera",
            "trace_id": "trace-builder-cooldown",
            "payload": {
                "reason": "cooldown",
                "cache_hit": True,
                "cooldown_remaining_sec": 241,
                "max_builder_calls_per_agent": 6,
            },
        },
        {
            "ts": "2026-05-21T00:00:07Z",
            "event_type": "build_plan.generation.skipped",
            "agent": "vera",
            "trace_id": "trace-builder-agent-cap",
            "payload": {
                "reason": "per_agent_cap",
                "max_builder_calls_per_agent": 6,
            },
        },
    ]
    (raw_dir / "vera.ndjson").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0,
            "min_parse_success": 0,
            "min_execution_rate": 0,
            "min_verified_success": 0,
            "min_intents": 0,
        },
    )

    metrics = data["agents"]["vera"]["builder_plan_metrics"]
    assert metrics["builder_plan_generated"] == 2
    assert metrics["builder_plan_paid_calls"] == 1
    assert metrics["builder_plan_local_calls"] == 1
    assert metrics["builder_plan_estimated_usd"] == 0.0123
    assert metrics["builder_plan_prompt_tokens"] == 100
    assert metrics["builder_plan_completion_tokens"] == 40
    assert metrics["builder_plan_total_tokens"] == 140
    assert metrics["builder_plan_failures"] == 2
    assert metrics["builder_plan_fallbacks"] == 2
    assert metrics["builder_provider_breakdown"] == {"local": 1, "openrouter": 1}
    assert metrics["builder_plan_skipped_active"] == 1
    assert metrics["builder_plan_skipped_cooldown"] == 1
    assert metrics["builder_plan_skipped_per_agent_cap"] == 1
    assert metrics["builder_plan_cache_hits"] == 2
    assert metrics["builder_plan_max_per_agent"] == 6


def test_director_v2_counts_are_reported_without_changing_reliability_metrics(
    tmp_path: Path,
) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "director-v2"
    _write_bot_log(run_dir, "vera", ["Vera started."])
    _write_bot_log(run_dir, "rex", ["Rex started."])
    raw_dir = run_dir / "timeline-raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "ts": "2026-05-21T00:00:00Z",
            "event_type": "director.gate.decision",
            "agent": "vera",
            "payload": {
                "agent_id": "vera",
                "scene_id": "scene-1",
                "selected": True,
                "reason": "direct_address",
            },
        },
        {
            "ts": "2026-05-21T00:00:01Z",
            "event_type": "director.gate.decision",
            "agent": "rex",
            "payload": {
                "agent_id": "rex",
                "scene_id": "scene-1",
                "selected": False,
                "suppression_reason": "fanout_capped",
            },
        },
        {
            "ts": "2026-05-21T00:00:02Z",
            "event_type": "director.memory.compaction",
            "agent": "vera",
            "payload": {
                "scene_id": "scene-1",
                "distributed_to": ["vera", "rex"],
                "ok": True,
            },
        },
        {
            "ts": "2026-05-21T00:00:03Z",
            "event_type": "director.tool.call",
            "agent": "rex",
            "payload": {
                "agent_id": "rex",
                "scene_id": "scene-1",
                "tool_name": "fetch_url",
                "ok": False,
                "status": "error",
            },
        },
    ]
    (raw_dir / "director_v2.ndjson").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0,
            "min_parse_success": 0,
            "min_execution_rate": 0,
            "min_verified_success": 0,
            "min_intents": 0,
        },
    )

    assert data["agents"]["vera"]["metrics"]["intent_to_command_ratio"] == 1.0
    assert data["agents"]["vera"]["director_metrics"]["selected_turns"] == 1
    assert data["agents"]["vera"]["director_metrics"]["memory_compactions_participated"] == 1
    assert data["agents"]["rex"]["director_metrics"]["suppressed_turns"] == 1
    assert data["agents"]["rex"]["director_metrics"]["suppression_reasons"] == {"fanout_capped": 1}
    assert data["agents"]["rex"]["director_metrics"]["tool_calls"] == 1
    assert data["agents"]["rex"]["director_metrics"]["tool_failures"] == 1
    assert data["aggregate"]["director_metrics"]["memory_compactions_participated"] == 2


def test_collect_blocks_success_counts_as_verified_execution(tmp_path: Path) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "collect-run"
    _write_bot_log(
        run_dir,
        "sentinel",
        [
            "Awaiting LM Studio response from model local/test",
            'Generated response: !collectBlocks("cobblestone", 10)',
            'Sentinel full response to Pixel: ""!collectBlocks("cobblestone", 10)""',
            "parsed command: { commandName: '!collectBlocks', args: [ 'cobblestone', 10 ] }",
            "executing code...",
            "Agent executed: !collectBlocks and got: Action output:",
            "Collected 10 cobblestone.",
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0,
            "min_parse_success": 0,
            "min_execution_rate": 0,
            "min_verified_success": 0,
            "min_intents": 1,
        },
    )

    sentinel = data["agents"]["sentinel"]
    assert sentinel["counts"]["emitted_commands"] == 1
    assert sentinel["counts"]["command_executions"] == 1
    assert sentinel["counts"]["execution_successes"] == 1
    assert sentinel["counts"]["verified_actions"] == 1
    assert sentinel["metrics"]["verified_success_rate"] == 1.0


def test_support_information_commands_do_not_lower_verified_success_rate(
    tmp_path: Path,
) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "support-information"
    _write_bot_log(
        run_dir,
        "alpha",
        [
            "Generated response: !inventory",
            'Alpha full response to system: ""!inventory""',
            "parsed command: { commandName: '!inventory', args: [] }",
            "Agent executed: !inventory and got: INVENTORY { oak_log: 64, cobblestone: 32 }",
            "Saved memory to: ./bots/Alpha/memory.json",
            "Generated response: !nearbyBlocks",
            'Alpha full response to system: ""!nearbyBlocks""',
            "parsed command: { commandName: '!nearbyBlocks', args: [] }",
            "Agent executed: !nearbyBlocks and got: NEARBY_BLOCKS oak_log,cobblestone,torch",
            "Saved memory to: ./bots/Alpha/memory.json",
            'Generated response: !searchForBlock("cobblestone", 16)',
            'Alpha full response to system: ""!searchForBlock("cobblestone", 16)""',
            "parsed command: { commandName: '!searchForBlock', args: [ 'cobblestone', 16 ] }",
            "Agent executed: !searchForBlock and got: Action output:",
            "Minimum search range is 32.",
            "Found cobblestone at (-6, 64, -6). Navigating...",
            "Found non-destructive path.",
            "You have reached at -6, 64, -6.",
            "Saved memory to: ./bots/Alpha/memory.json",
            'Generated response: !placeHere("torch")',
            'Alpha full response to system: ""!placeHere("torch")""',
            "parsed command: { commandName: '!placeHere', args: [ 'torch' ] }",
            "Agent executed: !placeHere and got: Action output: Placed torch at (0, 64, 0).",
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0.6,
            "min_parse_success": 0.8,
            "min_execution_rate": 0.7,
            "min_verified_success": 0.5,
            "min_intents": 1,
        },
    )

    alpha = data["agents"]["alpha"]
    assert data["acceptable"] is True
    assert alpha["counts"]["execution_successes"] == 4
    assert alpha["counts"]["verified_actions"] == 2
    assert alpha["counts"]["support_information_successes"] == 3
    assert alpha["counts"]["support_information_verified_actions"] == 1
    assert alpha["metrics"]["verified_success_rate"] == 1.0


def test_same_command_name_with_different_args_counts_distinct_accepts(tmp_path: Path) -> None:
    analyzer = _load_analyzer()
    run_dir = tmp_path / "multi-command"
    _write_bot_log(
        run_dir,
        "pixel",
        [
            'Pixel full response to Vera: ""!placeHere("oak_log") !placeHere("cobblestone")""',
            "Agent executed: !placeHere and got: Action output: Placed oak_log at (1, 64, 1).",
            "Agent executed: !placeHere and got: Action output: Placed cobblestone at (2, 64, 1).",
        ],
    )

    data = analyzer.analyze_run(
        run_dir,
        thresholds={
            "min_intent_to_command": 0,
            "min_parse_success": 0,
            "min_execution_rate": 0,
            "min_verified_success": 0,
            "min_intents": 1,
        },
    )

    pixel = data["agents"]["pixel"]
    assert pixel["counts"]["emitted_commands"] == 2
    assert pixel["counts"]["command_executions"] == 2
    assert pixel["counts"]["verified_actions"] == 2


def test_cli_writes_artifacts_and_fails_on_parser_failure_thresholds(tmp_path: Path) -> None:
    run_dir = tmp_path / "parse-failure-run"
    _write_bot_log(
        run_dir,
        "vera",
        [
            "[CHAT] Vera: I will place a visible block.",
            "empty parsed response from local model",
            "No commands found in response",
            "[CHAT] Vera: I will try a custom command.",
            "Command dance does not exist",
            'Could not parse command: !placeHere("oak_log"',
            "Error parsing command arguments: expected 2 arguments got 1",
        ],
    )

    proc = _run_cli(run_dir, "--min-intents", "1", "--top-n", "5")

    assert proc.returncode == 1
    data = json.loads((run_dir / "action-reliability.json").read_text(encoding="utf-8"))
    markdown = (run_dir / "action-reliability.md").read_text(encoding="utf-8")
    assert data["acceptable"] is False
    assert data["agents"]["vera"]["counts"]["parse_failures"] == 5
    assert data["agents"]["vera"]["metrics"]["parse_success_rate"] == 0.0
    assert {item["class"] for item in data["aggregate"]["parser_failure_classes"]} >= {
        "empty_response",
        "no_commands_found",
        "unknown_command",
        "parse_error",
        "argument_error",
    }
    assert any(item["metric"] == "parse_success_rate" for item in data["threshold_violations"])
    assert "Failed Parse Examples" in markdown
    assert "Verified Success Examples" in markdown
    assert "NOT ACCEPTABLE" in markdown


def test_intent_without_command_fails_the_intent_to_command_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "intent-without-command-run"
    _write_bot_log(
        run_dir,
        "rex",
        [
            "[CHAT] Rex: I will build the first wall.",
            "[CHAT] Rex: I will place oak logs by spawn.",
            "[CHAT] Rex: I am going to move east.",
            "[CHAT] Rex: I will craft a tool.",
            "[CHAT] Rex: I will search for stone.",
        ],
    )

    proc = _run_cli(run_dir, "--min-intents", "5")

    assert proc.returncode == 1
    data = json.loads((run_dir / "action-reliability.json").read_text(encoding="utf-8"))
    rex = data["agents"]["rex"]
    assert rex["counts"]["intent_utterances"] == 5
    assert rex["counts"]["emitted_commands"] == 0
    assert rex["metrics"]["intent_to_command_ratio"] == 0.0
    assert rex["metrics"]["command_execution_rate"] == 0.0
    assert any(item["metric"] == "intent_to_command_ratio" for item in data["threshold_violations"])


def test_empty_llm_response_is_classified_as_parser_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty-response-run"
    _write_bot_log(
        run_dir,
        "pixel",
        [
            "[CHAT] Pixel: I will place a torch.",
            "blank LLM response",
            "No commands found",
        ],
    )

    proc = _run_cli(run_dir, "--min-intents", "1", "--top-n", "5")

    assert proc.returncode == 1
    data = json.loads((run_dir / "action-reliability.json").read_text(encoding="utf-8"))
    pixel_failures = data["agents"]["pixel"]["parser_failure_classes"]
    assert pixel_failures == [
        {"class": "empty_response", "count": 1},
        {"class": "no_commands_found", "count": 1},
    ]


def test_cli_threshold_flags_override_defaults(tmp_path: Path) -> None:
    run_dir = tmp_path / "threshold-override-run"
    _write_bot_log(
        run_dir,
        "fork",
        [
            "[CHAT] Fork: I will place a block.",
            "empty parsed response",
            "No commands found",
        ],
    )

    proc = _run_cli(
        run_dir,
        "--min-intents",
        "1",
        "--min-intent-to-command",
        "0",
        "--min-parse-success",
        "0",
        "--min-execution-rate",
        "0",
        "--min-verified-success",
        "0",
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads((run_dir / "action-reliability.json").read_text(encoding="utf-8"))
    assert data["acceptable"] is True
    assert data["thresholds"]["min_parse_success"] == 0.0
    assert data["threshold_violations"] == []

"""Static tests for the Director V2 acceptance soak contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts" / "minecraft"
SOAK = SCRIPT_DIR / "soak.sh"
RUN_LOCAL_SIM = SCRIPT_DIR / "run-local-sim.sh"
REPORT_BUILDER = SCRIPT_DIR / "build_director_acceptance_report.py"
DOC = REPO_ROOT / "docs" / "minecraft" / "director-v2-acceptance-soak.md"
MULTI_AGENT_DOC = REPO_ROOT / "docs" / "minecraft" / "multi-agent-soak.md"
PACKAGE = REPO_ROOT / "package.json"

_MINECRAFT_ENV_KEYS = {
    "CONVERSATION_MODE",
    "DIRECTOR_V2_GATE",
    "EMBEDDING_PROVIDER",
    "ENV_FILE",
    "LLM_PROVIDER",
    "MC_HOST",
    "MC_PORT",
    "SERVER_DIR",
    "SERVER_PORT",
    "SOAK_PROFILE",
    "WHITELIST",
    "WORLD_CONFIG",
}
_MINECRAFT_ENV_PREFIXES = ("LOCAL_LLM", "MC_HEARTBEAT", "MC_SIM", "MINECRAFT_", "SOAK_")


def _clean_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _MINECRAFT_ENV_KEYS and not key.startswith(_MINECRAFT_ENV_PREFIXES)
    }
    if overrides:
        env.update(overrides)
    return env


def _run_soak(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SOAK), *args],
        cwd=REPO_ROOT,
        env=_clean_env(env),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_soak_help_documents_director_acceptance_profile() -> None:
    proc = _run_soak("--help")

    assert proc.returncode == 0
    for needle in (
        "--profile director_v2",
        "SOAK_PROFILE",
        "SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD",
        "SOAK_ACCEPTANCE_WARMUP_SECONDS",
        "SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO",
        "SOAK_REQUIRE_DIRECTOR_ACCEPTANCE",
        "director-decisions.ndjson",
        "tool-parity.ndjson",
        "macro-evidence.ndjson",
        "memory-digest.ndjson",
        "acceptance-report.json",
        "acceptance-report.md",
    ):
        assert needle in proc.stdout

    wrapper = subprocess.run(
        ["bash", str(RUN_LOCAL_SIM), "--help"],
        cwd=REPO_ROOT,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert wrapper.returncode == 0
    assert "smoke-director" in wrapper.stdout
    assert "soak-director" in wrapper.stdout
    assert "optional OpenRouter-builder mode" in wrapper.stdout


def test_director_profile_dry_run_forces_gate_and_acceptance_contract() -> None:
    proc = _run_soak("--profile", "director_v2", "--dry-run")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "profile:        director_v2" in proc.stdout
    assert "conversation:   mode=director_v2 director_gate=1" in proc.stdout
    assert "LM queue:       enabled" in proc.stdout
    assert "acceptance:     queue<16 after 300s; selected_ratio<=0.5; require=1" in proc.stdout
    assert (
        "evidence:       director-decisions.ndjson tool-parity.ndjson macro-evidence.ndjson "
        "memory-digest.ndjson acceptance-report.json"
    ) in proc.stdout
    assert "no services checked, no bots launched" in proc.stdout


def test_local_sim_director_modes_delegate_to_director_profile(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_BASE_URL=http://localhost:1234/v1",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "EMBEDDING_PROVIDER=deterministic",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
            ]
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["bash", str(RUN_LOCAL_SIM), "smoke-director", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "mode: smoke-director" in proc.stdout
    assert "duration: 0.25h" in proc.stdout
    assert "conversation mode: director_v2" in proc.stdout
    assert "Director V2 gate: 1" in proc.stdout
    assert "soak profile: director_v2" in proc.stdout
    assert "profile:        director_v2" in proc.stdout


def test_package_json_exposes_director_acceptance_aliases() -> None:
    scripts = json.loads(PACKAGE.read_text(encoding="utf-8"))["scripts"]

    assert scripts["mc:sim:smoke"] == "scripts/minecraft/run-local-sim.sh smoke"
    assert scripts["mc:sim:soak"] == "scripts/minecraft/run-local-sim.sh soak"
    assert scripts["mc:sim:smoke:director"] == ("scripts/minecraft/run-local-sim.sh smoke-director")
    assert scripts["mc:sim:soak:director"] == ("scripts/minecraft/run-local-sim.sh soak-director")
    assert scripts["verify:director-acceptance-soak"] == (
        ".venv/bin/pytest tests/backend/test_minecraft_director_acceptance_soak.py -v"
    )


def test_acceptance_doc_has_required_sections_and_downstream_mapping() -> None:
    text = DOC.read_text(encoding="utf-8")

    for heading in (
        "## Smoke Profile",
        "## Soak Profile",
        "## Local Single-Model Mode",
        "## Optional OpenRouter Builder Mode",
        "## Evidence: Monitor",
        "## Evidence: Timeline",
        "## Evidence: Action Reliability",
        "## Evidence: Director Decisions",
        "## Evidence: Tool Parity",
        "## Evidence: Builder Macro",
        "## Evidence: Memory Digest",
        "## Evidence: Acceptance Report",
        "## Acceptance Criteria Mapping",
        "## Residual Gaps",
    ):
        assert heading in text
    for artifact in (
        "director-decisions.ndjson",
        "tool-parity.ndjson",
        "macro-evidence.ndjson",
        "memory-digest.ndjson",
        "acceptance-report.json",
        "acceptance-report.md",
        "monitor.html",
        "timeline.ndjson",
        "action-reliability.json",
    ):
        assert artifact in text
    for schema_key in (
        "schema_version",
        "overall_status",
        "thresholds",
        "evidence_files",
        "metrics",
        "criteria",
        "residual_gaps",
        "downstream_epics",
    ):
        assert f"`{schema_key}`" in text
    for issue in ("#511", "#512", "#514"):
        assert issue in text

    multi_agent = MULTI_AGENT_DOC.read_text(encoding="utf-8")
    assert "## Director V2 Acceptance Soak" in multi_agent
    assert "director-v2-acceptance-soak.md" in multi_agent


def test_acceptance_report_builder_writes_evidence_and_schema(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    raw_dir = run_dir / "timeline-raw"
    raw_dir.mkdir(parents=True)
    (run_dir / "metadata.env").write_text(
        "start_utc=2026-05-21T00:00:00Z\ncost_agents=alpha vera rex aurora pixel fork sentinel grok\n",
        encoding="utf-8",
    )
    (run_dir / "behavior-totals.env").write_text(
        "behavior_gate_status=pass\ntotal_restart_recurrences=0\n",
        encoding="utf-8",
    )
    (run_dir / "early-exits.tsv").write_text("", encoding="utf-8")
    (run_dir / "heartbeat-halts.tsv").write_text("", encoding="utf-8")
    events = [
        {
            "ts": "2026-05-21T00:05:10Z",
            "event_type": "llm.queue.enqueued",
            "trace_id": "queue-1",
            "payload": {"queued": 2, "running": 1, "model": "local/test"},
        },
        {
            "ts": "2026-05-21T00:05:11Z",
            "event_type": "director.scene.opened",
            "agent": "alpha",
            "trace_id": "scene-1",
            "payload": {"scene_id": "scene-1", "participants": ["alpha", "vera"]},
        },
        {
            "ts": "2026-05-21T00:05:12Z",
            "event_type": "director.gate.decision",
            "agent": "alpha",
            "trace_id": "scene-1",
            "payload": {
                "scene_id": "scene-1",
                "selected": True,
                "turn_kind": "speaker",
                "reason_code": "direct_address",
                "queue_depth": 1,
                "llm_prompt_count": 1,
                "available_tools": ["recall_memory"],
            },
        },
        {
            "ts": "2026-05-21T00:05:13Z",
            "event_type": "director.gate.decision",
            "agent": "vera",
            "trace_id": "scene-1",
            "payload": {
                "scene_id": "scene-1",
                "selected": True,
                "turn_kind": "speaker",
                "reason_code": "followup",
                "queue_depth": 1,
                "llm_prompt_count": 1,
                "available_tools": [],
            },
        },
        {
            "ts": "2026-05-21T00:05:14Z",
            "event_type": "director.gate.decision",
            "agent": "rex",
            "trace_id": "scene-1",
            "payload": {
                "scene_id": "scene-1",
                "selected": False,
                "suppression_reason": "fanout_capped",
                "queue_depth": 1,
                "avoided_prompt_count": 1,
            },
        },
        {
            "ts": "2026-05-21T00:05:15Z",
            "event_type": "director.tool.call",
            "agent": "alpha",
            "payload": {
                "scene_id": "scene-1",
                "tool_name": "recall_memory",
                "classification": "callable_now",
                "ok": True,
                "latency_ms": 12,
            },
        },
        {
            "ts": "2026-05-21T00:05:16Z",
            "event_type": "director.scene.digest",
            "agent": "alpha",
            "payload": {
                "scene_id": "scene-1",
                "participants": ["alpha", "vera"],
                "distributed_to": ["alpha", "vera"],
                "entries_count": 4,
                "tokens": 38,
                "summary": "Alpha and Vera agreed to build a torch-lit marker.",
            },
        },
        {
            "ts": "2026-05-21T00:05:17Z",
            "event_type": "build_plan.generation.completed",
            "agent": "alpha",
            "payload": {
                "scene_id": "scene-1",
                "owner": "alpha",
                "plan_id": "plan-1",
                "provider": "local",
                "status": "completed",
                "plan": {"blocks": [{"dx": 0, "dy": 0, "dz": 0, "block_type": "torch"}]},
            },
        },
    ]
    (run_dir / "timeline.ndjson").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(REPORT_BUILDER), "--run-dir", str(run_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((run_dir / "acceptance-report.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["profile"] == "director_v2"
    assert report["overall_status"] == "pass"
    assert report["metrics"]["queue_depth_after_warmup_max"] == 2
    assert report["metrics"]["multi_turn_collaboration_scene_ids"] == ["scene-1"]
    assert report["metrics"]["useful_memory_digest_count"] == 1
    assert report["metrics"]["tool_call_count"] == 1
    assert report["metrics"]["macro_attempt_count"] == 1
    assert (
        "None. Evidence is sufficient to unblock #511, #512, and #514." in report["residual_gaps"]
    )
    for artifact in (
        "director-decisions.ndjson",
        "tool-parity.ndjson",
        "macro-evidence.ndjson",
        "memory-digest.ndjson",
        "acceptance-report.md",
    ):
        assert (run_dir / artifact).is_file()


def test_acceptance_report_counts_distinct_selected_agents_for_storm_ratio(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.env").write_text(
        "start_utc=2026-05-21T00:00:00Z\ncost_agents=alpha vera rex aurora pixel fork sentinel grok\n",
        encoding="utf-8",
    )
    (run_dir / "behavior-totals.env").write_text(
        "behavior_gate_status=pass\ntotal_restart_recurrences=0\n",
        encoding="utf-8",
    )
    (run_dir / "early-exits.tsv").write_text("", encoding="utf-8")
    (run_dir / "heartbeat-halts.tsv").write_text("", encoding="utf-8")
    events = [
        {
            "ts": "2026-05-21T00:05:10Z",
            "event_type": "llm.queue.enqueued",
            "payload": {"queue_depth": 1},
        },
        *[
            {
                "ts": f"2026-05-21T00:05:{11 + index:02d}Z",
                "event_type": "director.gate.decision",
                "agent": "alpha",
                "payload": {
                    "scene_id": "scene-1",
                    "selected": True,
                    "reason_code": "followup",
                    "available_tools": [],
                },
            }
            for index in range(5)
        ],
        {
            "ts": "2026-05-21T00:05:20Z",
            "event_type": "director.scene.digest",
            "agent": "alpha",
            "payload": {
                "scene_id": "scene-1",
                "distributed_to": ["alpha"],
                "entries_count": 5,
                "summary": "Alpha continued the same scene without fanout.",
            },
        },
        {
            "ts": "2026-05-21T00:05:21Z",
            "event_type": "build_plan.generation.completed",
            "agent": "alpha",
            "payload": {"scene_id": "scene-1", "plan_id": "plan-1", "provider": "local"},
        },
    ]
    (run_dir / "timeline.ndjson").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(REPORT_BUILDER),
            "--run-dir",
            str(run_dir),
            "--max-selected-agent-ratio",
            "0.5",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((run_dir / "acceptance-report.json").read_text(encoding="utf-8"))
    assert report["overall_status"] == "pass"
    assert report["metrics"]["max_selected_agent_scene_ratio"] == 0.125

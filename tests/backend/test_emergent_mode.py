"""Emergent-mode acceptance gate, classifier task-path, and stall-fix coverage (#909).

This is the QA capstone for the emergent pivot (E21-7e). It proves:

* the settlement smoke classifier reads a task-board-organized run as
  ``collaborative`` via the new task-lifecycle path, even with zero
  world-changing tools and no objective/role chat regex match;
* ``emergent_acceptance.evaluate_emergent_acceptance`` passes on a healthy
  emergent fixture (timeline + decision log);
* the settlement regression harness still classifies/accepts unchanged;
* the three stall fixes hold (#903 model precedence, #904 first-claim-wins,
  #905 no emergent seed);
* the operator contract (30-min smoke command, emergent default, zero seed) is
  documented and wired.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_MINECRAFT = REPO_ROOT / "scripts" / "minecraft"
if str(SCRIPTS_MINECRAFT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_MINECRAFT))

import emergent_acceptance  # noqa: E402

from core.eval.settlement_smoke_signals import (  # noqa: E402
    classify_sim_folder,
    collect_task_events,
)
from core.redis_keys import ScopedRedis  # noqa: E402
from core.shared_state import SharedWorkingState  # noqa: E402
from core.simulation.decision_logger import DecisionLogger  # noqa: E402
from tools.task_management import ManageTaskTool  # noqa: E402

RUN_LOCAL_SIM = SCRIPTS_MINECRAFT / "run-local-sim.sh"
SOAK = SCRIPTS_MINECRAFT / "soak.sh"
EMERGENT_DOC = REPO_ROOT / "docs" / "minecraft" / "emergent-mode.md"
ACCEPTANCE_DOC = REPO_ROOT / "docs" / "minecraft" / "director-v2-acceptance-soak.md"


# ─── Decision-log fixture helper ───────────────────────────────────────────


def _build_decision_log(sim_folder: Path, events: list[tuple[str, dict]]) -> Path:
    """Drive the real DecisionLogger to write a fixture decision_log.jsonl."""
    sim_folder.mkdir(parents=True, exist_ok=True)
    logger = DecisionLogger(sim_folder)
    try:
        for kind, payload in events:
            getattr(logger, f"log_{kind}")(**payload)
    finally:
        logger.close()
    return sim_folder


def _pure_task_lifecycle_events() -> list[tuple[str, dict]]:
    """Two creators, two claimers, one completion — and NO world-changing build.

    With chat that matches no objective/role regex, this can only classify as
    ``collaborative`` through the new task-lifecycle branch (#909); without it,
    the chat heuristics would file it as ``partial``.
    """
    return [
        ("utterance", {"actor_id": "vera", "text": "Morning, team."}),
        (
            "tool_intent",
            {
                "actor_id": "vera",
                "tool_name": "manage_task",
                "args": {"action": "create_task", "title": "Storage hall"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "rex",
                "tool_name": "manage_task",
                "args": {"action": "create_task", "title": "Watch post"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "aurora",
                "tool_name": "manage_task",
                "args": {"action": "claim_task", "task_id": "task-1"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "pixel",
                "tool_name": "manage_task",
                "args": {"action": "claim_task", "task_id": "task-2"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "aurora",
                "tool_name": "manage_task",
                "args": {"action": "update_status", "task_id": "task-1", "status": "done"},
                "status": "executed",
            },
        ),
    ]


def _emergent_run_decision_log_events() -> list[tuple[str, dict]]:
    """A full healthy emergent run: 3 creators, 2 claimers, claim_then_build,
    completion, a civilization tool, and world-changes from 2 distinct agents."""
    return [
        ("utterance", {"actor_id": "vera", "text": "Good morning."}),
        (
            "tool_intent",
            {
                "actor_id": "vera",
                "tool_name": "manage_task",
                "args": {"action": "create_task", "title": "Storage hall"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "rex",
                "tool_name": "manage_task",
                "args": {"action": "create_task", "title": "Perimeter"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "pixel",
                "tool_name": "manage_task",
                "args": {"action": "create_task", "title": "Garden"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "aurora",
                "tool_name": "manage_task",
                "args": {"action": "claim_task", "task_id": "task-1"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "aurora",
                "tool_name": "buildFromPlan",
                "args": {"name": "storage_hall"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "fork",
                "tool_name": "manage_task",
                "args": {"action": "claim_task", "task_id": "task-2"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "fork",
                "tool_name": "placeHere",
                "args": {"block": "oak_log"},
                "status": "executed",
            },
        ),
        (
            "tool_intent",
            {
                "actor_id": "aurora",
                "tool_name": "manage_task",
                "args": {"action": "update_status", "task_id": "task-1", "status": "done"},
                "status": "executed",
            },
        ),
        (
            "ownership_delta",
            {
                "claim_id": "claim-1",
                "owner_agent_id": "aurora",
                "target_type": "structure",
                "target_ref": {"name": "storage_hall"},
                "action": "claim",
                "motivation": "I built this hall",
            },
        ),
    ]


def _settlement_collaborative_events() -> list[tuple[str, dict]]:
    """The existing #821 settlement smoke shape — collaborative via chat heuristics."""
    return [
        ("utterance", {"actor_id": "alpha", "text": "Let's build a starter farm together."}),
        ("utterance", {"actor_id": "rex", "text": "I'll build the perimeter wall."}),
        ("utterance", {"actor_id": "vera", "text": "I'll gather logs for Rex."}),
        (
            "tool_intent",
            {
                "actor_id": "rex",
                "tool_name": "buildFromPlan",
                "args": {"name": "wall"},
                "status": "executed",
            },
        ),
        ("utterance", {"actor_id": "fork", "text": "Looks off — let's fix the corner."}),
    ]


# ─── Timeline fixture helpers (run_dir for build_report) ───────────────────


def _write_timeline(run_dir: Path, events: list[dict[str, Any]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "timeline.ndjson").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )


def _emergent_timeline_events() -> list[dict[str, Any]]:
    """Two distinct selected turns in one scene (multi-turn), no settlement objective."""
    return [
        {
            "ts": "2026-05-28T00:05:11Z",
            "event_type": "director.gate.decision",
            "agent": "alpha",
            "payload": {"scene_id": "scene-1", "selected": True, "reason_code": "direct_address"},
        },
        {
            "ts": "2026-05-28T00:05:12Z",
            "event_type": "director.gate.decision",
            "agent": "vera",
            "payload": {"scene_id": "scene-1", "selected": True, "reason_code": "followup"},
        },
    ]


def _settlement_timeline_events() -> list[dict[str, Any]]:
    """A phase-ordered settlement objective macro with a structured result."""
    return [
        {
            "ts": "2026-05-28T00:05:11Z",
            "event_type": "director.gate.decision",
            "agent": "alpha",
            "payload": {"scene_id": "scene-1", "selected": True, "reason_code": "direct_address"},
        },
        {
            "ts": "2026-05-28T00:05:12Z",
            "event_type": "director.gate.decision",
            "agent": "vera",
            "payload": {"scene_id": "scene-1", "selected": True, "reason_code": "followup"},
        },
        {
            "ts": "2026-05-28T00:05:17Z",
            "event_type": "build_plan.generation.completed",
            "agent": "alpha",
            "payload": {
                "scene_id": "scene-1",
                "owner": "alpha",
                "objective_id": "phase-cabin",
                "phase_index": 0,
                "phase_owner": "alpha",
                "plan_id": "plan-1",
                "provider": "local",
                "status": "completed",
                "metric": {"intended_count": 1, "steps_verified": 1, "completion_ratio": 1.0},
            },
        },
    ]


# ─── 1. Classifier task-lifecycle path ─────────────────────────────────────


def test_collect_task_events_summary(tmp_path: Path) -> None:
    folder = _build_decision_log(tmp_path / "sim", _emergent_run_decision_log_events())
    from core.simulation.decision_logger import DecisionLogReader

    summary = collect_task_events(DecisionLogReader(folder).replay())
    assert summary.distinct_task_creators == 3
    assert summary.created_task_count == 3
    assert summary.distinct_task_claimers == 2
    assert summary.claimed_task_count == 2
    assert summary.completed_task_count == 1
    assert summary.claim_then_build >= 1
    assert set(summary.creator_ids) == {"vera", "rex", "pixel"}
    assert set(summary.claimer_ids) == {"aurora", "fork"}


def test_classify_task_lifecycle_collaborative_without_build(tmp_path: Path) -> None:
    """Pure task-board collaboration with no build is collaborative via the new path."""
    folder = _build_decision_log(tmp_path / "sim", _pure_task_lifecycle_events())
    outcome = classify_sim_folder(folder)

    assert outcome.classification == "collaborative"
    assert outcome.failure_class is None
    # The genuinely-new branch: zero world-changing actions, upgraded from partial.
    assert outcome.world_changing_action_count == 0
    assert outcome.sub_counts["distinct_task_creators"] == 2
    assert outcome.sub_counts["distinct_task_claimers"] == 2
    assert outcome.sub_counts["completed_task_count"] == 1
    assert outcome.sub_counts["claim_then_build"] == 0


def test_classify_emergent_full_run_collaborative(tmp_path: Path) -> None:
    folder = _build_decision_log(tmp_path / "sim", _emergent_run_decision_log_events())
    outcome = classify_sim_folder(folder)

    assert outcome.classification == "collaborative"
    assert outcome.sub_counts["distinct_task_creators"] == 3
    assert outcome.sub_counts["claim_then_build"] >= 1
    assert outcome.sub_counts["distinct_world_changing_actors"] == 2
    assert outcome.sub_counts["ownership_events"] == 1


# ─── 2. Emergent acceptance gate ───────────────────────────────────────────


def test_evaluate_emergent_acceptance_passes(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _build_decision_log(run_dir, _emergent_run_decision_log_events())
    _write_timeline(run_dir, _emergent_timeline_events())

    result = emergent_acceptance.evaluate_emergent_acceptance(run_dir, run_dir)

    failed = [c.criterion_id for c in result.criteria if c.status != "pass"]
    assert result.passed, failed
    assert result.classification == "collaborative"
    statuses = {c.criterion_id: c.status for c in result.criteria}
    assert statuses["emergent_empty_task_board_at_start"] == "pass"
    assert statuses["emergent_distinct_task_creators"] == "pass"
    assert statuses["emergent_tasks_claimed_by_distinct_agents"] == "pass"
    assert statuses["emergent_task_completed_with_evidence"] == "pass"
    assert statuses["emergent_build_fired_from_claim"] == "pass"
    assert statuses["emergent_civilization_tool_fired"] == "pass"
    assert statuses["emergent_no_phase_rotation_stall"] == "pass"
    assert statuses["multi_turn_collaboration_scene"] == "pass"
    assert statuses["emergent_distinct_world_change_proxy"] == "pass"
    assert statuses["emergent_collaborative_classification"] == "pass"


def test_evaluate_emergent_acceptance_fails_on_seeded_objectives(tmp_path: Path) -> None:
    """A settlement objective leaking into an emergent run trips the empty-board gate."""
    run_dir = tmp_path / "run"
    _build_decision_log(run_dir, _emergent_run_decision_log_events())
    _write_timeline(run_dir, _settlement_timeline_events())  # carries objective_id

    result = emergent_acceptance.evaluate_emergent_acceptance(run_dir, run_dir)

    statuses = {c.criterion_id: c.status for c in result.criteria}
    assert statuses["emergent_empty_task_board_at_start"] == "fail"
    assert statuses["emergent_no_phase_rotation_stall"] == "fail"
    assert not result.passed


def test_evaluate_emergent_acceptance_fails_when_no_collaboration(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _build_decision_log(
        run_dir,
        [("utterance", {"actor_id": "alpha", "text": "Hello."})],
    )
    _write_timeline(run_dir, _emergent_timeline_events())

    result = emergent_acceptance.evaluate_emergent_acceptance(run_dir, run_dir)

    assert not result.passed
    statuses = {c.criterion_id: c.status for c in result.criteria}
    assert statuses["emergent_distinct_task_creators"] == "fail"
    assert statuses["emergent_collaborative_classification"] == "fail"


def test_emergent_acceptance_writes_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _build_decision_log(run_dir, _emergent_run_decision_log_events())
    _write_timeline(run_dir, _emergent_timeline_events())

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_MINECRAFT / "build_director_acceptance_report.py"),
            "--mode",
            "emergent",
            "--run-dir",
            str(run_dir),
            "--sim-folder",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((run_dir / "emergent-acceptance.json").read_text(encoding="utf-8"))
    assert report["profile"] == "emergent"
    assert report["overall_status"] == "pass"
    assert (run_dir / "emergent-acceptance.md").is_file()


# ─── 3. Settlement regression (must stay green) ────────────────────────────


def test_settlement_fixture_still_collaborative(tmp_path: Path) -> None:
    folder = _build_decision_log(tmp_path / "sim", _settlement_collaborative_events())
    outcome = classify_sim_folder(folder)
    assert outcome.classification == "collaborative"
    # Collaboration came from the chat heuristics, not the task lifecycle.
    assert outcome.sub_counts["distinct_task_creators"] == 0
    assert outcome.failure_class is None


def test_settlement_acceptance_report_still_passes(tmp_path: Path) -> None:
    """The settlement (default) report path is unchanged by the emergent additions."""
    run_dir = tmp_path / "run"
    _write_timeline(run_dir, _settlement_timeline_events())
    (run_dir / "behavior-totals.env").write_text(
        "behavior_gate_status=pass\ntotal_restart_recurrences=0\n", encoding="utf-8"
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_MINECRAFT / "build_director_acceptance_report.py"),
            "--run-dir",
            str(run_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    report = json.loads((run_dir / "acceptance-report.json").read_text(encoding="utf-8"))
    assert report["profile"] == "director_v2"
    assert report["metrics"]["settlement_objective_count"] == 1
    settlement = next(
        c for c in report["criteria"] if c["id"] == "settlement_objectives_have_structured_results"
    )
    assert settlement["status"] == "pass"


# ─── 4. Stall fix #904 — emergent first-claim-wins ─────────────────────────


class _InMemoryRedis:
    """Minimal async Redis backing SharedWorkingState.claim_task / add_task."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}

    async def hset(self, key: str, field: str, value: str) -> int:
        self.hashes.setdefault(key, {})[field] = value
        return 1

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key: str, *fields: str) -> int:
        bucket = self.hashes.get(key, {})
        return sum(1 for f in fields if bucket.pop(f, None) is not None)

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.strings:
            return False
        self.strings[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)


def _emergent_state() -> SharedWorkingState:
    import uuid

    return SharedWorkingState(ScopedRedis(_InMemoryRedis(), uuid.uuid4()))


async def test_emergent_default_create_task_is_claimable_by_another_agent() -> None:
    """D3 auto-approve: a default (unowned) create_task can be claimed by anyone."""
    state = _emergent_state()
    creator = ManageTaskTool(shared_state=state, agent_id="vera")
    created = await creator.execute(action="create_task", title="Storage hall")
    assert created["owner"] is None  # open proposal

    task_id = created["task_id"]
    claimer = ManageTaskTool(shared_state=state, agent_id="rex")
    claimed = await claimer.execute(action="claim_task", task_id=task_id)
    assert claimed["status"] == "ok"
    assert claimed["new_owner"] == "rex"


async def test_emergent_contested_claim_has_exactly_one_winner() -> None:
    """Two distinct agents racing the same pending task: exactly one wins."""
    import asyncio

    state = _emergent_state()
    creator = ManageTaskTool(shared_state=state, agent_id="vera")
    created = await creator.execute(action="create_task", title="Lead the build")
    task_id = created["task_id"]

    rex = ManageTaskTool(shared_state=state, agent_id="rex")
    aurora = ManageTaskTool(shared_state=state, agent_id="aurora")
    results = await asyncio.gather(
        rex.execute(action="claim_task", task_id=task_id),
        aurora.execute(action="claim_task", task_id=task_id),
    )
    winners = [r for r in results if r["status"] == "ok"]
    losers = [r for r in results if r["status"] == "already_claimed"]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0]["owner"] == winners[0]["new_owner"]


# ─── 5. Stall fix #903 — .env model precedence over a stale parent export ──

_ENV_KEYS = {"CONVERSATION_MODE", "ENV_FILE"}
_ENV_PREFIXES = ("LOCAL_LLM", "MC_HEARTBEAT", "MC_SIM", "MINECRAFT_", "SOAK_", "LLM_")


def _clean_env(overrides: dict[str, str]) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _ENV_KEYS and not key.startswith(_ENV_PREFIXES)
    }
    env.update(overrides)
    return env


def test_env_file_local_model_wins_over_stale_parent_export(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EMBEDDING_PROVIDER=deterministic\nLOCAL_LLM_MODEL=google/gemma-4-e4b\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_LOCAL_SIM), "soak-director"],
        cwd=REPO_ROOT,
        env=_clean_env(
            {
                "ENV_FILE": str(env_file),
                "MC_SIM_PRINT_ENV": "1",
                # Stale parent-shell export that must NOT mask the .env value.
                "LOCAL_LLM_MODEL": "stale/parent-model",
            }
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    parsed = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    assert parsed["LOCAL_LLM_MODEL"] == "google/gemma-4-e4b"
    assert parsed["MC_SIM_BUILD_MODE"] == "emergent"


# ─── 6. Static operator contract ───────────────────────────────────────────


def test_emergent_doc_documents_30_minute_smoke_and_artifacts() -> None:
    text = EMERGENT_DOC.read_text(encoding="utf-8")
    assert "MC_SIM_BUILD_MODE=emergent MC_SIM_SOAK_HOURS=0.5 pnpm mc:sim:soak:director" in text
    assert "emergent-acceptance.json" in text
    assert "emergent-acceptance.md" in text
    assert "localhost:25566" in text
    # Fallback to the settlement regression harness must be documented.
    assert "settlement" in text.lower()


def test_acceptance_doc_has_emergent_section() -> None:
    text = ACCEPTANCE_DOC.read_text(encoding="utf-8")
    assert "## Emergent Mode Acceptance" in text
    assert "emergent-acceptance.json" in text
    assert "MC_SIM_BUILD_MODE=emergent" in text


def test_soak_director_defaults_to_emergent_in_source() -> None:
    body = RUN_LOCAL_SIM.read_text(encoding="utf-8")
    assert 'MC_SIM_BUILD_MODE="${MC_SIM_BUILD_MODE:-emergent}"' in body


def test_soak_seeds_zero_objectives_in_emergent_mode() -> None:
    """The settlement seed step is gated to settlement mode, so emergent seeds nothing."""
    soak = SOAK.read_text(encoding="utf-8")
    # Anchor on the seed INVOCATION (with its preflight log path) — distinct from
    # the verify-static grep pattern that also mentions the run_checked label.
    seed_idx = soak.index(
        'run_checked "seed settlement objectives" "$RUN_DIR/preflight/seed-settlement-objectives.txt"'
    )
    # The invocation is guarded by an explicit settlement-mode check just above it.
    guard = soak.rindex('if [ "$MC_SIM_BUILD_MODE" = "settlement" ]; then', 0, seed_idx)
    assert 0 <= guard < seed_idx
    assert "Emergent mode seeds nothing" in soak


@pytest.mark.parametrize("flag", ["--mode", "--sim-folder"])
def test_report_builder_exposes_emergent_cli(flag: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_MINECRAFT / "build_director_acceptance_report.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert flag in proc.stdout

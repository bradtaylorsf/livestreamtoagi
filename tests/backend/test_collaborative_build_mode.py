"""Tests for role-based collaborative Minecraft build mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.minecraft.build_plan import Position3D
from core.minecraft.build_script import BuildCommand, BuildScript
from core.minecraft.collaborative_build import (
    CollaborativeRoleRoster,
    collaborative_mode_enabled,
    load_collaborative_build_ledger,
    write_collaborative_build,
)
from core.minecraft.replay import ChatEvent, ExecuteBuildScriptEvent, ReplayScheduler
from core.simulation.decision_log_schema import SCHEMA_VERSION


def _script(intent_id: str = "build-collab") -> BuildScript:
    commands = [
        BuildCommand(
            kind="fill",
            position=Position3D(x=0, y=64, z=0),
            region_to=Position3D(x=4, y=64, z=4),
            block_type="stone_bricks",
        ),
        BuildCommand(
            kind="fill",
            position=Position3D(x=0, y=65, z=0),
            region_to=Position3D(x=4, y=67, z=4),
            block_type="smooth_sandstone",
        ),
        BuildCommand(
            kind="setblock",
            position=Position3D(x=2, y=65, z=0),
            block_type="air",
        ),
        BuildCommand(
            kind="setblock",
            position=Position3D(x=2, y=66, z=0),
            block_type="air",
        ),
        BuildCommand(
            kind="fill",
            position=Position3D(x=1, y=65, z=1),
            region_to=Position3D(x=3, y=65, z=3),
            block_type="sand",
        ),
        BuildCommand(
            kind="setblock",
            position=Position3D(x=1, y=66, z=1),
            block_type="smooth_sandstone_stairs",
        ),
    ]
    return BuildScript(
        intent_id=intent_id,
        structure_type="coliseum",
        size_class="epic",
        origin=Position3D(x=0, y=64, z=0),
        commands=commands,
        materials_manifest={
            "stone_bricks": 25,
            "smooth_sandstone": 75,
            "sand": 9,
            "smooth_sandstone_stairs": 1,
        },
        total_blocks=sum(command.block_count() for command in commands),
        estimated_seconds=10,
        source_plan_hash="hash",
        compiler_version=1,
    )


def _write_decision_log(sim_folder: Path, rows: list[dict[str, Any]]) -> None:
    with (sim_folder / "decision_log.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _write_build_intent(sim_folder: Path, intent_id: str) -> None:
    with (sim_folder / "build_intents.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "intent_id": intent_id,
                    "actor_id": "rex",
                    "submitted_at": 2.0,
                    "args": {"intent_id": intent_id},
                }
            )
            + "\n"
        )


def _propose_build(intent_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "tool_intent",
        "tick": 2,
        "wall_time": "2026-06-05T05:00:00Z",
        "sim_time": 2.0,
        "actor_id": "rex",
        "payload": {
            "tool_name": "propose_build",
            "args": {"intent_id": intent_id, "structure_type": "coliseum"},
            "status": "simulated",
        },
    }


def test_collaborative_mode_env_gate() -> None:
    assert collaborative_mode_enabled({"MC_SIM_COLLABORATIVE_BUILD_MODE": "roles"})
    assert collaborative_mode_enabled({"MC_SIM_BUILD_MODE": "collaborative"})
    assert not collaborative_mode_enabled({"MC_SIM_COLLABORATIVE_BUILD_MODE": "off"})


def test_write_collaborative_build_creates_role_ledger_and_job_scripts(tmp_path: Path) -> None:
    script = _script()
    source_dir = tmp_path / "build_scripts"
    source_dir.mkdir()
    source_path = source_dir / f"{script.intent_id}.script.json"
    source_path.write_text(json.dumps(script.to_jsonable()), encoding="utf-8")

    ledger = write_collaborative_build(
        script,
        sim_folder=tmp_path,
        source_script_path=source_path,
        roster=CollaborativeRoleRoster(
            manager="vera",
            resource_gatherers=["sentinel"],
            crafters=["aurora"],
            builders=["rex", "alpha"],
            inspector="pixel",
        ),
        max_builder_commands=2,
    )

    ledger_path = tmp_path / "collaborative_builds" / script.intent_id / "ledger.json"
    loaded = load_collaborative_build_ledger(ledger_path)
    assert loaded.source_intent_id == script.intent_id
    assert loaded.roster.manager == "vera"
    assert loaded.jobs[0].role == "manager"
    assert loaded.jobs[-1].role == "inspector"
    builder_jobs = [job for job in ledger.jobs if job.role == "builder"]
    assert [job.owner_agent_id for job in builder_jobs] == ["rex", "alpha", "rex"]
    assert [idx for job in builder_jobs for idx in job.command_indices] == list(
        range(len(script.commands))
    )
    assert all(job.script_path for job in builder_jobs)
    assert all((tmp_path / str(job.script_path)).is_file() for job in builder_jobs)
    assert builder_jobs[1].depends_on == [builder_jobs[0].job_id]


def test_replay_scheduler_expands_collaborative_build_jobs(tmp_path: Path) -> None:
    script = _script("build-replay")
    source_dir = tmp_path / "build_scripts"
    source_dir.mkdir()
    source_path = source_dir / f"{script.intent_id}.script.json"
    source_path.write_text(json.dumps(script.to_jsonable()), encoding="utf-8")
    write_collaborative_build(
        script,
        sim_folder=tmp_path,
        source_script_path=source_path,
        max_builder_commands=3,
    )
    _write_decision_log(tmp_path, [_propose_build(script.intent_id)])
    _write_build_intent(tmp_path, script.intent_id)

    events = ReplayScheduler(sim_folder=tmp_path, collaborative_builds=True).events()

    chat_events = [event for event in events if isinstance(event, ChatEvent)]
    build_events = [event for event in events if isinstance(event, ExecuteBuildScriptEvent)]
    assert any(event.actor_id == "vera" and "managing" in event.text for event in chat_events)
    assert any(event.actor_id in {"sentinel", "fork"} for event in chat_events)
    assert len(build_events) == 2
    assert all(event.intent_id.startswith(f"{script.intent_id}-build-") for event in build_events)
    assert all(event.script_path.is_file() for event in build_events)


def test_replay_scheduler_can_filter_to_one_build_intent(tmp_path: Path) -> None:
    wanted = _script("build-wanted")
    other = _script("build-other")
    source_dir = tmp_path / "build_scripts"
    source_dir.mkdir()
    for script in (wanted, other):
        (source_dir / f"{script.intent_id}.script.json").write_text(
            json.dumps(script.to_jsonable()),
            encoding="utf-8",
        )
    _write_decision_log(
        tmp_path, [_propose_build(wanted.intent_id), _propose_build(other.intent_id)]
    )
    with (tmp_path / "build_intents.jsonl").open("w", encoding="utf-8") as fh:
        for script in (wanted, other):
            fh.write(
                json.dumps(
                    {
                        "intent_id": script.intent_id,
                        "actor_id": "rex",
                        "submitted_at": 2.0,
                        "args": {"intent_id": script.intent_id},
                    }
                )
                + "\n"
            )

    events = ReplayScheduler(sim_folder=tmp_path, intent_ids=frozenset({"build-wanted"})).events()

    build_events = [event for event in events if isinstance(event, ExecuteBuildScriptEvent)]
    assert [event.intent_id for event in build_events] == ["build-wanted"]

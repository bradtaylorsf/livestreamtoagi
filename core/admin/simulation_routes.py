"""Simulation endpoints.

Provides simulation CRUD, cloning, snapshots, timeline, conversations,
artifacts, management log, costs, memory state, social graph, assertions,
reports, and world chunk inspection.
"""

from __future__ import annotations

import time as _time_mod
import uuid as uuid_mod
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.admin.dependencies import get_db, get_registry
from core.models import (
    Artifact,
    Conversation,
    PaginatedResponse,
    Simulation,
    SimulationCostResponse,
    TimelineEvent,
)

if TYPE_CHECKING:
    from fastapi.responses import RedirectResponse

    from core.agent_registry import AgentRegistry
    from core.database import Database

router = APIRouter(tags=["simulations"])


# ── Request/Response models ──────────────────────────────────


class NewSimulationRequest(BaseModel):
    name: str | None = None
    agents: list[str] = Field(default_factory=list)
    convo_type: str = "freeform"
    topic: str | None = None
    turns: int | None = None
    management_shadow: bool = True
    # When set, launch via scripts/run_simulation.py with this scenario YAML
    # (relative to the project's scenarios/ dir). The convo_type / agents
    # fields are ignored in that branch.
    seed_file: str | None = None
    max_cost: float | None = Field(default=None, ge=0, le=10)


class NewSimulationResponse(BaseModel):
    simulation_id: str
    name: str
    status: str


class ScenarioInfo(BaseModel):
    filename: str
    name: str
    description: str | None = None


class CloneSimulationRequest(BaseModel):
    name: str | None = None
    agents: list[str] | None = None


class CloneSimulationResponse(BaseModel):
    simulation_id: str
    name: str
    source_simulation_id: str
    restore_result: dict[str, Any] = {}


class SnapshotExportResponse(BaseModel):
    simulation_id: str
    snapshot_at: str
    agent_count: int
    world_chunk_count: int
    relationship_count: int
    goal_count: int
    transaction_count: int = 0
    challenge_count: int = 0
    world_event_count: int = 0
    alliance_count: int = 0
    filename: str = ""
    path: str = ""


def _time_str() -> str:
    return _time_mod.strftime("%Y%m%d-%H%M%S")


def _project_root() -> Any:
    """Return the project root path (the directory containing scenarios/, scripts/).

    Extracted so tests can monkey-patch a temporary project layout without
    juggling ``__file__`` overrides.
    """
    from pathlib import Path

    return Path(__file__).resolve().parent.parent.parent


# ── Simulation CRUD ──────────────────────────────────────────


@router.post("/simulations", response_model=NewSimulationResponse)
async def create_simulation(
    body: NewSimulationRequest,
    registry: AgentRegistry = Depends(get_registry),
    db: Database = Depends(get_db),
) -> NewSimulationResponse:
    """Create a new simulation and launch it as a background subprocess.

    Two launch paths:
      * ``body.seed_file`` set → run scripts/run_simulation.py against a
        scenario YAML in scenarios/. Used by the dashboard "Run new
        simulation" launcher.
      * otherwise → run scripts/watch_conversations.py in test mode
        (legacy admin path).
    """
    import subprocess
    import sys

    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)

    project_root = _project_root()

    if body.seed_file is not None:
        # Reject path traversal / absolute paths — only accept relative paths
        # that resolve inside scenarios/.
        scenarios_dir = (project_root / "scenarios").resolve()
        candidate = (scenarios_dir / body.seed_file).resolve()
        try:
            candidate.relative_to(scenarios_dir)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="seed_file must resolve inside scenarios/",
            ) from exc
        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(status_code=400, detail="seed_file not found")

        from core.models import SimulationCreate

        sim_name = body.name or f"dashboard-{candidate.stem}-{_time_str()}"
        max_cost = body.max_cost if body.max_cost is not None else 2.0
        seed_file_rel = str(candidate.relative_to(project_root))

        sim = await sim_repo.create(
            SimulationCreate(
                name=sim_name,
                config={
                    "seed_file": seed_file_rel,
                    "max_cost": max_cost,
                    "source": "dashboard",
                },
            )
        )

        cmd = [
            sys.executable,
            str(project_root / "scripts" / "run_simulation.py"),
            "--name",
            sim_name,
            "--seed-file",
            str(candidate),
            "--max-cost",
            str(max_cost),
            "--sim-id",
            str(sim.id),
        ]

        subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(project_root),
        )

        return NewSimulationResponse(
            simulation_id=str(sim.id),
            name=sim_name,
            status="running",
        )

    sim_name = body.name or f"dashboard-{body.convo_type}-{_time_str()}"

    agents = body.agents or [
        a.id for a in registry.get_all_agents() if a.id not in ("management", "alpha")
    ]

    from core.models import SimulationCreate

    sim = await sim_repo.create(
        SimulationCreate(
            name=sim_name,
            config={
                "convo_type": body.convo_type,
                "turns": body.turns,
                "topic": body.topic,
                "management_shadow": body.management_shadow,
                "agents": agents,
                "source": "dashboard",
            },
            agents_participated=agents,
        )
    )

    cmd = [
        sys.executable,
        str(project_root / "scripts" / "watch_conversations.py"),
        "--test",
        "--test-type",
        body.convo_type,
        "--agents",
        ",".join(agents),
        "--sim-id",
        str(sim.id),
    ]
    if body.turns is not None:
        cmd += ["--turns", str(body.turns)]
    if body.topic is not None:
        cmd += ["--topic", body.topic]
    if body.management_shadow:
        cmd.append("--management-shadow")

    subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return NewSimulationResponse(
        simulation_id=str(sim.id),
        name=sim_name,
        status="running",
    )


@router.get("/scenarios", response_model=list[ScenarioInfo])
async def list_scenarios() -> list[ScenarioInfo]:
    """List scenario YAMLs in scenarios/ for the dashboard launcher.

    Description is best-effort: if the file starts with comment lines
    (``# ...``), the first contiguous block is used; otherwise null.
    """
    project_root = _project_root()
    scenarios_dir = project_root / "scenarios"
    if not scenarios_dir.is_dir():
        return []

    out: list[ScenarioInfo] = []
    for path in sorted(scenarios_dir.glob("*.yaml")):
        if not path.is_file():
            continue
        description: str | None = None
        try:
            with open(path) as f:
                lines: list[str] = []
                for raw in f:
                    stripped = raw.strip()
                    if stripped.startswith("#"):
                        text = stripped.lstrip("#").strip()
                        # Skip empty comment lines until we have content,
                        # but stop at the first blank comment after content
                        # so descriptions stay tight.
                        if text or lines:
                            lines.append(text)
                    elif stripped == "":
                        if lines:
                            break
                    else:
                        break
                # Trim trailing blanks
                while lines and not lines[-1]:
                    lines.pop()
                if lines:
                    description = " ".join(lines).strip() or None
        except OSError:
            description = None
        out.append(
            ScenarioInfo(
                filename=path.name,
                name=path.stem,
                description=description,
            )
        )
    return out


@router.get("/simulations")
async def list_simulations(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> PaginatedResponse[Simulation]:
    """List all simulations with summary stats."""
    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)

    simulations = await sim_repo.list(status=status, limit=limit, offset=offset)
    total = await sim_repo.count(status=status)
    return PaginatedResponse(items=simulations, total=total, limit=limit, offset=offset)


@router.get("/simulations/compare")
async def compare_simulations(
    sim_a: uuid_mod.UUID = Query(...),
    sim_b: uuid_mod.UUID = Query(...),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Side-by-side comparison of two simulation runs."""
    from core.reporting.comparison import CrossRunComparison
    from core.repos.relationship_repo import RelationshipRepo

    relationship_repo = RelationshipRepo(db)
    cross = CrossRunComparison(
        db=db,
        simulation_ids=[str(sim_a), str(sim_b)],
        relationship_repo=relationship_repo,
    )
    result = await cross.compare()

    daily_costs: dict[str, list[dict[str, Any]]] = {"run_a": [], "run_b": []}
    for label, sim_id in [("run_a", sim_a), ("run_b", sim_b)]:
        rows = await db.fetch(
            """SELECT DATE(created_at) as day, SUM(cost) as daily_cost
               FROM cost_events WHERE simulation_id = $1
               GROUP BY DATE(created_at) ORDER BY day""",
            sim_id,
        )
        daily_costs[label] = [{"day": str(r["day"]), "cost": str(r["daily_cost"])} for r in rows]

    data = result.to_dict()
    data["daily_costs"] = daily_costs
    return data


@router.get("/simulations/{sim_id}", response_model=Simulation)
async def get_simulation(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> Simulation:
    """Full simulation detail: config, stats, phases, timing."""
    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)

    sim = await sim_repo.get(sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return sim


@router.post("/simulations/{sim_id}/clone", response_model=CloneSimulationResponse)
async def clone_simulation(
    sim_id: uuid_mod.UUID,
    body: CloneSimulationRequest,
    db: Database = Depends(get_db),
) -> CloneSimulationResponse:
    """Clone a simulation by exporting its full state and importing into a new simulation."""
    from core.repos.simulation_repo import SimulationRepo
    from core.simulation.snapshot import SimulationSnapshotExporter, SimulationSnapshotImporter

    sim_repo = SimulationRepo(db)
    source = await sim_repo.get(sim_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source simulation not found")

    exporter = SimulationSnapshotExporter(db)
    snapshot_data = await exporter.export(str(sim_id), agents=body.agents)

    from core.models import SimulationCreate

    clone_name = body.name or f"clone-{source.name}-{_time_str()}"
    new_sim = await sim_repo.create(
        SimulationCreate(
            name=clone_name,
            description=f"Cloned from {source.name} ({sim_id})",
            config={
                "source": "clone",
                "source_simulation_id": str(sim_id),
                **(source.config or {}),
            },
            agents_participated=list(snapshot_data.get("agents", {}).keys()),
        )
    )

    importer = SimulationSnapshotImporter(db)
    restore_result = await importer.restore(
        snapshot_data,
        str(new_sim.id),
        agents=body.agents,
    )

    return CloneSimulationResponse(
        simulation_id=str(new_sim.id),
        name=clone_name,
        source_simulation_id=str(sim_id),
        restore_result={
            "agents_restored": restore_result.agents_restored,
            "core_memories": restore_result.core_memories_restored,
            "recall_memories": restore_result.recall_memories_restored,
            "journal_entries": restore_result.journal_entries_restored,
            "relationships": restore_result.relationships_restored,
            "goals": restore_result.goals_restored,
            "agent_states": restore_result.agent_states_restored,
            "agent_accounts": restore_result.agent_accounts_restored,
            "world_chunks": restore_result.world_chunks_restored,
            "transactions": restore_result.transactions_restored,
            "challenges": restore_result.challenges_restored,
            "world_events": restore_result.world_events_restored,
            "alliances": restore_result.alliances_restored,
            "warnings": restore_result.warnings,
        },
    )


@router.post("/simulations/{sim_id}/snapshot/export")
async def export_simulation_snapshot(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> SnapshotExportResponse:
    """Export a complete simulation snapshot (full state) to JSON."""
    import json as _json
    import re
    from pathlib import Path

    from core.repos.simulation_repo import SimulationRepo
    from core.simulation.snapshot import SimulationSnapshotExporter

    sim_repo = SimulationRepo(db)
    source = await sim_repo.get(sim_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    exporter = SimulationSnapshotExporter(db)
    snapshot_data = await exporter.export(str(sim_id))

    snapshots_dir = Path(__file__).resolve().parent.parent.parent / "snapshots"
    snapshots_dir.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^\w\-]", "_", source.name)
    filename = f"full-{safe_name}-{_time_str()}.json"
    filepath = snapshots_dir / filename
    filepath.write_text(_json.dumps(snapshot_data, indent=2, default=str))

    return SnapshotExportResponse(
        simulation_id=str(sim_id),
        snapshot_at=snapshot_data.get("snapshot_at", ""),
        agent_count=len(snapshot_data.get("agents", {})),
        world_chunk_count=len(snapshot_data.get("world_chunks", [])),
        relationship_count=len(snapshot_data.get("relationships", [])),
        goal_count=sum(len(goals) for goals in snapshot_data.get("agent_goals", {}).values()),
        transaction_count=len(snapshot_data.get("transactions", [])),
        challenge_count=len(snapshot_data.get("challenges", [])),
        world_event_count=len(snapshot_data.get("world_events", [])),
        alliance_count=len(snapshot_data.get("alliances", [])),
        filename=filename,
        path=str(filepath),
    )


@router.delete("/simulations/{sim_id}")
async def delete_simulation(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> dict[str, bool]:
    """Delete a simulation and all its data."""
    from core.constants import LIVE_SIMULATION_ID
    from core.repos.simulation_repo import SimulationRepo

    if sim_id == LIVE_SIMULATION_ID:
        raise HTTPException(status_code=400, detail="Cannot delete the live simulation")

    sim_repo = SimulationRepo(db)
    source = await sim_repo.get(sim_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    if source.status == "running":
        raise HTTPException(status_code=400, detail="Cannot delete a running simulation")

    deleted = await sim_repo.delete(sim_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete simulation")
    return {"deleted": True}


@router.get("/simulations/{sim_id}/timeline", response_model=list[TimelineEvent])
async def get_simulation_timeline(
    sim_id: uuid_mod.UUID,
    agent_id: str | None = Query(None),
    event_type: str | None = Query(None),
    db: Database = Depends(get_db),
) -> list[TimelineEvent]:
    """Chronological event stream for a simulation."""
    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)

    events = await sim_repo.get_timeline_events(sim_id, agent_id=agent_id, event_type=event_type)
    return [TimelineEvent(**e) for e in events]


@router.get("/simulations/{sim_id}/conversations")
async def get_simulation_conversations(
    sim_id: uuid_mod.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> PaginatedResponse[Conversation]:
    """All conversations in this simulation."""
    from core.repos.conversation_repo import ConversationRepo

    conv_repo = ConversationRepo(db)

    conversations, total = await conv_repo.get_conversations_by_simulation(
        sim_id, limit=limit, offset=offset
    )
    return PaginatedResponse(items=conversations, total=total, limit=limit, offset=offset)


@router.get("/simulations/{sim_id}/artifacts")
async def get_simulation_artifacts(
    sim_id: uuid_mod.UUID,
    agent_id: str | None = Query(None),
    artifact_type: str | None = Query(None, alias="type"),
    db: Database = Depends(get_db),
) -> list[Artifact]:
    """All artifacts from this simulation."""
    from core.repos.artifact_repo import ArtifactRepo

    artifact_repo = ArtifactRepo(db)

    return await artifact_repo.get_artifacts_by_simulation(
        sim_id, agent_id=agent_id, artifact_type=artifact_type
    )


@router.get("/simulations/{sim_id}/management-log")
async def get_simulation_management_log(
    sim_id: uuid_mod.UUID,
    severity_min: int = Query(1, ge=1, le=5),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """All Management shadow flags from this simulation."""
    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)

    return await sim_repo.get_management_log(sim_id, severity_min=severity_min)


@router.get("/simulations/{sim_id}/costs", response_model=SimulationCostResponse)
async def get_simulation_costs(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> SimulationCostResponse:
    """Cost breakdown by agent, by tool type, total."""
    from core.repos.cost_repo import CostRepo

    cost_repo = CostRepo(db)

    data = await cost_repo.get_costs_by_simulation(sim_id)
    return SimulationCostResponse(**data)


@router.get("/simulations/{sim_id}/assertions")
async def get_simulation_assertions(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """All assertion results for a simulation."""
    from core.repos.assertion_repo import AssertionRepo

    repo = AssertionRepo(db)
    rows = await repo.get_by_simulation(sim_id)
    # Transform DB fields to match frontend AssertionResult interface
    for row in rows:
        passed = row.pop("passed", False)
        severity = row.get("severity", "warning")
        if passed:
            row["status"] = "pass"
        elif severity == "warning" or severity == "info":
            row["status"] = "warning"
        else:
            row["status"] = "fail"
        if "error_message" in row:
            row["message"] = row.pop("error_message")
    return rows


@router.get("/simulations/{sim_id}/assertions/summary")
async def get_simulation_assertions_summary(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Pass/fail/warn summary for simulation assertions."""
    from core.repos.assertion_repo import AssertionRepo

    repo = AssertionRepo(db)
    rates = await repo.get_pass_rates(sim_id)
    # Transform to match frontend AssertionSummary interface
    return {
        "passed": rates.get("passed", 0),
        "failed": rates.get("failed_error", 0),
        "warnings": rates.get("failed_warning", 0) + rates.get("failed_info", 0),
    }


@router.get("/simulations/{sim_id}/social-graph")
async def get_social_graph(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Full relationship matrix for a simulation."""
    from core.repos.relationship_repo import RelationshipRepo

    repo = RelationshipRepo(db)
    relationships = await repo.get_social_graph(sim_id)
    return [r.model_dump(mode="json") for r in relationships]


# ── Snapshots & Memory ───────────────────────────────────────


@router.get("/simulations/{sim_id}/snapshots")
async def list_snapshots(
    sim_id: uuid_mod.UUID,
) -> list[dict[str, Any]]:
    """List available memory snapshots for a simulation."""
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    snapshots_dir = Path("snapshots")
    results: list[dict[str, Any]] = []
    if not snapshots_dir.exists():
        return results

    for f in sorted(snapshots_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            source_id = data.get("source_simulation_id", "")
            if source_id == str(sim_id) or not source_id:
                agents = data.get("agents", {})
                snapshot_at = (
                    data.get("snapshot_at")
                    or datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).isoformat()
                )
                results.append(
                    {
                        "filename": f.name,
                        "simulation_id": source_id,
                        "snapshot_at": snapshot_at,
                        "agent_count": len(agents),
                    }
                )
        except Exception:
            continue
    return results


@router.get("/simulations/{sim_id}/snapshots/{filename}")
async def get_snapshot(
    sim_id: uuid_mod.UUID,
    filename: str,
) -> dict[str, Any]:
    """Read and return a specific snapshot file."""
    import json
    from pathlib import Path

    safe_name = Path(filename).name
    snapshot_path = Path("snapshots") / safe_name
    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    try:
        data = json.loads(snapshot_path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    source_id = data.get("source_simulation_id") or data.get("simulation_id")
    if source_id is not None and str(source_id) != str(sim_id):
        raise HTTPException(
            status_code=403,
            detail="Snapshot does not belong to this simulation",
        )
    return data


@router.post("/simulations/{sim_id}/snapshots")
async def create_snapshot(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Export a new memory snapshot for this simulation.

    DEPRECATED: Use POST /simulations/{sim_id}/snapshot/export instead.
    """
    import json
    from pathlib import Path

    from core.memory.snapshot import MemorySnapshotExporter
    from core.repos.memory_repo import MemoryRepo
    from core.repos.relationship_repo import RelationshipRepo

    memory_repo = MemoryRepo(db)
    relationship_repo = RelationshipRepo(db)
    exporter = MemorySnapshotExporter(
        db=db,
        memory_repo=memory_repo,
        relationship_repo=relationship_repo,
    )
    snapshot_data = await exporter.export(str(sim_id))

    snapshots_dir = Path("snapshots")
    snapshots_dir.mkdir(exist_ok=True)
    timestamp = snapshot_data.get("snapshot_at", "unknown").replace(":", "-").replace("+", "")[:19]
    filename = f"snapshot-{str(sim_id)[:8]}-{timestamp}.json"
    filepath = snapshots_dir / filename
    filepath.write_text(json.dumps(snapshot_data, indent=2, default=str))

    return {
        "filename": filename,
        "simulation_id": str(sim_id),
        "snapshot_at": snapshot_data.get("snapshot_at", ""),
        "agent_count": len(snapshot_data.get("agents", {})),
    }


@router.get("/simulations/{sim_id}/memory-current")
async def get_current_memory_state(
    sim_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Return current memory state for comparison with snapshots."""
    from core.repos.memory_repo import MemoryRepo

    memory_repo = MemoryRepo(db)

    row = await db.fetchrow("SELECT agents_participated FROM simulations WHERE id = $1", sim_id)
    if not row:
        raise HTTPException(status_code=404, detail="Simulation not found")

    agents = row.get("agents_participated") or []
    result: dict[str, Any] = {"agents": {}}

    for agent_id in agents:
        agent_data: dict[str, Any] = {"core_memory": "", "recall_count": 0, "journal_count": 0}
        core = await memory_repo.get_core_memory(agent_id, simulation_id=sim_id)
        if core:
            agent_data["core_memory"] = core.content

        recall, total_recall = await memory_repo.get_recall_memories_paginated(
            agent_id,
            limit=0,
            simulation_id=sim_id,
        )
        agent_data["recall_count"] = total_recall

        entries, total_journal = await memory_repo.get_journal_entries(
            agent_id, limit=0, simulation_id=sim_id
        )
        agent_data["journal_count"] = total_journal

        result["agents"][agent_id] = agent_data

    return result


@router.get("/simulations/{sim_id}/report")
async def get_simulation_report(
    sim_id: uuid_mod.UUID,
    days: str | None = Query(default=None),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Generate structured timeline report for a simulation."""
    from core.reporting.timeline_reporter import TimelineReporter
    from core.repos.relationship_repo import RelationshipRepo

    relationship_repo = RelationshipRepo(db)
    reporter = TimelineReporter(
        db=db,
        simulation_id=str(sim_id),
        relationship_repo=relationship_repo,
    )
    day_list = None
    if days:
        try:
            day_list = [int(d.strip()) for d in days.split(",")]
        except ValueError:
            pass
    report = await reporter.generate(days=day_list, format="json")

    from core.reporting.scorecard import LaunchScorecard
    from core.reporting.timeline_reporter import ReportSection
    from core.repos.assertion_repo import AssertionRepo

    assertion_repo = AssertionRepo(db)
    scorecard = LaunchScorecard(
        db=db,
        simulation_id=str(sim_id),
        assertion_repo=assertion_repo,
        relationship_repo=relationship_repo,
        report_sections=[{"title": s.title, "data": s.data} for s in report.sections],
    )
    scorecard_result = await scorecard.evaluate()
    report.sections.append(
        ReportSection(
            title="Launch Readiness Scorecard",
            data=scorecard_result.to_dict(),
        )
    )

    return report.to_dict()


# ── World Chunks ─────────────────────────────────────────────


@router.get("/chunks/{chunk_id}")
async def get_chunk(
    chunk_id: int,
    db: Database = Depends(get_db),
) -> dict:
    """Get chunk metadata and tile data for frontend rendering."""
    from core.repos.world_repo import WorldRepo

    repo = WorldRepo(db)
    chunk = await repo.get_chunk(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return chunk.model_dump(mode="json")


@router.get("/chunks/{chunk_id}/tileset.png")
async def get_chunk_tileset(
    chunk_id: int,
    db: Database = Depends(get_db),
) -> RedirectResponse:
    """Serve or redirect to the tileset image for a chunk."""
    from fastapi.responses import RedirectResponse

    from core.repos.world_repo import WorldRepo

    repo = WorldRepo(db)
    chunk = await repo.get_chunk(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    if not chunk.tileset_url:
        raise HTTPException(status_code=404, detail="No tileset URL for this chunk")
    return RedirectResponse(url=chunk.tileset_url)

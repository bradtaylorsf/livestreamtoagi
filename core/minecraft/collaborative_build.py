"""Role-based decomposition for compiled Minecraft ``BuildScript`` artifacts.

The normal headless path records agent dialog, then lowers one ``propose_build``
intent into one macro ``BuildScript``. This module keeps that deterministic
compiler output intact while adding an auditable collaboration layer around it:
manager planning jobs, resource staging jobs, crafting jobs, sequential builder
job scripts, and a final inspector job.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.minecraft.build_script import BLOCKS_PER_SECOND, BuildCommand, BuildScript

COLLABORATIVE_BUILDS_DIRNAME = "collaborative_builds"
DEFAULT_MAX_BUILDER_COMMANDS = 350

CollaborativeRole = Literal[
    "manager",
    "resource_gatherer",
    "crafter",
    "builder",
    "inspector",
]
CollaborativePhase = Literal["plan", "gather", "craft", "build", "inspect"]

_TRUE_VALUES = frozenset(("1", "true", "yes", "on", "roles", "role"))


class CollaborativeRoleRoster(BaseModel):
    """Agents assigned to the collaboration roles for one build."""

    model_config = ConfigDict(extra="forbid")

    manager: str = Field(min_length=1)
    resource_gatherers: list[str] = Field(min_length=1)
    crafters: list[str] = Field(min_length=1)
    builders: list[str] = Field(min_length=1)
    inspector: str = Field(min_length=1)


class CollaborativeBuildJob(BaseModel):
    """One role-owned unit of work in the collaborative build ledger."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    phase_index: int = Field(ge=0)
    phase: CollaborativePhase
    role: CollaborativeRole
    owner_agent_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    materials: dict[str, int] = Field(default_factory=dict)
    command_indices: list[int] = Field(default_factory=list)
    command_count: int = 0
    total_blocks: int = 0
    script_path: str | None = None
    bounds: dict[str, int] | None = None


class CollaborativeBuildLedger(BaseModel):
    """Serializable role ledger for a collaborative build replay."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    mode: Literal["roles"] = "roles"
    source_intent_id: str = Field(min_length=1)
    source_script_path: str | None = None
    structure_type: str = Field(min_length=1)
    size_class: str = Field(min_length=1)
    origin: dict[str, int]
    roster: CollaborativeRoleRoster
    materials_manifest: dict[str, int] = Field(default_factory=dict)
    total_source_commands: int
    total_source_blocks: int
    jobs: list[CollaborativeBuildJob] = Field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.model_dump(mode="json"), sort_keys=True))


def collaborative_mode_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return true when the operator requested role-based build artifacts."""

    source = env if env is not None else os.environ
    explicit = source.get("MC_SIM_COLLABORATIVE_BUILD_MODE", "").strip().casefold()
    if explicit:
        return explicit in _TRUE_VALUES
    return source.get("MC_SIM_BUILD_MODE", "").strip().casefold() == "collaborative"


def roster_from_env(env: Mapping[str, str] | None = None) -> CollaborativeRoleRoster:
    """Build a role roster from env vars, falling back to the show cast."""

    source = env if env is not None else os.environ
    return CollaborativeRoleRoster(
        manager=source.get("MC_SIM_COLLAB_MANAGER", "vera").strip() or "vera",
        resource_gatherers=_csv(
            source.get("MC_SIM_COLLAB_RESOURCE_GATHERERS"),
            default=("sentinel", "fork"),
        ),
        crafters=_csv(source.get("MC_SIM_COLLAB_CRAFTERS"), default=("aurora", "pixel")),
        builders=_csv(source.get("MC_SIM_COLLAB_BUILDERS"), default=("rex", "alpha")),
        inspector=source.get("MC_SIM_COLLAB_INSPECTOR", "vera").strip() or "vera",
    )


def create_collaborative_build_ledger(
    script: BuildScript,
    *,
    roster: CollaborativeRoleRoster | None = None,
    source_script_path: Path | str | None = None,
    max_builder_commands: int = DEFAULT_MAX_BUILDER_COMMANDS,
) -> CollaborativeBuildLedger:
    """Create a role/job ledger without writing files."""

    selected_roster = roster or roster_from_env()
    max_commands = max(1, int(max_builder_commands))
    material_items = [
        (material, count)
        for material, count in sorted(script.materials_manifest.items())
        if material != "air" and count > 0
    ]

    jobs: list[CollaborativeBuildJob] = []
    plan_job_id = f"{script.intent_id}-plan"
    jobs.append(
        CollaborativeBuildJob(
            job_id=plan_job_id,
            phase_index=0,
            phase="plan",
            role="manager",
            owner_agent_id=selected_roster.manager,
            title="Plan work packages",
            description=(
                f"Split the {script.structure_type} into role-gated material, "
                "crafting, building, and inspection jobs."
            ),
        )
    )

    gather_job_ids: list[str] = []
    for idx, (material, count) in enumerate(material_items):
        owner = selected_roster.resource_gatherers[idx % len(selected_roster.resource_gatherers)]
        job_id = f"{script.intent_id}-gather-{idx + 1:03d}"
        gather_job_ids.append(job_id)
        jobs.append(
            CollaborativeBuildJob(
                job_id=job_id,
                phase_index=1,
                phase="gather",
                role="resource_gatherer",
                owner_agent_id=owner,
                title=f"Stage {material}",
                description=f"Gather or allocate {count} {material} for the shared build.",
                depends_on=[plan_job_id],
                materials={material: count},
            )
        )

    craft_job_ids: list[str] = []
    for idx, group in enumerate(
        _partition_materials(material_items, len(selected_roster.crafters))
    ):
        if not group:
            continue
        owner = selected_roster.crafters[idx % len(selected_roster.crafters)]
        materials = dict(group)
        job_id = f"{script.intent_id}-craft-{idx + 1:03d}"
        craft_job_ids.append(job_id)
        jobs.append(
            CollaborativeBuildJob(
                job_id=job_id,
                phase_index=2,
                phase="craft",
                role="crafter",
                owner_agent_id=owner,
                title=f"Prepare {', '.join(materials)}",
                description=(
                    "Convert staged resources into the finished block types needed "
                    f"for {', '.join(materials)}."
                ),
                depends_on=gather_job_ids or [plan_job_id],
                materials=materials,
            )
        )

    build_depends_on = craft_job_ids or gather_job_ids or [plan_job_id]
    previous_build_job_id: str | None = None
    builder_jobs = _builder_jobs(
        script,
        roster=selected_roster,
        first_depends_on=build_depends_on,
        previous_build_job_id=previous_build_job_id,
        max_builder_commands=max_commands,
    )
    jobs.extend(builder_jobs)

    inspect_depends_on = [builder_jobs[-1].job_id] if builder_jobs else build_depends_on
    jobs.append(
        CollaborativeBuildJob(
            job_id=f"{script.intent_id}-inspect",
            phase_index=4,
            phase="inspect",
            role="inspector",
            owner_agent_id=selected_roster.inspector,
            title="Inspect completed structure",
            description=(
                "Verify dimensions, recognizable silhouette, openings, materials, "
                "and completion against the source build script."
            ),
            depends_on=inspect_depends_on,
        )
    )

    source_path_text = str(source_script_path) if source_script_path is not None else None
    return CollaborativeBuildLedger(
        source_intent_id=script.intent_id,
        source_script_path=source_path_text,
        structure_type=str(script.structure_type),
        size_class=str(script.size_class),
        origin=script.origin.model_dump(mode="json"),
        roster=selected_roster,
        materials_manifest=dict(script.materials_manifest),
        total_source_commands=len(script.commands),
        total_source_blocks=script.total_blocks,
        jobs=jobs,
    )


def write_collaborative_build(
    script: BuildScript,
    *,
    sim_folder: Path | str,
    source_script_path: Path | str | None = None,
    roster: CollaborativeRoleRoster | None = None,
    max_builder_commands: int = DEFAULT_MAX_BUILDER_COMMANDS,
) -> CollaborativeBuildLedger:
    """Write ``ledger.json`` and per-builder job scripts for ``script``."""

    sim_root = Path(sim_folder)
    root = sim_root / COLLABORATIVE_BUILDS_DIRNAME / script.intent_id
    jobs_dir = root / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    ledger = create_collaborative_build_ledger(
        script,
        roster=roster,
        source_script_path=source_script_path,
        max_builder_commands=max_builder_commands,
    )

    updated_jobs: list[CollaborativeBuildJob] = []
    for job in ledger.jobs:
        if job.role != "builder":
            updated_jobs.append(job)
            continue
        job_script = _job_script(script, job)
        relative_path = (
            Path(COLLABORATIVE_BUILDS_DIRNAME)
            / script.intent_id
            / "jobs"
            / f"{job.job_id}.script.json"
        )
        target = sim_root / relative_path
        target.write_text(
            json.dumps(job_script.to_jsonable(), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        updated_jobs.append(job.model_copy(update={"script_path": str(relative_path)}))

    ledger = ledger.model_copy(update={"jobs": updated_jobs})
    (root / "ledger.json").write_text(
        json.dumps(ledger.to_jsonable(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "summary.md").write_text(_summary_markdown(ledger), encoding="utf-8")
    return ledger


def ledger_path_for(sim_folder: Path | str, intent_id: str) -> Path:
    return Path(sim_folder) / COLLABORATIVE_BUILDS_DIRNAME / intent_id / "ledger.json"


def load_collaborative_build_ledger(path: Path | str) -> CollaborativeBuildLedger:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return CollaborativeBuildLedger.model_validate(payload)


def _builder_jobs(
    script: BuildScript,
    *,
    roster: CollaborativeRoleRoster,
    first_depends_on: list[str],
    previous_build_job_id: str | None,
    max_builder_commands: int,
) -> list[CollaborativeBuildJob]:
    jobs: list[CollaborativeBuildJob] = []
    command_indices = list(range(len(script.commands)))
    previous = previous_build_job_id
    for chunk_index, start in enumerate(
        range(0, len(command_indices), max_builder_commands), start=1
    ):
        indices = command_indices[start : start + max_builder_commands]
        commands = [script.commands[i] for i in indices]
        owner = roster.builders[(chunk_index - 1) % len(roster.builders)]
        job_id = f"{script.intent_id}-build-{chunk_index:03d}"
        category = _dominant_category(commands)
        depends_on = [previous] if previous else list(first_depends_on)
        jobs.append(
            CollaborativeBuildJob(
                job_id=job_id,
                phase_index=3,
                phase="build",
                role="builder",
                owner_agent_id=owner,
                title=f"Build {_category_title(category)}",
                description=(
                    f"Place command chunk {chunk_index} for {_category_title(category).lower()} "
                    "while preserving compiler order."
                ),
                depends_on=[dep for dep in depends_on if dep],
                materials=_materials_for(commands),
                command_indices=indices,
                command_count=len(indices),
                total_blocks=sum(cmd.block_count() for cmd in commands),
                bounds=_bounds_for(commands),
            )
        )
        previous = job_id
    return jobs


def _job_script(source: BuildScript, job: CollaborativeBuildJob) -> BuildScript:
    commands = [source.commands[i] for i in job.command_indices]
    total_blocks = sum(cmd.block_count() for cmd in commands)
    return BuildScript(
        intent_id=job.job_id,
        structure_type=source.structure_type,
        size_class=source.size_class,
        origin=source.origin,
        commands=commands,
        materials_manifest=_materials_for(commands),
        total_blocks=total_blocks,
        estimated_seconds=total_blocks / BLOCKS_PER_SECOND if total_blocks else 0.0,
        source_plan_hash=f"{source.source_plan_hash}:{job.job_id}",
        compiler_version=source.compiler_version,
        skill_cards_invoked=list(source.skill_cards_invoked),
    )


def _partition_materials(
    items: Sequence[tuple[str, int]],
    buckets: int,
) -> list[list[tuple[str, int]]]:
    if buckets <= 0:
        return []
    groups: list[list[tuple[str, int]]] = [[] for _ in range(buckets)]
    for idx, item in enumerate(items):
        groups[idx % buckets].append(item)
    return groups


def _materials_for(commands: Sequence[BuildCommand]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for command in commands:
        block = _normalize_block(command.block_type)
        if not block or block == "air" or command.kind == "wait":
            continue
        counter[block] += command.block_count()
    return dict(sorted(counter.items()))


def _dominant_category(commands: Sequence[BuildCommand]) -> str:
    scores: Counter[str] = Counter()
    for command in commands:
        scores[_category_for(command)] += max(1, command.block_count())
    if not scores:
        return "empty"
    return scores.most_common(1)[0][0]


def _category_for(command: BuildCommand) -> str:
    block = _normalize_block(command.block_type)
    if command.kind == "wait":
        return "pause"
    if block == "sand":
        return "arena_floor"
    if block == "stone_bricks":
        return "foundation_and_base"
    if block.endswith("_stairs"):
        return "seating_bowl"
    if block == "air":
        return "gate_and_arch_openings"
    if block in {"chiseled_stone_bricks", "polished_andesite", "lantern"}:
        return "trim_and_lighting"
    return "outer_wall_arcades"


def _category_title(category: str) -> str:
    return {
        "arena_floor": "arena floor",
        "foundation_and_base": "foundation and base",
        "seating_bowl": "seating bowl",
        "gate_and_arch_openings": "gates and arch openings",
        "trim_and_lighting": "trim and lighting",
        "outer_wall_arcades": "outer wall arcades",
        "pause": "timed pause",
        "empty": "empty chunk",
    }.get(category, category.replace("_", " "))


def _bounds_for(commands: Sequence[BuildCommand]) -> dict[str, int] | None:
    xs: list[int] = []
    ys: list[int] = []
    zs: list[int] = []
    for command in commands:
        points = [command.position]
        if command.region_to is not None:
            points.append(command.region_to)
        for point in points:
            xs.append(point.x)
            ys.append(point.y)
            zs.append(point.z)
    if not xs:
        return None
    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
        "min_z": min(zs),
        "max_z": max(zs),
    }


def _normalize_block(name: str | None) -> str:
    if not name:
        return ""
    block = name.strip().lower()
    if block.startswith("minecraft:"):
        block = block.split(":", 1)[1]
    return block.replace(" ", "_").replace("-", "_")


def _csv(raw: str | None, *, default: Sequence[str]) -> list[str]:
    if raw is None or not raw.strip():
        return [item for item in default if item]
    parsed = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    return parsed or [item for item in default if item]


def _summary_markdown(ledger: CollaborativeBuildLedger) -> str:
    lines = [
        f"# Collaborative Build: {ledger.source_intent_id}",
        "",
        f"- Structure: `{ledger.structure_type}` / `{ledger.size_class}`",
        f"- Source commands: `{ledger.total_source_commands}`",
        f"- Source blocks: `{ledger.total_source_blocks}`",
        f"- Manager: `{ledger.roster.manager}`",
        f"- Resource gatherers: `{', '.join(ledger.roster.resource_gatherers)}`",
        f"- Crafters: `{', '.join(ledger.roster.crafters)}`",
        f"- Builders: `{', '.join(ledger.roster.builders)}`",
        f"- Inspector: `{ledger.roster.inspector}`",
        "",
        "## Jobs",
        "",
    ]
    for job in ledger.jobs:
        script_note = f", script `{job.script_path}`" if job.script_path else ""
        lines.append(
            f"- `{job.job_id}` [{job.phase}/{job.role}] `{job.owner_agent_id}`: "
            f"{job.title} ({job.command_count} commands, {job.total_blocks} blocks{script_note})"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "COLLABORATIVE_BUILDS_DIRNAME",
    "DEFAULT_MAX_BUILDER_COMMANDS",
    "CollaborativeBuildJob",
    "CollaborativeBuildLedger",
    "CollaborativePhase",
    "CollaborativeRole",
    "CollaborativeRoleRoster",
    "collaborative_mode_enabled",
    "create_collaborative_build_ledger",
    "ledger_path_for",
    "load_collaborative_build_ledger",
    "roster_from_env",
    "write_collaborative_build",
]

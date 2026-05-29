#!/usr/bin/env python3
"""Seed settlement build objectives onto the shared blackboard for a soak run.

This is the keystone of the overnight settlement path. The operator soak
(``scripts/minecraft/soak.sh``) never instantiates ``EmbodiedSimulationSupervisor``
-- the only class that seeds settlement objectives -- so without this step nothing
ever writes the objective board into the Redis scope the bots actually read, and
the agents fall back to copy-pasting "small shared cabin" forever.

This thin step runs from ``soak.sh`` *before any bot launches* and *only in
settlement mode*. It writes the objective board into the exact
``ScopedRedis(LTAG_SIMULATION_ID)`` scope that ``python_bridge.js`` and
``memory_context.js`` resolve from the same ``LTAG_SIMULATION_ID`` env var, so the
seed and the bots share one explicit simulation scope.

It is a no-op (exit 0) unless ``MC_SIM_BUILD_MODE == "settlement"`` and shared
state is enabled. It is idempotent: ``set_settlement_objectives`` replaces the
list, so re-running re-seeds the same board. It also appends one
``settlement_objective.seeded`` timeline event per objective to
``$MC_RUN_DIR/timeline-raw/settlement-seed.ndjson`` so the Director V2 acceptance
report reflects blackboard truth.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.redis_client import RedisClient  # noqa: E402
from core.redis_keys import ScopedRedis  # noqa: E402
from core.shared_state import SettlementObjective, SharedWorkingState  # noqa: E402
from core.simulation.settlement_objectives import (  # noqa: E402
    _env_enabled,
    _settlement_objective_descriptions,
    _settlement_objective_payload,
    _settlement_owner_order,
    _settlement_plan_build_owner_allowlist,
)

SEED_EVENT_TYPE = "settlement_objective.seeded"
SEED_TIMELINE_FILENAME = "settlement-seed.ndjson"


def should_seed(env: dict[str, str] | None = None) -> bool:
    """Return True only for settlement runs with shared state enabled."""

    source = env if env is not None else os.environ
    if source.get("MC_SIM_BUILD_MODE") != "settlement":
        return False
    return _env_enabled(source.get("MC_SIM_SHARED_STATE_ENABLED"), default=True)


def require_simulation_id(env: dict[str, str] | None = None) -> uuid.UUID:
    """Resolve the shared simulation scope, failing loudly when it is missing.

    The seed step and the launched bots MUST agree on a single ``LTAG_SIMULATION_ID``;
    otherwise the seed writes to a scope no bot ever reads.
    """

    source = env if env is not None else os.environ
    raw = (source.get("LTAG_SIMULATION_ID") or "").strip()
    if not raw:
        raise SystemExit(
            "seed_settlement_objectives: LTAG_SIMULATION_ID is required but unset. "
            "The seed step and every launched bot must share one explicit simulation scope."
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise SystemExit(
            f"seed_settlement_objectives: LTAG_SIMULATION_ID is not a valid UUID: {raw!r}"
        ) from exc


def build_objectives(env: dict[str, str] | None = None) -> list[SettlementObjective]:
    """Derive the ordered settlement objectives from the soak environment."""

    source = env if env is not None else os.environ
    descriptions = _settlement_objective_descriptions(source.get("MC_SIM_SETTLEMENT_OBJECTIVES"))
    if not descriptions:
        return []
    agents = (source.get("SOAK_BOTS") or "").split()
    owner_order = _settlement_owner_order(
        source.get("MC_SIM_SETTLEMENT_OWNER_ORDER"),
        agents,
        allowed_agents=_settlement_plan_build_owner_allowlist(source),
    )
    return [
        SettlementObjective(**_settlement_objective_payload(index, description, owner_order))
        for index, description in enumerate(descriptions)
    ]


def seed_timeline_event(objective: SettlementObjective, *, ts: str) -> dict:
    """Build one ``settlement_objective.seeded`` timeline event for an objective."""

    owner = objective.owner_agent_id or ""
    return {
        "ts": ts,
        "event_type": SEED_EVENT_TYPE,
        "agent": owner,
        "payload": {
            "objective_id": objective.objective_id,
            "phase_index": objective.phase_index,
            "phase_owner": owner,
            "owner": owner,
            "description": objective.description,
            "status": objective.status,
        },
    }


def write_seed_timeline(
    objectives: list[SettlementObjective],
    run_dir: str | os.PathLike[str] | None,
    *,
    ts: str,
) -> Path | None:
    """Append one seeded-objective timeline event per objective.

    The events land in ``<run_dir>/timeline-raw/<SEED_TIMELINE_FILENAME>`` which
    ``build_timeline.py`` picks up via its ``timeline-raw/*.ndjson`` glob. The
    end-of-soak timeline export rewrites ``timeline.ndjson`` from these raw files,
    so writing the canonical ``timeline.ndjson`` directly here would be clobbered.
    """

    if not run_dir:
        return None
    raw_dir = Path(run_dir) / "timeline-raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / SEED_TIMELINE_FILENAME
    with path.open("w", encoding="utf-8") as handle:
        for objective in objectives:
            handle.write(json.dumps(seed_timeline_event(objective, ts=ts)) + "\n")
    return path


async def seed_objectives(
    simulation_id: uuid.UUID,
    objectives: list[SettlementObjective],
    *,
    redis: RedisClient | None = None,
) -> None:
    """Write the objective board into the LTAG_SIMULATION_ID-scoped blackboard."""

    client = redis or RedisClient()
    owns_client = redis is None
    if owns_client:
        await client.connect()
    try:
        state = SharedWorkingState(ScopedRedis(client, simulation_id))
        await state.set_settlement_objectives(objectives)
    finally:
        if owns_client:
            await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    env = os.environ
    if not should_seed(env):
        return 0
    simulation_id = require_simulation_id(env)
    objectives = build_objectives(env)
    if not objectives:
        print(
            "seed_settlement_objectives: MC_SIM_SETTLEMENT_OBJECTIVES is empty; "
            "nothing to seed.",
            flush=True,
        )
        return 0
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    asyncio.run(seed_objectives(simulation_id, objectives))
    timeline_path = write_seed_timeline(objectives, env.get("MC_RUN_DIR"), ts=ts)
    print(
        f"seed_settlement_objectives: seeded {len(objectives)} objective(s) into "
        f"sim scope {simulation_id} (timeline={timeline_path})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

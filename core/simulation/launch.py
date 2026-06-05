"""Shared helpers for launching simulation subprocesses."""

from __future__ import annotations

import subprocess
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def build_run_simulation_command(
    *,
    project_root: str | Path,
    name: str,
    seed_file: str | Path,
    max_cost: float,
    sim_id: str | uuid.UUID,
    agents: Sequence[str] | None = None,
    run_config_file: str | Path | None = None,
) -> list[str]:
    """Build the canonical ``scripts/run_simulation.py`` command."""

    root = Path(project_root)
    cmd = [
        sys.executable,
        str(root / "scripts" / "run_simulation.py"),
        "--name",
        name,
        "--seed-file",
        str(seed_file),
        "--max-cost",
        str(max_cost),
        "--sim-id",
        str(sim_id),
    ]
    if agents is not None:
        cmd.extend(["--agents", ",".join(agents)])
    if run_config_file is not None:
        cmd.extend(["--run-config-file", str(run_config_file)])
    return cmd


def build_headless_simulation_command(
    *,
    project_root: str | Path,
    scenario: str | Path,
    name: str,
    max_cost: float,
    sim_id: str | uuid.UUID,
    seed: int | None = None,
) -> list[str]:
    """Build the canonical ``scripts/run_headless_sim.py`` command."""

    root = Path(project_root)
    cmd = [
        sys.executable,
        str(root / "scripts" / "run_headless_sim.py"),
        "--scenario",
        str(scenario),
        "--name",
        name,
        "--max-cost",
        str(max_cost),
        "--sim-id",
        str(sim_id),
    ]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    return cmd


def launch_detached(command: Sequence[str], *, cwd: str | Path) -> subprocess.Popen[Any]:
    """Launch a simulation command detached from the API process."""

    return subprocess.Popen(  # noqa: S603
        list(command),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(cwd),
    )

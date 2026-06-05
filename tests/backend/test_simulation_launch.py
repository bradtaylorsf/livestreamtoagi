"""Tests for shared simulation subprocess launch helpers."""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

from core.simulation.launch import (
    build_headless_simulation_command,
    build_run_simulation_command,
    launch_detached,
)


def test_build_run_simulation_command_includes_public_run_config_options(
    tmp_path: Path,
) -> None:
    sim_id = uuid.uuid4()
    command = build_run_simulation_command(
        project_root=tmp_path,
        name="public-smoke",
        seed_file=tmp_path / "scenarios" / "awakening.yaml",
        max_cost=0.5,
        sim_id=sim_id,
        agents=["vera", "rex"],
        run_config_file=tmp_path / "runs" / "run_config.json",
    )

    assert command == [
        sys.executable,
        str(tmp_path / "scripts" / "run_simulation.py"),
        "--name",
        "public-smoke",
        "--seed-file",
        str(tmp_path / "scenarios" / "awakening.yaml"),
        "--max-cost",
        "0.5",
        "--sim-id",
        str(sim_id),
        "--agents",
        "vera,rex",
        "--run-config-file",
        str(tmp_path / "runs" / "run_config.json"),
    ]


def test_build_headless_simulation_command_includes_optional_seed(tmp_path: Path) -> None:
    sim_id = uuid.uuid4()
    command = build_headless_simulation_command(
        project_root=tmp_path,
        scenario=tmp_path / "scenarios" / "smoke.yaml",
        name="headless-smoke",
        max_cost=1.0,
        sim_id=sim_id,
        seed=42,
    )

    assert command == [
        sys.executable,
        str(tmp_path / "scripts" / "run_headless_sim.py"),
        "--scenario",
        str(tmp_path / "scenarios" / "smoke.yaml"),
        "--name",
        "headless-smoke",
        "--max-cost",
        "1.0",
        "--sim-id",
        str(sim_id),
        "--seed",
        "42",
    ]


def test_launch_detached_uses_api_process_safe_subprocess_defaults(
    tmp_path: Path,
) -> None:
    with patch("subprocess.Popen") as popen:
        launch_detached(["python", "script.py"], cwd=tmp_path)

    popen.assert_called_once_with(
        ["python", "script.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(tmp_path),
    )

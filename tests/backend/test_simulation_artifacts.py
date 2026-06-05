"""Tests for shared simulation artifact path helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.simulation.artifacts import (
    build_sim_artifact_folder,
    headless_snapshots_dir,
    read_metadata,
    resolve_headless_sim_folder,
    write_metadata,
)


def test_headless_snapshots_dir_uses_project_relative_path(tmp_path: Path) -> None:
    assert headless_snapshots_dir(tmp_path) == tmp_path / "snapshots" / "headless"


def test_build_sim_artifact_folder_uses_timestamp_and_name(tmp_path: Path) -> None:
    folder = build_sim_artifact_folder(
        tmp_path,
        "headless-smoke",
        now=datetime(2026, 6, 5, 12, 30, 0, tzinfo=UTC),
    )

    assert folder == tmp_path / "20260605T123000Z_headless-smoke"
    assert folder.is_dir()


def test_metadata_round_trip_and_resolve_by_simulation_id(tmp_path: Path) -> None:
    folder = build_sim_artifact_folder(
        tmp_path,
        "headless-smoke",
        now=datetime(2026, 6, 5, 12, 30, 0, tzinfo=UTC),
    )
    path = write_metadata(folder, {"simulation_id": "sim-123", "name": "headless-smoke"})

    assert path == folder / "metadata.json"
    assert read_metadata(folder) == {"simulation_id": "sim-123", "name": "headless-smoke"}
    assert resolve_headless_sim_folder("sim-123", root=tmp_path) == folder


def test_resolve_headless_sim_folder_ignores_invalid_metadata(tmp_path: Path) -> None:
    bad = tmp_path / "20260605T123000Z_bad"
    bad.mkdir()
    (bad / "metadata.json").write_text("{not json", encoding="utf-8")
    direct = tmp_path / "sim-folder-name"
    direct.mkdir()

    assert resolve_headless_sim_folder("sim-folder-name", root=tmp_path) == direct

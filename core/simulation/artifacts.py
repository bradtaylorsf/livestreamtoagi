"""Shared helpers for simulation runtime artifact folders."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.observability.files import write_json_file

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HEADLESS_SNAPSHOTS_RELATIVE = Path("snapshots") / "headless"


def headless_snapshots_dir(project_root: str | Path | None = None) -> Path:
    """Return the root folder under which headless sim artifacts are written."""

    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    return root / HEADLESS_SNAPSHOTS_RELATIVE


def build_sim_artifact_folder(
    output_dir: str | Path,
    name: str,
    *,
    now: datetime | None = None,
) -> Path:
    """Create a timestamped simulation artifact folder under ``output_dir``."""

    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(output_dir).expanduser().resolve() / f"{timestamp}_{name}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_metadata(sim_folder: str | Path, payload: dict[str, Any]) -> Path:
    """Write a simulation artifact metadata file and return its path."""

    path = Path(sim_folder) / "metadata.json"
    return write_json_file(path, payload)


def read_metadata(sim_folder: str | Path) -> dict[str, Any] | None:
    """Read a simulation metadata file, returning None on missing/invalid data."""

    path = Path(sim_folder) / "metadata.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_headless_sim_folder(
    sim_id: str,
    *,
    root: str | Path | None = None,
) -> Path | None:
    """Find a headless sim folder by metadata simulation_id or folder name."""

    snapshots_root = Path(root) if root is not None else headless_snapshots_dir()
    if not snapshots_root.is_dir():
        return None
    for entry in sorted(snapshots_root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        meta = read_metadata(entry)
        if (meta and meta.get("simulation_id") == sim_id) or entry.name == sim_id:
            return entry
    return None

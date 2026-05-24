"""Typed loader for unified run-spec YAML/JSON files."""

from __future__ import annotations

from pathlib import Path

import yaml

from core.models import RunSpec


def load_run_spec(path: str | Path) -> RunSpec:
    """Load a run-spec mapping from YAML or JSON and validate it."""
    spec_path = Path(path)
    raw = yaml.safe_load(spec_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Run spec must be a mapping: {spec_path}")
    return RunSpec(**raw)

#!/usr/bin/env python3
"""Validate scenario YAML files against the canonical schema.

Usage:
    python scripts/validate_scenario.py scenarios/awakening.yaml
    python scripts/validate_scenario.py 'scenarios/*.yaml'
    python scripts/validate_scenario.py --strict scenarios/*.yaml

Exit code is non-zero if any file fails. With ``--strict``, files that
validate but are missing an ``eval_targets`` block also fail.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path
from typing import Sequence

# Ensure project root is importable when invoked as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from core.simulation.scenario_schema import validate_scenario_dict  # noqa: E402


def _expand(paths: Sequence[str]) -> list[Path]:
    """Expand shell globs and return existing paths."""
    expanded: list[Path] = []
    for raw in paths:
        matches = sorted(glob.glob(raw))
        if not matches and Path(raw).exists():
            matches = [raw]
        for m in matches:
            p = Path(m)
            if p.is_file():
                expanded.append(p)
    return expanded


def _validate_one(path: Path, *, strict: bool) -> tuple[bool, str]:
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        return False, f"yaml parse error: {exc}"

    if not isinstance(data, dict):
        return False, "top-level YAML must be a mapping"

    try:
        scenario = validate_scenario_dict(data)
    except ValidationError as exc:
        return False, f"schema error:\n{exc}"
    except ValueError as exc:
        return False, f"schema error: {exc}"

    if strict and scenario.eval_targets is None:
        return False, "missing eval_targets block (--strict)"

    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="+", help="Scenario YAML files or shell globs"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also fail when a scenario is missing an eval_targets block",
    )
    args = parser.parse_args(argv)

    paths = _expand(args.paths)
    if not paths:
        print("no matching files", file=sys.stderr)
        return 2

    failures = 0
    for path in paths:
        ok, msg = _validate_one(path, strict=args.strict)
        if ok:
            print(f"OK    {path}")
        else:
            failures += 1
            print(f"FAIL  {path}: {msg}", file=sys.stderr)

    if failures:
        print(f"\n{failures} of {len(paths)} scenario(s) failed", file=sys.stderr)
        return 1
    print(f"\nall {len(paths)} scenario(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Create collaborative build-mode artifacts for existing headless BuildScripts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.minecraft.build_script import BuildScript  # noqa: E402
from core.minecraft.collaborative_build import (  # noqa: E402
    DEFAULT_MAX_BUILDER_COMMANDS,
    load_collaborative_build_ledger,
    roster_from_env,
    write_collaborative_build,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    sim_folder = Path(args.sim_folder).expanduser().resolve()
    if not sim_folder.is_dir():
        parser.error(f"--sim-folder not found: {sim_folder}")
    scripts = _select_scripts(sim_folder, intent_id=args.intent_id)
    if not scripts:
        parser.error(f"no BuildScript files found under {sim_folder / 'build_scripts'}")

    roster = roster_from_env()
    ledgers = []
    for script_path in scripts:
        script = BuildScript.model_validate(json.loads(script_path.read_text(encoding="utf-8")))
        ledger = write_collaborative_build(
            script,
            sim_folder=sim_folder,
            source_script_path=script_path,
            roster=roster,
            max_builder_commands=args.max_builder_commands,
        )
        ledgers.append(ledger)

    for ledger in ledgers:
        ledger_path = sim_folder / "collaborative_builds" / ledger.source_intent_id / "ledger.json"
        loaded = load_collaborative_build_ledger(ledger_path)
        builder_jobs = [job for job in loaded.jobs if job.role == "builder"]
        print(
            f"collaborative build artifacts: {loaded.source_intent_id} "
            f"jobs={len(loaded.jobs)} builder_jobs={len(builder_jobs)} "
            f"ledger={ledger_path}"
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split existing BuildScripts into role-based collaborative build jobs.",
    )
    parser.add_argument("--sim-folder", required=True, help="Headless sim folder")
    parser.add_argument(
        "--intent-id",
        default=None,
        help="Only process one BuildScript intent id (default: all scripts)",
    )
    parser.add_argument(
        "--max-builder-commands",
        type=int,
        default=DEFAULT_MAX_BUILDER_COMMANDS,
        help="Maximum compiled commands per builder job script",
    )
    return parser


def _select_scripts(sim_folder: Path, *, intent_id: str | None) -> list[Path]:
    scripts_dir = sim_folder / "build_scripts"
    if intent_id:
        target = scripts_dir / f"{intent_id}.script.json"
        return [target] if target.is_file() else []
    return sorted(scripts_dir.glob("*.script.json"))


if __name__ == "__main__":
    raise SystemExit(main())

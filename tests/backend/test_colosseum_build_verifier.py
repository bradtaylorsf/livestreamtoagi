"""Tests for the Roman Colosseum blueprint verifier."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from core.agents.build_intent import BuildIntent
from core.minecraft.build_plan_catalog import StaticBuildPlanCatalog
from core.minecraft.build_plan_compiler import BuildPlanCompiler
from scripts.minecraft.verify_colosseum_build import (
    BLUEPRINT_SPEC,
    build_world,
    compare_build,
    render_topdown,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT = REPO_ROOT / "building" / "blueprints" / "roman-colosseum.png"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _utterance(actor: str, text: str, tick: int) -> dict:
    return {
        "event_type": "utterance",
        "tick": tick,
        "wall_time": datetime.now(UTC).isoformat(),
        "actor_id": actor,
        "payload": {"text": text},
    }


def test_colosseum_catalog_build_passes_blueprint_verifier(tmp_path: Path) -> None:
    catalog = StaticBuildPlanCatalog()
    plan = catalog.get("coliseum")
    assert plan is not None

    intent = BuildIntent(
        proposer_id="rex",
        structure_type="coliseum",
        size_class="epic",
        location_intent="open_area",
        motivation="Build the Roman Colosseum from the supplied blueprint.",
        reference_image_id=str(BLUEPRINT),
    )
    script = BuildPlanCompiler().compile(plan, intent=intent)
    scripts_dir = tmp_path / "build_scripts"
    scripts_dir.mkdir()
    (scripts_dir / f"{intent.intent_id}.script.json").write_text(
        json.dumps(script.to_jsonable(), sort_keys=True),
        encoding="utf-8",
    )
    _write_jsonl(
        tmp_path / "build_intents.jsonl",
        [
            {
                "intent_id": intent.intent_id,
                "actor_id": "rex",
                "submitted_at": 1.0,
                "args": intent.to_log_payload(),
            }
        ],
    )
    _write_jsonl(
        tmp_path / "decision_log.jsonl",
        [
            _utterance("vera", "Rex owns the build; I will track dimensions.", 1),
            _utterance("aurora", "Materials: sandstone walls and stone-brick base.", 2),
            _utterance("fork", "I will review gates, arena, arches, and seats.", 3),
        ],
    )

    world = build_world(script)
    metrics = compare_build(sim_folder=tmp_path, blueprint=BLUEPRINT, script=script, world=world)
    assert all(metric.passed for metric in metrics), [
        (metric.name, metric.expected, metric.actual) for metric in metrics if not metric.passed
    ]
    assert script.total_blocks > BLUEPRINT_SPEC["width"] * BLUEPRINT_SPEC["depth"]

    photo = render_topdown(world, tmp_path / "photo.png", scale=2)
    assert photo.is_file()

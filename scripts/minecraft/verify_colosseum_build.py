#!/usr/bin/env python3
"""Verify a Roman Colosseum headless build against the supplied blueprint.

The live screenshot path is useful when BlueMap or a Minecraft camera bridge
is available, but the acceptance harness needs deterministic evidence even
when those services are not. This script replays the compiled BuildScript into
an in-memory block map, renders a top-down "photo", and compares the resulting
structure to the key specs visible in ``building/blueprints/roman-colosseum.png``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from core.minecraft.build_script import BuildCommand, BuildScript  # noqa: E402

BLUEPRINT_SPEC = {
    "width": 120,
    "depth": 100,
    "height": 42,
    "arena_width": 56,
    "arena_depth": 36,
    "arch_tiers": 4,
    "seat_rows": 24,
    "main_gates": 4,
}

MATERIAL_COLORS = {
    "air": (8, 16, 26),
    "sand": (199, 174, 111),
    "stone_bricks": (94, 101, 106),
    "chiseled_stone_bricks": (118, 124, 128),
    "polished_andesite": (144, 148, 147),
    "smooth_sandstone": (188, 167, 118),
    "smooth_sandstone_stairs": (170, 145, 93),
    "smooth_sandstone_slab": (211, 191, 144),
    "lantern": (238, 169, 64),
}

World = dict[tuple[int, int, int], str]


@dataclass
class Metric:
    name: str
    passed: bool
    expected: Any
    actual: Any
    details: str = ""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            rows.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return rows


def _load_coliseum_script(
    sim_folder: Path, blueprint: Path | None = None
) -> tuple[BuildScript, Path]:
    scripts_dir = sim_folder / "build_scripts"
    if not scripts_dir.is_dir():
        raise FileNotFoundError(f"build_scripts directory not found: {scripts_dir}")
    preferred_ids = _preferred_intent_ids(sim_folder, blueprint) if blueprint is not None else set()
    candidates = sorted(
        scripts_dir.glob("*.script.json"),
        key=lambda path: (path.stem.removesuffix(".script") not in preferred_ids, path.name),
    )
    for path in candidates:
        payload = json.loads(path.read_text(encoding="utf-8"))
        script = BuildScript.model_validate(payload)
        structure = getattr(script.structure_type, "value", script.structure_type)
        if structure == "coliseum":
            return script, path
    raise FileNotFoundError(f"no coliseum BuildScript found under {scripts_dir}")


def _preferred_intent_ids(sim_folder: Path, blueprint: Path | None) -> set[str]:
    if blueprint is None:
        return set()
    expected = str(blueprint)
    preferred: set[str] = set()
    for row in _load_jsonl(sim_folder / "build_intents.jsonl"):
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        ref = str(args.get("reference_image_id", ""))
        if ref == expected or ref.endswith(blueprint.name):
            intent_id = row.get("intent_id") or args.get("intent_id")
            if intent_id:
                preferred.add(str(intent_id))
    return preferred


def _coord_range(a: int, b: int) -> range:
    return range(min(a, b), max(a, b) + 1)


def _apply_command(world: World, command: BuildCommand) -> None:
    if command.kind == "wait":
        return
    if command.kind == "structure":
        block_type = command.structure_id or command.block_type or "structure_block"
        pos = command.position
        world[(pos.x, pos.y, pos.z)] = block_type
        return
    if command.kind == "setblock":
        positions = [(command.position.x, command.position.y, command.position.z)]
    elif command.kind == "fill":
        end = command.region_to or command.position
        positions = [
            (x, y, z)
            for x in _coord_range(command.position.x, end.x)
            for y in _coord_range(command.position.y, end.y)
            for z in _coord_range(command.position.z, end.z)
        ]
    else:
        return

    block_type = command.block_type or "air"
    if block_type == "air":
        for pos in positions:
            world.pop(pos, None)
        return
    for pos in positions:
        world[pos] = block_type


def build_world(script: BuildScript) -> World:
    world: World = {}
    for command in script.commands:
        _apply_command(world, command)
    return world


def _world_extents(world: World) -> tuple[int, int, int, int, int, int]:
    if not world:
        raise ValueError("world is empty after applying BuildScript")
    xs = [pos[0] for pos in world]
    ys = [pos[1] for pos in world]
    zs = [pos[2] for pos in world]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _block_counts(world: World) -> Counter[str]:
    return Counter(world.values())


def _sand_floor_bbox(world: World, floor_y: int) -> tuple[int, int] | None:
    cells = [(x, z) for (x, y, z), block in world.items() if y == floor_y and block == "sand"]
    if not cells:
        return None
    xs = [x for x, _ in cells]
    zs = [z for _, z in cells]
    return max(xs) - min(xs) + 1, max(zs) - min(zs) + 1


def _air_command_dims(command: BuildCommand) -> tuple[int, int, int]:
    end = command.region_to or command.position
    dx = abs(end.x - command.position.x) + 1
    dy = abs(end.y - command.position.y) + 1
    dz = abs(end.z - command.position.z) + 1
    return dx, dy, dz


def _opening_metrics(script: BuildScript) -> tuple[int, int, int]:
    arch_openings = 0
    gate_openings = 0
    arch_levels: set[int] = set()
    floor_y = script.origin.y
    for command in script.commands:
        if command.block_type != "air":
            continue
        dx, dy, dz = _air_command_dims(command)
        horizontal_span = max(dx, dz)
        if command.position.y <= floor_y + 1 and dy >= 10 and horizontal_span >= 9:
            gate_openings += 1
            continue
        if dy >= 5 and horizontal_span >= 4:
            arch_openings += 1
            arch_levels.add(command.position.y)
    return arch_openings, len(arch_levels), gate_openings


def _seat_rows(script: BuildScript) -> int:
    rows: set[int] = set()
    for command in script.commands:
        if command.block_type != "smooth_sandstone_stairs":
            continue
        rows.add(command.position.y)
    return len(rows)


def _reference_image_ok(sim_folder: Path, blueprint: Path) -> tuple[bool, list[str]]:
    expected = str(blueprint)
    matches: list[str] = []
    for row in _load_jsonl(sim_folder / "build_intents.jsonl"):
        args = row.get("args") if isinstance(row.get("args"), dict) else {}
        ref = str(args.get("reference_image_id", ""))
        if ref:
            matches.append(ref)
        if ref == expected or ref.endswith(blueprint.name):
            return True, matches
    return False, matches


def _coordination_metrics(sim_folder: Path) -> tuple[int, int]:
    speakers: set[str] = set()
    role_hits = 0
    terms = (
        "claim",
        "owner",
        "build",
        "review",
        "check",
        "scout",
        "materials",
        "gate",
        "arena",
        "arches",
    )
    for row in _load_jsonl(sim_folder / "decision_log.jsonl"):
        if row.get("event_type") != "utterance":
            continue
        actor = row.get("actor_id")
        if actor:
            speakers.add(str(actor))
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        text = str(payload.get("text") or payload.get("dialogue") or "").lower()
        if any(term in text for term in terms):
            role_hits += 1
    return len(speakers), role_hits


def compare_build(
    *,
    sim_folder: Path,
    blueprint: Path,
    script: BuildScript,
    world: World,
) -> list[Metric]:
    min_x, min_y, min_z, max_x, max_y, max_z = _world_extents(world)
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    depth = max_z - min_z + 1
    counts = _block_counts(world)
    arena_dims = _sand_floor_bbox(world, script.origin.y)
    arch_openings, arch_tiers, gates = _opening_metrics(script)
    seat_rows = _seat_rows(script)
    reference_ok, refs = _reference_image_ok(sim_folder, blueprint)
    speaker_count, role_hits = _coordination_metrics(sim_folder)

    metrics = [
        Metric("overall_width", width == BLUEPRINT_SPEC["width"], BLUEPRINT_SPEC["width"], width),
        Metric("overall_depth", depth == BLUEPRINT_SPEC["depth"], BLUEPRINT_SPEC["depth"], depth),
        Metric(
            "overall_height",
            height == BLUEPRINT_SPEC["height"],
            BLUEPRINT_SPEC["height"],
            height,
        ),
        Metric(
            "arena_floor",
            arena_dims == (BLUEPRINT_SPEC["arena_width"], BLUEPRINT_SPEC["arena_depth"]),
            [BLUEPRINT_SPEC["arena_width"], BLUEPRINT_SPEC["arena_depth"]],
            list(arena_dims) if arena_dims else None,
        ),
        Metric(
            "arch_tiers",
            arch_tiers == BLUEPRINT_SPEC["arch_tiers"],
            BLUEPRINT_SPEC["arch_tiers"],
            arch_tiers,
            f"{arch_openings} arcade openings carved",
        ),
        Metric(
            "main_gates", gates == BLUEPRINT_SPEC["main_gates"], BLUEPRINT_SPEC["main_gates"], gates
        ),
        Metric(
            "seat_rows",
            seat_rows == BLUEPRINT_SPEC["seat_rows"],
            BLUEPRINT_SPEC["seat_rows"],
            seat_rows,
        ),
        Metric(
            "materials",
            all(counts.get(material, 0) > 0 for material in _required_materials()),
            sorted(_required_materials()),
            {material: counts.get(material, 0) for material in sorted(_required_materials())},
        ),
        Metric(
            "reference_image",
            reference_ok,
            str(blueprint),
            refs,
            "BuildIntent should preserve the source blueprint path.",
        ),
        Metric(
            "agent_coordination",
            speaker_count >= 3 and role_hits >= 2,
            {"speakers": ">=3", "role_or_spec_utterances": ">=2"},
            {"speakers": speaker_count, "role_or_spec_utterances": role_hits},
        ),
    ]
    return metrics


def _required_materials() -> set[str]:
    return {
        "sand",
        "stone_bricks",
        "smooth_sandstone",
        "smooth_sandstone_stairs",
        "chiseled_stone_bricks",
        "polished_andesite",
    }


def _top_blocks(world: World) -> dict[tuple[int, int], tuple[int, str]]:
    top: dict[tuple[int, int], tuple[int, str]] = {}
    for (x, y, z), block in world.items():
        key = (x, z)
        current = top.get(key)
        if current is None or y > current[0]:
            top[key] = (y, block)
    return top


def render_topdown(world: World, output_path: Path, *, scale: int = 8) -> Path:
    min_x, min_y, min_z, max_x, max_y, max_z = _world_extents(world)
    width = max_x - min_x + 1
    depth = max_z - min_z + 1
    image = Image.new("RGB", (width * scale, depth * scale), (8, 16, 26))
    draw = ImageDraw.Draw(image)
    for (x, z), (y, block) in _top_blocks(world).items():
        base = MATERIAL_COLORS.get(block, (180, 180, 180))
        shade = 0.78 + 0.22 * ((y - min_y) / max(1, max_y - min_y))
        color = tuple(min(255, int(channel * shade)) for channel in base)
        px = (x - min_x) * scale
        pz = (z - min_z) * scale
        draw.rectangle((px, pz, px + scale - 1, pz + scale - 1), fill=color)

    draw.rectangle((0, 0, image.width - 1, image.height - 1), outline=(230, 230, 220), width=2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def render_comparison(
    *,
    blueprint: Path,
    build_photo: Path,
    output_path: Path,
    metrics: list[Metric],
) -> Path:
    blueprint_img = Image.open(blueprint).convert("RGB")
    build_img = Image.open(build_photo).convert("RGB")
    target_h = 720
    blueprint_img.thumbnail((900, target_h), Image.Resampling.LANCZOS)
    build_img.thumbnail((900, target_h), Image.Resampling.NEAREST)

    summary_h = 180
    pad = 24
    width = blueprint_img.width + build_img.width + pad * 3
    height = max(blueprint_img.height, build_img.height) + summary_h + pad * 3
    canvas = Image.new("RGB", (width, height), (10, 22, 34))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    draw.text((pad, pad), "Blueprint", fill=(230, 240, 245), font=font)
    draw.text(
        (pad * 2 + blueprint_img.width, pad),
        "Built block-map photo",
        fill=(230, 240, 245),
        font=font,
    )
    canvas.paste(blueprint_img, (pad, pad + 18))
    canvas.paste(build_img, (pad * 2 + blueprint_img.width, pad + 18))

    y = max(blueprint_img.height, build_img.height) + pad * 2 + 24
    passed = sum(1 for metric in metrics if metric.passed)
    draw.text(
        (pad, y),
        f"Verification: {passed}/{len(metrics)} checks passed",
        fill=(118, 224, 151) if passed == len(metrics) else (244, 183, 90),
        font=font,
    )
    y += 18
    for metric in metrics[:8]:
        status = "PASS" if metric.passed else "FAIL"
        draw.text(
            (pad, y),
            f"{status} {metric.name}: expected {metric.expected}, actual {metric.actual}",
            fill=(205, 216, 220),
            font=font,
        )
        y += 16

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


def write_reports(
    *,
    sim_folder: Path,
    blueprint: Path,
    script_path: Path,
    build_photo: Path,
    comparison: Path,
    metrics: list[Metric],
    output_dir: Path,
) -> tuple[Path, Path]:
    passed = all(metric.passed for metric in metrics)
    payload = {
        "passed": passed,
        "sim_folder": str(sim_folder),
        "blueprint": str(blueprint),
        "script": str(script_path),
        "build_photo": str(build_photo),
        "comparison_image": str(comparison),
        "spec": BLUEPRINT_SPEC,
        "metrics": [asdict(metric) for metric in metrics],
    }
    json_path = output_dir / "colosseum-verification.json"
    md_path = output_dir / "colosseum-verification.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Roman Colosseum Build Verification",
        "",
        f"Status: {'PASS' if passed else 'FAIL'}",
        "",
        f"- Blueprint: `{blueprint}`",
        f"- BuildScript: `{script_path}`",
        f"- Build photo: `{build_photo}`",
        f"- Comparison image: `{comparison}`",
        "",
        "## Checks",
        "",
    ]
    for metric in metrics:
        status = "PASS" if metric.passed else "FAIL"
        detail = f" - {metric.details}" if metric.details else ""
        lines.append(
            f"- {status} `{metric.name}`: expected `{metric.expected}`, "
            f"actual `{metric.actual}`{detail}"
        )
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def run(args: argparse.Namespace) -> int:
    sim_folder = Path(args.sim_folder).resolve()
    blueprint = Path(args.blueprint).resolve()
    if not blueprint.is_file():
        raise FileNotFoundError(f"blueprint not found: {blueprint}")
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else sim_folder / "colosseum-verification"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    script, script_path = _load_coliseum_script(sim_folder, blueprint)
    world = build_world(script)
    metrics = compare_build(sim_folder=sim_folder, blueprint=blueprint, script=script, world=world)
    build_photo = render_topdown(world, output_dir / "colosseum-build-photo.png")
    comparison = render_comparison(
        blueprint=blueprint,
        build_photo=build_photo,
        output_path=output_dir / "colosseum-comparison.png",
        metrics=metrics,
    )
    json_path, md_path = write_reports(
        sim_folder=sim_folder,
        blueprint=blueprint,
        script_path=script_path,
        build_photo=build_photo,
        comparison=comparison,
        metrics=metrics,
        output_dir=output_dir,
    )
    print(f"colosseum verification: {'PASS' if all(m.passed for m in metrics) else 'FAIL'}")
    print(f"json: {json_path}")
    print(f"report: {md_path}")
    print(f"photo: {build_photo}")
    print(f"comparison: {comparison}")
    return 0 if all(m.passed for m in metrics) or not args.strict else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim-folder", required=True)
    parser.add_argument(
        "--blueprint",
        default=str(PROJECT_ROOT / "building" / "blueprints" / "roman-colosseum.png"),
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return run(_build_parser().parse_args(argv))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Live smoke for the propose_new_building pipeline (issue #861).

Exercises the cloud chain end-to-end:

1. Generate a blueprint image via OpenAI ``gpt-image-2``.
2. Decompose the image into a ``BuildPlan`` via Gemini 3.5 Flash structured JSON.
3. Compile the ``BuildPlan`` into a deterministic ``BuildScript``.

The compiler is the same one the embodied executor uses to drive Mindcraft, so
a successful run confirms the full image → blueprint → Minecraft path works.

Defaults are conservative ($0.05 total cap) so the smoke is cheap. Pass
``--prompt`` to test custom concepts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from core.minecraft.build_plan import (
    BuildPlan,
    Position3D,
)
from core.minecraft.build_plan_compiler import BuildPlanCompiler
from core.minecraft.cloud_providers import (
    GeminiVisionDecomposer,
    OpenAIImageProvider,
)

DEFAULT_CONCEPT = "Roman Watchtower with Crenellated Battlements"


async def run(prompt: str, output_dir: Path, structure_type: str, size_class: str) -> None:
    print(f"[1/3] generating image via {OpenAIImageProvider.model_id}...")
    print(f"      prompt ({len(prompt)} chars):")
    for line in prompt.splitlines():
        print(f"        {line}")
    img_provider = OpenAIImageProvider()
    image_bytes = await img_provider.generate(prompt)
    image_path = output_dir / "blueprint.png"
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(image_bytes)
    print(f"    saved {len(image_bytes)} bytes -> {image_path}")

    print(f"[2/3] decomposing via {GeminiVisionDecomposer.model_id}...")
    decomposer = GeminiVisionDecomposer()
    intent_hints = {
        "concept": prompt,
        "structure_type": structure_type,
        "size_class": size_class,
        "source_image_id": "smoke:blueprint.png",
    }
    plan_dict = await decomposer.decompose_bytes(
        image_bytes=image_bytes,
        intent_hints=intent_hints,
        structure_type=structure_type,
        size_class=size_class,
    )
    plan_dict.setdefault("source_image_id", "smoke:blueprint.png")
    plan_path = output_dir / "build_plan.json"
    plan_path.write_text(json.dumps(plan_dict, indent=2))
    print(f"    saved BuildPlan -> {plan_path}")

    try:
        plan = BuildPlan.model_validate(plan_dict)
    except Exception as exc:
        print(f"    ✗ BuildPlan validation failed: {exc}", file=sys.stderr)
        print("    raw decomposer output kept at build_plan.json for inspection.")
        sys.exit(1)
    st = getattr(plan.structure_type, "value", plan.structure_type)
    sc = getattr(plan.size_class, "value", plan.size_class)
    print(
        f"    plan ok: structure={st} size={sc} "
        f"footprint={plan.footprint.bbox.w}x{plan.footprint.bbox.h} "
        f"levels={len(plan.levels)} materials={len(plan.materials)} "
        f"key_features={len(plan.key_features)}"
    )

    print("[3/3] compiling BuildPlan -> Minecraft script...")
    compiler = BuildPlanCompiler()
    script = compiler.compile(
        plan,
        intent_id="smoke-propose-new-building",
        origin=Position3D(x=0, y=64, z=0),
        seed=42,
    )
    script_path = output_dir / "build_script.json"
    script_path.write_text(script.model_dump_json(indent=2))
    print(
        f"    script ok: {len(script.commands)} commands, "
        f"{script.total_blocks} blocks, ~{script.estimated_seconds:.1f}s build, "
        f"materials={script.materials_manifest}"
    )
    print(f"    saved BuildScript -> {script_path}")

    estimated_cost = float(img_provider.cost_per_call) + float(decomposer.cost_per_call)
    print()
    print("PASS: end-to-end image -> BuildPlan -> Minecraft script")
    print(f"      estimated cost: ${estimated_cost:.3f}")
    print(f"      artifacts in: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--concept",
        default=DEFAULT_CONCEPT,
        help="Short noun phrase fed to the BlueprintGenerator template.",
    )
    parser.add_argument("--vibe", default="medieval")
    parser.add_argument("--biome-fit", default="plains")
    parser.add_argument(
        "--prompt", default=None, help="Override the generated prompt (for ad-hoc testing)."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("snapshots/smoke-propose-new-building"),
    )
    parser.add_argument("--structure-type", default="watchtower")
    parser.add_argument("--size-class", default="medium")
    parser.add_argument(
        "--motivation",
        default="Smoke test of the cloud refinement chain.",
    )
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set in environment.")
    if not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("GOOGLE_API_KEY not set in environment.")

    if args.prompt is None:
        from core.agents.new_building_intent import NewBuildingIntent
        from core.minecraft.blueprint_generator import build_image_prompt

        intent = NewBuildingIntent(
            intent_id="smoke-newbuild",
            proposer_id="aurora",
            concept=args.concept,
            intended_use="Smoke-testing the Minecraft technical-blueprint pipeline.",
            vibe=args.vibe,
            size_class=args.size_class,
            biome_fit=args.biome_fit,
            motivation=args.motivation,
        )
        prompt = build_image_prompt(intent)
    else:
        prompt = args.prompt

    asyncio.run(run(prompt, args.output_dir, args.structure_type, args.size_class))


if __name__ == "__main__":
    main()

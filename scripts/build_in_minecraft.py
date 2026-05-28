"""Generate a blueprint and build it in a live Minecraft world.

Runs the full E22-11 cloud chain from the CLI:

  concept → gpt-image-2 image → gemini-3.5-flash BuildPlan →
  BuildPlanCompiler BuildScript → HttpBridgeClient → /fill commands in MC

Pre-conditions
--------------
* ``OPENAI_API_KEY`` and ``GOOGLE_API_KEY`` in env (for gpt-image-2 + Gemini).
* For ``--live`` mode (default):
  - A Minecraft 1.21.6 server on localhost:25565 (e.g. ``scripts/minecraft/start-server.sh``).
  - The FastAPI backend running with the Minecraft bridge endpoint enabled
    (``pnpm dev`` boots it on http://127.0.0.1:8010).
  - A Mindcraft bridge bot connected (``scripts/minecraft/connect-bridge-bot.sh``).
  - Env: ``MC_EVAL_LIVE_BRIDGE_URL`` and ``MINECRAFT_BRIDGE_TOKEN``.
* For ``--dry-run`` mode: nothing — prints the /fill commands without sending.

Examples
--------
    # Dry run — prints the prompt + commands without touching Minecraft.
    .venv/bin/python scripts/build_in_minecraft.py \\
        --concept "Stone Watchtower" --vibe gothic --size-class medium \\
        --biome-fit plains --dry-run

    # Live build at the origin (0,64,0) on the connected server.
    MC_EVAL_LIVE_BRIDGE_URL=http://127.0.0.1:8010/api/minecraft/bridge/command \\
    MINECRAFT_BRIDGE_TOKEN=... \\
        .venv/bin/python scripts/build_in_minecraft.py \\
            --concept "Stone Watchtower" --vibe gothic --size-class medium \\
            --biome-fit plains --origin 100,72,100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from core.agents.new_building_intent import NewBuildingIntent
from core.minecraft.blueprint_generator import build_image_prompt
from core.minecraft.build_executors import command_to_minecraft as _command_to_minecraft
from core.minecraft.build_plan import BuildPlan, Position3D
from core.minecraft.build_plan_compiler import BuildPlanCompiler
from core.minecraft.build_script import BuildScript
from core.minecraft.cloud_providers import (
    GeminiVisionDecomposer,
    OpenAIImageProvider,
)


def _parse_origin(raw: str) -> Position3D:
    try:
        parts = [int(x.strip()) for x in raw.split(",")]
        if len(parts) != 3:
            raise ValueError("expected x,y,z")
        return Position3D(x=parts[0], y=parts[1], z=parts[2])
    except Exception as exc:  # noqa: BLE001 — argparse error path
        raise argparse.ArgumentTypeError(f"--origin must be x,y,z (got {raw!r}): {exc}") from exc


async def _generate(
    intent: NewBuildingIntent,
    output_dir: Path,
    origin: Position3D,
) -> tuple[BuildScript, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_image_prompt(intent)
    (output_dir / "prompt.txt").write_text(prompt)
    print(f"[1/3] generating image via {OpenAIImageProvider.model_id}...")
    img_provider = OpenAIImageProvider()
    image_bytes = await img_provider.generate(prompt)
    image_path = output_dir / "blueprint.png"
    image_path.write_bytes(image_bytes)
    print(f"      saved {len(image_bytes):,} bytes → {image_path}")

    print(f"[2/3] decomposing via {GeminiVisionDecomposer.model_id}...")
    decomposer = GeminiVisionDecomposer()
    plan_dict = await decomposer.decompose_bytes(
        image_bytes=image_bytes,
        intent_hints={
            "concept": intent.concept,
            "structure_type": "watchtower",
            "size_class": intent.size_class,
            "source_image_id": f"build:{image_path.name}",
        },
        structure_type="watchtower",
        size_class=intent.size_class,
    )
    plan_dict.setdefault("source_image_id", f"build:{image_path.name}")
    (output_dir / "build_plan.json").write_text(json.dumps(plan_dict, indent=2))
    plan = BuildPlan.model_validate(plan_dict)
    print(
        f"      plan ok: footprint={plan.footprint.bbox.w}×{plan.footprint.bbox.h}, "
        f"levels={len(plan.levels)}, materials={len(plan.materials)}, "
        f"key_features={len(plan.key_features)}"
    )

    print("[3/3] compiling BuildPlan → Minecraft script...")
    compiler = BuildPlanCompiler()
    script = compiler.compile(
        plan,
        intent_id=intent.intent_id,
        origin=origin,
        seed=42,
    )
    script_path = output_dir / "build_script.json"
    script_path.write_text(script.model_dump_json(indent=2))
    print(
        f"      script ok: {len(script.commands)} commands, "
        f"{script.total_blocks:,} blocks, "
        f"~{script.estimated_seconds:.1f}s estimated build, "
        f"materials={dict(script.materials_manifest)}"
    )
    return script, output_dir


async def _send_live(script: BuildScript, *, throttle_ms: int = 60) -> tuple[int, int]:
    """Send every BuildCommand to the live Minecraft bridge (HTTP bridge mode)."""
    from core.minecraft.eval.live_cli import HttpBridgeClient, LiveBridgeConfigError

    url = os.environ.get("MC_EVAL_LIVE_BRIDGE_URL")
    token = os.environ.get("MINECRAFT_BRIDGE_TOKEN")
    if not url or not token:
        raise LiveBridgeConfigError(
            "live build requires MC_EVAL_LIVE_BRIDGE_URL and MINECRAFT_BRIDGE_TOKEN. "
            "Either set both or pass --dry-run or --rcon-host."
        )

    client = HttpBridgeClient(url, token)
    sent = 0
    skipped = 0
    for cmd in script.commands:
        if cmd.kind == "wait":
            await asyncio.sleep(cmd.wait_seconds or 0.0)
            continue
        text = _command_to_minecraft(cmd)
        if text is None:
            skipped += 1
            continue
        try:
            await client.send_command(text)
            sent += 1
            if throttle_ms:
                await asyncio.sleep(throttle_ms / 1000.0)
        except Exception as exc:  # noqa: BLE001 — surface every send error
            print(f"      ✗ command {sent + skipped + 1} failed: {exc}", file=sys.stderr)
            skipped += 1
    return sent, skipped


async def _send_rcon(
    script: BuildScript,
    *,
    host: str,
    port: int,
    password: str,
    throttle_ms: int = 30,
    auto_ground: bool = True,
    foundation: str = "cobblestone",
) -> tuple[int, int, BuildScript]:
    """Send every BuildCommand directly to the Minecraft server via RCON.

    Simpler than the bridge path: no bot needed, just the server with
    ``enable-rcon=true`` and a password. Commands are sent without the
    leading ``/`` (the RCON protocol takes them bare).

    When ``auto_ground`` is True we query the world via the same RCON
    connection to find the highest non-air block at the origin column,
    shift the script's y so the build sits on terrain, and prepend a
    cobblestone foundation pillar so steep terrain doesn't leave the
    build hanging over a cliff. Returns the (possibly shifted) script as
    the third tuple element so callers can report the resolved y.
    """
    from core.minecraft.build_executors import async_safe_mcrcon_class
    from core.minecraft.terrain import auto_ground_script, make_rcon_block_matcher

    MCRcon = async_safe_mcrcon_class()

    sent = 0
    skipped = 0
    final_script = script
    with MCRcon(host, password, port=port, timeout=10) as mcr:
        foundation_cmds: list[str] = []
        if auto_ground:
            matcher = make_rcon_block_matcher(mcr)
            final_script, foundation_cmds = auto_ground_script(
                script, matcher, foundation=foundation
            )
            if final_script.origin.y != script.origin.y:
                print(
                    f"      auto-ground: y {script.origin.y} → {final_script.origin.y} "
                    f"(+{len(foundation_cmds)} foundation /fill commands)"
                )

        for foundation_cmd in foundation_cmds:
            cmd_text = (
                foundation_cmd[1:] if foundation_cmd.startswith("/") else foundation_cmd
            )
            try:
                resp = mcr.command(cmd_text)
                sent += 1
                if resp and "error" in resp.lower():
                    print(f"      ⚠ rcon response: {resp.strip()[:120]}", file=sys.stderr)
                if throttle_ms:
                    await asyncio.sleep(throttle_ms / 1000.0)
            except Exception as exc:  # noqa: BLE001 — surface every send error
                print(
                    f"      ✗ foundation {sent + skipped + 1} ({cmd_text[:60]}) failed: {exc}",
                    file=sys.stderr,
                )
                skipped += 1

        for cmd in final_script.commands:
            if cmd.kind == "wait":
                await asyncio.sleep(cmd.wait_seconds or 0.0)
                continue
            text = _command_to_minecraft(cmd)
            if text is None:
                skipped += 1
                continue
            # RCON expects bare commands (no leading slash).
            cmd_text = text[1:] if text.startswith("/") else text
            try:
                resp = mcr.command(cmd_text)
                sent += 1
                if resp and "error" in resp.lower():
                    print(f"      ⚠ rcon response: {resp.strip()[:120]}", file=sys.stderr)
                if throttle_ms:
                    await asyncio.sleep(throttle_ms / 1000.0)
            except Exception as exc:  # noqa: BLE001 — surface every send error
                print(
                    f"      ✗ command {sent + skipped + 1} ({cmd_text[:60]}) failed: {exc}",
                    file=sys.stderr,
                )
                skipped += 1
    return sent, skipped, final_script


def _print_dry_run(script: BuildScript) -> None:
    print(f"[dry-run] {len(script.commands)} commands would be sent:")
    for i, cmd in enumerate(script.commands, start=1):
        text = _command_to_minecraft(cmd)
        if text is None and cmd.kind == "wait":
            print(f"  {i:>3}. (wait {cmd.wait_seconds}s)")
        else:
            print(f"  {i:>3}. {text}")


async def main_async(args: argparse.Namespace) -> int:
    intent = NewBuildingIntent(
        intent_id=f"cli-build-{int(time.time())}",
        proposer_id=args.proposer,
        concept=args.concept,
        intended_use=args.intended_use,
        vibe=args.vibe,
        size_class=args.size_class,
        biome_fit=args.biome_fit,
        motivation=args.motivation,
    )
    script, output_dir = await _generate(intent, args.output_dir, args.origin)

    if args.dry_run:
        _print_dry_run(script)
        print()
        print(f"PASS (dry-run). artifacts in: {output_dir}")
        return 0

    final_script = script
    if args.rcon_host:
        print(
            f"[4/4] sending {len(script.commands)} commands via RCON to "
            f"{args.rcon_host}:{args.rcon_port}..."
        )
        if not args.rcon_password:
            sys.exit("--rcon-host requires --rcon-password (or RCON_PASSWORD in env).")
        started = time.monotonic()
        sent, skipped, final_script = await _send_rcon(
            script,
            host=args.rcon_host,
            port=args.rcon_port,
            password=args.rcon_password,
            throttle_ms=args.throttle_ms,
            auto_ground=args.auto_ground,
            foundation=args.foundation,
        )
    else:
        if args.auto_ground:
            print(
                "      ⚠ --auto-ground requested without --rcon-host; "
                "the HTTP bridge path cannot query terrain. Building at literal "
                f"y={args.origin.y}."
            )
        print(f"[4/4] sending {len(script.commands)} commands to HTTP bridge...")
        started = time.monotonic()
        sent, skipped = await _send_live(script, throttle_ms=args.throttle_ms)
    elapsed = time.monotonic() - started
    print(f"      sent={sent} skipped={skipped} elapsed={elapsed:.1f}s")
    print()
    print(f"PASS. artifacts in: {output_dir}")
    view_origin = final_script.origin
    print(
        f"      Connect a Minecraft 1.21.6 client to localhost:25565 and "
        f"teleport to the resolved origin (/tp <name> {view_origin.x} "
        f"{view_origin.y} {view_origin.z}) to view the build."
    )
    return 0 if skipped == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--concept", required=True, help="Short noun phrase, e.g. 'Stone Watchtower'"
    )
    parser.add_argument(
        "--vibe",
        default="gothic",
        choices=[
            "rustic",
            "classical",
            "futuristic",
            "organic",
            "brutalist",
            "gothic",
            "cyberpunk",
            "cottagecore",
        ],
    )
    parser.add_argument(
        "--biome-fit",
        default="plains",
        help="Target biome (free-form; enum validated by NewBuildingIntent)",
    )
    parser.add_argument(
        "--size-class", default="medium", choices=["small", "medium", "large", "epic"]
    )
    parser.add_argument("--intended-use", default="CLI build for live inspection.")
    parser.add_argument(
        "--motivation", default="Manual CLI invocation of the propose_new_building pipeline."
    )
    parser.add_argument("--proposer", default="cli", help="Recorded as proposer_id on the intent")
    parser.add_argument(
        "--origin",
        type=_parse_origin,
        default=_parse_origin("0,72,0"),
        help="Build origin as x,y,z (default 0,72,0)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("snapshots/cli-builds") / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        help="Folder for blueprint.png + build_plan.json + build_script.json",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print /fill commands without sending to Minecraft"
    )
    parser.add_argument(
        "--throttle-ms", type=int, default=60, help="Sleep between commands in ms (default 60)"
    )
    parser.add_argument(
        "--rcon-host",
        default=None,
        help="Use RCON directly to the server (e.g. 127.0.0.1). "
        "When set, --rcon-password is required and the "
        "HTTP bridge path is skipped.",
    )
    parser.add_argument("--rcon-port", type=int, default=25575)
    parser.add_argument(
        "--rcon-password",
        default=os.environ.get("RCON_PASSWORD"),
        help="RCON password (or set RCON_PASSWORD in env).",
    )
    parser.add_argument(
        "--auto-ground",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Query the world via RCON to find the terrain top at the origin "
            "column, then shift the build's y so it sits on the ground. "
            "Requires --rcon-host. Use --no-auto-ground to build at the literal "
            "--origin y."
        ),
    )
    parser.add_argument(
        "--foundation",
        default="cobblestone",
        help=(
            "Block to use for the foundation pillar emitted under steep terrain "
            "(default: cobblestone). Ignored when --no-auto-ground is set."
        ),
    )
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set in environment.")
    if not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("GOOGLE_API_KEY not set in environment.")

    rc = asyncio.run(main_async(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()

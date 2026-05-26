#!/usr/bin/env python3
"""Replay a headless sim folder visually in Minecraft (issue #858).

Reads ``decision_log.jsonl`` + ``build_intents.jsonl`` from a sim folder and
drives a live (or fake) Minecraft bridge to recreate the recorded
conversation and scripted builds, capturing screenshots at declared
milestones. See ``docs/MINECRAFT-REPLAY.md`` for the full reference.

Example:

    python scripts/replay_in_minecraft.py \\
        --sim-folder runs/headless/abc-123 \\
        --speed-multiplier 4.0 \\
        --screenshot-milestones build_start,build_complete,hourly \\
        --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.minecraft.build_script import BuildCommand, BuildScript  # noqa: E402
from core.minecraft.eval.live_cli import (  # noqa: E402
    HttpBridgeClient,
    LiveBridgeConfigError,
    _resolve_path,
)
from core.minecraft.eval.live_profile import DEFAULT_PROFILE_NAME  # noqa: E402
from core.minecraft.eval.live_runner import BridgeClient  # noqa: E402
from core.minecraft.replay import (  # noqa: E402
    REPLAY_MILESTONES,
    ChatEvent,
    ExecuteBuildScriptEvent,
    FakeReplayBridge,
    PoseEvent,
    ReplayManifest,
    ReplayMilestone,
    ReplayScheduler,
    ScreenshotEntry,
    ScreenshotEvent,
    capture_screenshot,
)

_LIVE_ENABLED_VALUES = frozenset(("1", "true", "yes", "on"))
_REQUIRED_LIVE_ENV = ("MC_EVAL_LIVE_BRIDGE_URL", "MINECRAFT_BRIDGE_TOKEN")


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    bridge: BridgeClient | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    load_env: bool = True,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code)

    if load_env and env is None:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    resolved_env = os.environ if env is None else env

    sim_folder = _resolve_path(args.sim_folder)
    if not sim_folder.is_dir():
        print(f"ERROR: --sim-folder not found: {sim_folder}", file=err)
        return 1

    try:
        milestones = _parse_milestones(args.screenshot_milestones)
        output_dir = (
            _resolve_path(args.output_dir)
            if args.output_dir
            else sim_folder / "replay" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )
        selected_bridge, dry_run = (
            (bridge, args.dry_run) if bridge is not None
            else _make_replay_bridge(args, resolved_env)
        )
        manifest = asyncio.run(
            run_replay(
                sim_folder=sim_folder,
                output_dir=output_dir,
                bridge=selected_bridge,
                speed_multiplier=args.speed_multiplier,
                milestones=milestones,
                world_profile=args.profile,
                dry_run=dry_run,
            )
        )
    except (LiveBridgeConfigError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=err)
        return 1
    except Exception as exc:
        print(f"ERROR: Minecraft replay failed: {exc}", file=err)
        return 1

    print(
        f"replay complete: {manifest.events_replayed_count} events, "
        f"{len(manifest.screenshots)} screenshots, manifest at "
        f"{output_dir / 'replay_manifest.json'}",
        file=out,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a headless sim into Minecraft with screenshot capture",
    )
    parser.add_argument("--sim-folder", required=True, help="Path to a headless sim folder")
    parser.add_argument(
        "--speed-multiplier",
        type=float,
        default=1.0,
        help="Replay speed multiplier (>1 plays faster, <1 slower)",
    )
    parser.add_argument(
        "--screenshot-milestones",
        default=",".join(REPLAY_MILESTONES),
        help=f"Comma-separated milestones. Default: {','.join(REPLAY_MILESTONES)}",
    )
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="Minecraft live eval profile name (used for the bridge connection)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for screenshots + manifest (default: <sim-folder>/replay/<timestamp>)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force the deterministic fake bridge (default unless MC_EVAL_LIVE_ENABLED=1)",
    )
    return parser


def _make_replay_bridge(
    args: argparse.Namespace, env: Mapping[str, str]
) -> tuple[BridgeClient, bool]:
    """Replay-flavoured bridge selector.

    Mirrors :func:`core.minecraft.eval.live_cli._make_bridge_client` but
    falls back to :class:`FakeReplayBridge` (permissive vocabulary)
    rather than the eval :class:`FakeBridgeClient` (strict to the
    seven-command eval vocabulary).
    """
    if args.dry_run or env.get("MC_EVAL_LIVE_ENABLED", "").strip().casefold() not in _LIVE_ENABLED_VALUES:
        return FakeReplayBridge(), True

    missing = [key for key in _REQUIRED_LIVE_ENV if not env.get(key)]
    if missing:
        required = ", ".join(_REQUIRED_LIVE_ENV)
        missing_text = ", ".join(missing)
        raise LiveBridgeConfigError(
            "live Minecraft replay is explicitly gated; "
            f"MC_EVAL_LIVE_ENABLED=1 requires {required}. "
            f"Missing: {missing_text}. Pass --dry-run for deterministic local replay."
        )
    return (
        HttpBridgeClient(env["MC_EVAL_LIVE_BRIDGE_URL"], env["MINECRAFT_BRIDGE_TOKEN"]),
        False,
    )


def _parse_milestones(raw: str) -> tuple[ReplayMilestone, ...]:
    if not raw.strip():
        return ()
    parsed: list[ReplayMilestone] = []
    valid = set(REPLAY_MILESTONES)
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        if token not in valid:
            raise ValueError(
                f"unknown screenshot milestone {token!r}; "
                f"valid: {', '.join(sorted(valid))}"
            )
        parsed.append(token)  # type: ignore[arg-type]
    return tuple(parsed)


async def run_replay(
    *,
    sim_folder: Path,
    output_dir: Path,
    bridge: BridgeClient,
    speed_multiplier: float = 1.0,
    milestones: Sequence[ReplayMilestone] = REPLAY_MILESTONES,
    world_profile: str = DEFAULT_PROFILE_NAME,
    dry_run: bool = True,
) -> ReplayManifest:
    """Walk the sim folder's scheduled events against ``bridge``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    scheduler = ReplayScheduler(sim_folder=sim_folder, enabled_milestones=tuple(milestones))
    events = scheduler.events()

    manifest = ReplayManifest(
        sim_folder=str(sim_folder),
        output_dir=str(output_dir),
        started_at=datetime.now(UTC),
        world_profile=world_profile,
        speed_multiplier=speed_multiplier,
        screenshot_milestones=list(milestones),
        bridge_kind=type(bridge).__name__,
        dry_run=dry_run,
    )

    pause_event = asyncio.Event()
    pause_event.set()
    _install_pause_signal_handlers(pause_event)

    speed = max(0.01, float(speed_multiplier))
    last_sim_time: float | None = None
    chat_count = 0
    build_scripts: list[str] = []

    for event in events:
        await pause_event.wait()
        if last_sim_time is not None and event.sim_time > last_sim_time:
            delay = (event.sim_time - last_sim_time) / speed
            if delay > 0:
                await asyncio.sleep(min(delay, 5.0))
        last_sim_time = event.sim_time

        if isinstance(event, ChatEvent):
            await bridge.send_command(
                f"!chat {event.actor_id} {_escape_chat(event.text)}"
            )
            chat_count += 1
        elif isinstance(event, PoseEvent):
            pos = event.position
            await bridge.send_command(
                f"!goToCoordinates {pos.get('x', 0)} {pos.get('y', 64)} {pos.get('z', 0)} 1"
            )
        elif isinstance(event, ExecuteBuildScriptEvent):
            script = _load_build_script(event.script_path)
            if script is not None:
                await _execute_build_script(bridge, script)
                build_scripts.append(event.intent_id)
        elif isinstance(event, ScreenshotEvent):
            filename = f"{event.milestone}_{event.row_idx:06d}.png"
            result = await capture_screenshot(
                bridge,
                label=event.label,
                output_path=screenshots_dir / filename,
            )
            manifest.screenshots.append(
                ScreenshotEntry(
                    filename=filename,
                    milestone=event.milestone,
                    sim_time=event.sim_time,
                    decision_log_row_idx=event.row_idx,
                    status=result.status,
                    label=event.label,
                    intent_id=event.intent_id,
                )
            )

    manifest.events_replayed_count = len(events)
    manifest.chat_events_replayed = chat_count
    manifest.build_scripts_executed = build_scripts
    manifest.finished_at = datetime.now(UTC)
    manifest.write(output_dir / "replay_manifest.json")
    return manifest


def _escape_chat(text: str) -> str:
    # Strip newlines so the chat command stays single-line; the bridge
    # treats anything after the agent_id as the message body.
    return text.replace("\n", " ").replace("\r", " ").strip()


def _load_build_script(path: Path) -> BuildScript | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return BuildScript.model_validate(payload)
    except Exception:
        return None


async def _execute_build_script(bridge: BridgeClient, script: BuildScript) -> None:
    for command in script.commands:
        await bridge.send_command(_command_to_text(command))


def _command_to_text(command: BuildCommand) -> str:
    if command.kind == "setblock":
        pos = command.position
        return f"!setblock {pos.x} {pos.y} {pos.z} {command.block_type}"
    if command.kind == "fill":
        a = command.position
        b = command.region_to or command.position
        return f"!fill {a.x} {a.y} {a.z} {b.x} {b.y} {b.z} {command.block_type}"
    if command.kind == "structure":
        pos = command.position
        return f"!structureBlock {pos.x} {pos.y} {pos.z} {command.structure_id or ''}".strip()
    if command.kind == "wait":
        return f"!wait {command.wait_seconds or 0}"
    return f"!noop {command.kind}"


def _install_pause_signal_handlers(pause_event: asyncio.Event) -> None:
    """Wire SIGUSR1/SIGUSR2 to pause/resume the replay on Unix.

    SIGUSR1 sets a pause flag, SIGUSR2 resumes. Falls back to a no-op on
    platforms (e.g. Windows) that don't expose these signals.
    """
    if not hasattr(signal, "SIGUSR1") or not hasattr(signal, "SIGUSR2"):
        return
    loop = asyncio.get_event_loop()
    with suppress(NotImplementedError, RuntimeError):
        loop.add_signal_handler(signal.SIGUSR1, pause_event.clear)
        loop.add_signal_handler(signal.SIGUSR2, pause_event.set)


if __name__ == "__main__":
    raise SystemExit(main())

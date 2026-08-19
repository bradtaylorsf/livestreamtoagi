#!/usr/bin/env python3
"""Replay headless sim dialog and BuildScripts directly to Minecraft via RCON."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.minecraft.build_executors import (  # noqa: E402
    async_safe_mcrcon_class,
    command_to_minecraft,
)
from core.minecraft.build_script import BuildScript  # noqa: E402
from core.minecraft.replay import ChatEvent, ExecuteBuildScriptEvent, ReplayScheduler  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    args = _build_parser().parse_args(argv)
    sim_folder = Path(args.sim_folder).expanduser().resolve()
    if not sim_folder.is_dir():
        print(f"ERROR: --sim-folder not found: {sim_folder}", file=sys.stderr)
        return 1

    host = args.rcon_host or os.environ.get("RCON_HOST") or "127.0.0.1"
    port = args.rcon_port or _int_env("RCON_PORT", 25575)
    password = args.rcon_password or os.environ.get("RCON_PASSWORD", "")
    if not args.dry_run and not password:
        print(
            "ERROR: RCON password is required via --rcon-password or RCON_PASSWORD", file=sys.stderr
        )
        return 1

    output_log = (
        Path(args.output_log).expanduser().resolve()
        if args.output_log
        else sim_folder / "replay" / datetime.now(UTC).strftime("rcon-%Y%m%dT%H%M%SZ.jsonl")
    )
    output_log.parent.mkdir(parents=True, exist_ok=True)

    scheduler = ReplayScheduler(
        sim_folder=sim_folder,
        collaborative_builds=args.collaborative_builds,
        collaborative_step_seconds=args.collaborative_step_seconds,
        intent_ids=frozenset(args.intent_id) if args.intent_id else None,
    )
    events = scheduler.events()
    result = _run_replay(
        events=events,
        host=host,
        port=port,
        password=password,
        output_log=output_log,
        dry_run=args.dry_run,
        speed_multiplier=args.speed_multiplier,
        throttle_ms=args.throttle_ms,
    )
    print(
        f"rcon replay complete: events={result['events']} chat={result['chat']} "
        f"build_scripts={result['build_scripts']} commands={result['commands']} "
        f"dry_run={args.dry_run} log={output_log}"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a headless sim folder to a live Minecraft server over RCON.",
    )
    parser.add_argument("--sim-folder", required=True, help="Headless sim folder")
    parser.add_argument("--rcon-host", default=None, help="RCON host (default: env or 127.0.0.1)")
    parser.add_argument(
        "--rcon-port", type=int, default=None, help="RCON port (default: env or 25575)"
    )
    parser.add_argument("--rcon-password", default=None, help="RCON password (default: env)")
    parser.add_argument(
        "--collaborative-builds",
        action="store_true",
        help="Use collaborative_builds ledgers and per-job scripts when present.",
    )
    parser.add_argument(
        "--intent-id",
        action="append",
        default=None,
        help="Only replay one build intent id. Repeat to include multiple builds.",
    )
    parser.add_argument(
        "--collaborative-step-seconds",
        type=float,
        default=3.0,
        help="Synthetic sim-time spacing between collaborative role jobs.",
    )
    parser.add_argument(
        "--speed-multiplier",
        type=float,
        default=12.0,
        help="Replay speed multiplier for dialog/job spacing.",
    )
    parser.add_argument(
        "--throttle-ms",
        type=int,
        default=30,
        help="Delay between Minecraft block commands.",
    )
    parser.add_argument("--output-log", default=None, help="JSONL replay command log path")
    parser.add_argument("--dry-run", action="store_true", help="Write the replay log only")
    return parser


def _run_replay(
    *,
    events: list[object],
    host: str,
    port: int,
    password: str,
    output_log: Path,
    dry_run: bool,
    speed_multiplier: float,
    throttle_ms: int,
) -> dict[str, int]:
    stats = {"events": 0, "chat": 0, "build_scripts": 0, "commands": 0}
    speed = max(0.01, float(speed_multiplier))
    throttle_seconds = max(0, int(throttle_ms)) / 1000.0
    last_sim_time: float | None = None
    mcr_context = None
    if not dry_run:
        MCRcon = async_safe_mcrcon_class()  # noqa: N806
        mcr_context = MCRcon(host, password, port=port, timeout=10)

    with output_log.open("w", encoding="utf-8") as fh:
        if mcr_context is None:
            mcr = None
            _replay_events(
                events,
                mcr=mcr,
                fh=fh,
                stats=stats,
                speed=speed,
                throttle_seconds=throttle_seconds,
                last_sim_time=last_sim_time,
            )
        else:
            with mcr_context as mcr:
                _replay_events(
                    events,
                    mcr=mcr,
                    fh=fh,
                    stats=stats,
                    speed=speed,
                    throttle_seconds=throttle_seconds,
                    last_sim_time=last_sim_time,
                )
    return stats


def _replay_events(
    events: list[object],
    *,
    mcr: object | None,
    fh,
    stats: dict[str, int],
    speed: float,
    throttle_seconds: float,
    last_sim_time: float | None,
) -> None:
    for event in events:
        current_sim_time = float(getattr(event, "sim_time", 0.0))
        if last_sim_time is not None and current_sim_time > last_sim_time:
            delay = (current_sim_time - last_sim_time) / speed
            if delay > 0:
                time.sleep(min(delay, 5.0))
        last_sim_time = current_sim_time
        stats["events"] += 1

        if isinstance(event, ChatEvent):
            command = f"say {event.actor_id}: {_sanitize_chat(event.text)}"
            _send_or_log(mcr, fh, command, event_type="chat")
            stats["chat"] += 1
        elif isinstance(event, ExecuteBuildScriptEvent):
            script = _load_build_script(event.script_path)
            if script is None:
                _write_log(fh, "missing_script", str(event.script_path), event)
                continue
            stats["build_scripts"] += 1
            for build_command in script.commands:
                if build_command.kind == "wait":
                    if build_command.wait_seconds:
                        time.sleep(build_command.wait_seconds)
                    continue
                text = command_to_minecraft(build_command)
                if text is None:
                    continue
                _send_or_log(
                    mcr, fh, text[1:] if text.startswith("/") else text, event_type="build"
                )
                stats["commands"] += 1
                if throttle_seconds:
                    time.sleep(throttle_seconds)


def _send_or_log(mcr: object | None, fh, command: str, *, event_type: str) -> None:
    response = None
    if mcr is not None:
        response = mcr.command(command)
    _write_log(fh, event_type, command, response=response)


def _write_log(
    fh, event_type: str, command: str, event: object | None = None, response=None
) -> None:
    payload = {
        "event_type": event_type,
        "command": command,
        "response": response,
        "sim_time": getattr(event, "sim_time", None),
        "intent_id": getattr(event, "intent_id", None),
    }
    fh.write(json.dumps(payload, sort_keys=True) + "\n")
    fh.flush()


def _load_build_script(path: Path) -> BuildScript | None:
    if not path.is_file():
        return None
    return BuildScript.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _sanitize_chat(text: str) -> str:
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())[:220]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


if __name__ == "__main__":
    raise SystemExit(main())

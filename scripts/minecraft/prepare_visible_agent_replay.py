#!/usr/bin/env python3
"""Prepare the local Minecraft world for a visible collaborative replay."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from mcrcon import MCRcon

DEFAULT_AGENTS = ("Vera", "Sentinel", "Fork", "Aurora", "Pixel", "Rex", "Alpha")


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _clear_commands() -> list[str]:
    commands: list[str] = []
    for x0 in range(-8, 128, 16):
        x1 = min(x0 + 15, 127)
        for z0 in range(-8, 112, 16):
            z1 = min(z0 + 15, 111)
            commands.append(f"fill {x0} 64 {z0} {x1} 112 {z1} air")
    commands.append("fill -8 63 -8 127 63 111 smooth_stone")
    return commands


def _platform_commands(*, teleport_watchers: bool) -> list[str]:
    commands = [
        "fill 42 106 124 78 106 148 polished_andesite",
        "fill 42 107 124 78 108 124 glass",
        "fill 42 107 148 78 108 148 glass",
        "fill 42 107 124 42 108 148 glass",
        "fill 78 107 124 78 108 148 glass",
        "setworldspawn 60 107 136",
    ]
    if teleport_watchers:
        commands.append("tp @a 60 108 136")
    return commands


def build_commands(*, agents: tuple[str, ...], teleport_watchers: bool) -> list[str]:
    commands = [
        "gamerule commandBlockOutput false",
        "gamerule sendCommandFeedback false",
        "gamerule doDaylightCycle false",
        "gamerule doWeatherCycle false",
        "time set day",
        "weather clear",
        "difficulty peaceful",
        "kill @e[type=armor_stand]",
    ]
    commands.extend(f"op {agent}" for agent in agents)
    commands.extend(_clear_commands())
    commands.extend(_platform_commands(teleport_watchers=teleport_watchers))
    commands.append("say Area reset. Visible Mineflayer agents can join and build next.")
    return commands


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset the local Minecraft build area for the visible-agent Colosseum replay."
    )
    parser.add_argument("--env-file", default=".env", help="Env file with RCON settings")
    parser.add_argument("--rcon-host", default=None, help="RCON host override")
    parser.add_argument("--rcon-port", type=int, default=None, help="RCON port override")
    parser.add_argument(
        "--agent",
        dest="agents",
        action="append",
        help="Agent username to op; repeatable. Defaults to the Colosseum cohort.",
    )
    parser.add_argument(
        "--no-teleport-watchers",
        action="store_true",
        help="Do not teleport all connected players to the viewing platform.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the command count only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _load_env(Path(args.env_file))
    host = args.rcon_host or os.environ.get("RCON_HOST") or "127.0.0.1"
    port = args.rcon_port or int(os.environ.get("RCON_PORT") or "25575")
    password = os.environ.get("RCON_PASSWORD")
    if not password:
        raise SystemExit("RCON_PASSWORD is required in the environment or .env")

    agents = tuple(args.agents or DEFAULT_AGENTS)
    commands = build_commands(agents=agents, teleport_watchers=not args.no_teleport_watchers)
    if args.dry_run:
        print(f"would send {len(commands)} prep commands to {host}:{port}; agents={list(agents)}")
        return 0

    with MCRcon(host, password, port=port, timeout=10) as mcr:
        for command in commands:
            mcr.command(command)
    print(f"prepared visible-agent replay; commands={len(commands)} agents={list(agents)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

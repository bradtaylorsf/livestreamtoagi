#!/usr/bin/env python3
"""Interactive agent chat launcher.

Presents a menu to pick an agent and mode, then delegates to test_agent.py
or watch_conversations.py.  Can also be invoked directly with arguments.

Usage:
    pnpm chat              # interactive menu
    pnpm chat rex          # jump straight to chatting with Rex
    pnpm chat vera auto    # run auto-test on Vera
    pnpm chat --dry-run    # dry-run with default agent (Rex)
    pnpm chat convo        # multi-agent conversation (interactive menu)
    pnpm chat convo --topic "Should we rewrite in Rust?"
    pnpm chat convo --agents rex,fork,aurora --type debate --turns 10
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

AGENTS = [
    ("vera", "Vera — The Showrunner", "bright_magenta", "Coordinator, keeps everyone on track"),
    ("rex", "Rex — The Skeptic", "bright_green", "Engineer, builder, dry sarcasm"),
    ("aurora", "Aurora — The Visionary", "bright_cyan", "Creative director, big ideas"),
    ("pixel", "Pixel — The Enthusiast", "bright_yellow", "Researcher, audience liaison"),
    ("fork", "Fork — The Contrarian", "bright_red", "Code reviewer, open-source evangelist"),
    ("sentinel", "Sentinel — The Accountant", "blue", "Budget monitor, cost hawk"),
    ("grok", "Grok — The Wild Card", "dark_orange", "Provocateur, chaotic insights"),
    ("overseer", "The Overseer", "bright_white", "Content filter, ominous presence"),
    ("alpha", "Alpha — The Wolf", "grey70", "Errand runner, non-verbal"),
]

SINGLE_MODES = [
    ("chat", "Interactive chat (REPL)", "--interactive"),
    ("auto", "Automated test sequence (5 prompts)", "--auto"),
    ("diagnostic", "Diagnostic — test all tools through agent pipeline", "--diagnostic"),
    ("reflect", "Run reflection cycle (updates core memory)", "--reflect"),
    ("dry-run", "Dry-run — show context assembly, no LLM calls", "--dry-run"),
]

CONVO_TYPES = [
    ("freeform", "Free-form — agents pick their own topic"),
    ("standup", "Daily standup — Vera leads a morning check-in"),
    ("debate", "Debate — agents argue a seeded topic"),
    ("idle", "Idle trigger — boredom-driven conversation"),
]

ALL_AGENT_IDS = [a[0] for a in AGENTS]


def print_banner() -> None:
    console.print()
    console.print(Panel(
        "[bold bright_cyan]🤖  Livestream to AGI — Agent Chat[/bold bright_cyan]\n"
        "[dim]Talk to any agent, test memory, or run multi-agent conversations[/dim]",
        border_style="bright_cyan",
        padding=(1, 2),
    ))


def pick_agent() -> str | None:
    console.print()
    table = Table(show_header=True, border_style="dim", padding=(0, 1))
    table.add_column("#", style="bold", width=3)
    table.add_column("Agent", width=30)
    table.add_column("Description", style="dim")

    for i, (agent_id, name, color, desc) in enumerate(AGENTS, 1):
        table.add_row(str(i), f"[{color}]{name}[/{color}]", desc)

    console.print(table)
    console.print()

    try:
        choice = console.input("[bold]Pick an agent (1-9, name, or 'q' to quit): [/bold]").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice.lower() in ("q", "quit", "exit"):
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(AGENTS):
            return AGENTS[idx][0]
    except ValueError:
        pass

    choice_lower = choice.lower()
    for agent_id, name, _, _ in AGENTS:
        if choice_lower == agent_id or choice_lower in name.lower():
            return agent_id

    console.print(f"[red]Unknown agent: '{choice}'[/red]")
    return pick_agent()


def pick_mode() -> str | None:
    console.print()
    console.print("  [bold bright_cyan]Single-agent modes:[/bold bright_cyan]")
    for i, (mode_id, desc, _) in enumerate(SINGLE_MODES, 1):
        console.print(f"  [bold]{i}[/bold]  {desc}")
    console.print()
    console.print("  [bold bright_cyan]Multi-agent modes:[/bold bright_cyan]")
    console.print(f"  [bold]{len(SINGLE_MODES) + 1}[/bold]  Multi-agent conversation (pick agents, topic, type)")
    console.print()

    try:
        choice = console.input(
            f"[bold]Pick a mode (1-{len(SINGLE_MODES) + 1}, or 'q' to quit): [/bold]"
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice.lower() in ("q", "quit", "exit"):
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(SINGLE_MODES):
            return SINGLE_MODES[idx][0]
        if idx == len(SINGLE_MODES):
            return "convo"
    except ValueError:
        pass

    choice_lower = choice.lower()
    if choice_lower == "convo":
        return "convo"
    for mode_id, _, _ in SINGLE_MODES:
        if choice_lower == mode_id:
            return mode_id

    return "chat"


# ── Multi-agent conversation menu ────────────────────────────


def pick_convo_agents() -> list[str] | None:
    """Pick which agents participate in the conversation."""
    console.print()
    console.print("[bold]Who should participate?[/bold]")
    console.print("[dim]Enter agent numbers/names separated by commas, 'all' for everyone, or 'q' to quit[/dim]")
    console.print()

    table = Table(show_header=True, border_style="dim", padding=(0, 1))
    table.add_column("#", style="bold", width=3)
    table.add_column("Agent", width=30)

    # Exclude overseer and alpha from default conversation participants
    conversational = [(i, a) for i, a in enumerate(AGENTS, 1) if a[0] not in ("overseer", "alpha")]
    for i, (agent_id, name, color, _) in conversational:
        table.add_row(str(i), f"[{color}]{name}[/{color}]")

    console.print(table)
    console.print()

    try:
        choice = console.input("[bold]Agents (e.g. 1,2,5 or rex,fork,aurora or 'all'): [/bold]").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice.lower() in ("q", "quit", "exit"):
        return None

    if choice.lower() == "all":
        return [a[0] for _, a in conversational]

    selected: list[str] = []
    for part in choice.split(","):
        part = part.strip().lower()
        # Try as number
        try:
            idx = int(part) - 1
            if 0 <= idx < len(AGENTS):
                selected.append(AGENTS[idx][0])
                continue
        except ValueError:
            pass
        # Try as name
        for agent_id, name, _, _ in AGENTS:
            if part == agent_id or part in name.lower():
                selected.append(agent_id)
                break
        else:
            console.print(f"[yellow]Skipping unknown: '{part}'[/yellow]")

    if len(selected) < 2:
        console.print("[red]Need at least 2 agents for a conversation.[/red]")
        return pick_convo_agents()

    return selected


def pick_convo_type() -> str:
    """Pick the conversation type / trigger."""
    console.print()
    for i, (type_id, desc) in enumerate(CONVO_TYPES, 1):
        console.print(f"  [bold]{i}[/bold]  {desc}")
    console.print()

    try:
        choice = console.input("[bold]Conversation type (1-4, default: freeform): [/bold]").strip()
    except (EOFError, KeyboardInterrupt):
        return "freeform"

    if not choice:
        return "freeform"

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(CONVO_TYPES):
            return CONVO_TYPES[idx][0]
    except ValueError:
        pass

    choice_lower = choice.lower()
    for type_id, _ in CONVO_TYPES:
        if choice_lower == type_id:
            return type_id

    return "freeform"


def pick_topic() -> str | None:
    """Optionally seed a conversation topic."""
    console.print()
    try:
        topic = console.input(
            "[bold]Seed a topic? (enter topic or press Enter to skip): [/bold]"
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None

    return topic if topic else None


def pick_turns() -> int | None:
    """Optionally cap the number of turns."""
    console.print()
    try:
        turns_str = console.input(
            "[bold]Max turns? (enter number or press Enter for default ~8-14): [/bold]"
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not turns_str:
        return None

    try:
        return max(2, int(turns_str))
    except ValueError:
        return None


def run_convo(
    agents: list[str],
    convo_type: str,
    topic: str | None = None,
    turns: int | None = None,
    speed: float = 1.0,
    quiet: bool = False,
    verbose: bool = False,
    no_overseer: bool = False,
) -> None:
    """Launch a multi-agent conversation using the same pipeline as single-agent chat."""
    import asyncio
    from scripts.test_agent import bootstrap_services, run_multi, shutdown_services

    async def _run() -> None:
        services = await bootstrap_services()
        try:
            await run_multi(
                agent_ids=agents,
                services=services,
                convo_type=convo_type,
                topic=topic,
                max_turns=turns,
                verbose=verbose,
            )
        finally:
            await shutdown_services(services)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[dim]Conversation ended.[/dim]")


def run_single(
    agent_id: str,
    mode: str,
    verbose: bool = False,
    tts: bool = False,
) -> None:
    """Delegate to test_agent.py with the right flags."""
    from scripts.test_agent import async_main, parse_args
    import asyncio

    flag_map = {m[0]: m[2] for m in SINGLE_MODES}
    argv = ["--agent", agent_id, flag_map.get(mode, "--interactive")]
    if verbose:
        argv.append("--verbose")
    if tts:
        argv.append("--tts")

    args = parse_args(argv)
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        console.print("\n[dim]Session ended.[/dim]")


def main() -> None:
    args = sys.argv[1:]

    # ── Quick-launch: pnpm chat convo ... ──
    if args and args[0].lower() == "convo":
        convo_args = args[1:]
        # Parse convo CLI args
        agents = None
        convo_type = "freeform"
        topic = None
        turns = None
        speed = 1.0
        quiet = False
        verbose = False
        no_overseer = False
        i = 0
        while i < len(convo_args):
            arg = convo_args[i]
            if arg == "--agents" and i + 1 < len(convo_args):
                agents = convo_args[i + 1].split(",")
                i += 2
            elif arg == "--type" and i + 1 < len(convo_args):
                convo_type = convo_args[i + 1]
                i += 2
            elif arg == "--topic" and i + 1 < len(convo_args):
                topic = convo_args[i + 1]
                i += 2
            elif arg == "--turns" and i + 1 < len(convo_args):
                turns = int(convo_args[i + 1])
                i += 2
            elif arg == "--speed" and i + 1 < len(convo_args):
                speed = float(convo_args[i + 1])
                i += 2
            elif arg in ("--quiet", "-q"):
                quiet = True
                i += 1
            elif arg in ("--verbose", "-v"):
                verbose = True
                i += 1
            elif arg == "--no-overseer":
                no_overseer = True
                i += 1
            else:
                i += 1

        if not agents:
            # Fall through to interactive picker
            print_banner()
            agents = pick_convo_agents()
            if not agents:
                console.print("[dim]Goodbye.[/dim]")
                return
            if convo_type == "freeform":
                convo_type = pick_convo_type()
            if topic is None:
                topic = pick_topic()
            if turns is None:
                turns = pick_turns()

        run_convo(agents, convo_type, topic, turns, speed, quiet, verbose, no_overseer)
        return

    # ── Quick-launch: pnpm chat --dry-run or --list-agents ──
    if args and args[0].startswith("--"):
        from scripts.test_agent import async_main, parse_args
        import asyncio
        parsed = parse_args(args)
        try:
            asyncio.run(async_main(parsed))
        except KeyboardInterrupt:
            console.print("\n[dim]Session ended.[/dim]")
        return

    # ── Quick-launch: pnpm chat rex / pnpm chat rex auto ──
    if args:
        agent_id = args[0].lower()
        valid_ids = [a[0] for a in AGENTS]
        if agent_id not in valid_ids:
            console.print(f"[red]Unknown agent: '{agent_id}'[/red]")
            console.print(f"[dim]Available: {', '.join(valid_ids)}[/dim]")
            console.print(f"[dim]Or use: pnpm chat convo[/dim]")
            sys.exit(1)

        mode = "chat"
        verbose = False
        tts = False
        for arg in args[1:]:
            if arg.lower() in ("auto", "dry-run", "chat", "reflect", "diagnostic"):
                mode = arg.lower()
            elif arg in ("-v", "--verbose"):
                verbose = True
            elif arg == "--tts":
                tts = True

        run_single(agent_id, mode, verbose, tts=tts)
        return

    # ── Interactive menu ──
    print_banner()

    mode = pick_mode()
    if not mode:
        console.print("[dim]Goodbye.[/dim]")
        return

    # ── Options (apply to all modes) ──
    console.print()
    console.print("  [bold bright_cyan]Options:[/bold bright_cyan]")
    verbose = False
    no_overseer = False
    tts = False
    try:
        opts = console.input(
            "[bold]Options (v=verbose, t=TTS voice, "
            "n=no-overseer, Enter=skip): [/bold]"
        ).strip().lower()
        verbose = "v" in opts
        tts = "t" in opts
        no_overseer = "n" in opts
    except (EOFError, KeyboardInterrupt):
        pass

    if mode == "convo":
        agents = pick_convo_agents()
        if not agents:
            console.print("[dim]Goodbye.[/dim]")
            return
        convo_type = pick_convo_type()
        topic = pick_topic()
        turns = pick_turns()
        run_convo(agents, convo_type, topic, turns, verbose=verbose, no_overseer=no_overseer)
        return

    # Single-agent modes need an agent pick
    agent_id = pick_agent()
    if not agent_id:
        console.print("[dim]Goodbye.[/dim]")
        return

    run_single(agent_id, mode, verbose=verbose, tts=tts)


if __name__ == "__main__":
    main()

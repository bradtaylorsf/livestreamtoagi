#!/usr/bin/env python3
"""Interactive agent chat launcher.

Presents a menu to pick an agent and mode, then delegates to test_agent.py.
Can also be invoked directly with arguments to skip the menu.

Usage:
    pnpm chat              # interactive menu
    pnpm chat rex          # jump straight to chatting with Rex
    pnpm chat vera auto    # run auto-test on Vera
    pnpm chat --dry-run    # dry-run with default agent (Rex)
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
from rich.text import Text

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

MODES = [
    ("chat", "Interactive chat (REPL)", "--interactive"),
    ("auto", "Automated test sequence (5 prompts)", "--auto"),
    ("reflect", "Run reflection cycle (updates core memory)", "--reflect"),
    ("dry-run", "Dry-run — show context assembly, no LLM calls", "--dry-run"),
]


def print_banner() -> None:
    console.print()
    console.print(Panel(
        "[bold bright_cyan]🤖  Livestream to AGI — Agent Chat[/bold bright_cyan]\n"
        "[dim]Talk to any agent, test memory, or inspect context assembly[/dim]",
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

    # By number
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(AGENTS):
            return AGENTS[idx][0]
    except ValueError:
        pass

    # By name
    choice_lower = choice.lower()
    for agent_id, name, _, _ in AGENTS:
        if choice_lower == agent_id or choice_lower in name.lower():
            return agent_id

    console.print(f"[red]Unknown agent: '{choice}'[/red]")
    return pick_agent()


def pick_mode() -> str | None:
    console.print()
    for i, (mode_id, desc, _) in enumerate(MODES, 1):
        console.print(f"  [bold]{i}[/bold]  {desc}")
    console.print()

    try:
        choice = console.input("[bold]Pick a mode (1-4, or 'q' to quit): [/bold]").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice.lower() in ("q", "quit", "exit"):
        return None

    # By number
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(MODES):
            return MODES[idx][0]
    except ValueError:
        pass

    # By name
    choice_lower = choice.lower()
    for mode_id, _, _ in MODES:
        if choice_lower == mode_id:
            return mode_id

    # Default to chat
    return "chat"


def run(agent_id: str, mode: str, verbose: bool = False) -> None:
    """Delegate to test_agent.py with the right flags."""
    from scripts.test_agent import async_main, parse_args
    import asyncio

    flag_map = {m[0]: m[2] for m in MODES}
    argv = ["--agent", agent_id, flag_map.get(mode, "--interactive")]
    if verbose:
        argv.append("--verbose")

    args = parse_args(argv)
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        console.print("\n[dim]Session ended.[/dim]")


def main() -> None:
    args = sys.argv[1:]

    # Quick-launch: pnpm chat rex
    # Quick-launch: pnpm chat rex auto
    # Quick-launch: pnpm chat --dry-run
    if args:
        # Check for flag-only invocation like --dry-run or --list-agents
        if args[0].startswith("--"):
            from scripts.test_agent import async_main, parse_args
            import asyncio
            parsed = parse_args(args)
            try:
                asyncio.run(async_main(parsed))
            except KeyboardInterrupt:
                console.print("\n[dim]Session ended.[/dim]")
            return

        agent_id = args[0].lower()
        # Validate agent
        valid_ids = [a[0] for a in AGENTS]
        if agent_id not in valid_ids:
            console.print(f"[red]Unknown agent: '{agent_id}'[/red]")
            console.print(f"[dim]Available: {', '.join(valid_ids)}[/dim]")
            sys.exit(1)

        mode = "chat"
        verbose = False
        for arg in args[1:]:
            if arg.lower() in ("auto", "dry-run", "chat", "reflect"):
                mode = arg.lower()
            elif arg in ("-v", "--verbose"):
                verbose = True

        run(agent_id, mode, verbose)
        return

    # Interactive menu
    print_banner()
    agent_id = pick_agent()
    if not agent_id:
        console.print("[dim]Goodbye.[/dim]")
        return

    mode = pick_mode()
    if not mode:
        console.print("[dim]Goodbye.[/dim]")
        return

    verbose_input = ""
    try:
        verbose_input = console.input("[bold]Verbose mode? (y/N): [/bold]").strip().lower()
    except (EOFError, KeyboardInterrupt):
        pass

    run(agent_id, mode, verbose=verbose_input in ("y", "yes"))


if __name__ == "__main__":
    main()

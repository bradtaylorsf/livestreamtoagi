#!/usr/bin/env python3
"""Interactive agent chat launcher.

Presents a menu to pick an agent and mode, then delegates to the appropriate
script.  Can also be invoked directly with arguments.

Usage:
    pnpm chat                   # interactive menu
    pnpm chat rex               # jump straight to chatting with Rex
    pnpm chat vera auto         # run auto-test on Vera
    pnpm chat --dry-run         # dry-run with default agent (Rex)

    # Multi-agent conversations
    pnpm chat convo             # interactive conversation menu
    pnpm chat convo --topic "Should we rewrite in Rust?"
    pnpm chat convo --agents rex,fork,aurora --type debate --turns 10

    # Simulations (new orchestrator)
    pnpm chat sim               # interactive scenario picker
    pnpm chat sim awakening     # run awakening Day 1 scenario
    pnpm chat sim tool-coverage # run tool coverage scenario
    pnpm chat sim full-day      # run full scripted day
    pnpm chat sim autonomous    # autonomous trigger-driven (defaults: 1d, 42x)
    pnpm chat sim autonomous --duration 7d --max-cost 50
    pnpm chat sim --seed-file scenarios/custom.yaml --name my-test

    # Evals
    pnpm chat eval <sim-name>              # run full eval suite
    pnpm chat eval <sim-name> --suite quick
    pnpm chat eval <sim-name> --view-last  # view last eval results
    pnpm chat eval --list                  # list eval categories

    # Tool coverage check
    pnpm chat coverage <sim-name>
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
    console.print(f"  [bold]{len(SINGLE_MODES) + 2}[/bold]  Simulation — seeded scenarios or autonomous (new orchestrator)")
    console.print()

    try:
        choice = console.input(
            f"[bold]Pick a mode (1-{len(SINGLE_MODES) + 2}, or 'q' to quit): [/bold]"
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
        if idx == len(SINGLE_MODES) + 1:
            return "simulate"
    except ValueError:
        pass

    choice_lower = choice.lower()
    if choice_lower in ("convo", "sim", "simulate"):
        return "simulate" if choice_lower in ("sim", "simulate") else "convo"
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


def run_simulation(
    agents: list[str],
    convo_type: str,
    topic: str | None = None,
    turns: int | None = None,
    speed: float = 1.0,
    verbose: bool = False,
    overseer_shadow: bool = True,
    sim_name: str | None = None,
) -> None:
    """Launch a tracked simulation via watch_conversations.py --test --simulate (legacy)."""
    import subprocess

    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "watch_conversations.py"),
        "--test", "--simulate",
        "--test-type", convo_type,
        "--agents", ",".join(agents),
        "--speed", str(speed),
    ]
    if turns is not None:
        cmd += ["--turns", str(turns)]
    if topic is not None:
        cmd += ["--topic", topic]
    if verbose:
        cmd.append("--verbose")
    if overseer_shadow:
        cmd.append("--overseer-shadow")
    if sim_name:
        cmd += ["--sim-name", sim_name]

    console.print(f"\n[bold bright_cyan]Starting simulation...[/bold bright_cyan]")
    console.print(f"[dim]Agents: {', '.join(agents)}[/dim]")
    console.print(f"[dim]Type: {convo_type} | Turns: {turns or 'default'} | Overseer shadow: {overseer_shadow}[/dim]\n")

    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        console.print("\n[dim]Simulation interrupted.[/dim]")


# ── New simulation orchestrator integration ──────────────────

SCENARIOS_DIR = PROJECT_ROOT / "scenarios"

SCENARIO_PRESETS: list[tuple[str, str, str]] = [
    ("awakening", "Day 1 blank-slate — agents discover each other", "scenarios/awakening.yaml"),
    ("tool-coverage", "Exercise all 19 tools end-to-end", "scenarios/tool_coverage.yaml"),
    ("full-day", "Full scripted day with standup, building, reflection", "scenarios/full_day.yaml"),
    ("autonomous", "Trigger-driven — no script, agents decide what to do", ""),
]


def _discover_scenarios() -> list[tuple[str, str, str]]:
    """Return scenario presets plus any extra YAML files in scenarios/."""
    known_files = {p[2] for p in SCENARIO_PRESETS}
    extra = []
    if SCENARIOS_DIR.exists():
        for f in sorted(SCENARIOS_DIR.glob("*.yaml")):
            rel = f"scenarios/{f.name}"
            if rel not in known_files:
                name = f.stem.replace("_", "-")
                extra.append((name, f"Custom scenario: {f.name}", rel))
    return SCENARIO_PRESETS + extra


def pick_scenario() -> tuple[str, str | None]:
    """Interactive scenario picker. Returns (name, seed_file_or_None)."""
    scenarios = _discover_scenarios()
    console.print()
    console.print("[bold bright_cyan]Simulation scenarios:[/bold bright_cyan]")
    for i, (name, desc, _) in enumerate(scenarios, 1):
        console.print(f"  [bold]{i}[/bold]  [bright_white]{name}[/bright_white] — {desc}")
    console.print()

    try:
        choice = console.input(f"[bold]Pick a scenario (1-{len(scenarios)}): [/bold]").strip()
    except (EOFError, KeyboardInterrupt):
        return ("", None)

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(scenarios):
            name, _, seed = scenarios[idx]
            return (name, seed if seed else None)
    except ValueError:
        # Try matching by name
        for name, _, seed in scenarios:
            if choice.lower() == name.lower():
                return (name, seed if seed else None)

    console.print("[red]Invalid choice[/red]")
    return pick_scenario()


def pick_duration() -> str:
    """Pick simulated duration for autonomous mode."""
    console.print()
    console.print("  [bold]1[/bold]  12 hours")
    console.print("  [bold]2[/bold]  1 day")
    console.print("  [bold]3[/bold]  3 days")
    console.print("  [bold]4[/bold]  7 days (full week)")
    console.print("  [bold]5[/bold]  Custom")
    console.print()

    try:
        choice = console.input("[bold]Simulated duration (1-5, default: 1 day): [/bold]").strip()
    except (EOFError, KeyboardInterrupt):
        return "1d"

    mapping = {"1": "12h", "2": "1d", "3": "3d", "4": "7d"}
    if choice in mapping:
        return mapping[choice]
    if choice == "5":
        try:
            custom = console.input("[bold]Duration (e.g. 2d, 6h, 1d12h): [/bold]").strip()
            return custom or "1d"
        except (EOFError, KeyboardInterrupt):
            return "1d"
    return "1d"


def pick_max_cost() -> float:
    """Pick cost limit."""
    console.print()
    try:
        cost_str = console.input(
            "[bold]Max cost in $ (Enter for $10.00): [/bold]"
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return 10.0
    if not cost_str:
        return 10.0
    try:
        return float(cost_str.replace("$", ""))
    except ValueError:
        return 10.0


def run_sim_orchestrator(
    *,
    name: str,
    seed_file: str | None = None,
    duration: str | None = None,
    speed_multiplier: float = 0,
    max_cost: float = 10.0,
    verbose: bool = False,
    dry_run: bool = False,
) -> None:
    """Run a simulation via the new orchestrator (run_simulation.py)."""
    import subprocess

    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "run_simulation.py"),
        "--name", name,
        "--max-cost", str(max_cost),
    ]
    if seed_file:
        cmd += ["--seed-file", seed_file]
    if duration:
        cmd += ["--duration", duration]
    if speed_multiplier > 0:
        cmd += ["--speed-multiplier", str(speed_multiplier)]
    if verbose:
        cmd.append("--verbose")
    if dry_run:
        cmd.append("--dry-run")

    mode = "seeded" if seed_file else "autonomous"
    console.print(f"\n[bold bright_cyan]Starting {mode} simulation: {name}[/bold bright_cyan]")
    if seed_file:
        console.print(f"[dim]Scenario: {seed_file}[/dim]")
    else:
        console.print(f"[dim]Duration: {duration} | Speed: {speed_multiplier}x[/dim]")
    console.print(f"[dim]Max cost: ${max_cost:.2f}[/dim]\n")

    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        console.print("\n[dim]Simulation interrupted.[/dim]")


def run_eval_cli(
    *,
    simulation_name: str | None = None,
    simulation_id: str | None = None,
    suite: str = "full",
    categories: str | None = None,
    view_last: bool = False,
    verbose: bool = False,
) -> None:
    """Run evals via run_eval.py, resolving simulation by name if needed."""
    import asyncio

    async def _resolve_sim_id() -> str | None:
        if simulation_id:
            return simulation_id
        if not simulation_name:
            return None
        # Look up by name
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.simulation_repo import SimulationRepo

        svc = await bootstrap_services()
        sim_repo = SimulationRepo(svc.db)
        sims = await sim_repo.list(limit=100)
        await shutdown_services(svc)
        for s in sims:
            if s.name == simulation_name:
                return str(s.id)
        return None

    resolved_id = asyncio.run(_resolve_sim_id())
    if not resolved_id:
        console.print(f"[red]Could not find simulation '{simulation_name or simulation_id}'[/red]")

        # List available simulations
        import asyncio as _asyncio

        async def _list() -> None:
            from core.bootstrap import bootstrap_services, shutdown_services
            from core.repos.simulation_repo import SimulationRepo

            svc = await bootstrap_services()
            sim_repo = SimulationRepo(svc.db)
            sims = await sim_repo.list(limit=20)
            await shutdown_services(svc)
            if sims:
                console.print("\n[bold]Available simulations:[/bold]")
                for s in sims:
                    console.print(f"  {s.name} — {s.status} ({s.id})")
            else:
                console.print("[dim]No simulations found. Run one first.[/dim]")

        _asyncio.run(_list())
        return

    import subprocess

    cmd = [
        sys.executable, str(PROJECT_ROOT / "scripts" / "run_eval.py"),
        "--simulation-id", resolved_id,
        "--suite", suite,
    ]
    if categories:
        cmd += ["--categories", categories]
    if view_last:
        cmd.append("--view-last")
    if verbose:
        cmd.append("--verbose")

    console.print(f"\n[bold bright_cyan]Running {suite} eval suite[/bold bright_cyan]")
    console.print(f"[dim]Simulation: {simulation_name or resolved_id}[/dim]\n")

    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        console.print("\n[dim]Eval interrupted.[/dim]")


def run_coverage_check(simulation_name: str | None = None) -> None:
    """Run tool coverage check via check_tool_coverage.py."""
    import subprocess

    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "check_tool_coverage.py")]
    if simulation_name:
        cmd += ["--name", simulation_name]
    else:
        console.print("[red]Simulation name required for coverage check[/red]")
        return

    console.print(f"\n[bold bright_cyan]Checking tool coverage: {simulation_name}[/bold bright_cyan]\n")

    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        console.print("\n[dim]Coverage check interrupted.[/dim]")


def pick_sim_name() -> str | None:
    """Optionally name the simulation."""
    console.print()
    try:
        name = console.input(
            "[bold]Simulation name? (Enter to auto-generate): [/bold]"
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return name if name else None


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

    # ── Quick-launch: pnpm chat sim ... ──
    if args and args[0].lower() == "sim":
        sim_args = args[1:]
        verbose = "-v" in sim_args or "--verbose" in sim_args
        dry_run = "--dry-run" in sim_args

        # Check for scenario preset: pnpm chat sim awakening
        scenario_names = {s[0]: s[2] for s in _discover_scenarios()}

        if sim_args and sim_args[0].lower() in scenario_names:
            preset_name = sim_args[0].lower()
            seed = scenario_names[preset_name]
            # Parse optional flags
            max_cost = 10.0
            name = preset_name
            speed_multiplier = 0.0
            duration = None
            i = 1
            while i < len(sim_args):
                arg = sim_args[i]
                if arg == "--max-cost" and i + 1 < len(sim_args):
                    max_cost = float(sim_args[i + 1]); i += 2
                elif arg == "--name" and i + 1 < len(sim_args):
                    name = sim_args[i + 1]; i += 2
                elif arg in ("--speed", "--speed-multiplier") and i + 1 < len(sim_args):
                    speed_multiplier = float(sim_args[i + 1]); i += 2
                elif arg == "--duration" and i + 1 < len(sim_args):
                    duration = sim_args[i + 1]; i += 2
                else:
                    i += 1

            if preset_name == "autonomous":
                if not duration:
                    duration = "1d"
                if speed_multiplier == 0:
                    speed_multiplier = 42.0
                run_sim_orchestrator(
                    name=name, duration=duration,
                    speed_multiplier=speed_multiplier,
                    max_cost=max_cost, verbose=verbose, dry_run=dry_run,
                )
            else:
                run_sim_orchestrator(
                    name=name, seed_file=seed,
                    speed_multiplier=speed_multiplier,
                    max_cost=max_cost, verbose=verbose, dry_run=dry_run,
                )
            return

        # Parse general sim flags
        seed_file = None
        duration = None
        speed_multiplier = 0.0
        max_cost = 10.0
        name = None
        i = 0
        while i < len(sim_args):
            arg = sim_args[i]
            if arg == "--seed-file" and i + 1 < len(sim_args):
                seed_file = sim_args[i + 1]; i += 2
            elif arg == "--duration" and i + 1 < len(sim_args):
                duration = sim_args[i + 1]; i += 2
            elif arg in ("--speed", "--speed-multiplier") and i + 1 < len(sim_args):
                speed_multiplier = float(sim_args[i + 1]); i += 2
            elif arg == "--max-cost" and i + 1 < len(sim_args):
                max_cost = float(sim_args[i + 1]); i += 2
            elif arg == "--name" and i + 1 < len(sim_args):
                name = sim_args[i + 1]; i += 2
            elif arg in ("-v", "--verbose", "--dry-run"):
                i += 1
            else:
                i += 1

        # If no flags at all, show interactive picker
        if not seed_file and not duration and not name:
            print_banner()
            scenario_name, seed_file = pick_scenario()
            if not scenario_name:
                console.print("[dim]Goodbye.[/dim]")
                return
            name = pick_sim_name() or scenario_name
            max_cost = pick_max_cost()

            if seed_file is None:
                # Autonomous mode
                dur = pick_duration()
                speed_multiplier = 42.0
                run_sim_orchestrator(
                    name=name, duration=dur,
                    speed_multiplier=speed_multiplier,
                    max_cost=max_cost, verbose=verbose, dry_run=dry_run,
                )
            else:
                run_sim_orchestrator(
                    name=name, seed_file=seed_file,
                    max_cost=max_cost, verbose=verbose, dry_run=dry_run,
                )
            return

        if not name:
            name = f"sim-{seed_file or 'auto'}"

        run_sim_orchestrator(
            name=name, seed_file=seed_file, duration=duration,
            speed_multiplier=speed_multiplier,
            max_cost=max_cost, verbose=verbose, dry_run=dry_run,
        )
        return

    # ── Quick-launch: pnpm chat report ... ──
    if args and args[0].lower() == "report":
        import subprocess

        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "report_simulation.py")] + args[1:]
        try:
            subprocess.run(cmd, check=False)
        except KeyboardInterrupt:
            console.print("\n[dim]Report cancelled.[/dim]")
        return

    # ── Quick-launch: pnpm chat snapshot ... ──
    if args and args[0].lower() == "snapshot":
        import subprocess

        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "snapshot_memory.py")] + args[1:]
        try:
            subprocess.run(cmd, check=False)
        except KeyboardInterrupt:
            console.print("\n[dim]Snapshot cancelled.[/dim]")
        return

    # ── Quick-launch: pnpm chat restore ... ──
    if args and args[0].lower() == "restore":
        import subprocess

        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "restore_memory.py")] + args[1:]
        try:
            subprocess.run(cmd, check=False)
        except KeyboardInterrupt:
            console.print("\n[dim]Restore cancelled.[/dim]")
        return

    # ── Quick-launch: pnpm chat eval ... ──
    if args and args[0].lower() == "eval":
        eval_args = args[1:]
        verbose = "-v" in eval_args or "--verbose" in eval_args

        if not eval_args or eval_args[0].startswith("-"):
            # No sim name — list categories or show help
            if "--list" in eval_args or "--list-categories" in eval_args:
                import subprocess
                subprocess.run([
                    sys.executable, str(PROJECT_ROOT / "scripts" / "run_eval.py"),
                    "--list-categories",
                ], check=False)
                return

            console.print("[yellow]Usage: pnpm chat eval <simulation-name> [--suite quick|full] [--view-last][/yellow]")
            console.print("[dim]  pnpm chat eval --list          List eval categories[/dim]")
            return

        sim_name = eval_args[0]
        suite = "full"
        categories = None
        view_last = False
        sim_id = None
        i = 1
        while i < len(eval_args):
            arg = eval_args[i]
            if arg == "--suite" and i + 1 < len(eval_args):
                suite = eval_args[i + 1]; i += 2
            elif arg == "--categories" and i + 1 < len(eval_args):
                categories = eval_args[i + 1]; i += 2
            elif arg == "--id" and i + 1 < len(eval_args):
                sim_id = eval_args[i + 1]; i += 2
            elif arg == "--view-last":
                view_last = True; i += 1
            else:
                i += 1

        run_eval_cli(
            simulation_name=sim_name if not sim_id else None,
            simulation_id=sim_id,
            suite=suite,
            categories=categories,
            view_last=view_last,
            verbose=verbose,
        )
        return

    # ── Quick-launch: pnpm chat coverage <name> ──
    if args and args[0].lower() == "coverage":
        sim_name = args[1] if len(args) > 1 else None
        run_coverage_check(sim_name)
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

    if mode == "simulate":
        scenario_name, seed_file = pick_scenario()
        if not scenario_name:
            console.print("[dim]Goodbye.[/dim]")
            return
        sim_name = pick_sim_name() or scenario_name
        max_cost = pick_max_cost()

        if seed_file is None:
            # Autonomous mode
            dur = pick_duration()
            run_sim_orchestrator(
                name=sim_name, duration=dur,
                speed_multiplier=42.0,
                max_cost=max_cost, verbose=verbose,
            )
        else:
            run_sim_orchestrator(
                name=sim_name, seed_file=seed_file,
                max_cost=max_cost, verbose=verbose,
            )
        return

    # Single-agent modes need an agent pick
    agent_id = pick_agent()
    if not agent_id:
        console.print("[dim]Goodbye.[/dim]")
        return

    run_single(agent_id, mode, verbose=verbose, tts=tts)


if __name__ == "__main__":
    main()

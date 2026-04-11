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


def _load_agents() -> list[tuple[str, str, str, str]]:
    """Load agent list from registry configs."""
    from core.agent_registry import AgentRegistry

    registry = AgentRegistry(redis_client=None)
    agents_map = registry._load_all_from_yaml()
    return [
        (a.id, a.display_name, a.color_rich, a.role)
        for a in agents_map.values()
    ]


AGENTS = _load_agents()

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

    # Exclude management and alpha from default conversation participants
    conversational = [(i, a) for i, a in enumerate(AGENTS, 1) if a[0] not in ("management", "alpha")]
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
    no_management: bool = False,
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


# ── Simulation orchestrator integration ──────────────────────

SCENARIOS_DIR = PROJECT_ROOT / "scenarios"

SCENARIO_PRESETS: list[tuple[str, str, str]] = [
    ("awakening", "Day 1 blank-slate — agents discover each other", "scenarios/awakening.yaml"),
    ("tool-coverage", "Exercise all 19 tools end-to-end", "scenarios/tool_coverage.yaml"),
    ("full-day", "Full scripted day with standup, building, reflection", "scenarios/full_day.yaml"),
    ("autonomous", "Trigger-driven — no script, agents decide what to do", ""),
    ("initiative-test", "Test initiative wiring — who starts conversations?", "scenarios/initiative_test.yaml"),
    ("goal-generation-test", "Test autonomous goal generation in reflections", "scenarios/goal_generation_test.yaml"),
    ("budget-crisis", "Test economic behavior under budget pressure", "scenarios/budget_crisis.yaml"),
    ("topic-exhaustion-test", "Test cross-conversation memory & topic exhaustion", "scenarios/topic_exhaustion_test.yaml"),
    ("novelty-injection-test", "Test random event generation & reactions", "scenarios/novelty_injection_test.yaml"),
    ("dream-smoke-test", "Minimal dream smoke test — verify goals+journal are created", "scenarios/dream_smoke_test.yaml"),
    ("dream-cycle-test", "Test dream system & creative output", "scenarios/dream_cycle_test.yaml"),
    ("faction-emergence-test", "Test alliance formation over 48h", "scenarios/faction_emergence_test.yaml"),
    ("full-evolution-7d", "7-day full integration — all features", "scenarios/full_evolution_7d.yaml"),
    ("dress-rehearsal", "24h real-time streaming readiness test", "scenarios/dress_rehearsal.yaml"),
    ("first-48h", "Awakening + dress rehearsal — full first 2 days", "scenarios/first_48h.yaml"),
    ("ab-test", "Standardized baseline for A/B feature comparison", "scenarios/ab_test.yaml"),
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
    world_sim: bool = False,
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
    if world_sim:
        cmd.append("--world-sim")

    if max_cost < 0:
        console.print("[red]--max-cost cannot be negative[/red]")
        return
    if speed_multiplier < 0:
        console.print("[red]--speed-multiplier cannot be negative[/red]")
        return

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
        if simulation_name or simulation_id:
            console.print(f"[red]Could not find simulation '{simulation_name or simulation_id}'[/red]")
        else:
            console.print("[yellow]No simulation specified. Usage:[/yellow]")
            console.print("[dim]  pnpm chat eval <simulation-name>[/dim]")
            console.print("[dim]  pnpm chat eval --id <uuid>[/dim]")

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


def _create_issues_from_eval(
    *,
    simulation_name: str | None = None,
    simulation_id: str | None = None,
    threshold: int = 60,
) -> None:
    """Create GitHub issues from the latest eval run's low-scoring categories."""
    import asyncio

    async def _run() -> None:
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.eval_repo import EvalRepo
        from core.repos.simulation_repo import SimulationRepo
        from core.eval.issue_generator import EvalIssueGenerator

        svc = await bootstrap_services()
        try:
            # Resolve simulation ID
            sim_repo = SimulationRepo(svc.db)
            resolved_id = simulation_id
            if not resolved_id and simulation_name:
                sims = await sim_repo.list(limit=100)
                for s in sims:
                    if s.name == simulation_name:
                        resolved_id = str(s.id)
                        break
            if not resolved_id:
                console.print("[red]Could not resolve simulation for issue creation[/red]")
                return

            import uuid as uuid_mod
            eval_repo = EvalRepo(svc.db)
            latest_run = await eval_repo.get_latest_eval_run(uuid_mod.UUID(resolved_id))
            if not latest_run:
                console.print("[red]No eval runs found for this simulation[/red]")
                return

            console.print(f"\n[bold bright_cyan]Creating issues from eval {str(latest_run.id)[:8]}[/bold bright_cyan]")
            console.print(f"[dim]Threshold: {threshold}/100 (categories scoring below will get issues)[/dim]\n")

            generator = EvalIssueGenerator(
                db=svc.db,
                eval_repo=eval_repo,
                eval_run_id=latest_run.id,
                score_threshold=threshold,
            )
            issues = await generator.generate_and_create()

            if not issues:
                console.print("[green]All categories scored above threshold — no issues created.[/green]")
                return

            for issue in issues:
                if issue["status"] == "created":
                    console.print(f"  [green]Created:[/green] {issue['title']} → {issue['url']}")
                elif issue["status"] == "skipped":
                    console.print(f"  [yellow]Skipped:[/yellow] {issue['title']} ({issue.get('reason', '')})")
                else:
                    console.print(f"  [red]Error:[/red] {issue['title']} ({issue.get('reason', '')})")

            created = sum(1 for i in issues if i["status"] == "created")
            console.print(f"\n[bold]{created} issue(s) created, {len(issues) - created} skipped/errored.[/bold]")
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


def run_coverage_check(
    simulation_name: str | None = None,
    simulation_id: str | None = None,
) -> None:
    """Run tool coverage check via check_tool_coverage.py."""
    import subprocess

    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "check_tool_coverage.py")]
    if simulation_id:
        cmd += ["--simulation-id", simulation_id]
    elif simulation_name:
        cmd += ["--name", simulation_name]
    else:
        console.print("[yellow]No simulation specified. Usage:[/yellow]")
        console.print("[dim]  pnpm chat coverage <simulation-name>[/dim]")
        console.print("[dim]  pnpm chat coverage --id <uuid>[/dim]")
        return

    label = simulation_name or simulation_id
    console.print(f"\n[bold bright_cyan]Checking tool coverage: {label}[/bold bright_cyan]\n")

    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        console.print("\n[dim]Coverage check interrupted.[/dim]")


def _sim_list(args: list[str]) -> None:
    """List past simulations: pnpm chat sim list [--status running|completed|failed]"""
    import asyncio

    status_filter = None
    limit = 20
    i = 0
    while i < len(args):
        if args[i] == "--status" and i + 1 < len(args):
            status_filter = args[i + 1]; i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    async def _run() -> None:
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.simulation_repo import SimulationRepo

        svc = await bootstrap_services()
        try:
            sim_repo = SimulationRepo(svc.db)
            sims = await sim_repo.list(status=status_filter, limit=limit)
            total = await sim_repo.count(status=status_filter)

            if not sims:
                console.print("[dim]No simulations found.[/dim]")
                return

            table = Table(show_header=True, border_style="dim", padding=(0, 1))
            table.add_column("Name", style="bold", width=30)
            table.add_column("Status", width=12)
            table.add_column("Agents", width=8)
            table.add_column("Convos", width=8)
            table.add_column("Cost", width=10)
            table.add_column("Started", width=20)
            table.add_column("ID", style="dim", width=36)

            status_colors = {
                "running": "green",
                "completed": "blue",
                "failed": "red",
                "cancelled": "yellow",
            }

            for s in sims:
                status_color = status_colors.get(s.status, "white")
                agent_count = len(s.agents_participated) if s.agents_participated else 0
                started = s.started_at.strftime("%Y-%m-%d %H:%M") if s.started_at else "—"
                cost = f"${float(s.total_cost):.4f}" if s.total_cost else "$0"
                table.add_row(
                    s.name,
                    f"[{status_color}]{s.status}[/{status_color}]",
                    str(agent_count),
                    str(s.total_conversations),
                    cost,
                    started,
                    str(s.id),
                )

            console.print(f"\n[bold bright_cyan]Simulations[/bold bright_cyan] ({total} total)\n")
            console.print(table)
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


async def _resolve_sim(sim_repo: Any, target: str) -> Any:
    """Find a simulation by UUID or name. Returns None if not found."""
    import uuid as uuid_mod
    sim = None
    try:
        sim = await sim_repo.get(uuid_mod.UUID(target))
    except ValueError:
        pass
    if sim is None:
        sim = await sim_repo.get_by_name(target)
    return sim


def _sim_view(args: list[str]) -> None:
    """View a specific simulation: pnpm chat sim view <name-or-id>"""
    import asyncio

    if not args:
        console.print("[red]Usage: pnpm chat sim view <name-or-id>[/red]")
        return

    target = args[0]

    async def _run() -> None:
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.simulation_repo import SimulationRepo
        from core.repos.cost_repo import CostRepo
        import uuid as uuid_mod

        svc = await bootstrap_services()
        try:
            sim_repo = SimulationRepo(svc.db)

            sim = await _resolve_sim(sim_repo, target)
            if sim is None:
                console.print(f"[red]Simulation not found: {target}[/red]")
                return

            # Display
            console.print(f"\n[bold bright_cyan]Simulation: {sim.name}[/bold bright_cyan]")
            console.print(f"  [bold]ID:[/bold] {sim.id}")
            console.print(f"  [bold]Status:[/bold] {sim.status}")
            console.print(f"  [bold]Started:[/bold] {sim.started_at}")
            console.print(f"  [bold]Completed:[/bold] {sim.completed_at or '—'}")
            console.print(f"  [bold]Agents:[/bold] {', '.join(sim.agents_participated or [])}")
            console.print(f"  [bold]Conversations:[/bold] {sim.total_conversations}")
            console.print(f"  [bold]Turns:[/bold] {sim.total_turns}")
            console.print(f"  [bold]Tokens:[/bold] {sim.total_tokens:,}")
            console.print(f"  [bold]Cost:[/bold] ${float(sim.total_cost):.4f}")
            console.print(f"  [bold]Artifacts:[/bold] {sim.total_artifacts}")
            console.print(f"  [bold]Management Flags:[/bold] {sim.total_management_flags}")

            if sim.config:
                console.print(f"  [bold]Config:[/bold]")
                for k, v in sim.config.items():
                    console.print(f"    {k}: {v}")
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


def _sim_compare(args: list[str]) -> None:
    """Compare two simulations: pnpm chat sim compare <id-a> <id-b>"""
    import asyncio

    if len(args) < 2:
        console.print("[red]Usage: pnpm chat sim compare <id-or-name-a> <id-or-name-b>[/red]")
        return

    async def _run() -> None:
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.simulation_repo import SimulationRepo

        svc = await bootstrap_services()
        try:
            sim_repo = SimulationRepo(svc.db)
            sim_a = await _resolve_sim(sim_repo, args[0])
            sim_b = await _resolve_sim(sim_repo, args[1])

            if not sim_a:
                console.print(f"[red]Simulation A not found: {args[0]}[/red]"); return
            if not sim_b:
                console.print(f"[red]Simulation B not found: {args[1]}[/red]"); return

            table = Table(show_header=True, border_style="dim", padding=(0, 1))
            table.add_column("Metric", style="bold", width=25)
            table.add_column(sim_a.name, width=25)
            table.add_column(sim_b.name, width=25)

            comparisons = [
                ("Status", sim_a.status, sim_b.status),
                ("Agents", str(len(sim_a.agents_participated or [])), str(len(sim_b.agents_participated or []))),
                ("Conversations", str(sim_a.total_conversations), str(sim_b.total_conversations)),
                ("Turns", str(sim_a.total_turns), str(sim_b.total_turns)),
                ("Tokens", f"{sim_a.total_tokens:,}", f"{sim_b.total_tokens:,}"),
                ("Cost", f"${float(sim_a.total_cost):.4f}", f"${float(sim_b.total_cost):.4f}"),
                ("Artifacts", str(sim_a.total_artifacts), str(sim_b.total_artifacts)),
                ("Mgmt Flags", str(sim_a.total_management_flags), str(sim_b.total_management_flags)),
            ]
            for label, va, vb in comparisons:
                table.add_row(label, va, vb)

            console.print(f"\n[bold bright_cyan]Simulation Comparison[/bold bright_cyan]\n")
            console.print(table)
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


def _sim_delete(args: list[str]) -> None:
    """Delete a simulation: pnpm chat sim delete <id-or-name>"""
    import asyncio

    if not args:
        console.print("[red]Usage: pnpm chat sim delete <id-or-name>[/red]")
        return

    target = args[0]
    force = "--force" in args

    async def _run() -> None:
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.simulation_repo import SimulationRepo
        import uuid as uuid_mod

        svc = await bootstrap_services()
        try:
            sim_repo = SimulationRepo(svc.db)
            sim = await _resolve_sim(sim_repo, target)
            if sim is None:
                console.print(f"[red]Simulation not found: {target}[/red]")
                return

            if sim.is_live:
                console.print("[red]Cannot delete the live simulation.[/red]")
                return

            if sim.status == "running":
                console.print("[red]Cannot delete a running simulation. Stop it first.[/red]")
                return

            if not force:
                try:
                    confirm = console.input(
                        f"[bold yellow]Delete simulation '{sim.name}' ({sim.id})? [y/N]: [/bold yellow]"
                    ).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    return
                if confirm != "y":
                    console.print("[dim]Cancelled.[/dim]")
                    return

            deleted = await sim_repo.delete(sim.id)
            if deleted:
                console.print(f"[green]Deleted simulation: {sim.name}[/green]")
            else:
                console.print(f"[red]Failed to delete simulation (may have FK constraints).[/red]")
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


def _sim_clone(args: list[str]) -> None:
    """Clone a simulation: pnpm chat sim clone <id-or-name> [--name new-name]"""
    import asyncio

    if not args:
        console.print("[red]Usage: pnpm chat sim clone <id-or-name> [--name new-name][/red]")
        return

    target = args[0]
    clone_name = None
    i = 1
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            clone_name = args[i + 1]; i += 2
        else:
            i += 1

    async def _run() -> None:
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.simulation_repo import SimulationRepo
        from core.simulation.snapshot import SimulationSnapshotExporter, SimulationSnapshotImporter
        from core.models import SimulationCreate
        import time as _time

        svc = await bootstrap_services()
        try:
            sim_repo = SimulationRepo(svc.db)
            sim = await _resolve_sim(sim_repo, target)
            if sim is None:
                console.print(f"[red]Simulation not found: {target}[/red]")
                return

            console.print(f"[bold bright_cyan]Cloning simulation: {sim.name}[/bold bright_cyan]")

            # Export
            exporter = SimulationSnapshotExporter(svc.db)
            console.print("[dim]Exporting state...[/dim]")
            snapshot_data = await exporter.export(str(sim.id))

            # Create new sim
            name = clone_name or f"clone-{sim.name}-{_time.strftime('%Y%m%d-%H%M%S')}"
            new_sim = await sim_repo.create(SimulationCreate(
                name=name,
                description=f"Cloned from {sim.name} ({sim.id})",
                config={"source": "clone", "source_simulation_id": str(sim.id)},
                agents_participated=list(snapshot_data.get("agents", {}).keys()),
            ))

            # Import
            importer = SimulationSnapshotImporter(svc.db)
            console.print("[dim]Importing state...[/dim]")
            result = await importer.restore(snapshot_data, str(new_sim.id))

            console.print(f"\n[green]Cloned successfully![/green]")
            console.print(f"  [bold]New simulation:[/bold] {name}")
            console.print(f"  [bold]ID:[/bold] {new_sim.id}")
            console.print(f"  [bold]Agents:[/bold] {len(result.agents_restored)}")
            console.print(f"  [bold]Core memories:[/bold] {result.core_memories_restored}")
            console.print(f"  [bold]Recall memories:[/bold] {result.recall_memories_restored}")
            console.print(f"  [bold]Journal entries:[/bold] {result.journal_entries_restored}")
            console.print(f"  [bold]Goals:[/bold] {result.goals_restored}")
            console.print(f"  [bold]Agent states:[/bold] {result.agent_states_restored}")
            console.print(f"  [bold]Accounts:[/bold] {result.agent_accounts_restored}")
            console.print(f"  [bold]World chunks:[/bold] {result.world_chunks_restored}")
            console.print(f"  [bold]Relationships:[/bold] {result.relationships_restored}")
            console.print(f"  [bold]Transactions:[/bold] {result.transactions_restored}")
            console.print(f"  [bold]Challenges:[/bold] {result.challenges_restored}")
            console.print(f"  [bold]World events:[/bold] {result.world_events_restored}")
            console.print(f"  [bold]Alliances:[/bold] {result.alliances_restored}")
            if result.warnings:
                console.print(f"  [yellow]Warnings:[/yellow] {len(result.warnings)}")
                for w in result.warnings[:5]:
                    console.print(f"    - {w}")
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


def _sim_export(args: list[str]) -> None:
    """Export full simulation snapshot: pnpm chat sim export <id-or-name> [--output file.json]"""
    import asyncio

    if not args:
        console.print("[red]Usage: pnpm chat sim export <id-or-name> [--output file.json][/red]")
        return

    target = args[0]
    output_path = None
    i = 1
    while i < len(args):
        if args[i] in ("--output", "-o") and i + 1 < len(args):
            output_path = args[i + 1]; i += 2
        else:
            i += 1

    async def _run() -> None:
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.simulation_repo import SimulationRepo
        from core.simulation.snapshot import SimulationSnapshotExporter
        import json as _json

        svc = await bootstrap_services()
        try:
            sim_repo = SimulationRepo(svc.db)
            sim = await _resolve_sim(sim_repo, target)
            if sim is None:
                console.print(f"[red]Simulation not found: {target}[/red]")
                return

            console.print(f"[bold bright_cyan]Exporting simulation: {sim.name}[/bold bright_cyan]")
            exporter = SimulationSnapshotExporter(svc.db)
            snapshot_data = await exporter.export(str(sim.id))

            out = output_path or f"snapshots/full-{sim.name}.json"
            from pathlib import Path
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(_json.dumps(snapshot_data, indent=2, default=str))

            agent_count = len(snapshot_data.get("agents", {}))
            chunk_count = len(snapshot_data.get("world_chunks", []))
            rel_count = len(snapshot_data.get("relationships", []))
            goal_count = sum(len(g) for g in snapshot_data.get("agent_goals", {}).values())
            tx_count = len(snapshot_data.get("transactions", []))
            challenge_count = len(snapshot_data.get("challenges", []))
            event_count = len(snapshot_data.get("world_events", []))
            alliance_count = len(snapshot_data.get("alliances", []))

            console.print(f"\n[green]Exported to {out}[/green]")
            console.print(f"  [bold]Agents:[/bold] {agent_count}")
            console.print(f"  [bold]World chunks:[/bold] {chunk_count}")
            console.print(f"  [bold]World events:[/bold] {event_count}")
            console.print(f"  [bold]Relationships:[/bold] {rel_count}")
            console.print(f"  [bold]Goals:[/bold] {goal_count}")
            console.print(f"  [bold]Transactions:[/bold] {tx_count}")
            console.print(f"  [bold]Challenges:[/bold] {challenge_count}")
            console.print(f"  [bold]Alliances:[/bold] {alliance_count}")
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


def _sim_import(args: list[str]) -> None:
    """Import a full simulation snapshot: pnpm chat sim import <file.json> [--name name] [--clear]"""
    import asyncio

    if not args:
        console.print("[red]Usage: pnpm chat sim import <file.json> [--name name] [--clear][/red]")
        return

    filepath = args[0]
    sim_name = None
    clear_first = False
    i = 1
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            sim_name = args[i + 1]; i += 2
        elif args[i] == "--clear":
            clear_first = True; i += 1
        else:
            i += 1

    async def _run() -> None:
        from pathlib import Path
        import json as _json
        import time as _time
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.repos.simulation_repo import SimulationRepo
        from core.simulation.snapshot import SimulationSnapshotImporter
        from core.models import SimulationCreate

        snapshot_path = Path(filepath)
        if not snapshot_path.exists():
            console.print(f"[red]File not found: {filepath}[/red]")
            return

        try:
            snapshot_data = _json.loads(snapshot_path.read_text())
        except Exception as exc:
            console.print(f"[red]Failed to parse JSON: {exc}[/red]")
            return

        svc = await bootstrap_services()
        try:
            sim_repo = SimulationRepo(svc.db)

            name = sim_name or f"import-{_time.strftime('%Y%m%d-%H%M%S')}"
            source_id = snapshot_data.get("source_simulation_id", "unknown")
            agent_keys = list(snapshot_data.get("agents", {}).keys())

            new_sim = await sim_repo.create(SimulationCreate(
                name=name,
                description=f"Imported from {snapshot_path.name} (source: {source_id})",
                config={"source": "import", "file": str(snapshot_path.name)},
                agents_participated=agent_keys,
            ))

            importer = SimulationSnapshotImporter(svc.db)
            console.print(f"[dim]Importing into simulation '{name}'...[/dim]")
            result = await importer.restore(
                snapshot_data, str(new_sim.id), clear_first=clear_first,
            )

            console.print(f"\n[green]Imported successfully![/green]")
            console.print(f"  [bold]Simulation:[/bold] {name}")
            console.print(f"  [bold]ID:[/bold] {new_sim.id}")
            console.print(f"  [bold]Agents:[/bold] {len(result.agents_restored)}")
            console.print(f"  [bold]Core memories:[/bold] {result.core_memories_restored}")
            console.print(f"  [bold]Recall memories:[/bold] {result.recall_memories_restored}")
            console.print(f"  [bold]Journal entries:[/bold] {result.journal_entries_restored}")
            console.print(f"  [bold]Goals:[/bold] {result.goals_restored}")
            console.print(f"  [bold]Agent states:[/bold] {result.agent_states_restored}")
            console.print(f"  [bold]Accounts:[/bold] {result.agent_accounts_restored}")
            console.print(f"  [bold]World chunks:[/bold] {result.world_chunks_restored}")
            console.print(f"  [bold]Relationships:[/bold] {result.relationships_restored}")
            console.print(f"  [bold]Transactions:[/bold] {result.transactions_restored}")
            console.print(f"  [bold]Challenges:[/bold] {result.challenges_restored}")
            console.print(f"  [bold]World events:[/bold] {result.world_events_restored}")
            console.print(f"  [bold]Alliances:[/bold] {result.alliances_restored}")
            if result.warnings:
                console.print(f"  [yellow]Warnings:[/yellow] {len(result.warnings)}")
                for w in result.warnings[:10]:
                    console.print(f"    - {w}")
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


def _sim_seed(args: list[str]) -> None:
    """Seed a new simulation from a template: pnpm chat sim seed [template-name] [--name name]"""
    import asyncio
    from pathlib import Path

    seeds_dir = PROJECT_ROOT / "scenarios" / "seeds"
    available = list(seeds_dir.glob("*.json")) if seeds_dir.exists() else []

    if not available:
        console.print("[red]No seed templates found in scenarios/seeds/[/red]")
        return

    # Resolve template
    template_path = None
    sim_name = None
    clear_first = False
    i = 0
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            sim_name = args[i + 1]; i += 2
        elif args[i] == "--clear":
            clear_first = True; i += 1
        elif not args[i].startswith("--") and template_path is None:
            # Try to match template name
            target = args[i].lower().replace(".json", "")
            for p in available:
                if p.stem.lower() == target:
                    template_path = p
                    break
            if template_path is None:
                console.print(f"[red]Template not found: {args[i]}[/red]")
                console.print(f"[dim]Available: {', '.join(p.stem for p in available)}[/dim]")
                return
            i += 1
        else:
            i += 1

    if template_path is None:
        # Interactive picker
        console.print("\n[bold bright_cyan]Available seed templates:[/bold bright_cyan]")
        for idx, p in enumerate(available, 1):
            console.print(f"  [bold]{idx}[/bold]  {p.stem}")
        console.print()
        try:
            choice = console.input(f"[bold]Pick a template (1-{len(available)}): [/bold]").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(available):
                template_path = available[idx]
            else:
                console.print("[red]Invalid choice[/red]")
                return
        except (EOFError, KeyboardInterrupt, ValueError):
            return

    # Delegate to import
    import_args = [str(template_path)]
    if sim_name:
        import_args += ["--name", sim_name]
    else:
        import_args += ["--name", f"seed-{template_path.stem}"]
    if clear_first:
        import_args.append("--clear")

    _sim_import(import_args)


def _sim_capture_live(args: list[str]) -> None:
    """Capture the live simulation state: pnpm chat sim capture-live [--output file.json]"""
    import asyncio

    output_path = None
    i = 0
    while i < len(args):
        if args[i] in ("--output", "-o") and i + 1 < len(args):
            output_path = args[i + 1]; i += 2
        else:
            i += 1

    async def _run() -> None:
        from core.bootstrap import bootstrap_services, shutdown_services
        from core.simulation.snapshot import SimulationSnapshotExporter
        from core.constants import LIVE_SIMULATION_ID
        import json as _json
        import time as _time

        svc = await bootstrap_services()
        try:
            console.print("[bold bright_cyan]Capturing live simulation state...[/bold bright_cyan]")
            exporter = SimulationSnapshotExporter(svc.db)
            snapshot_data = await exporter.export(str(LIVE_SIMULATION_ID))

            out = output_path or f"snapshots/live-capture-{_time.strftime('%Y%m%d-%H%M%S')}.json"
            from pathlib import Path
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(_json.dumps(snapshot_data, indent=2, default=str))

            agent_count = len(snapshot_data.get("agents", {}))
            chunk_count = len(snapshot_data.get("world_chunks", []))
            rel_count = len(snapshot_data.get("relationships", []))
            goal_count = sum(len(g) for g in snapshot_data.get("agent_goals", {}).values())
            tx_count = len(snapshot_data.get("transactions", []))
            challenge_count = len(snapshot_data.get("challenges", []))
            event_count = len(snapshot_data.get("world_events", []))

            console.print(f"\n[green]Live state captured to {out}[/green]")
            console.print(f"  [bold]Agents:[/bold] {agent_count}")
            console.print(f"  [bold]World chunks:[/bold] {chunk_count}")
            console.print(f"  [bold]World events:[/bold] {event_count}")
            console.print(f"  [bold]Relationships:[/bold] {rel_count}")
            console.print(f"  [bold]Goals:[/bold] {goal_count}")
            console.print(f"  [bold]Transactions:[/bold] {tx_count}")
            console.print(f"  [bold]Challenges:[/bold] {challenge_count}")
            console.print(f"\n[dim]Use 'pnpm chat sim import {out}' to seed a new simulation from this state.[/dim]")
        finally:
            await shutdown_services(svc)

    asyncio.run(_run())


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
        no_management = False
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
            elif arg == "--no-management":
                no_management = True
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

        run_convo(agents, convo_type, topic, turns, speed, quiet, verbose, no_management)
        return

    # ── Quick-launch: pnpm chat sim ... ──
    if args and args[0].lower() == "sim":
        sim_args = args[1:]

        # ── Sub-commands: list, view, compare, delete, clone ──
        if sim_args and sim_args[0].lower() in ("--list", "list"):
            _sim_list(sim_args[1:])
            return
        if sim_args and sim_args[0].lower() in ("--view", "view"):
            _sim_view(sim_args[1:])
            return
        if sim_args and sim_args[0].lower() in ("--compare", "compare"):
            _sim_compare(sim_args[1:])
            return
        if sim_args and sim_args[0].lower() in ("--delete", "delete"):
            _sim_delete(sim_args[1:])
            return
        if sim_args and sim_args[0].lower() in ("--clone", "clone"):
            _sim_clone(sim_args[1:])
            return
        if sim_args and sim_args[0].lower() in ("--export", "export"):
            _sim_export(sim_args[1:])
            return
        if sim_args and sim_args[0].lower() in ("--import", "import"):
            _sim_import(sim_args[1:])
            return
        if sim_args and sim_args[0].lower() in ("--capture-live", "capture-live"):
            _sim_capture_live(sim_args[1:])
            return
        if sim_args and sim_args[0].lower() in ("--seed", "seed"):
            _sim_seed(sim_args[1:])
            return

        verbose = "-v" in sim_args or "--verbose" in sim_args
        dry_run = "--dry-run" in sim_args
        world_sim = "--world-sim" in sim_args

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
                    world_sim=world_sim,
                )
            else:
                run_sim_orchestrator(
                    name=name, seed_file=seed,
                    speed_multiplier=speed_multiplier,
                    max_cost=max_cost, verbose=verbose, dry_run=dry_run,
                    world_sim=world_sim,
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
            elif arg in ("-v", "--verbose", "--dry-run", "--world-sim"):
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
                    world_sim=world_sim,
                )
            else:
                run_sim_orchestrator(
                    name=name, seed_file=seed_file,
                    max_cost=max_cost, verbose=verbose, dry_run=dry_run,
                    world_sim=world_sim,
                )
            return

        if not name:
            name = f"sim-{seed_file or 'auto'}"

        run_sim_orchestrator(
            name=name, seed_file=seed_file, duration=duration,
            speed_multiplier=speed_multiplier,
            max_cost=max_cost, verbose=verbose, dry_run=dry_run,
            world_sim=world_sim,
        )
        return

    # ── Quick-launch: pnpm chat evolve ... ──
    if args and args[0].lower() == "evolve":
        import subprocess

        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "run_evolution.py")] + args[1:]
        try:
            subprocess.run(cmd, check=False)
        except KeyboardInterrupt:
            console.print("\n[dim]Evolution loop interrupted.[/dim]")
        return

    # ── Quick-launch: pnpm chat seed-config ──
    if args and args[0].lower() == "seed-config":
        import subprocess

        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "seed_config.py")] + args[1:]
        try:
            subprocess.run(cmd, check=False)
        except KeyboardInterrupt:
            console.print("\n[dim]Seed cancelled.[/dim]")
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

        # Check for --list flag
        if "--list" in eval_args or "--list-categories" in eval_args:
            import subprocess
            subprocess.run([
                sys.executable, str(PROJECT_ROOT / "scripts" / "run_eval.py"),
                "--list-categories",
            ], check=False)
            return

        # Parse all flags first
        sim_name = None
        suite = "full"
        categories = None
        view_last = False
        sim_id = None
        create_issues = False
        issue_threshold = 60
        positional_args: list[str] = []
        i = 0
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
            elif arg == "--create-issues":
                create_issues = True; i += 1
            elif arg == "--threshold" and i + 1 < len(eval_args):
                issue_threshold = int(eval_args[i + 1]); i += 2
            elif arg in ("-v", "--verbose"):
                i += 1
            elif not arg.startswith("-"):
                positional_args.append(arg); i += 1
            else:
                i += 1

        if positional_args:
            sim_name = positional_args[0]

        # If no sim name and no --id, list available simulations
        if not sim_name and not sim_id:
            run_eval_cli(simulation_name=None, simulation_id=None)
            return

        run_eval_cli(
            simulation_name=sim_name if not sim_id else None,
            simulation_id=sim_id,
            suite=suite,
            categories=categories,
            view_last=view_last,
            verbose=verbose,
        )

        # After eval run, optionally create GitHub issues from findings
        if create_issues:
            _create_issues_from_eval(
                simulation_name=sim_name,
                simulation_id=sim_id,
                threshold=issue_threshold,
            )
        return

    # ── Quick-launch: pnpm chat coverage <name> | --id <uuid> ──
    if args and args[0].lower() == "coverage":
        coverage_args = args[1:]
        cov_name = None
        cov_id = None
        i = 0
        while i < len(coverage_args):
            if coverage_args[i] == "--id" and i + 1 < len(coverage_args):
                cov_id = coverage_args[i + 1]; i += 2
            elif not coverage_args[i].startswith("-"):
                cov_name = coverage_args[i]; i += 1
            else:
                i += 1
        run_coverage_check(simulation_name=cov_name, simulation_id=cov_id)
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
    no_management = False
    tts = False
    try:
        opts = console.input(
            "[bold]Options (v=verbose, t=TTS voice, "
            "n=no-management, Enter=skip): [/bold]"
        ).strip().lower()
        verbose = "v" in opts
        tts = "t" in opts
        no_management = "n" in opts
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
        run_convo(agents, convo_type, topic, turns, verbose=verbose, no_management=no_management)
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

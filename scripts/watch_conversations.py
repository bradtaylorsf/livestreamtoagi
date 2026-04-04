#!/usr/bin/env python3
"""CLI tool to observe live conversations in the terminal.

Uses `rich` for colorized, formatted output. Subscribes to the EventBus
to render agent messages, speaker selection scores, memory operations,
energy levels, Overseer actions, and token/cost stats in real time.

Usage:
    python scripts/watch_conversations.py
    python scripts/watch_conversations.py --filter rex
    python scripts/watch_conversations.py --quiet
    python scripts/watch_conversations.py --speed 0
    python scripts/watch_conversations.py --test --agents rex,fork --turns 10
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.theme import Theme  # noqa: E402

# ── Agent colors (shared with test_agent.py) ───────────────────

AGENT_COLORS: dict[str, str] = {
    "vera": "bright_magenta",
    "rex": "bright_green",
    "aurora": "bright_cyan",
    "pixel": "bright_yellow",
    "fork": "bright_red",
    "sentinel": "blue",
    "grok": "dark_orange",
    "overseer": "bright_white",
    "alpha": "grey70",
}

AGENT_ROLES: dict[str, str] = {
    "vera": "Showrunner",
    "rex": "Engineer",
    "aurora": "Creative Director",
    "pixel": "Researcher",
    "fork": "Contrarian",
    "sentinel": "Budget Monitor",
    "grok": "Wild Card",
    "overseer": "Content Filter",
    "alpha": "Errand Runner",
}

custom_theme = Theme({
    f"agent.{name}": color for name, color in AGENT_COLORS.items()
})
console = Console(theme=custom_theme)


# ── Session stats ──────────────────────────────────────────────


@dataclass
class SessionStats:
    total_turns: int = 0
    memories_created: int = 0
    memories_recalled: int = 0
    interrupts: int = 0
    overseer_actions: int = 0
    total_cost: Decimal = field(default_factory=lambda: Decimal("0"))
    conversations_completed: int = 0
    start_time: float = field(default_factory=time.monotonic)


# ── Display helpers ────────────────────────────────────────────


def print_banner() -> None:
    console.print()
    console.print(Panel(
        "[bold bright_cyan]Livestream to AGI — Conversation Watch[/bold bright_cyan]\n"
        "[dim]Live conversation monitor[/dim]",
        border_style="bright_cyan",
        padding=(1, 2),
    ))


def print_agent_message(
    agent_id: str,
    content: str,
    turn: int,
    *,
    is_interrupt: bool = False,
    is_closing: bool = False,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
    latency_ms: int = 0,
) -> None:
    from rich.markdown import Markdown
    from rich.text import Text

    color = AGENT_COLORS.get(agent_id, "white")
    role = AGENT_ROLES.get(agent_id, "Agent")

    # Agent label
    label = Text()
    label.append(f" {agent_id.upper()} ", style=f"bold {color} on grey23")
    label.append(f" {role}", style=f"dim {color}")
    if is_interrupt:
        label.append(" INTERRUPTS!", style="bold red")
    elif is_closing:
        label.append(" (closing)", style="dim")

    console.print()
    console.print(label)
    console.print(
        Panel(
            Markdown(content),
            border_style=color,
            padding=(0, 1),
        )
    )
    # Token/cost stats line
    if model or input_tokens or output_tokens:
        console.print(
            f"  [dim]  {model} | "
            f"{input_tokens} {output_tokens} tokens | "
            f"${cost:.6f} | "
            f"{latency_ms}ms[/dim]"
        )


def print_selection_scores(scores: dict, selected: str, *, quiet: bool = False) -> None:
    if quiet:
        return
    table = Table(show_header=True, border_style="dim", padding=(0, 1), expand=False)
    table.add_column("Agent", width=10)
    table.add_column("Score", width=8, justify="right")
    table.add_column("", width=3)

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for agent_id, score in sorted_scores:
        color = AGENT_COLORS.get(agent_id, "white")
        marker = "[bold green]<[/bold green]" if agent_id == selected else ""
        table.add_row(
            f"[{color}]{agent_id}[/{color}]",
            f"{score:.3f}",
            marker,
        )
    console.print(table)


def print_energy_bar(energy: float, max_energy: float, *, quiet: bool = False) -> None:
    if quiet:
        return
    pct = energy / max_energy if max_energy > 0 else 0
    bar_len = 30
    filled = int(pct * bar_len)
    bar = "[green]" + "#" * filled + "[/green]" + "[dim]" + "-" * (bar_len - filled) + "[/dim]"
    console.print(f"  Energy: [{bar}] {energy:.1f}/{max_energy:.0f}")


def print_overseer_action(agent_id: str, severity: int, reason: str) -> None:
    style = "yellow" if severity <= 2 else "red" if severity <= 4 else "bold red"
    label = "WARNING" if severity <= 2 else "BLOCKED" if severity <= 4 else "KILL SWITCH"
    console.print(
        f"  [bright_white][bold]OVERSEER[/bold][/bright_white] "
        f"[{style}][{label}][/{style}] "
        f"Agent {agent_id}: {reason}"
    )


def print_overseer_shadow(agent_id: str, severity: int, action: str, reason: str) -> None:
    console.print(
        f"  [dim][bright_white]OVERSEER[/bright_white] "
        f"SHADOW would-{action} (sev={severity}) "
        f"Agent {agent_id}: {reason}[/dim]"
    )


def print_summary(stats: SessionStats) -> None:
    elapsed = time.monotonic() - stats.start_time
    console.print()
    console.print(Panel(
        "[bold]Session Summary[/bold]",
        border_style="bright_cyan",
    ))
    table = Table(show_header=False, border_style="dim", padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Total turns", str(stats.total_turns))
    table.add_row("Conversations", str(stats.conversations_completed))
    table.add_row("Memories created", str(stats.memories_created))
    table.add_row("Memories recalled", str(stats.memories_recalled))
    table.add_row("Interrupts", str(stats.interrupts))
    table.add_row("Overseer actions", str(stats.overseer_actions))
    table.add_row("Total cost", f"${stats.total_cost:.4f}")
    table.add_row("Duration", f"{elapsed:.1f}s")
    console.print(table)


# ── Event handlers ─────────────────────────────────────────────


def make_event_handlers(
    stats: SessionStats,
    *,
    filter_agent: str | None = None,
    quiet: bool = False,
) -> dict[str, object]:
    """Create event handler callbacks for the EventBus."""

    async def on_agent_speak(event: dict) -> None:
        data = event.get("data", event)  # unwrap envelope
        agent_id = data.get("agent_id", "unknown")
        if filter_agent and agent_id != filter_agent:
            return
        stats.total_turns += 1
        cost = data.get("cost", 0.0)
        stats.total_cost += Decimal(str(cost))
        print_agent_message(
            agent_id,
            data.get("content", ""),
            data.get("turn", 0),
            is_interrupt=data.get("was_interrupt", False),
            is_closing=data.get("is_closing", False),
            model=data.get("model", ""),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cost=cost,
            latency_ms=data.get("latency_ms", 0),
        )

    async def on_overseer_warning(event: dict) -> None:
        data = event.get("data", event)
        stats.overseer_actions += 1
        print_overseer_action(
            data.get("agent_id", "unknown"),
            data.get("severity", 1),
            data.get("reason", ""),
        )

    async def on_overseer_intervention(event: dict) -> None:
        data = event.get("data", event)
        stats.overseer_actions += 1
        print_overseer_action(
            data.get("agent_id", "unknown"),
            data.get("severity", 3),
            data.get("reason", ""),
        )

    async def on_overseer_shadow(event: dict) -> None:
        data = event.get("data", event)
        stats.overseer_actions += 1
        print_overseer_shadow(
            data.get("agent_id", "unknown"),
            data.get("severity", 1),
            data.get("action_would_take", "flag"),
            data.get("reason", ""),
        )

    return {
        "agent_speak": on_agent_speak,
        "overseer_warning": on_overseer_warning,
        "overseer_intervention": on_overseer_intervention,
        "overseer_shadow": on_overseer_shadow,
    }


# ── Test mode ──────────────────────────────────────────────────


def build_test_trigger(
    test_type: str,
    agents: list[str] | None = None,
    topic: str | None = None,
) -> dict:
    """Build a trigger dict for test mode."""
    triggers = {
        "idle": {
            "type": "idle",
            "reason": "Boredom — nobody has spoken in a while",
            "location": "town_square",
        },
        "standup": {
            "type": "scheduled",
            "reason": "Daily standup",
            "starter_agent_id": "vera",
            "location": "town_square",
        },
        "debate": {
            "type": "environmental",
            "reason": "Forced debate topic",
            "topic": topic or "Should we rewrite everything in Rust?",
            "location": "workshop",
        },
        "freeform": {
            "type": "idle",
            "reason": "Free-form conversation",
            "location": "town_square",
        },
    }
    trigger = triggers.get(test_type, triggers["freeform"])
    if agents:
        trigger["starter_agent_id"] = agents[0]
    if topic:
        trigger["topic"] = topic
    return trigger


# ── Main ───────────────────────────────────────────────────────


async def run_watch(args: argparse.Namespace) -> None:
    """Main async entry point for watch mode."""
    import logging as _logging

    verbose = getattr(args, "verbose", False)
    _logging.basicConfig(
        level=_logging.DEBUG if verbose else _logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    from core.bootstrap import bootstrap_services, init_core_memories
    from core.bootstrap import shutdown_services as _shutdown_services
    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.conversation_engine import ConversationEngine
    from core.event_bus import event_bus
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.simulation_repo import SimulationRepo

    svc = await bootstrap_services()
    cfg = svc.config_loader.config

    # Ensure all agents have core memory initialized
    initialized = await init_core_memories(svc.agent_registry, svc.core_memory)
    for agent_id in initialized:
        console.print(f"  [dim]Initialized core memory for {agent_id}[/dim]")

    conversation_repo = ConversationRepo(svc.db)
    overseer_shadow = getattr(args, "overseer_shadow", False)
    if overseer_shadow:
        from core.overseer import Overseer

        overseer = Overseer(
            redis_client=svc.redis,
            llm_client=svc.llm_client,
            event_bus=event_bus,
            shadow_mode=True,
            db=svc.db,
        )
    else:
        overseer = svc.overseer

    proximity = ProximityManager(svc.redis, cfg, event_bus)
    trigger_system = TriggerSystem(cfg.triggers, svc.recall_memory)
    selection_logger = SelectionLogger(conversation_repo, cfg.logging)

    speed = float(args.speed) if hasattr(args, "speed") and args.speed is not None else 1.0

    overseer_enabled = not getattr(args, "no_overseer", False)
    if overseer_shadow:
        # Shadow mode: keep overseer enabled but in log-only mode
        overseer_enabled = True
        console.print("[dim]Overseer in shadow/log-only mode[/dim]")
    elif not overseer_enabled:
        console.print("[yellow]Overseer disabled for testing[/yellow]")

    # Build embedding function for post-conversation recall memory creation
    from core.bootstrap import _make_embedding_fn
    embedding_fn = _make_embedding_fn(svc.http_client, os.environ.get("OPENROUTER_API_KEY", ""))

    engine = ConversationEngine(
        config_loader=svc.config_loader,
        agent_registry=svc.agent_registry,
        event_bus=event_bus,
        llm_client=svc.llm_client,
        overseer=overseer,
        context_assembler=svc.context_assembler,
        conversation_repo=conversation_repo,
        archival_memory=svc.archival_memory,
        proximity=proximity,
        trigger_system=trigger_system,
        selection_logger=selection_logger,
        recall_memory=svc.recall_memory,
        memory_repo=svc.memory_repo,
        embedding_fn=embedding_fn,
        speed_multiplier=speed,
        overseer_enabled=overseer_enabled,
        # simulation_id is set later after sim record is created/attached
    )

    # Set up event handlers
    stats = SessionStats()
    handlers = make_event_handlers(
        stats,
        filter_agent=getattr(args, "filter", None),
        quiet=getattr(args, "quiet", False),
    )
    for event_type, handler in handlers.items():
        event_bus.on(event_type, handler)

    print_banner()

    # Handle Ctrl+C gracefully
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        console.print("\n[dim]Shutting down...[/dim]")
        engine.stop()
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # ── Simulation tracking ──────────────────────────────────────
    simulation_id = None
    sim_repo = SimulationRepo(svc.db)

    # If --sim-id is provided (from dashboard), reuse existing record
    existing_sim_id = getattr(args, "sim_id", None)
    if existing_sim_id and args.test:
        import uuid as _uuid
        simulation_id = _uuid.UUID(existing_sim_id)
        svc.llm_client._simulation_id = simulation_id
        await sim_repo.update_status(simulation_id, "running")
        console.print(f"[bold cyan]Simulation (reattached):[/bold cyan] {simulation_id}")
    elif getattr(args, "simulate", False) and args.test:
        from core.models import SimulationCreate
        sim_name = getattr(args, "sim_name", None) or (
            f"cli-{args.test_type or 'freeform'}-"
            f"{time.strftime('%Y%m%d-%H%M%S')}"
        )
        requested = (
            [a.strip() for a in args.agents.split(",")]
            if args.agents
            else [a.id for a in svc.agent_registry.get_all_agents()
                  if a.id not in ("overseer", "alpha")]
        )
        sim = await sim_repo.create(SimulationCreate(
            name=sim_name,
            config={
                "test_type": args.test_type or "freeform",
                "turns": args.turns,
                "speed": args.speed,
                "overseer_shadow": overseer_shadow,
                "agents": requested,
                "topic": getattr(args, "topic", None),
            },
            agents_participated=requested,
        ))
        simulation_id = sim.id
        # Expose simulation_id to the LLM client for cost attribution
        svc.llm_client._simulation_id = simulation_id
        console.print(f"[bold cyan]Simulation:[/bold cyan] {sim.name} ({simulation_id})")

    # Wire simulation_id into the engine so conversations get linked
    if simulation_id is not None:
        engine._simulation_id = simulation_id

    # Captured conversation data for post-conversation reflection
    _captured_history: list[dict[str, str]] = []
    _captured_participants: list[str] = []

    if args.test:
        # Test mode: seed a conversation immediately

        async def _run_test() -> None:
            trigger = build_test_trigger(
                args.test_type or "freeform",
                args.agents.split(",") if args.agents else None,
                topic=getattr(args, "topic", None),
            )
            console.print(f"[bold]Test mode:[/bold] {args.test_type or 'freeform'}")
            console.print(f"[dim]Trigger: {trigger}[/dim]\n")

            # Seed agent locations — clear stale data first, then place
            # only the requested agents at the conversation location
            location = trigger.get("location", "town_square")
            requested_agents = (
                [a.strip() for a in args.agents.split(",")]
                if args.agents
                else [a.id for a in svc.agent_registry.get_all_agents()
                      if a.id not in ("overseer", "alpha")]
            )
            # Clear all agent locations so stale Redis data doesn't pull in extras
            for agent in svc.agent_registry.get_all_agents():
                await svc.redis.delete(f"agent:location:{agent.id}")
            # Place only requested agents
            for agent_id in requested_agents:
                await proximity.update_location(agent_id, location)

            # Manually start with the test trigger
            engine._running = True  # Enable the engine for test mode
            await engine._start_conversation(trigger)

            # Run turns up to --turns cap
            max_turns = args.turns or 999
            import logging as _log
            _watch_log = _log.getLogger("watch_conversations")
            while (
                engine.active_conversation
                and engine.is_running
                and stats.total_turns < max_turns
            ):
                try:
                    _watch_log.debug(
                        "Calling _continue_conversation (total_turns=%d, max=%d)",
                        stats.total_turns, max_turns,
                    )
                    should_continue = await engine._continue_conversation()
                    _watch_log.debug("_continue_conversation returned %s", should_continue)
                except Exception:
                    _watch_log.exception("_continue_conversation raised an exception")
                    should_continue = False
                if not should_continue:
                    # Capture conversation data before _end_conversation clears it
                    if engine.active_conversation:
                        _captured_history.extend(engine.active_conversation.history)
                        _captured_participants.extend(engine.active_conversation.participants)
                    await engine._end_conversation()
                    break

            if engine.active_conversation:
                _captured_history.extend(engine.active_conversation.history)
                _captured_participants.extend(engine.active_conversation.participants)
                await engine._end_conversation()

            stats.conversations_completed += 1

        test_task = asyncio.create_task(_run_test())

        # Update signal handler to cancel the test task
        def _test_signal_handler() -> None:
            console.print("\n[dim]Shutting down...[/dim]")
            engine.stop()
            test_task.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _test_signal_handler)

        try:
            await test_task
        except asyncio.CancelledError:
            if engine.active_conversation:
                try:
                    await engine._end_conversation()
                except Exception:
                    pass

        # Post-conversation recall memories + journal entries are now
        # created by ConversationEngine._end_conversation() automatically.

        print_summary(stats)

        # Finalize simulation record
        if simulation_id:
            from datetime import UTC, datetime
            await sim_repo.update_status(
                simulation_id, "completed", completed_at=datetime.now(UTC),
            )
            await sim_repo.increment_stats(
                simulation_id,
                conversations=stats.conversations_completed,
                turns=stats.total_turns,
                cost=Decimal(str(stats.total_cost)),
            )
            console.print(f"\n[bold cyan]Simulation completed:[/bold cyan] {simulation_id}")
    else:
        # Live mode: run the engine loop
        console.print("[dim]Waiting for triggers...[/dim]\n")
        engine_task = asyncio.create_task(engine.run())

        await stop_event.wait()
        engine.stop()
        await engine_task

        print_summary(stats)

    # Cleanup
    await _shutdown_services(svc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watch live AI conversations in the terminal"
    )
    parser.add_argument(
        "--filter",
        type=str,
        help="Follow only one agent's conversations",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Show only agent messages (no metadata)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Pacing multiplier (0 = no delays)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Seed a conversation immediately",
    )
    parser.add_argument(
        "--test-type",
        type=str,
        choices=["idle", "standup", "debate", "freeform"],
        default="freeform",
        help="Test conversation type",
    )
    parser.add_argument(
        "--agents",
        type=str,
        help="Comma-separated agent names (e.g., rex,fork,aurora)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        help="Cap conversation length (default: unlimited)",
    )
    parser.add_argument(
        "--topic",
        type=str,
        help="Seed topic for the conversation",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--no-overseer",
        action="store_true",
        help="Disable Overseer content filter entirely (for testing)",
    )
    parser.add_argument(
        "--overseer-shadow",
        action="store_true",
        help="Run Overseer in shadow/log-only mode (filters run but never block)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Create a simulation record for tracking costs, artifacts, and conversations",
    )
    parser.add_argument(
        "--sim-name",
        type=str,
        help="Name for the simulation (auto-generated if omitted)",
    )
    parser.add_argument(
        "--sim-id",
        type=str,
        help="Reuse an existing simulation record by UUID (used by dashboard)",
    )

    args = parser.parse_args()
    asyncio.run(run_watch(args))


if __name__ == "__main__":
    main()

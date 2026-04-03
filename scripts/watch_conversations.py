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
) -> None:
    color = AGENT_COLORS.get(agent_id, "white")
    role = AGENT_ROLES.get(agent_id, "Agent")
    timestamp = time.strftime("%H:%M:%S")

    prefix = ""
    if is_interrupt:
        prefix = "[bold red]INTERRUPTS![/bold red] "
    elif is_closing:
        prefix = "[dim](closing)[/dim] "

    console.print(
        f"  [dim]{timestamp}[/dim] "
        f"[{color}][bold]{agent_id.capitalize()}[/bold] ({role})[/{color}] "
        f"{prefix}{content}"
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

    async def on_agent_speak(data: dict) -> None:
        agent_id = data.get("agent_id", "unknown")
        if filter_agent and agent_id != filter_agent:
            return
        stats.total_turns += 1
        print_agent_message(
            agent_id,
            data.get("content", ""),
            data.get("turn", 0),
            is_interrupt=data.get("was_interrupt", False),
            is_closing=data.get("is_closing", False),
        )

    async def on_overseer_warning(data: dict) -> None:
        stats.overseer_actions += 1
        print_overseer_action(
            data.get("agent_id", "unknown"),
            data.get("severity", 1),
            data.get("reason", ""),
        )

    async def on_overseer_intervention(data: dict) -> None:
        stats.overseer_actions += 1
        print_overseer_action(
            data.get("agent_id", "unknown"),
            data.get("severity", 3),
            data.get("reason", ""),
        )

    return {
        "agent_speak": on_agent_speak,
        "overseer_warning": on_overseer_warning,
        "overseer_intervention": on_overseer_intervention,
    }


# ── Test mode ──────────────────────────────────────────────────


def build_test_trigger(
    test_type: str, agents: list[str] | None = None
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
            "topic": "Should we rewrite everything in Rust?",
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
    return trigger


# ── Main ───────────────────────────────────────────────────────


async def run_watch(args: argparse.Namespace) -> None:
    """Main async entry point for watch mode."""
    from core.agent_registry import AgentRegistry
    from core.config_loader import ConfigLoader
    from core.context_assembly import ContextAssembler
    from core.conversation.proximity import ProximityManager
    from core.conversation.selection_logger import SelectionLogger
    from core.conversation.triggers import TriggerSystem
    from core.conversation_engine import ConversationEngine
    from core.database import Database
    from core.event_bus import event_bus
    from core.llm_client import OpenRouterClient
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.memory.token_counter import TokenCounter
    from core.overseer import Overseer
    from core.redis_client import RedisClient
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.cost_repo import CostRepo
    from core.repos.memory_repo import MemoryRepo
    from core.repos.transcript_repo import TranscriptRepo

    # Connect services
    db = Database()
    redis_client = RedisClient()
    await db.connect()
    await redis_client.connect()

    # Load agents and config
    agent_registry = AgentRegistry(redis_client=redis_client)
    await agent_registry.load_all()
    config_loader = ConfigLoader()
    config_loader.load()
    cfg = config_loader.config

    # Initialize subsystems
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    cost_repo = CostRepo(db)
    llm_client = OpenRouterClient(api_key=api_key, cost_repo=cost_repo)

    memory_repo = MemoryRepo(db)
    transcript_repo = TranscriptRepo(db)
    token_counter = TokenCounter()

    core_memory = CoreMemoryManager(memory_repo, token_counter)

    async def _dummy_embed(text: str) -> list[float]:
        return [0.0] * 1536

    recall_memory = RecallMemoryManager(memory_repo, _dummy_embed)
    archival_memory = ArchivalMemoryManager(transcript_repo, token_counter)

    context_assembler = ContextAssembler(
        agent_registry=agent_registry,
        core_memory=core_memory,
        recall_memory=recall_memory,
        archival_memory=archival_memory,
        token_counter=token_counter,
        redis_client=redis_client,
    )

    conversation_repo = ConversationRepo(db)
    overseer = Overseer(
        redis_client=redis_client,
        llm_client=llm_client,
        event_bus=event_bus,
    )

    proximity = ProximityManager(redis_client, cfg, event_bus)
    trigger_system = TriggerSystem(cfg.triggers, recall_memory)
    selection_logger = SelectionLogger(conversation_repo, cfg.logging)

    speed = float(args.speed) if hasattr(args, "speed") and args.speed is not None else 1.0

    engine = ConversationEngine(
        config_loader=config_loader,
        agent_registry=agent_registry,
        event_bus=event_bus,
        llm_client=llm_client,
        overseer=overseer,
        context_assembler=context_assembler,
        conversation_repo=conversation_repo,
        archival_memory=archival_memory,
        proximity=proximity,
        trigger_system=trigger_system,
        selection_logger=selection_logger,
        speed_multiplier=speed,
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

    if args.test:
        # Test mode: seed a conversation immediately
        trigger = build_test_trigger(
            args.test_type or "freeform",
            args.agents.split(",") if args.agents else None,
        )
        console.print(f"[bold]Test mode:[/bold] {args.test_type or 'freeform'}")
        console.print(f"[dim]Trigger: {trigger}[/dim]\n")

        # If --agents specified, seed agent locations
        if args.agents:
            for agent_id in args.agents.split(","):
                location = trigger.get("location", "town_square")
                await proximity.update_location(agent_id.strip(), location)

        # Manually start with the test trigger
        await engine._start_conversation(trigger)

        # Run turns up to --turns cap
        max_turns = args.turns or 999
        while engine.active_conversation and stats.total_turns < max_turns:
            should_continue = await engine._continue_conversation()
            if not should_continue:
                await engine._end_conversation()
                break

        if engine.active_conversation:
            await engine._end_conversation()

        stats.conversations_completed += 1
        print_summary(stats)
    else:
        # Live mode: run the engine loop
        console.print("[dim]Waiting for triggers...[/dim]\n")
        engine_task = asyncio.create_task(engine.run())

        await stop_event.wait()
        engine.stop()
        await engine_task

        print_summary(stats)

    # Cleanup
    await llm_client.close()
    await redis_client.disconnect()
    await db.disconnect()


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

    args = parser.parse_args()
    asyncio.run(run_watch(args))


if __name__ == "__main__":
    main()

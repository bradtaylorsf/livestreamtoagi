#!/usr/bin/env python3
"""Single-agent CLI test harness.

Exercises the full agent pipeline: config loading → context assembly →
LLM call → memory storage → recall → compaction.  Supports interactive
REPL, automated test sequences, and dry-run (context-only) modes.

Usage:
    python scripts/test_agent.py --agent rex --interactive
    python scripts/test_agent.py --agent vera --auto
    python scripts/test_agent.py --agent rex --dry-run --verbose
    python scripts/test_agent.py --help
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time
from decimal import Decimal
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ── Agent color theme ─────────────────────────────────────────────

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


# ── Stats tracker ─────────────────────────────────────────────────

class SessionStats:
    def __init__(self) -> None:
        self.turns: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost: Decimal = Decimal("0")
        self.total_latency_ms: int = 0
        self.memories_stored: int = 0
        self.memories_recalled: int = 0
        self.compactions_run: int = 0
        self.start_time: float = time.monotonic()

    def record_llm_call(
        self,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
        latency_ms: int,
    ) -> None:
        self.turns += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost
        self.total_latency_ms += latency_ms


# ── Display helpers ───────────────────────────────────────────────

def agent_label(agent_id: str) -> Text:
    color = AGENT_COLORS.get(agent_id, "white")
    role = AGENT_ROLES.get(agent_id, "Agent")
    text = Text()
    text.append(f" {agent_id.upper()} ", style=f"bold {color} on grey23")
    text.append(f" {role}", style=f"dim {color}")
    return text


def print_agent_response(agent_id: str, content: str) -> None:
    color = AGENT_COLORS.get(agent_id, "white")
    console.print()
    console.print(agent_label(agent_id))
    console.print(
        Panel(
            Markdown(content),
            border_style=color,
            padding=(0, 1),
        )
    )


def print_memory_event(icon: str, message: str) -> None:
    console.print(f"  [dim]{icon} {message}[/dim]")


def print_token_usage(
    input_tokens: int,
    output_tokens: int,
    cost: Decimal,
    latency_ms: int,
    model: str,
) -> None:
    console.print(
        f"  [dim]⚡ {model} │ "
        f"↑{input_tokens} ↓{output_tokens} tokens │ "
        f"${cost:.6f} │ "
        f"{latency_ms}ms[/dim]"
    )


def print_context_breakdown(sections: dict[str, int]) -> None:
    table = Table(title="Context Assembly", show_header=True, border_style="dim")
    table.add_column("Section", style="cyan")
    table.add_column("Tokens", justify="right", style="green")
    total = 0
    for section, tokens in sections.items():
        table.add_row(section, str(tokens))
        total += tokens
    table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]")
    console.print(table)


def print_session_summary(stats: SessionStats) -> None:
    elapsed = time.monotonic() - stats.start_time
    table = Table(title="Session Summary", show_header=False, border_style="bright_cyan")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")
    table.add_row("Turns", str(stats.turns))
    table.add_row("Input tokens", f"{stats.total_input_tokens:,}")
    table.add_row("Output tokens", f"{stats.total_output_tokens:,}")
    table.add_row("Total cost", f"${stats.total_cost:.6f}")
    table.add_row("Avg latency", f"{stats.total_latency_ms // max(stats.turns, 1)}ms")
    table.add_row("Memories stored", str(stats.memories_stored))
    table.add_row("Memories recalled", str(stats.memories_recalled))
    table.add_row("Compactions", str(stats.compactions_run))
    table.add_row("Elapsed", f"{elapsed:.1f}s")
    console.print()
    console.print(table)


# ── Service bootstrapping ─────────────────────────────────────────

async def bootstrap_services(dry_run: bool = False):
    """Wire up all services and return them as a dict.

    In dry-run mode, database and Redis are not connected — repos/LLM
    are replaced with lightweight stubs so context assembly still works.
    """
    from core.agent_registry import AgentRegistry
    from core.memory.token_counter import TokenCounter

    token_counter = TokenCounter()

    if dry_run:
        return await _bootstrap_dry_run(token_counter)

    from core.database import Database
    from core.llm_client import OpenRouterClient
    from core.memory.archival_memory import ArchivalMemoryManager
    from core.memory.compaction import MemoryCompactor
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.redis_client import RedisClient
    from core.repos.cost_repo import CostRepo
    from core.repos.memory_repo import MemoryRepo
    from core.repos.transcript_repo import TranscriptRepo

    import httpx

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        console.print("[bold red]Error:[/bold red] OPENROUTER_API_KEY not set in .env")
        sys.exit(1)

    db = Database()
    redis_client = RedisClient()

    console.print("[dim]Connecting to services...[/dim]")
    await db.connect()
    await redis_client.connect()
    console.print("[dim green]✓ Database and Redis connected[/dim green]")

    # Auto-run migrations if tables are missing
    try:
        await db.fetchval("SELECT 1 FROM core_memory LIMIT 0")
    except Exception:
        console.print("[dim yellow]Tables missing — running migrations...[/dim yellow]")
        import asyncpg as _apg

        conn = await _apg.connect(db.dsn, timeout=60)
        try:
            from db.migrate import up
            await up(conn)
            console.print("[dim green]✓ Migrations applied[/dim green]")
        finally:
            await conn.close()

    agent_registry = AgentRegistry(redis_client=redis_client)
    await agent_registry.load_all()

    cost_repo = CostRepo(db)
    memory_repo = MemoryRepo(db)
    transcript_repo = TranscriptRepo(db)
    http_client = httpx.AsyncClient()

    llm_client = OpenRouterClient(api_key=api_key, cost_repo=cost_repo)
    core_memory = CoreMemoryManager(memory_repo=memory_repo, token_counter=token_counter)
    recall_memory = RecallMemoryManager(
        memory_repo=memory_repo,
        embedding_fn=_make_embedding_fn(http_client, api_key),
    )
    archival_memory = ArchivalMemoryManager(
        transcript_repo=transcript_repo, token_counter=token_counter
    )
    compactor = MemoryCompactor(
        archival=archival_memory,
        recall=recall_memory,
        llm_client=llm_client,
        http_client=http_client,
        openrouter_api_key=api_key,
    )

    from core.context_assembly import ContextAssembler

    context_assembler = ContextAssembler(
        agent_registry=agent_registry,
        core_memory=core_memory,
        recall_memory=recall_memory,
        archival_memory=archival_memory,
        token_counter=token_counter,
        redis_client=redis_client,
    )

    return {
        "db": db,
        "redis": redis_client,
        "http_client": http_client,
        "agent_registry": agent_registry,
        "llm_client": llm_client,
        "core_memory": core_memory,
        "recall_memory": recall_memory,
        "archival_memory": archival_memory,
        "compactor": compactor,
        "context_assembler": context_assembler,
        "token_counter": token_counter,
        "memory_repo": memory_repo,
    }


async def _bootstrap_dry_run(token_counter):
    """Lightweight bootstrap for --dry-run: no DB/Redis needed."""
    from core.agent_registry import AgentRegistry
    from core.context_assembly import ContextAssembler

    agent_registry = AgentRegistry(redis_client=None)
    await agent_registry.load_all()

    # Stub memory managers that return empty data
    class StubCoreMemory:
        async def get_core_memory(self, agent_id: str):
            return None

    class StubRecallMemory:
        async def retrieve_recall_memories(self, agent_id: str, query: str, limit: int = 3):
            return ""

    class StubArchivalMemory:
        async def retrieve_full_transcript(self, transcript_id: int):
            return None

    context_assembler = ContextAssembler(
        agent_registry=agent_registry,
        core_memory=StubCoreMemory(),
        recall_memory=StubRecallMemory(),
        archival_memory=StubArchivalMemory(),
        token_counter=token_counter,
        redis_client=None,
    )

    return {
        "db": None,
        "redis": None,
        "http_client": None,
        "agent_registry": agent_registry,
        "llm_client": None,
        "core_memory": None,
        "recall_memory": None,
        "archival_memory": None,
        "compactor": None,
        "context_assembler": context_assembler,
        "token_counter": token_counter,
        "memory_repo": None,
    }


def _make_embedding_fn(http_client, api_key):
    from core.memory.embeddings import generate_embedding

    async def embedding_fn(text: str) -> list[float]:
        return await generate_embedding(text, http_client, api_key)

    return embedding_fn


async def shutdown_services(services: dict) -> None:
    if services.get("llm_client"):
        await services["llm_client"].close()
    if services.get("http_client"):
        await services["http_client"].aclose()
    if services.get("redis"):
        await services["redis"].disconnect()
    if services.get("db"):
        await services["db"].disconnect()


# ── Core pipeline: one turn ───────────────────────────────────────


async def run_turn(
    agent_id: str,
    user_message: str,
    conversation_history: list[dict[str, str]],
    services: dict,
    stats: SessionStats,
    verbose: bool = False,
) -> str:
    """Execute one full turn: assemble context → call LLM → return response."""
    context_assembler = services["context_assembler"]
    llm_client = services["llm_client"]
    token_counter = services["token_counter"]

    agent_config = services["agent_registry"].get_agent(agent_id)
    if agent_config is None:
        console.print(f"[bold red]Agent '{agent_id}' not found[/bold red]")
        return ""

    model = agent_config.model_conversation

    # Add user message to history
    conversation_history.append({"role": "user", "content": user_message})

    # Assemble context
    messages = await context_assembler.assemble_context(
        agent_id=agent_id,
        conversation_history=conversation_history,
    )

    if verbose:
        # Show context breakdown
        sections = {}
        for msg in messages:
            role = msg["role"]
            tokens = token_counter.count_tokens(msg["content"])
            sections[f"{role} ({tokens}t)"] = tokens
        print_context_breakdown(sections)

    # Call LLM
    console.print(f"  [dim]🤖 Calling {model}...[/dim]")
    response = await llm_client.complete(
        messages=messages,
        model=model,
        agent_id=agent_id,
        max_tokens=500,
    )

    stats.record_llm_call(
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost=response.estimated_cost,
        latency_ms=response.latency_ms,
    )

    print_agent_response(agent_id, response.content)
    print_token_usage(
        response.input_tokens,
        response.output_tokens,
        response.estimated_cost,
        response.latency_ms,
        model,
    )

    # Add assistant response to history
    conversation_history.append({"role": "assistant", "content": response.content})

    # Check if recall memories were used in context
    for msg in messages:
        if "Relevant memories" in msg.get("content", ""):
            stats.memories_recalled += 1
            print_memory_event("🔍", "Recalled memories were included in context")
            break

    return response.content


# ── End-of-session: compact + reflect ─────────────────────────────


async def end_session(
    agent_id: str,
    conversation_history: list[dict[str, str]],
    services: dict,
    stats: SessionStats,
) -> None:
    """Graceful session end: compact full conversation → run reflection → update core memory."""
    if not conversation_history:
        return

    console.print()
    console.print("[bold cyan]━━━ Saving session memories... ━━━[/bold cyan]")

    compactor = services.get("compactor")
    if compactor:
        # Compact the full conversation into archival + recall
        transcript_text = "\n".join(
            f"[{msg['role']}] {msg['content']}" for msg in conversation_history
        )
        result = await compactor.compact_interaction(
            agent_id=agent_id,
            interaction=transcript_text,
            event_type="test_harness_session",
            participants=[agent_id, "user"],
        )
        if result:
            stats.memories_stored += 1
            stats.compactions_run += 1
            print_memory_event(
                "📝",
                f"Full conversation → transcript #{result.transcript.id}, "
                f"recall #{result.recall_memory.id}",
            )

    # Run a mini-reflection to promote important facts to core memory
    llm_client = services.get("llm_client")
    core_memory_mgr = services.get("core_memory")
    memory_repo = services.get("memory_repo")
    token_counter = services.get("token_counter")
    agent_registry = services.get("agent_registry")

    if all([llm_client, core_memory_mgr, memory_repo, token_counter, agent_registry]):
        from core.memory.reflection import ReflectionManager

        console.print("  [dim]Running reflection to update core memory...[/dim]")
        reflection_mgr = ReflectionManager(
            memory_repo=memory_repo,
            llm_client=llm_client,
            core_memory_mgr=core_memory_mgr,
            token_counter=token_counter,
            agent_registry=agent_registry,
        )

        try:
            result = await reflection_mgr.run_6hour_reflection(agent_id)
            if result.promoted_count > 0:
                print_memory_event(
                    "🧠",
                    f"Core memory updated: {result.promoted_count} items promoted",
                )
            if result.importance_updates > 0:
                print_memory_event(
                    "⚖️",
                    f"Re-scored {result.importance_updates} memory importance ratings",
                )
            if result.journal_entry:
                print_memory_event(
                    "📓",
                    f"Journal entry written ({result.journal_entry.token_count} tokens)",
                )
        except Exception as exc:
            print_memory_event("⚠️", f"Reflection failed: {exc}")

    console.print("[bold cyan]━━━ Session saved ━━━[/bold cyan]")


# ── Reflect mode ──────────────────────────────────────────────────


async def run_reflect(agent_id: str | None, services: dict, run_all: bool = False) -> None:
    """Run 6-hour reflection on one agent or all agents."""
    from core.memory.reflection import ReflectionManager

    llm_client = services["llm_client"]
    core_memory_mgr = services["core_memory"]
    memory_repo = services["memory_repo"]
    token_counter = services["token_counter"]
    agent_registry = services["agent_registry"]

    reflection_mgr = ReflectionManager(
        memory_repo=memory_repo,
        llm_client=llm_client,
        core_memory_mgr=core_memory_mgr,
        token_counter=token_counter,
        agent_registry=agent_registry,
    )

    if run_all:
        agents = [a for a in agent_registry.get_all_agents() if a.chattiness > 0]
        console.print(Panel(
            f"[bold]Running reflection on {len(agents)} agents[/bold]\n"
            f"[dim]Skipping agents with chattiness=0 (overseer, alpha)[/dim]",
            border_style="cyan",
        ))
    else:
        agent = agent_registry.get_agent(agent_id)
        if agent is None:
            console.print(f"[bold red]Agent '{agent_id}' not found[/bold red]")
            return
        agents = [agent]

    for agent_config in agents:
        aid = agent_config.id
        color = AGENT_COLORS.get(aid, "white")
        console.print()
        console.print(agent_label(aid))

        # Ensure core memory exists
        await _ensure_core_memory(aid, agent_config, services)

        # Show before state
        before = await core_memory_mgr.get_core_memory(aid)
        before_version = None
        if before:
            record = await memory_repo.get_core_memory(aid)
            before_version = record.version if record else None

        console.print(f"  [dim]Running 6-hour reflection...[/dim]")
        try:
            result = await reflection_mgr.run_6hour_reflection(aid)

            if result.promoted_count > 0:
                print_memory_event("🧠", f"Core memory: {result.promoted_count} items promoted")
            else:
                print_memory_event("💤", "No new items promoted to core memory")

            if result.importance_updates > 0:
                print_memory_event("⚖️", f"Re-scored {result.importance_updates} memories")

            if result.journal_entry:
                print_memory_event("📓", f"Journal entry: {result.journal_entry.token_count} tokens")

            # Show what changed
            after = await core_memory_mgr.get_core_memory(aid)
            record_after = await memory_repo.get_core_memory(aid)
            if record_after and before_version and record_after.version > before_version:
                console.print(f"  [dim green]Core memory updated (v{before_version} → v{record_after.version})[/dim green]")

        except Exception as exc:
            console.print(f"  [bold red]Reflection failed: {exc}[/bold red]")

    console.print()
    console.print("[bold green]Reflection complete.[/bold green]")


async def run_reflect_interactive(agent_id: str, services: dict) -> None:
    """Run reflection for a single agent from within interactive mode."""
    from core.memory.reflection import ReflectionManager

    llm_client = services.get("llm_client")
    core_memory_mgr = services.get("core_memory")
    memory_repo = services.get("memory_repo")
    token_counter = services.get("token_counter")
    agent_registry = services.get("agent_registry")

    if not all([llm_client, core_memory_mgr, memory_repo, token_counter, agent_registry]):
        console.print("  [red]Reflection requires full services (not available in dry-run)[/red]")
        return

    reflection_mgr = ReflectionManager(
        memory_repo=memory_repo,
        llm_client=llm_client,
        core_memory_mgr=core_memory_mgr,
        token_counter=token_counter,
        agent_registry=agent_registry,
    )

    console.print("  [dim]Running reflection...[/dim]")
    try:
        result = await reflection_mgr.run_6hour_reflection(agent_id)
        if result.promoted_count > 0:
            print_memory_event("🧠", f"Core memory: {result.promoted_count} items promoted")
        else:
            print_memory_event("💤", "No new items to promote")
        if result.importance_updates > 0:
            print_memory_event("⚖️", f"Re-scored {result.importance_updates} memories")
        if result.journal_entry:
            print_memory_event("📓", f"Journal entry written ({result.journal_entry.token_count} tokens)")
    except Exception as exc:
        console.print(f"  [red]Reflection failed: {exc}[/red]")


# ── Dry-run mode ──────────────────────────────────────────────────

async def run_dry_run(agent_id: str, services: dict, verbose: bool) -> None:
    """Show assembled context without calling LLM."""
    context_assembler = services["context_assembler"]
    token_counter = services["token_counter"]

    agent_config = services["agent_registry"].get_agent(agent_id)
    if agent_config is None:
        console.print(f"[bold red]Agent '{agent_id}' not found[/bold red]")
        return

    sample_history = [
        {"role": "user", "content": "What are you working on today?"},
    ]

    messages = await context_assembler.assemble_context(
        agent_id=agent_id,
        conversation_history=sample_history,
    )

    console.print(Panel(
        f"[bold]Dry-run context assembly for {agent_id}[/bold]\n"
        f"Model: {agent_config.model_conversation}",
        border_style=AGENT_COLORS.get(agent_id, "white"),
    ))

    total_tokens = 0
    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        tokens = token_counter.count_tokens(content)
        total_tokens += tokens

        if verbose:
            console.print(Panel(
                content[:2000] + ("..." if len(content) > 2000 else ""),
                title=f"[{i}] {role} ({tokens} tokens)",
                border_style="dim",
            ))
        else:
            console.print(f"  [{i}] {role}: {tokens} tokens")

    console.print(f"\n  [bold green]Total: {total_tokens} tokens across {len(messages)} messages[/bold green]")


# ── Interactive mode ──────────────────────────────────────────────

async def run_interactive(agent_id: str, services: dict, verbose: bool) -> None:
    """REPL loop: type messages, see responses."""
    stats = SessionStats()
    conversation_history: list[dict[str, str]] = []

    color = AGENT_COLORS.get(agent_id, "white")
    console.print(Panel(
        f"[bold]Interactive session with {agent_id.upper()}[/bold]\n"
        f"Type messages and press Enter. Type 'quit' or Ctrl+C to exit.\n"
        f"Commands: /memory  /reflect  /stats  /clear  /verbose  /help",
        border_style=color,
    ))

    while True:
        try:
            console.print()
            user_input = console.input("[bold bright_white]You > [/bold bright_white]")
        except (EOFError, KeyboardInterrupt):
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "/quit", "/exit"):
            break

        if user_input.lower() == "/stats":
            print_session_summary(stats)
            continue

        if user_input.lower() == "/clear":
            conversation_history.clear()
            console.print("  [dim]Conversation history cleared[/dim]")
            continue

        if user_input.lower() == "/verbose":
            verbose = not verbose
            console.print(f"  [dim]Verbose mode: {'on' if verbose else 'off'}[/dim]")
            continue

        if user_input.lower() == "/memory":
            core_mem = services.get("core_memory")
            if core_mem:
                content = await core_mem.get_core_memory(agent_id)
                if content:
                    console.print(Panel(Markdown(content), title="Core Memory", border_style="cyan"))
                else:
                    console.print("  [dim]No core memory found (needs initialization)[/dim]")
            continue

        if user_input.lower() == "/reflect":
            await run_reflect_interactive(agent_id, services)
            continue

        if user_input.lower() == "/help":
            console.print(Panel(
                "[bold]/memory[/bold]   — Show this agent's core memory (Tier 1)\n"
                "[bold]/reflect[/bold]  — Run reflection cycle (promotes facts to core memory)\n"
                "[bold]/stats[/bold]    — Show session statistics\n"
                "[bold]/clear[/bold]    — Clear conversation history\n"
                "[bold]/verbose[/bold]  — Toggle verbose mode\n"
                "[bold]quit[/bold]      — Exit (saves session + runs reflection)",
                title="Commands",
                border_style="dim",
            ))
            continue

        await run_turn(
            agent_id=agent_id,
            user_message=user_input,
            conversation_history=conversation_history,
            services=services,
            stats=stats,
            verbose=verbose,
        )

    # End-of-session: compact and reflect
    await end_session(agent_id, conversation_history, services, stats)
    print_session_summary(stats)


# ── Auto mode ─────────────────────────────────────────────────────

AUTO_PROMPTS = [
    {
        "label": "Intro — verify agent responds in character",
        "prompt": "Hey! Introduce yourself — who are you and what do you do around here?",
    },
    {
        "label": "Store unique fact — test memory storage",
        "prompt": (
            "I want to tell you something important to remember: "
            "The team decided yesterday that the budget cap for API calls "
            "is exactly $47.50 per day. Sentinel was very insistent about this number."
        ),
    },
    {
        "label": "Unrelated topic — verify normal response",
        "prompt": "What's your opinion on pixel art versus 3D graphics for game worlds?",
    },
    {
        "label": "Recall test — verify memory retrieval",
        "prompt": "Hey, do you remember what the daily budget cap for API calls is? Sentinel set it recently.",
    },
    {
        "label": "Follow-up — test conversation continuity",
        "prompt": "Based on that budget, what would you prioritize building first?",
    },
]


async def run_auto(agent_id: str, services: dict, verbose: bool) -> None:
    """Run predefined test sequence exercising the full pipeline."""
    stats = SessionStats()
    conversation_history: list[dict[str, str]] = []

    color = AGENT_COLORS.get(agent_id, "white")
    console.print(Panel(
        f"[bold]Auto-test sequence for {agent_id.upper()}[/bold]\n"
        f"{len(AUTO_PROMPTS)} prompts testing: character, memory store, "
        f"normal response, memory recall, continuity",
        border_style=color,
    ))

    for i, step in enumerate(AUTO_PROMPTS, 1):
        console.print()
        console.print(
            f"[bold cyan]━━━ Step {i}/{len(AUTO_PROMPTS)}: "
            f"{step['label']} ━━━[/bold cyan]"
        )
        console.print(f"  [bright_white]You > {step['prompt']}[/bright_white]")

        await run_turn(
            agent_id=agent_id,
            user_message=step["prompt"],
            conversation_history=conversation_history,
            services=services,
            stats=stats,
            verbose=verbose,
        )

    # End-of-session: compact and reflect
    await end_session(agent_id, conversation_history, services, stats)
    print_session_summary(stats)


# ── Argument parsing ──────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Single-agent CLI test harness for Livestream AGI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python scripts/test_agent.py --agent rex --interactive
  python scripts/test_agent.py --agent vera --auto
  python scripts/test_agent.py --agent rex --dry-run --verbose
  python scripts/test_agent.py --agent vera --reflect
  python scripts/test_agent.py --reflect --all
  python scripts/test_agent.py --list-agents
        """,
    )

    parser.add_argument(
        "--agent", "-a",
        default="rex",
        help="Agent ID to test (default: rex)",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Interactive REPL mode (default)",
    )
    mode_group.add_argument(
        "--auto",
        action="store_true",
        help="Run automated test sequence",
    )
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Assemble context without calling LLM (no services needed)",
    )
    mode_group.add_argument(
        "--reflect",
        action="store_true",
        help="Run reflection cycle (updates core memory from recent conversations)",
    )
    mode_group.add_argument(
        "--list-agents",
        action="store_true",
        help="List all available agents and exit",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="With --reflect: run reflection on all agents",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full context assembly and debug info",
    )

    return parser.parse_args(argv)


# ── Main ──────────────────────────────────────────────────────────

async def _ensure_core_memory(agent_id: str, agent_config, services: dict) -> None:
    """Initialize core memory for an agent if it doesn't exist yet."""
    core_memory = services["core_memory"]
    existing = await core_memory.get_core_memory(agent_id)
    if existing is not None:
        return

    # Extract identity from system prompt (first paragraph after the character intro)
    identity = agent_config.system_prompt.strip()
    # Use the display_name and a brief identity line
    identity_line = (
        f"I am {agent_config.display_name}. "
        f"My conversation model is {agent_config.model_conversation}."
    )
    await core_memory.initialize_agent_memory(agent_id, identity_line)
    print_memory_event("🧠", f"Initialized core memory for {agent_id}")


async def async_main(args: argparse.Namespace) -> None:
    # List agents mode
    if args.list_agents:
        from core.agent_registry import AgentRegistry

        registry = AgentRegistry(redis_client=None)
        await registry.load_all()
        console.print()
        table = Table(title="Available Agents", show_header=True, border_style="cyan")
        table.add_column("ID", style="bold")
        table.add_column("Name")
        table.add_column("Role")
        table.add_column("Conv Model")
        table.add_column("Build Model")
        table.add_column("Chattiness")
        for agent in registry.get_all_agents():
            color = AGENT_COLORS.get(agent.id, "white")
            table.add_row(
                f"[{color}]{agent.id}[/{color}]",
                agent.display_name,
                AGENT_ROLES.get(agent.id, "—"),
                agent.model_conversation,
                agent.model_building,
                f"{agent.chattiness:.1f}",
            )
        console.print(table)
        return

    is_dry_run = args.dry_run
    services = await bootstrap_services(dry_run=is_dry_run)

    try:
        # Validate agent exists
        agent_config = services["agent_registry"].get_agent(args.agent)
        if agent_config is None:
            available = [a.id for a in services["agent_registry"].get_all_agents()]
            console.print(
                f"[bold red]Agent '{args.agent}' not found.[/bold red] "
                f"Available: {', '.join(available)}"
            )
            return

        console.print()
        console.print(agent_label(args.agent))
        console.print(f"  [dim]Model: {agent_config.model_conversation}[/dim]")
        console.print(f"  [dim]Chattiness: {agent_config.chattiness} │ "
                       f"Initiative: {agent_config.initiative}[/dim]")
        console.print()

        # Auto-initialize core memory if missing (requires DB)
        if not is_dry_run and services.get("core_memory"):
            await _ensure_core_memory(args.agent, agent_config, services)

        if is_dry_run:
            await run_dry_run(args.agent, services, args.verbose)
        elif args.reflect:
            await run_reflect(args.agent, services, run_all=args.all)
        elif args.auto:
            await run_auto(args.agent, services, args.verbose)
        else:
            # Default to interactive
            await run_interactive(args.agent, services, args.verbose)

    finally:
        await shutdown_services(services)


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted. Goodbye.[/dim]")


if __name__ == "__main__":
    main()

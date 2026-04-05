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
import json
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
    "management": "bright_white",
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
    "management": "Content Filter",
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


# ── Service bootstrapping (shared) ────────────────────────────────

from core.bootstrap import Services, bootstrap_services, shutdown_services  # noqa: E402


# ── Tool support (shared with ConversationEngine) ──────────────────

from core.tool_executor import (  # noqa: E402
    build_agent_tools as build_tools_for_agent,
    execute_tool_calls,
    tools_to_openai_schema,
)


# ── TTS playback ─────────────────────────────────────────────────


async def play_tts(
    agent_id: str, text: str, tts_pipeline, verbose: bool = False,
) -> None:
    """Generate TTS audio and play it through the system speaker."""
    if tts_pipeline is None:
        return

    console.print(f"  [dim]🔊 Generating voice...[/dim]")
    result = await tts_pipeline.speak(agent_id, text)
    if result is None:
        if verbose:
            console.print("  [dim]No voice for this agent[/dim]")
        return

    # Play the audio file (macOS: afplay, Linux: aplay/paplay)
    audio_path = tts_pipeline.audio_dir / Path(result["audio_url"]).name
    duration = result.get("duration", 0)
    if verbose:
        console.print(
            f"  [dim]🔊 Playing {duration:.1f}s audio[/dim]"
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "afplay", str(audio_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except FileNotFoundError:
        # afplay not available (not macOS) — try paplay (PulseAudio)
        try:
            proc = await asyncio.create_subprocess_exec(
                "paplay", str(audio_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except FileNotFoundError:
            console.print(
                "  [yellow]No audio player found "
                "(install afplay or paplay)[/yellow]"
            )


# ── Core pipeline: one turn ───────────────────────────────────────


async def run_turn(
    agent_id: str,
    user_message: str,
    conversation_history: list[dict[str, str]],
    services: Services,
    stats: SessionStats,
    verbose: bool = False,
    agent_tools: dict | None = None,
    tts_pipeline=None,
) -> str:
    """Execute one full turn: assemble context → call LLM → handle tool calls → return response."""
    context_assembler = services.context_assembler
    llm_client = services.llm_client
    token_counter = services.token_counter

    agent_config = services.agent_registry.get_agent(agent_id)
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

    # Build OpenAI tool schemas if tools are available
    openai_tools = tools_to_openai_schema(agent_tools) if agent_tools else None

    # Call LLM (with tool-call loop)
    max_tool_rounds = 5
    for round_num in range(max_tool_rounds + 1):
        console.print(f"  [dim]🤖 Calling {model}...[/dim]")
        response = await llm_client.complete(
            messages=messages,
            model=model,
            agent_id=agent_id,
            max_tokens=1000,
            tools=openai_tools,
        )

        stats.record_llm_call(
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost=response.estimated_cost,
            latency_ms=response.latency_ms,
        )

        # If no tool calls, we have the final response
        if not response.tool_calls or not agent_tools:
            break

        # Display and execute tool calls
        console.print(f"  [bold cyan]🔧 Agent wants to use {len(response.tool_calls)} tool(s):[/bold cyan]")
        for tc in response.tool_calls:
            console.print(f"    [cyan]→ {tc.name}[/cyan]")

        # Add assistant message with tool calls to messages
        assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, default=str)},
            }
            for tc in response.tool_calls
        ]
        messages.append(assistant_msg)

        # Execute tools and append results
        tool_results = await execute_tool_calls(
            response.tool_calls, agent_tools, agent_id,
        )
        for tr in tool_results:
            tool_name = next(
                (tc.name for tc in response.tool_calls if tc.id == tr["tool_call_id"]),
                "unknown",
            )
            result_data = json.loads(tr["content"])
            status = result_data.get("status", "unknown")
            status_color = "green" if status == "ok" or status == "sent" or status == "created" else "yellow"
            console.print(f"    [dim]← {tool_name}: [{status_color}]{status}[/{status_color}][/dim]")
            messages.append(tr)
    else:
        console.print("  [yellow]⚠ Max tool rounds reached, returning last response[/yellow]")

    print_agent_response(agent_id, response.content)
    print_token_usage(
        response.input_tokens,
        response.output_tokens,
        response.estimated_cost,
        response.latency_ms,
        model,
    )

    # Play TTS if enabled
    if tts_pipeline and response.content:
        await play_tts(agent_id, response.content, tts_pipeline, verbose)

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
    services: Services,
    stats: SessionStats,
) -> None:
    """Graceful session end: compact full conversation → run reflection → update core memory."""
    if not conversation_history:
        return

    console.print()
    console.print("[bold cyan]━━━ Saving session memories... ━━━[/bold cyan]")

    compactor = services.compactor
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
    llm_client = services.llm_client
    core_memory_mgr = services.core_memory
    memory_repo = services.memory_repo
    token_counter = services.token_counter
    agent_registry = services.agent_registry

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


async def run_reflect(agent_id: str | None, services: Services, run_all: bool = False) -> None:
    """Run 6-hour reflection on one agent or all agents."""
    from core.memory.reflection import ReflectionManager

    llm_client = services.llm_client
    core_memory_mgr = services.core_memory
    memory_repo = services.memory_repo
    token_counter = services.token_counter
    agent_registry = services.agent_registry

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
            f"[dim]Skipping agents with chattiness=0 (management, alpha)[/dim]",
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


async def run_reflect_interactive(agent_id: str, services: Services) -> None:
    """Run reflection for a single agent from within interactive mode."""
    from core.memory.reflection import ReflectionManager

    llm_client = services.llm_client
    core_memory_mgr = services.core_memory
    memory_repo = services.memory_repo
    token_counter = services.token_counter
    agent_registry = services.agent_registry

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

async def run_dry_run(agent_id: str, services: Services, verbose: bool) -> None:
    """Show assembled context without calling LLM."""
    context_assembler = services.context_assembler
    token_counter = services.token_counter

    agent_config = services.agent_registry.get_agent(agent_id)
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

async def run_interactive(
    agent_id: str,
    services: Services,
    verbose: bool,
    use_tools: bool = True,
    tts_enabled: bool = False,
) -> None:
    """REPL loop: type messages, see responses. Tools are available by default."""
    from core.tts import TTSPipeline

    stats = SessionStats()
    conversation_history: list[dict[str, str]] = []

    # Build tools for this agent
    agent_tools = (
        build_tools_for_agent(agent_id, services)
        if use_tools else None
    )
    tool_count = len(agent_tools) if agent_tools else 0

    # Initialize TTS pipeline if enabled
    tts_pipeline = TTSPipeline() if tts_enabled else None

    color = AGENT_COLORS.get(agent_id, "white")
    tools_note = (
        f"[green]{tool_count} tools loaded[/green]"
        if agent_tools else "[dim]no tools[/dim]"
    )
    tts_note = (
        " | [green]🔊 TTS on[/green]"
        if tts_enabled else ""
    )
    console.print(Panel(
        f"[bold]Interactive session with {agent_id.upper()}[/bold]"
        f" ({tools_note}{tts_note})\n"
        f"Type messages and press Enter. "
        f"Type 'quit' or Ctrl+C to exit.\n"
        f"Commands: /memory  /reflect  /stats  /clear  "
        f"/verbose  /tools  /tts  /help",
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
            core_mem = services.core_memory
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

        if user_input.lower() == "/tools":
            if agent_tools:
                console.print(Panel(
                    "\n".join(
                        f"[bold]{name}[/bold] — {tool.description}"
                        for name, tool in sorted(agent_tools.items())
                    ),
                    title=f"Available Tools ({len(agent_tools)})",
                    border_style="cyan",
                ))
            else:
                console.print("  [dim]No tools loaded[/dim]")
            continue

        if user_input.lower() == "/tts":
            if tts_pipeline is None:
                tts_pipeline = TTSPipeline()
                console.print("  [green]🔊 TTS enabled[/green]")
            else:
                await tts_pipeline.shutdown()
                tts_pipeline = None
                console.print("  [dim]🔇 TTS disabled[/dim]")
            continue

        if user_input.lower() == "/help":
            console.print(Panel(
                "[bold]/memory[/bold]   — Show agent's core memory\n"
                "[bold]/reflect[/bold]  — Run reflection cycle\n"
                "[bold]/stats[/bold]    — Show session statistics\n"
                "[bold]/tools[/bold]    — List available tools\n"
                "[bold]/tts[/bold]      — Toggle text-to-speech\n"
                "[bold]/clear[/bold]    — Clear conversation history\n"
                "[bold]/verbose[/bold]  — Toggle verbose mode\n"
                "[bold]quit[/bold]      — Exit (saves session)",
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
            agent_tools=agent_tools,
            tts_pipeline=tts_pipeline,
        )

    # Clean up TTS
    if tts_pipeline:
        await tts_pipeline.shutdown()

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


async def run_auto(agent_id: str, services: Services, verbose: bool) -> None:
    """Run predefined test sequence exercising the full pipeline."""
    stats = SessionStats()
    conversation_history: list[dict[str, str]] = []
    agent_tools = build_tools_for_agent(agent_id, services)

    color = AGENT_COLORS.get(agent_id, "white")
    console.print(Panel(
        f"[bold]Auto-test sequence for {agent_id.upper()}[/bold]\n"
        f"{len(AUTO_PROMPTS)} prompts testing: character, memory store, "
        f"normal response, memory recall, continuity\n"
        f"[green]{len(agent_tools)} tools available[/green]",
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
            agent_tools=agent_tools,
        )

    # End-of-session: compact and reflect
    await end_session(agent_id, conversation_history, services, stats)
    print_session_summary(stats)


# ── Diagnostic mode ──────────────────────────────────────────────

# Tools grouped by category so the agent exercises them in a logical order.
# Each entry: (tool_name, instruction for the agent, expected_status).
DIAGNOSTIC_TOOL_TESTS: list[dict[str, str]] = [
    # ── Core tools ──
    {
        "label": "get_world_state",
        "prompt": (
            "Use the get_world_state tool to check the current world state. "
            "Report what you find."
        ),
    },
    {
        "label": "get_audience_status",
        "prompt": (
            "Use the get_audience_status tool to check viewer count and recent chat. "
            "Report the results."
        ),
    },
    {
        "label": "send_message",
        "prompt": (
            "Use the send_message tool to send a test message to Rex saying "
            "'Diagnostic check — please ignore'. Report the result."
        ),
    },
    # ── Audience tools ──
    {
        "label": "create_poll",
        "prompt": (
            "Use the create_poll tool to create a test poll with the title "
            "'Diagnostic test poll' and options ['Option A', 'Option B']. "
            "Report the poll_id."
        ),
    },
    {
        "label": "get_poll_results",
        "prompt": (
            "Use the get_poll_results tool with the poll_id from the previous step "
            "to check poll results. Report what you see."
        ),
    },
    # ── Revenue tools ──
    {
        "label": "get_revenue_status",
        "prompt": (
            "Use the get_revenue_status tool to check current revenue and costs. "
            "Report the summary."
        ),
    },
    {
        "label": "draft_social_post",
        "prompt": (
            "Use the draft_social_post tool to draft a tweet about our diagnostic test. "
            "Platform: twitter, content: 'Diagnostic test post — ignore'. Report the result."
        ),
    },
    {
        "label": "draft_email",
        "prompt": (
            "Use the draft_email tool to draft an email with subject 'Diagnostic Test', "
            "recipient 'test@example.com', body 'This is a diagnostic test email'. "
            "Report the result."
        ),
    },
    # ── Web tools ──
    {
        "label": "web_search",
        "prompt": (
            "Use the web_search tool to search for 'python programming'. "
            "Report how many results you got and the first title."
        ),
    },
    {
        "label": "fetch_url",
        "prompt": (
            "Use the fetch_url tool to fetch 'https://httpbin.org/html'. "
            "Report whether you got content and approximately how long it is."
        ),
    },
    # ── Memory tools ──
    {
        "label": "update_core_memory (append)",
        "prompt": (
            "Use the update_core_memory tool with action 'append' and section 'notes', "
            "content 'Diagnostic test entry — safe to delete'. Report the result."
        ),
    },
    {
        "label": "recall_memory",
        "prompt": (
            "Use the recall_memory tool to search for 'diagnostic test'. "
            "Report what memories you found."
        ),
    },
    # ── Code execution ──
    {
        "label": "execute_code",
        "prompt": (
            "Use the execute_code tool to run this Python code: print('Hello from diagnostic!'). "
            "Report the output."
        ),
    },
    # ── Self-modification ──
    {
        "label": "view_evolution_log",
        "prompt": (
            "Use the view_evolution_log tool to check your evolution history. "
            "Report how many entries you found."
        ),
    },
]


async def run_diagnostic(agent_id: str, services: Services, verbose: bool) -> None:
    """Run diagnostic mode: systematically test each tool through the agent."""
    stats = SessionStats()
    conversation_history: list[dict[str, str]] = []
    agent_tools = build_tools_for_agent(agent_id, services)

    console.print(Panel(
        f"[bold]🔬 DIAGNOSTIC MODE — {agent_id.upper()}[/bold]\n"
        f"Testing {len(DIAGNOSTIC_TOOL_TESTS)} tools through the agent pipeline\n"
        f"[green]{len(agent_tools)} tools loaded:[/green] "
        + ", ".join(sorted(agent_tools.keys())),
        border_style="bright_yellow",
    ))

    # System message telling the agent it's in diagnostic mode
    diagnostic_system = (
        "[DIAGNOSTIC MODE] You are being tested in diagnostic mode. "
        "For each prompt, use the EXACT tool mentioned. Always call the tool — "
        "do not just describe what you would do. After calling the tool, "
        "briefly report the result status (success/failure) and key data returned. "
        "Keep responses short and factual."
    )
    conversation_history.append({"role": "user", "content": diagnostic_system})

    results: list[dict] = []

    for i, test in enumerate(DIAGNOSTIC_TOOL_TESTS, 1):
        tool_name = test["label"]
        # Skip tools this agent doesn't have
        base_tool_name = tool_name.split(" ")[0]
        if base_tool_name not in agent_tools:
            console.print(
                f"\n  [dim]⏭  Step {i}/{len(DIAGNOSTIC_TOOL_TESTS)}: "
                f"{tool_name} — [yellow]SKIPPED[/yellow] (not available for {agent_id})[/dim]"
            )
            results.append({"tool": tool_name, "status": "skipped", "reason": "not available"})
            continue

        console.print()
        console.print(
            f"[bold bright_yellow]━━━ Diagnostic {i}/{len(DIAGNOSTIC_TOOL_TESTS)}: "
            f"{tool_name} ━━━[/bold bright_yellow]"
        )

        try:
            response_text = await run_turn(
                agent_id=agent_id,
                user_message=test["prompt"],
                conversation_history=conversation_history,
                services=services,
                stats=stats,
                verbose=verbose,
                agent_tools=agent_tools,
            )
            results.append({"tool": tool_name, "status": "pass", "response": response_text[:200]})
        except Exception as exc:
            console.print(f"  [bold red]FAILED: {exc}[/bold red]")
            results.append({"tool": tool_name, "status": "fail", "error": str(exc)})

    # ── Summary report ──
    console.print()
    console.print(Panel("[bold]🔬 DIAGNOSTIC REPORT[/bold]", border_style="bright_yellow"))

    report_table = Table(show_header=True, border_style="bright_yellow")
    report_table.add_column("#", width=3)
    report_table.add_column("Tool", width=30)
    report_table.add_column("Status", width=10)
    report_table.add_column("Notes", style="dim")

    passed = skipped = failed = 0
    for i, r in enumerate(results, 1):
        status = r["status"]
        if status == "pass":
            status_text = "[green]PASS[/green]"
            passed += 1
        elif status == "skipped":
            status_text = "[yellow]SKIP[/yellow]"
            skipped += 1
        else:
            status_text = "[red]FAIL[/red]"
            failed += 1
        notes = r.get("error", r.get("reason", ""))
        report_table.add_row(str(i), r["tool"], status_text, notes[:60])

    console.print(report_table)
    console.print()
    console.print(
        f"  [bold]Results:[/bold] "
        f"[green]{passed} passed[/green], "
        f"[yellow]{skipped} skipped[/yellow], "
        f"[red]{failed} failed[/red] "
        f"out of {len(results)} tests"
    )
    print_session_summary(stats)


# ── Multi-agent conversation mode ────────────────────────────────


async def run_multi(
    agent_ids: list[str],
    services: Services,
    *,
    convo_type: str = "freeform",
    topic: str | None = None,
    max_turns: int | None = None,
    verbose: bool = False,
) -> None:
    """Run a multi-agent conversation using the same pipeline as single-agent chat.

    Reuses: bootstrap_services, context assembly, LLM client, memory,
    display formatting, and end-of-session compaction/reflection.
    """
    from core.config_loader import ConfigLoader
    from core.conversation.energy import ConversationEnergy
    from core.conversation.speaker_selector import InterruptState, SpeakerSelector
    from core.conversation.topic_detector import TopicDetector

    stats = SessionStats()
    conversation_history: list[dict[str, str]] = []
    agent_registry = services.agent_registry
    context_assembler = services.context_assembler
    llm_client = services.llm_client
    token_counter = services.token_counter

    # Load conversation config for speaker selection + energy
    config_loader = ConfigLoader()
    config_loader.load()
    cfg = config_loader.config

    selector = SpeakerSelector(cfg)
    topic_detector = TopicDetector(cfg.topics, llm_client)
    energy = ConversationEnergy(cfg.energy)
    interrupt_state = InterruptState()

    # Validate agents and ensure core memory
    agents = []
    for aid in agent_ids:
        agent_config = agent_registry.get_agent(aid)
        if agent_config is None:
            console.print(f"[bold red]Agent '{aid}' not found, skipping[/bold red]")
            continue
        agents.append(agent_config)

    if len(agents) < 2:
        console.print("[bold red]Need at least 2 valid agents for a conversation[/bold red]")
        return

    # Banner
    agent_names = ", ".join(
        f"[{AGENT_COLORS.get(a.id, 'white')}]{a.id}[/{AGENT_COLORS.get(a.id, 'white')}]"
        for a in agents
    )
    console.print(Panel(
        f"[bold]Multi-agent conversation[/bold]\n"
        f"Agents: {agent_names}\n"
        f"Type: {convo_type}"
        + (f" | Topic: {topic}" if topic else "")
        + (f" | Max turns: {max_turns}" if max_turns else ""),
        border_style="bright_cyan",
    ))

    turn_cap = max_turns or cfg.energy.maximum_turns
    detected_topic = "general"

    # ── Opening turn ──────────────────────────────────────────────
    # Pick opener: first specified agent, or Vera for standups
    opener = agents[0]
    if convo_type == "standup":
        vera = next((a for a in agents if a.id == "vera"), None)
        if vera:
            opener = vera

    # Build the opening prompt
    if topic:
        opening_prompt = (
            f"[The group wants to discuss: {topic}. "
            f"Open the conversation on this topic in your style.]"
        )
    elif convo_type == "standup":
        opening_prompt = "[It's time for the daily standup. Lead the check-in.]"
    else:
        opening_prompt = "[Start a conversation with whoever is nearby.]"

    # Generate opener using the same run_turn pipeline
    console.print()
    console.print(f"  [dim]Generating opening from {opener.id}...[/dim]")

    messages = await context_assembler.assemble_context(
        agent_id=opener.id,
        conversation_history=[{"role": "user", "content": opening_prompt}],
    )
    response = await llm_client.complete(
        messages=messages,
        model=opener.model_conversation,
        agent_id=opener.id,
        max_tokens=500,
    )
    stats.record_llm_call(
        response.input_tokens, response.output_tokens,
        response.estimated_cost, response.latency_ms,
    )

    print_agent_response(opener.id, response.content)
    print_token_usage(
        response.input_tokens, response.output_tokens,
        response.estimated_cost, response.latency_ms, opener.model_conversation,
    )

    conversation_history.append({
        "role": "assistant", "speaker": opener.id, "content": response.content,
    })
    energy.tick(detected_topic)

    # ── Conversation loop ─────────────────────────────────────────
    previous_speaker = opener.id
    turn = 1

    while energy.should_continue and turn < turn_cap:
        turn += 1

        # Detect topic from recent history
        detected_topic = await topic_detector.detect_topic(conversation_history[-5:])

        # Select next speaker
        result = selector.select(
            conversation_history=conversation_history,
            eligible_agents=agents,
            energy=energy.energy,
            detected_topic=detected_topic,
            interrupt_state=interrupt_state,
        )

        speaker = next((a for a in agents if a.id == result.selected_agent_id), None)
        if speaker is None:
            break

        # Build context: the conversation so far is the "history" for this agent.
        # Each agent sees the conversation as alternating user/assistant messages
        # from their perspective.
        agent_history: list[dict[str, str]] = []
        for msg in conversation_history:
            if msg.get("speaker") == speaker.id:
                agent_history.append({"role": "assistant", "content": msg["content"]})
            else:
                speaker_name = msg.get("speaker", "someone")
                agent_history.append({
                    "role": "user",
                    "content": f"[{speaker_name}]: {msg['content']}",
                })

        # Assemble context and call LLM
        messages = await context_assembler.assemble_context(
            agent_id=speaker.id,
            conversation_history=agent_history,
        )
        response = await llm_client.complete(
            messages=messages,
            model=speaker.model_conversation,
            agent_id=speaker.id,
            max_tokens=500,
        )
        stats.record_llm_call(
            response.input_tokens, response.output_tokens,
            response.estimated_cost, response.latency_ms,
        )

        # Display
        is_closing = not energy.should_continue or turn >= turn_cap
        if result.was_interrupt:
            console.print(f"  [bold red]⚡ {speaker.id} interrupts![/bold red]")

        print_agent_response(speaker.id, response.content)
        print_token_usage(
            response.input_tokens, response.output_tokens,
            response.estimated_cost, response.latency_ms, speaker.model_conversation,
        )

        # Check recall memories
        for msg in messages:
            if "Relevant memories" in msg.get("content", ""):
                stats.memories_recalled += 1
                print_memory_event("🔍", f"Recalled memories for {speaker.id}")
                break

        conversation_history.append({
            "role": "assistant", "speaker": speaker.id, "content": response.content,
        })

        # Tick energy
        events = []
        if detected_topic != (conversation_history[-2].get("topic") if len(conversation_history) > 1 else None):
            events.append("topic_shift")
        energy.tick(detected_topic, events=events)
        previous_speaker = speaker.id

    # ── End of conversation ───────────────────────────────────────
    console.print()
    console.print(
        f"[dim]Conversation ended: {turn} turns, "
        f"energy={energy.energy:.1f}[/dim]"
    )

    # Run end-of-session for each participant (compaction + reflection)
    for agent in agents:
        # Build this agent's view of the conversation
        agent_view = []
        for msg in conversation_history:
            if msg.get("speaker") == agent.id:
                agent_view.append({"role": "assistant", "content": msg["content"]})
            else:
                name = msg.get("speaker", "someone")
                agent_view.append({"role": "user", "content": f"[{name}]: {msg['content']}"})

        await end_session(agent.id, agent_view, services, stats)

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
        "--diagnostic",
        action="store_true",
        help="Run diagnostic mode — test all tools through the agent pipeline",
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
    parser.add_argument(
        "--tts",
        action="store_true",
        help="Enable text-to-speech voice output for agent responses",
    )

    return parser.parse_args(argv)


# ── Main ──────────────────────────────────────────────────────────

async def async_main(args: argparse.Namespace) -> None:
    # List agents mode
    if args.list_agents:
        list_svc = await bootstrap_services(dry_run=True)
        registry = list_svc.agent_registry
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
    services = await bootstrap_services(dry_run=is_dry_run, auto_migrate=True)

    try:
        # Validate agent exists
        agent_config = services.agent_registry.get_agent(args.agent)
        if agent_config is None:
            available = [a.id for a in services.agent_registry.get_all_agents()]
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

        if is_dry_run:
            await run_dry_run(args.agent, services, args.verbose)
        elif args.reflect:
            await run_reflect(args.agent, services, run_all=args.all)
        elif args.auto:
            await run_auto(args.agent, services, args.verbose)
        elif args.diagnostic:
            await run_diagnostic(args.agent, services, args.verbose)
        else:
            # Default to interactive
            await run_interactive(
                args.agent, services, args.verbose,
                tts_enabled=args.tts,
            )

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

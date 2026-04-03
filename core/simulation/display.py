"""Rich terminal display for simulation progress."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

if TYPE_CHECKING:
    from datetime import timedelta
    from decimal import Decimal

    from core.models import Simulation
    from core.simulation.orchestrator import SimulationConfig
    from core.simulation.phases import PhaseResult

# Same color scheme as watch_conversations.py
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

PHASE_ICONS: dict[str, str] = {
    "scheduled": ">>",
    "organic": "..",
    "challenge": "##",
    "tool_exercise": "->",
    "reflection": "~~",
    "audience_sim": "<<",
}

custom_theme = Theme({
    f"agent.{name}": color for name, color in AGENT_COLORS.items()
})
console = Console(theme=custom_theme)


class SimulationDisplay:
    """Rich-based terminal display for simulation progress."""

    def __init__(self, *, verbose: bool = False) -> None:
        self._verbose = verbose

    def show_simulation_start(self, sim: Any, config: SimulationConfig) -> None:
        """Display simulation header."""
        console.print()
        console.print(Panel(
            f"[bold bright_cyan]Simulation: {config.name}[/bold bright_cyan]\n"
            f"[dim]{config.description or 'No description'}[/dim]\n"
            f"[dim]ID: {sim.id}[/dim]\n"
            f"[dim]Agents: {', '.join(config.agents)}[/dim]\n"
            f"[dim]Phases: {len(config.phases)} | "
            f"Max cost: ${config.max_cost} | "
            f"Dry run: {config.dry_run}[/dim]",
            border_style="bright_cyan",
            padding=(1, 2),
        ))
        console.print()

    def show_phase_start(self, name: str, index: int, total: int) -> None:
        """Display phase start indicator."""
        progress = f"[{index + 1}/{total}]"
        console.print(
            f"  [bold bright_cyan]{progress}[/bold bright_cyan] "
            f"[bold]Starting phase:[/bold] {name}"
        )

    def show_phase_complete(self, result: PhaseResult, name: str) -> None:
        """Display phase completion stats."""
        status_style = "green" if result.status == "completed" else "red"
        stats = (
            f"[{status_style}]{result.status}[/{status_style}] "
            f"| {result.duration_seconds:.1f}s "
            f"| {result.turns} turns "
            f"| ${result.cost:.4f}"
        )
        if result.agents_participated:
            agents_str = ", ".join(
                f"[{AGENT_COLORS.get(a, 'white')}]{a}[/{AGENT_COLORS.get(a, 'white')}]"
                for a in result.agents_participated
            )
            stats += f" | agents: {agents_str}"
        if result.errors:
            stats += f" | [red]errors: {len(result.errors)}[/red]"

        console.print(f"       {stats}")

        if self._verbose and result.errors:
            for err in result.errors:
                console.print(f"       [red]  {err}[/red]")

        console.print()

    def show_cost_update(self, current: Decimal, limit: Decimal) -> None:
        """Display current cost vs limit."""
        pct = (current / limit * 100) if limit > 0 else 0
        style = "green" if pct < 50 else "yellow" if pct < 80 else "red"
        console.print(
            f"  [dim]Cost:[/dim] [{style}]${current:.4f}[/{style}] "
            f"[dim]/ ${limit:.2f} ({pct:.0f}%)[/dim]"
        )

    def show_cost_exceeded(self, current: Decimal, limit: Decimal) -> None:
        """Display cost limit exceeded warning."""
        console.print()
        console.print(Panel(
            f"[bold red]Cost limit exceeded![/bold red]\n"
            f"Spent: ${current:.4f} | Limit: ${limit:.2f}",
            border_style="red",
        ))

    def show_summary(self, sim: Simulation, real_duration: timedelta) -> None:
        """Display final simulation summary table."""
        console.print()
        console.print(Panel(
            "[bold]Simulation Summary[/bold]",
            border_style="bright_cyan",
        ))

        table = Table(show_header=False, border_style="dim", padding=(0, 2))
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        table.add_row("Status", sim.status)
        table.add_row("Total conversations", str(sim.total_conversations))
        table.add_row("Total turns", str(sim.total_turns))
        table.add_row("Total tokens", f"{sim.total_tokens:,}")
        table.add_row("Total cost", f"${sim.total_cost:.4f}")
        table.add_row("Total artifacts", str(sim.total_artifacts))
        table.add_row("Overseer flags", str(sim.total_overseer_flags))
        table.add_row("Agents", ", ".join(sim.agents_participated))
        table.add_row("Real duration", f"{real_duration.total_seconds():.1f}s")
        if sim.simulated_duration:
            hours = sim.simulated_duration.total_seconds() / 3600
            table.add_row("Simulated duration", f"{hours:.1f}h")

        console.print(table)
        console.print()

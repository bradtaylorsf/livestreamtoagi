"""Output formatters for timeline reports."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.reporting.timeline_reporter import ComparisonReport, Report


def format_terminal(report: Report) -> str:
    """Format report for terminal output with Rich-compatible markup."""
    lines: list[str] = []
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  SIMULATION TIMELINE REPORT")
    lines.append(f"  {report.simulation_name} ({report.simulation_id})")
    lines.append(f"{'=' * 60}\n")

    for section in report.sections:
        lines.append(f"\n--- {section.title} ---\n")
        _format_section_data(lines, section.data, indent=0)

    return "\n".join(lines)


def format_json(report: Report) -> str:
    """Format report as JSON string."""
    return json.dumps(report.to_dict(), indent=2, default=str)


def format_markdown(report: Report) -> str:
    """Format report as a markdown document."""
    lines: list[str] = []
    lines.append(f"# Simulation Timeline Report")
    lines.append(f"")
    lines.append(f"**Simulation:** {report.simulation_name}")
    lines.append(f"**ID:** {report.simulation_id}")
    lines.append(f"")

    for section in report.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        _format_markdown_data(lines, section.data, level=0)
        lines.append("")

    return "\n".join(lines)


def format_comparison_terminal(report: ComparisonReport) -> str:
    """Format comparison report for terminal."""
    data = report.to_dict()
    lines: list[str] = []
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  SIMULATION COMPARISON")
    lines.append(f"{'=' * 60}\n")

    a = data.get("simulation_a", {})
    b = data.get("simulation_b", {})
    comp = data.get("comparison", {})

    lines.append(f"  {'Metric':<25} {'Run A':<15} {'Run B':<15} {'Delta':<10}")
    lines.append(f"  {'-' * 65}")

    lines.append(f"  {'Name':<25} {a.get('name', ''):<15} {b.get('name', ''):<15}")
    lines.append(f"  {'Total Cost':<25} ${a.get('total_cost', '0'):<14} ${b.get('total_cost', '0'):<14} {comp.get('cost_delta', '0')}")
    lines.append(f"  {'Conversations':<25} {a.get('total_conversations', 0):<15} {b.get('total_conversations', 0):<15} {comp.get('conversation_delta', 0)}")
    lines.append(f"  {'Avg Turns':<25} {a.get('avg_turns', 0):<15} {b.get('avg_turns', 0):<15} {comp.get('turns_delta', 0)}")

    return "\n".join(lines)


def _format_section_data(lines: list[str], data: Any, indent: int) -> None:
    """Recursively format section data for terminal output."""
    prefix = "  " * (indent + 1)
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                _format_section_data(lines, value, indent + 1)
            else:
                lines.append(f"{prefix}{key}: {value}")
    elif isinstance(data, list):
        for item in data[:20]:  # Limit long lists
            if isinstance(item, dict):
                _format_section_data(lines, item, indent)
                lines.append(f"{prefix}---")
            else:
                lines.append(f"{prefix}- {item}")
        if len(data) > 20:
            lines.append(f"{prefix}... and {len(data) - 20} more")


def _format_markdown_data(lines: list[str], data: Any, level: int) -> None:
    """Recursively format section data as markdown."""
    prefix = "  " * level
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}**{key}:**")
                _format_markdown_data(lines, value, level + 1)
            else:
                lines.append(f"{prefix}- **{key}:** {value}")
    elif isinstance(data, list):
        for item in data[:20]:
            if isinstance(item, dict):
                summary = ", ".join(f"{k}: {v}" for k, v in list(item.items())[:3])
                lines.append(f"{prefix}- {summary}")
            else:
                lines.append(f"{prefix}- {item}")

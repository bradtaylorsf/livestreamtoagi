"""Prompt loader — discovers and loads eval prompt YAML files."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "evals" / "prompts"

REQUIRED_FIELDS = {"name", "system", "rubric", "sub_scores", "output_schema"}


def discover_categories(prompts_dir: Path | None = None) -> list[str]:
    """Scan prompts directory and return sorted list of category names."""
    d = prompts_dir or PROMPTS_DIR
    if not d.exists():
        return []
    return sorted(
        p.stem for p in d.glob("*.yaml")
        if not p.name.startswith("_")
    )


def load_prompt(category: str, prompts_dir: Path | None = None) -> dict[str, Any]:
    """Load and validate a single eval prompt YAML file."""
    d = prompts_dir or PROMPTS_DIR
    path = d / f"{category}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Eval prompt not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    validate_prompt_schema(data, category)
    return data


def validate_prompt_schema(data: dict[str, Any], category: str = "") -> None:
    """Raise ValueError if prompt is missing required fields."""
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(
            f"Eval prompt '{category}' missing required fields: {missing}"
        )


def render_user_prompt(
    prompt_config: dict[str, Any],
    category_data: dict[str, Any],
) -> str:
    """Format simulation data into the user message for the eval LLM call."""
    parts: list[str] = []

    # Rubric
    parts.append("## Scoring Rubric")
    rubric = prompt_config.get("rubric", {})
    for score_range, desc in rubric.items():
        parts.append(f"- **{score_range}**: {desc}")

    # Sub-scores
    parts.append("\n## Sub-scores to evaluate")
    for sub in prompt_config.get("sub_scores", []):
        if isinstance(sub, dict):
            for name, desc in sub.items():
                parts.append(f"- **{name}**: {desc}")
        else:
            parts.append(f"- {sub}")

    # Output format
    parts.append("\n## Required output format")
    parts.append("Respond with valid JSON matching this schema:")
    parts.append(f"```json\n{json.dumps(prompt_config.get('output_schema', {}), indent=2)}\n```")

    # Simulation data
    parts.append("\n## Simulation Data")

    # Summary context (totals) so filtered lists have proper framing
    total_arts = category_data.get("total_artifacts")
    total_convs = category_data.get("total_conversations")
    total_flags = category_data.get("total_management_flags")
    if total_arts is not None or total_convs is not None:
        parts.append("\n### Overall Simulation Totals")
        if total_convs is not None:
            parts.append(f"- Total conversations in simulation: {total_convs}")
        if total_arts is not None:
            parts.append(f"- Total artifacts in simulation: {total_arts}")
        if total_flags is not None:
            parts.append(f"- Total management flags in simulation: {total_flags}")

    if "transcript_text" in category_data:
        parts.append("\n### Transcripts")
        parts.append(str(category_data["transcript_text"])[:100_000])

    if "agent_turns" in category_data:
        parts.append("\n### Agent Turn Counts")
        parts.append(json.dumps(category_data["agent_turns"], indent=2))

    if "management_logs" in category_data:
        logs = category_data["management_logs"]
        parts.append(f"\n### Management Shadow Logs ({len(logs)} entries)")
        for entry in logs[:50]:
            parts.append(
                f"- Agent: {entry.get('agent_id')}, "
                f"Severity: {entry.get('severity')}, "
                f"Action: {entry.get('action_would_take')}, "
                f"Reason: {entry.get('reason', 'N/A')}"
            )

    if "artifacts" in category_data:
        arts = category_data["artifacts"]
        total_context = f" of {total_arts}" if total_arts is not None else ""
        parts.append(f"\n### Artifacts ({len(arts)} shown{total_context})")
        for art in arts[:50]:
            parts.append(
                f"- [{art.get('artifact_type')}] Agent: {art.get('agent_id')}, "
                f"Tool: {art.get('tool_name')}, Status: {art.get('status')}"
            )

    if "conversations" in category_data:
        convs = category_data["conversations"]
        total_context = f" of {total_convs}" if total_convs is not None else ""
        parts.append(f"\n### Conversations ({len(convs)} shown{total_context})")
        for conv in convs[:30]:
            parts.append(
                f"- Trigger: {conv.get('trigger_type')}, "
                f"Agents: {conv.get('participating_agents')}, "
                f"Turns: {conv.get('turn_count')}"
            )

    if "simulation" in category_data:
        sim = category_data["simulation"]
        error_log = sim.get("error_log")
        if error_log:
            parts.append("\n### Error Log")
            parts.append(json.dumps(error_log, indent=2, default=str))

    if "agent_goals" in category_data:
        goals = category_data["agent_goals"]
        parts.append(f"\n### Agent Goals ({len(goals)} total)")
        for goal in goals[:50]:
            parts.append(
                f"- [{goal.get('status')}] Agent: {goal.get('agent_id')}, "
                f"Goal: {goal.get('goal')}, Priority: {goal.get('priority')}, "
                f"Source: {goal.get('source')}"
            )

    if "tool_usage" in category_data:
        usage = category_data["tool_usage"]
        parts.append(f"\n### Tool Usage Summary ({len(usage)} entries)")
        for entry in usage[:50]:
            parts.append(
                f"- Agent: {entry.get('agent_id')}, "
                f"Tool: {entry.get('tool_name')}, "
                f"Uses: {entry.get('use_count')}"
            )

    return "\n".join(parts)

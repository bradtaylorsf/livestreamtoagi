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

    if "transcript_text" in category_data:
        parts.append("\n### Transcripts")
        parts.append(str(category_data["transcript_text"])[:100_000])

    if "agent_turns" in category_data:
        parts.append("\n### Agent Turn Counts")
        parts.append(json.dumps(category_data["agent_turns"], indent=2))

    if "overseer_logs" in category_data:
        logs = category_data["overseer_logs"]
        parts.append(f"\n### Overseer Shadow Logs ({len(logs)} entries)")
        for entry in logs[:50]:
            parts.append(
                f"- Agent: {entry.get('agent_id')}, "
                f"Severity: {entry.get('severity')}, "
                f"Action: {entry.get('action_would_take')}, "
                f"Reason: {entry.get('reason', 'N/A')}"
            )

    if "artifacts" in category_data:
        arts = category_data["artifacts"]
        parts.append(f"\n### Artifacts ({len(arts)} total)")
        for art in arts[:50]:
            parts.append(
                f"- [{art.get('artifact_type')}] Agent: {art.get('agent_id')}, "
                f"Tool: {art.get('tool_name')}, Status: {art.get('status')}"
            )

    if "conversations" in category_data:
        convs = category_data["conversations"]
        parts.append(f"\n### Conversations ({len(convs)} total)")
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

    return "\n".join(parts)

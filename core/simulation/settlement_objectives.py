"""Pure settlement-objective helpers shared across the embodied simulation.

Extracted from :mod:`core.simulation.embodied_supervisor` so the thin
``scripts/minecraft/seed_settlement_objectives.py`` seed step can reuse the
objective-derivation logic without importing the CrewAI-heavy supervisor and
orchestrator modules.
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_SETTLEMENT_OWNER_ORDER = (
    "fork",
    "rex",
    "pixel",
    "sentinel",
    "aurora",
    "vera",
    "grok",
    "alpha",
)


def _env_enabled(value: str | None, *, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _settlement_objective_descriptions(raw: str | None) -> list[str]:
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def _agent_id_order(raw: str | None) -> list[str]:
    return [
        part.strip().lower()
        for part in str(raw or "").replace(",", " ").replace("|", " ").split()
        if part.strip()
    ]


def _settlement_owner_order(
    raw: str | None,
    agents: list[str] | tuple[str, ...],
    *,
    allowed_agents: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    available = [agent.strip().lower() for agent in agents if agent and agent.strip()]
    allowed = [agent.strip().lower() for agent in allowed_agents or () if agent and agent.strip()]
    if allowed:
        allowed_set = set(allowed)
        available = [agent for agent in available if agent in allowed_set]
        for agent in allowed:
            if agent not in available:
                available.append(agent)
    available_set = set(available)
    if raw:
        preferred = _agent_id_order(raw)
    else:
        preferred = list(DEFAULT_SETTLEMENT_OWNER_ORDER)
    ordered: list[str] = []
    for agent in preferred:
        if agent and agent not in ordered and (not available_set or agent in available_set):
            ordered.append(agent)
    for agent in available:
        if agent not in ordered:
            ordered.append(agent)
    return ordered


def _settlement_plan_build_owner_allowlist(env: dict[str, str] | None = None) -> list[str]:
    source = env if env is not None else os.environ
    raw = source.get("MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST") or source.get("SOAK_PLAN_BUILD_BOTS")
    parsed = _agent_id_order(raw)
    return [] if any(agent in {"*", "all", "any"} for agent in parsed) else parsed


def _objective_slug(description: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in description.lower():
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")
    return slug or "objective"


def _settlement_objective_payload(
    index: int,
    description: str,
    owner_order: list[str] | None = None,
) -> dict[str, Any]:
    owner = owner_order[index % len(owner_order)] if owner_order else None
    return {
        "objective_id": f"phase-{index + 1}-{_objective_slug(description)}",
        "phase_index": index,
        "description": description,
        "owner_agent_id": owner,
        "status": "pending",
        "previous_owner_agent_ids": [],
        "owner_started_at_ms": None,
        "stale_after_ms": None,
        "cooldown_until_ms": None,
    }

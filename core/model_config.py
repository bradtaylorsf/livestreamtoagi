"""Environment-driven model selection for logical model roles.

The values here are logical model names. OpenRouter resolves them to provider
IDs; local providers map them to LOCAL_LLM_MODEL / LOCAL_LLM_MODEL_BUILDING.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ModelTier = Literal["fast", "building"]
AgentModelTier = Literal["conversation", "building"]

MODEL_REFERENCE_PREFIX = "model:"
LEGACY_FAST_MODEL = "anthropic/claude-haiku-4.5"
LEGACY_BUILDING_MODEL = "anthropic/claude-sonnet-4.6"


@dataclass(frozen=True)
class InternalModelRole:
    env_var: str
    tier: ModelTier


INTERNAL_MODEL_ROLES: dict[str, InternalModelRole] = {
    "management_filter": InternalModelRole("LTAG_MODEL_MANAGEMENT_FILTER", "fast"),
    "topic_classifier": InternalModelRole("LTAG_MODEL_TOPIC_CLASSIFIER", "fast"),
    "memory_summary": InternalModelRole("LTAG_MODEL_MEMORY_SUMMARY", "fast"),
    "conversation_summary": InternalModelRole("LTAG_MODEL_CONVERSATION_SUMMARY", "fast"),
    "conversation_commitments": InternalModelRole("LTAG_MODEL_CONVERSATION_COMMITMENTS", "fast"),
    "dream_fallback": InternalModelRole("LTAG_MODEL_DREAM_FALLBACK", "building"),
    "reflection_fallback": InternalModelRole("LTAG_MODEL_REFLECTION_FALLBACK", "building"),
    "departure_narrative": InternalModelRole("LTAG_MODEL_DEPARTURE_NARRATIVE", "fast"),
    "character_default_conversation": InternalModelRole(
        "LTAG_MODEL_CHARACTER_DEFAULT_CONVERSATION", "fast"
    ),
    "character_default_building": InternalModelRole(
        "LTAG_MODEL_CHARACTER_DEFAULT_BUILDING", "building"
    ),
    "character_concept": InternalModelRole("LTAG_MODEL_CHARACTER_CONCEPT", "building"),
    "character_config": InternalModelRole("LTAG_MODEL_CHARACTER_CONFIG", "fast"),
    "character_system_prompt": InternalModelRole("LTAG_MODEL_CHARACTER_SYSTEM_PROMPT", "fast"),
    "world_event": InternalModelRole("LTAG_MODEL_WORLD_EVENT", "fast"),
    "world_revenue": InternalModelRole("LTAG_MODEL_WORLD_REVENUE", "fast"),
    "recurring_persona_comment": InternalModelRole("LTAG_MODEL_RECURRING_PERSONA_COMMENT", "fast"),
    "recurring_persona_chat": InternalModelRole("LTAG_MODEL_RECURRING_PERSONA_CHAT", "fast"),
    "simulation_learning_summary": InternalModelRole(
        "LTAG_MODEL_SIMULATION_LEARNING_SUMMARY", "fast"
    ),
    "eval_engine": InternalModelRole("LTAG_MODEL_EVAL_ENGINE", "building"),
    "eval_analyzer": InternalModelRole("LTAG_MODEL_EVAL_ANALYZER", "building"),
    "relationship_sentiment": InternalModelRole("LTAG_MODEL_RELATIONSHIP_SENTIMENT", "fast"),
    "alpha_dispatch": InternalModelRole("LTAG_MODEL_ALPHA_DISPATCH", "building"),
}

AGENT_MODEL_DEFAULTS: dict[str, dict[AgentModelTier, str]] = {
    "alpha": {
        "conversation": "deepseek/deepseek-v3.2",
        "building": "deepseek/deepseek-v3.2",
    },
    "aurora": {
        "conversation": "google/gemini-flash",
        "building": "google/gemini-2.5-pro",
    },
    "fork": {
        "conversation": "deepseek/deepseek-v3.2",
        "building": "deepseek/deepseek-v3.2",
    },
    "grok": {
        "conversation": "x-ai/grok-3-mini",
        "building": "x-ai/grok-3",
    },
    "management": {
        "conversation": LEGACY_FAST_MODEL,
        "building": LEGACY_FAST_MODEL,
    },
    "pixel": {
        "conversation": "openai/gpt-4o-mini",
        "building": "openai/gpt-5.2",
    },
    "rex": {
        "conversation": LEGACY_FAST_MODEL,
        "building": LEGACY_BUILDING_MODEL,
    },
    "sentinel": {
        "conversation": LEGACY_FAST_MODEL,
        "building": LEGACY_FAST_MODEL,
    },
    "vera": {
        "conversation": LEGACY_FAST_MODEL,
        "building": LEGACY_BUILDING_MODEL,
    },
}


def env_key_for_agent_model(agent_id: str, tier: AgentModelTier) -> str:
    safe_agent = "".join(ch if ch.isalnum() else "_" for ch in agent_id.upper())
    return f"LTAG_MODEL_AGENT_{safe_agent}_{tier.upper()}"


def model_ref(role: str) -> str:
    return f"{MODEL_REFERENCE_PREFIX}{_normalize_role(role)}"


def agent_model_ref(agent_id: str, tier: AgentModelTier) -> str:
    return f"{MODEL_REFERENCE_PREFIX}agent:{agent_id}:{tier}"


def is_model_reference(value: object) -> bool:
    return isinstance(value, str) and value.strip().startswith(MODEL_REFERENCE_PREFIX)


def resolve_internal_model(role: str, configured: str | None = None) -> str:
    return _resolve_internal_model(_normalize_role(role), configured, seen=frozenset())


def resolve_agent_model(
    agent_id: str,
    tier: AgentModelTier,
    configured: str | None = None,
) -> str:
    if tier not in {"conversation", "building"}:
        raise ValueError(f"Unknown agent model tier: {tier}")
    return _resolve_agent_model(agent_id, tier, configured, seen=frozenset())


def resolve_model_reference(
    value: str,
    *,
    agent_id: str | None = None,
    tier: AgentModelTier | None = None,
    default_role: str | None = None,
) -> str:
    return _resolve_model_value(
        value,
        agent_id=agent_id,
        tier=tier,
        default_role=default_role,
        seen=frozenset(),
    )


def _resolve_model_value(
    value: str,
    *,
    agent_id: str | None,
    tier: AgentModelTier | None,
    default_role: str | None,
    seen: frozenset[str],
) -> str:
    text = value.strip()
    if not text:
        if default_role is not None:
            return _resolve_internal_model(_normalize_role(default_role), None, seen=seen)
        raise ValueError("Model value cannot be empty")
    if not text.startswith(MODEL_REFERENCE_PREFIX):
        return text

    ref = text.removeprefix(MODEL_REFERENCE_PREFIX).strip()
    if not ref:
        raise ValueError("Empty model reference")
    if ref in seen:
        raise ValueError(f"Cyclic model reference: {text}")
    seen = seen | {ref}

    parts = ref.split(":")
    if parts[0] == "agent":
        if len(parts) != 3:
            raise ValueError(f"Invalid agent model reference: {text}")
        ref_tier = _agent_tier(parts[2])
        return _resolve_agent_model(parts[1], ref_tier, None, seen=seen)

    if ref in {"conversation", "building"}:
        if agent_id is None:
            raise ValueError(f"Agent model reference {text!r} requires agent_id")
        return _resolve_agent_model(agent_id, _agent_tier(ref), None, seen=seen)

    if ref == "agent" and agent_id is not None and tier is not None:
        return _resolve_agent_model(agent_id, tier, None, seen=seen)

    return _resolve_internal_model(_normalize_role(ref), None, seen=seen)


def _resolve_internal_model(
    role: str,
    configured: str | None,
    *,
    seen: frozenset[str],
) -> str:
    spec = INTERNAL_MODEL_ROLES.get(role)
    tier: ModelTier = spec.tier if spec is not None else "fast"

    env_candidates: list[str] = []
    if spec is not None:
        env_candidates.append(spec.env_var)
    env_candidates.append("LTAG_MODEL_BUILDING" if tier == "building" else "LTAG_MODEL_FAST")

    for env_key in env_candidates:
        value = _env_model(env_key)
        if value is not None:
            return _resolve_model_value(
                value,
                agent_id=None,
                tier=None,
                default_role=role,
                seen=seen,
            )

    if configured is not None:
        return _resolve_model_value(
            configured,
            agent_id=None,
            tier=None,
            default_role=role,
            seen=seen,
        )

    return LEGACY_BUILDING_MODEL if tier == "building" else LEGACY_FAST_MODEL


def _resolve_agent_model(
    agent_id: str,
    tier: AgentModelTier,
    configured: str | None,
    *,
    seen: frozenset[str],
) -> str:
    env_candidates = [
        env_key_for_agent_model(agent_id, tier),
        f"LTAG_MODEL_AGENT_DEFAULT_{tier.upper()}",
    ]
    if tier == "conversation":
        env_candidates.extend(["LTAG_MODEL_CONVERSATION", "LTAG_MODEL_FAST"])
    else:
        env_candidates.append("LTAG_MODEL_BUILDING")

    for env_key in env_candidates:
        value = _env_model(env_key)
        if value is not None:
            return _resolve_model_value(
                value,
                agent_id=agent_id,
                tier=tier,
                default_role=None,
                seen=seen,
            )

    if configured is not None:
        return _resolve_model_value(
            configured,
            agent_id=agent_id,
            tier=tier,
            default_role=None,
            seen=seen,
        )

    agent_defaults = AGENT_MODEL_DEFAULTS.get(agent_id.lower())
    if agent_defaults is not None:
        return agent_defaults[tier]
    return LEGACY_BUILDING_MODEL if tier == "building" else LEGACY_FAST_MODEL


def _env_model(key: str) -> str | None:
    value = os.environ.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_role(role: str) -> str:
    return role.strip().lower().replace("-", "_")


def _agent_tier(value: str) -> AgentModelTier:
    tier = value.strip().lower()
    if tier not in {"conversation", "building"}:
        raise ValueError(f"Unknown agent model tier: {value}")
    return tier  # type: ignore[return-value]

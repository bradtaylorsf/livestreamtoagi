"""Tests for E8-5 Mindcraft personality-to-conversation mapping.

The mapping is intentionally deterministic and offline-safe: it proves
respond/initiate rates from ``agents/<id>/config.yaml`` without launching
Minecraft or calling an LLM.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GEN_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "gen_profiles.py"
AGENTS_DIR = REPO_ROOT / "agents"


def _load_gen_module():
    spec = importlib.util.spec_from_file_location("mc_gen_profiles_personality", GEN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


gen = _load_gen_module()


def _cfg(agent_id: str) -> dict[str, Any]:
    return yaml.safe_load((AGENTS_DIR / agent_id / "config.yaml").read_text())


def _personality(agent_id: str) -> dict[str, Any]:
    return gen.build_personality(_cfg(agent_id))


@pytest.mark.parametrize(
    ("chatty_agent", "quieter_agent"),
    [
        ("grok", "sentinel"),
        ("pixel", "fork"),
    ],
)
def test_chattier_agents_have_higher_respond_and_initiate_rates(
    chatty_agent: str, quieter_agent: str
) -> None:
    """Acceptance: chattier agents map to measurably higher conversation rates."""
    chatty = _personality(chatty_agent)
    quieter = _personality(quieter_agent)

    assert _cfg(chatty_agent)["chattiness"] > _cfg(quieter_agent)["chattiness"]
    assert chatty["respond_probability"] > quieter["respond_probability"]
    assert chatty["initiate_probability"] > quieter["initiate_probability"]


def test_alpha_never_responds_or_initiates_normal_conversation() -> None:
    personality = _personality("alpha")

    assert personality["respond_probability"] == 0.0
    assert personality["initiate_probability"] == 0.0
    assert "ignore" in personality["bot_responder"]


@pytest.mark.parametrize("agent_id", gen.discover_agent_ids())
def test_interrupt_and_eavesdrop_knobs_are_mirrored(agent_id: str) -> None:
    cfg = _cfg(agent_id)
    personality = gen.build_personality(cfg)

    assert personality["interrupt_bias"] == pytest.approx(cfg["interrupt_tendency"])
    assert personality["eavesdrop_probability"] == pytest.approx(
        cfg["eavesdrop_tendency"]
    )


@pytest.mark.parametrize("agent_id", gen.discover_agent_ids())
def test_generated_profiles_preserve_adjacency_from_config(agent_id: str) -> None:
    cfg = _cfg(agent_id)
    profile = gen.build_profile(
        agent_id,
        provider="lmstudio",
        local_chat="__LOCAL_LLM_MODEL__",
        local_code="__LOCAL_LLM_MODEL_BUILDING__",
    )

    assert profile["personality"]["adjacency"] == {
        str(key): float(value) for key, value in (cfg.get("adjacency") or {}).items()
    }


def test_profile_with_personality_round_trips_as_json() -> None:
    profile = gen.build_profile(
        "pixel",
        provider="lmstudio",
        local_chat="qwen3-8b",
        local_code="qwen3-30b",
    )

    assert json.loads(json.dumps(profile, indent=4)) == profile
    assert profile["bot_responder"]
    pixel_cfg = _cfg("pixel")
    assert profile["personality"]["respond_probability"] == pytest.approx(
        0.15
        + 0.7 * pixel_cfg["chattiness"]
        + 0.15 * pixel_cfg["interrupt_tendency"]
    )

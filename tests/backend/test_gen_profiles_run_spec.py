"""Run-spec persona override tests for Mindcraft profile generation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GEN_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "gen_profiles.py"
VERA_PROMPT = REPO_ROOT / "agents" / "vera" / "system_prompt.md"
RUN_SPEC_FIXTURE = (
    REPO_ROOT / "tests" / "backend" / "fixtures" / "scenarios" / "with_run_spec.yaml"
)
BASELINE_PROFILE_KEYS = {"name", "model", "code_model", "bot_responder", "personality"}


def _load_gen_module():
    spec = importlib.util.spec_from_file_location("mc_gen_profiles_run_spec", GEN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


gen = _load_gen_module()


def test_build_profile_applies_backstory_override_without_editing_agent_files() -> None:
    before = VERA_PROMPT.read_text()

    profile = gen.build_profile(
        "vera",
        persona_override={"backstory": "I once ran a pirate radio station."},
    )

    assert profile["backstory"] == "I once ran a pirate radio station."
    assert profile["persona"]["display_name"] == "Vera — The Showrunner"
    assert profile["persona"]["backstory_excerpt"] == "I once ran a pirate radio station."
    assert "pirate radio" not in VERA_PROMPT.read_text()
    assert VERA_PROMPT.read_text() == before


def test_build_all_profiles_applies_only_named_persona_overrides() -> None:
    profiles = gen.build_all_profiles(
        persona_overrides={
            "rex": {"backstory": "Rex remembers the first broken pickaxe."},
            "aurora": {
                "display_name": "Aurora Test",
                "backstory": "Aurora painted the spawn plaza before anyone arrived.",
            },
        }
    )

    assert profiles["rex"]["backstory"] == "Rex remembers the first broken pickaxe."
    assert profiles["aurora"]["persona"]["display_name"] == "Aurora Test"
    assert profiles["aurora"]["backstory"].startswith("Aurora painted")
    assert set(profiles["vera"]) == BASELINE_PROFILE_KEYS
    assert "backstory" not in profiles["vera"]
    assert "persona" not in profiles["vera"]


def test_build_all_profiles_applies_factions_and_goals_from_run_spec() -> None:
    profiles = gen.build_all_profiles(
        factions=[
            {
                "name": "builders",
                "members": ["vera", "rex"],
                "goal": "Raise a shared workshop.",
                "stance": "practical",
            }
        ],
        agent_goals={
            "vera": ["Survey the valley.", "Pick a safe build site."],
            "rex": ["Craft the first tool rack."],
        },
    )

    assert profiles["vera"]["faction"] == {
        "name": "builders",
        "role": "member",
        "goal": "Raise a shared workshop.",
        "members": ["vera", "rex"],
        "stance": "practical",
    }
    assert profiles["vera"]["goals"] == [
        "Survey the valley.",
        "Pick a safe build site.",
    ]
    assert profiles["rex"]["faction"]["name"] == "builders"
    assert profiles["rex"]["goals"] == ["Craft the first tool rack."]


def test_build_profile_without_faction_or_goals_keeps_baseline_shape() -> None:
    profile = gen.build_profile("vera", faction=None, goals=None)

    assert set(profile) == BASELINE_PROFILE_KEYS
    assert "faction" not in profile
    assert "goals" not in profile


def test_cli_run_spec_all_writes_profiles_with_override_backstory(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(GEN_SCRIPT),
            "--all",
            "--provider",
            "lmstudio",
            "--local-chat",
            "qwen3-8b",
            "--run-spec",
            str(RUN_SPEC_FIXTURE),
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert proc.returncode == 0, proc.stderr
    vera = json.loads((tmp_path / "vera-bot.json").read_text())
    rex = json.loads((tmp_path / "rex-bot.json").read_text())

    assert "precise memory of rain" in vera["backstory"]
    assert vera["persona"]["display_name"] == "Vera Prime"
    assert vera["faction"]["name"] == "planners"
    assert vera["goals"] == ["Stabilize the settlement before nightfall."]
    assert rex["faction"]["name"] == "planners"
    assert rex["goals"] == ["Build a shared workshop."]
    assert "backstory" not in rex
    assert "persona" not in rex


def test_build_profile_without_override_keeps_baseline_shape() -> None:
    baseline = gen.build_profile("vera")

    assert gen.build_profile("vera", persona_override=None) == baseline
    assert set(baseline) == BASELINE_PROFILE_KEYS


def test_build_all_profiles_rejects_duplicate_faction_names() -> None:
    with pytest.raises(ValueError, match="duplicate faction name"):
        gen.build_all_profiles(
            factions=[
                {"name": "builders", "members": ["vera"], "goal": "Build"},
                {"name": "builders", "members": ["rex"], "goal": "Also build"},
            ]
        )


def test_build_all_profiles_rejects_unknown_faction_member() -> None:
    with pytest.raises(ValueError, match="unknown members"):
        gen.build_all_profiles(
            factions=[
                {"name": "builders", "members": ["nosuch"], "goal": "Build"},
            ]
        )

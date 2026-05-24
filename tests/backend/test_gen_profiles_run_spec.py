"""Run-spec persona override tests for Mindcraft profile generation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

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
    assert set(rex) == BASELINE_PROFILE_KEYS


def test_build_profile_without_override_keeps_baseline_shape() -> None:
    baseline = gen.build_profile("vera")

    assert gen.build_profile("vera", persona_override=None) == baseline
    assert set(baseline) == BASELINE_PROFILE_KEYS

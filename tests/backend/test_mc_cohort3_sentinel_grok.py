"""Tests for E8-4 Sentinel/Grok embodied Mindcraft cohort.

The cohort launch path is intentionally offline-safe here: these tests inspect
committed settings/profile artifacts and run ``--verify``/``--dry-run`` only.
A real run still requires LM Studio, the E2 server, the pinned Mindcraft clone,
and a matching bridge token.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[2]
GEN_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "gen_profiles.py"
AGENTS_DIR = REPO_ROOT / "agents"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
GENERIC_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-cohort-bot.sh"
ALPHA_SETTINGS_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings-alpha.js"
MAIN_APP = REPO_ROOT / "core" / "main.py"

COHORT = {
    "sentinel": {
        "name": "Sentinel",
        "script": REPO_ROOT / "scripts" / "minecraft" / "connect-sentinel-bot.sh",
        "settings": REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings-sentinel.js",
        "profile": REPO_ROOT / "scripts" / "minecraft" / "profiles" / "sentinel-bot.json",
    },
    "grok": {
        "name": "Grok",
        "script": REPO_ROOT / "scripts" / "minecraft" / "connect-grok-bot.sh",
        "settings": REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings-grok.js",
        "profile": REPO_ROOT / "scripts" / "minecraft" / "profiles" / "grok-bot.json",
    },
}

PROFILE_KEYS = {"name", "model", "code_model", "bot_responder", "personality"}
E2_CONTRACT = {
    "host": "127.0.0.1",
    "port": 25565,
    "auth": "offline",
    "minecraft_version": "1.21.6",
    "auto_open_ui": False,
}
VERBAL_SETTINGS = {
    "chat_ingame": True,
    "narrate_behavior": True,
    "chat_bot_messages": True,
    "init_message": "",
    "speak": False,
    "only_chat_with": [],
}


def _load_gen_module():
    spec = importlib.util.spec_from_file_location("mc_gen_profiles_cohort3", GEN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


gen = _load_gen_module()


def _resolve_canonical(raw_id: str) -> str:
    canonical = MODEL_NAME_ALIASES.get(raw_id, raw_id)
    assert canonical in MODEL_REGISTRY, (
        f"{raw_id!r} does not resolve into MODEL_REGISTRY (got {canonical!r})"
    )
    return canonical


def _agent_config(agent_id: str) -> dict:
    return yaml.safe_load((AGENTS_DIR / agent_id / "config.yaml").read_text())


def _claude_row_models(agent_name: str) -> tuple[str, str]:
    pattern = (
        rf"^\|\s*{re.escape(agent_name)}\s*\|[^|]*\|"
        rf"\s*(?P<conversation>[^|]+?)\s*\|\s*(?P<building>[^|]+?)\s*\|"
    )
    for line in CLAUDE_MD.read_text().splitlines():
        match = re.match(pattern, line)
        if match:
            return match.group("conversation").strip(), match.group("building").strip()
    raise AssertionError(f"Could not find {agent_name} in CLAUDE.md model table")


def _claude_model_label(raw_model_id: str) -> str:
    """Render this repo's config model ids in the CLAUDE.md table style."""
    labels = {
        "anthropic/claude-haiku-4.5": "Claude Haiku 4.5",
        "x-ai/grok-3-mini": "Grok 3 Mini",
        "x-ai/grok-3": "Grok 3",
    }
    try:
        return labels[raw_model_id]
    except KeyError as exc:
        raise AssertionError(f"No CLAUDE.md label mapping for {raw_model_id!r}") from exc


def _parse_settings(text: str) -> dict:
    """Parse the Mindcraft settings object from a committed settings.js file."""
    out_lines: list[str] = []
    for line in text.splitlines():
        res: list[str] = []
        in_str = False
        esc = False
        i = 0
        while i < len(line):
            c = line[i]
            if in_str:
                res.append(c)
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                    res.append(c)
                elif c == "/" and i + 1 < len(line) and line[i + 1] == "/":
                    break
                else:
                    res.append(c)
            i += 1
        out_lines.append("".join(res))
    body = "\n".join(out_lines)
    match = re.search(r"const settings\s*=\s*(\{.*\})\s*;", body, re.S)
    assert match, "could not locate `const settings = { ... };` object"
    obj = re.sub(r",(\s*[}\]])", r"\1", match.group(1))
    return json.loads(obj)


def _run(agent_id: str, args: list[str], cwd: Path, extra_env: dict | None = None):
    env = {**os.environ, "MINDCRAFT_DIR": str(cwd / "mindcraft")}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(COHORT[agent_id]["script"]), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


@pytest.mark.parametrize("agent_id", COHORT)
def test_openrouter_profile_matches_config_and_claude_table(agent_id: str) -> None:
    cfg = _agent_config(agent_id)
    profile = gen.build_profile(agent_id)

    assert set(profile) == PROFILE_KEYS
    assert profile["name"] == COHORT[agent_id]["name"]
    assert profile["model"] == f"openrouter/{cfg['model_conversation']}"
    assert profile["code_model"] == f"openrouter/{cfg['model_building']}"
    assert _resolve_canonical(cfg["model_conversation"])
    assert _resolve_canonical(cfg["model_building"])

    claude_conversation, claude_building = _claude_row_models(profile["name"])
    assert claude_conversation == _claude_model_label(cfg["model_conversation"])
    assert claude_building == _claude_model_label(cfg["model_building"])


@pytest.mark.parametrize("agent_id", COHORT)
def test_local_dev_profile_template_matches_generator(agent_id: str) -> None:
    committed = json.loads(COHORT[agent_id]["profile"].read_text())
    generated = gen.build_profile(
        agent_id,
        provider="lmstudio",
        local_chat="__LOCAL_LLM_MODEL__",
        local_code="__LOCAL_LLM_MODEL_BUILDING__",
    )

    assert committed == generated
    assert set(committed) == PROFILE_KEYS
    assert "openrouter/" not in json.dumps(committed)


@pytest.mark.parametrize("agent_id", COHORT)
def test_settings_template_is_single_verbal_headless_bot(agent_id: str) -> None:
    settings = _parse_settings(COHORT[agent_id]["settings"].read_text())

    for key, expected in E2_CONTRACT.items():
        assert settings[key] == expected
    assert settings["profiles"] == [f"./profiles/{agent_id}-bot.json"]
    for key, expected in VERBAL_SETTINGS.items():
        assert settings[key] == expected


@pytest.mark.parametrize("agent_id", COHORT)
def test_settings_keep_alpha_shape_but_flip_verbal_surfaces(agent_id: str) -> None:
    alpha = _parse_settings(ALPHA_SETTINGS_TEMPLATE.read_text())
    settings = _parse_settings(COHORT[agent_id]["settings"].read_text())

    assert set(settings) == set(alpha)
    assert settings["profiles"] == [f"./profiles/{agent_id}-bot.json"]
    assert alpha["chat_ingame"] is False
    assert settings["chat_ingame"] is True
    assert alpha["narrate_behavior"] is False
    assert settings["narrate_behavior"] is True
    assert alpha["chat_bot_messages"] is False
    assert settings["chat_bot_messages"] is True
    assert settings["speak"] is False
    assert settings["init_message"] == ""


@pytest.mark.parametrize("agent_id", COHORT)
def test_launch_script_exists_executable_and_has_valid_bash(agent_id: str) -> None:
    script = COHORT[agent_id]["script"]
    assert script.is_file(), f"missing {script}"
    assert os.access(script, os.X_OK), f"{script.name} must be chmod +x"

    for path in (script, GENERIC_SCRIPT):
        proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("agent_id", COHORT)
def test_help_exits_zero_and_describes_agent_launcher(agent_id: str) -> None:
    proc = subprocess.run(
        ["bash", str(COHORT[agent_id]["script"]), "--help"],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    assert COHORT[agent_id]["script"].name in proc.stdout
    assert "--dry-run" in proc.stdout
    assert "--verify" in proc.stdout
    assert "set -euo pipefail" not in proc.stdout


@pytest.mark.parametrize("agent_id", COHORT)
def test_unknown_argument_is_rejected(agent_id: str) -> None:
    proc = subprocess.run(
        ["bash", str(COHORT[agent_id]["script"]), "--nope"],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


@pytest.mark.parametrize("agent_id", COHORT)
@pytest.mark.parametrize("mode", ["--help", "--verify", "--dry-run"])
def test_static_modes_exit_zero_and_do_not_clone(agent_id: str, mode: str, tmp_path: Path) -> None:
    proc = _run(agent_id, [mode], tmp_path)

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not (tmp_path / "mindcraft").exists(), "static modes must not create a clone"
    assert not (tmp_path / ".git").exists()


@pytest.mark.parametrize("agent_id", COHORT)
def test_verify_reports_verbal_cohort_contract(agent_id: str, tmp_path: Path) -> None:
    proc = _run(agent_id, ["--verify"], tmp_path)

    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert "Static verify passed" in out
    assert COHORT[agent_id]["name"] in out
    assert f"./profiles/{agent_id}-bot.json" in out
    assert "auth=offline" in out
    assert "chat_ingame=true" in out
    assert "narrate_behavior=true" in out
    assert "chat_bot_messages=true" in out
    assert "speak=false" in out
    assert "bridge action assets are present" in out
    assert "!observe" in out
    assert "!place" in out


@pytest.mark.parametrize("agent_id", COHORT)
def test_dry_run_prints_local_model_routing(agent_id: str, tmp_path: Path) -> None:
    proc = _run(
        agent_id,
        ["--dry-run"],
        tmp_path,
        {
            "LOCAL_LLM_MODEL": "qwen3-8b",
            "LOCAL_LLM_MODEL_BUILDING": "qwen3-30b",
            "MINECRAFT_BRIDGE_TOKEN": "test-token",
        },
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert f"bot name {COHORT[agent_id]['name']}" in out
    assert "lmstudio/qwen3-8b" in out
    assert "lmstudio/qwen3-30b" in out
    assert "openrouter/" not in out
    assert "Would copy:   fork-src/ bridge client, action handlers, and helper skills" in out
    assert "Would patch:  inject bridge/action commands" in out


def test_generic_launcher_stages_action_surface_that_feeds_bridge_memory() -> None:
    src = GENERIC_SCRIPT.read_text()

    for token in (
        "python_bridge.js",
        "move_action.js",
        "navigate_action.js",
        "place_action.js",
        "break_action.js",
        "build_from_plan_action.js",
        "execute_code_action.js",
        "observe_action.js",
        "perception.js",
        "building.js",
        "build_plan.js",
        "LTAG_AGENT_ID",
    ):
        assert token in src
    assert "MINECRAFT_BRIDGE_TOKEN is not set" in src
    assert "LOCAL_LLM_MODEL is not set" in src
    assert "node main.js --profiles" in src

    main_src = MAIN_APP.read_text()
    assert "register_memory_consumer" in main_src
    assert "app.include_router(bridge_router)" in main_src


@pytest.mark.parametrize("agent_id", COHORT)
def test_cli_lmstudio_output_matches_committed_template(agent_id: str) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(GEN_SCRIPT),
            agent_id,
            "--provider",
            "lmstudio",
            "--local-chat",
            "__LOCAL_LLM_MODEL__",
            "--local-code",
            "__LOCAL_LLM_MODEL_BUILDING__",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == json.loads(COHORT[agent_id]["profile"].read_text())

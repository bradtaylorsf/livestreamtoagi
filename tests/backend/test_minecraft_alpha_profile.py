"""Tests for Alpha's Mindcraft profile and non-verbal launch path (#565 E7-1).

Alpha is the E7 vertical-slice agent: it may act in-world through Mindcraft and
the Python bridge, but it must not participate in chat. These tests exercise the
offline-safe launch paths and the committed settings/profile artifacts only: no
clone, no network, no Node launch, and no OpenRouter spend.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-alpha-bot.sh"
SETTINGS_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings-alpha.js"
STOCK_SETTINGS_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings.js"
PROFILE_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "profiles" / "alpha-bot.json"
POLL_ERRAND_ACTION = (
    REPO_ROOT / "scripts" / "minecraft" / "fork-src" / "agent" / "commands" / "poll_errand_action.js"
)
ALPHA_DOC = REPO_ROOT / "docs" / "minecraft" / "alpha-profile.md"
CONNECT_DOC = REPO_ROOT / "docs" / "minecraft" / "mindcraft-connect.md"
PACKAGE_JSON = REPO_ROOT / "package.json"

PINNED_SHA = "35be480b4cc0bca990278e6103a1426392559d96"
ALPHA_BOT_NAME = "Alpha"
MC_HOST = "127.0.0.1"
MC_PORT = "25565"
MC_VERSION = "1.21.6"

E2_CONTRACT = {
    "host": MC_HOST,
    "port": int(MC_PORT),
    "auth": "offline",
    "minecraft_version": MC_VERSION,
    "auto_open_ui": False,
}

NON_VERBAL_SETTINGS = {
    "chat_ingame": False,
    "narrate_behavior": False,
    "chat_bot_messages": False,
    "init_message": "",
    "speak": False,
    "only_chat_with": [],
}


def _run(args: list[str], cwd: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


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
    m = re.search(r"const settings\s*=\s*(\{.*\})\s*;", body, re.S)
    assert m, "could not locate `const settings = { ... };` object"
    obj = re.sub(r",(\s*[}\]])", r"\1", m.group(1))
    return json.loads(obj)


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "connect-alpha-bot.sh must be chmod +x"


def test_bash_syntax_is_valid() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_help_exits_zero_and_describes_usage() -> None:
    proc = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "connect-alpha-bot.sh" in proc.stdout
    assert "--dry-run" in proc.stdout
    assert "--verify" in proc.stdout
    assert "set -euo pipefail" not in proc.stdout


def test_unknown_argument_is_rejected() -> None:
    proc = subprocess.run(["bash", str(SCRIPT), "--nope"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


@pytest.mark.parametrize("mode", ["--help", "--verify", "--dry-run"])
def test_static_modes_exit_zero_and_do_not_clone(mode: str, tmp_path: Path) -> None:
    proc = _run([mode], tmp_path, {"MINDCRAFT_DIR": str(tmp_path / "mindcraft")})
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not (tmp_path / "mindcraft").exists(), "static modes must not create a clone"
    assert not (tmp_path / ".git").exists()


def test_verify_reports_alpha_non_verbal_contract(tmp_path: Path) -> None:
    proc = _run(["--verify"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert f"{MC_HOST}:{MC_PORT}" in out
    assert "auth=offline" in out
    assert "Static verify passed" in out
    for key in NON_VERBAL_SETTINGS:
        assert key in out
    assert "chat_ingame=false" in out
    assert "chat_bot_messages=false" in out
    assert "narrate_behavior=false" in out


def test_dry_run_prints_resolved_e2_target_and_local_model(tmp_path: Path) -> None:
    proc = _run(
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
    assert f"host:        {MC_HOST}" in out
    assert f"port:        {MC_PORT}" in out
    assert "auth:        offline" in out
    assert f"minecraft:   {MC_VERSION}" in out
    assert ALPHA_BOT_NAME in out
    assert "lmstudio/qwen3-8b" in out
    assert "lmstudio/qwen3-30b" in out
    assert "openrouter/" not in out
    assert "chat_ingame=false" in out


def test_alpha_profile_is_lmstudio_local_only_with_fixed_name() -> None:
    data = json.loads(PROFILE_TEMPLATE.read_text())
    assert set(data) == {"name", "model", "code_model", "bot_responder", "personality"}
    assert data["name"] == ALPHA_BOT_NAME
    assert data["model"] == "lmstudio/__LOCAL_LLM_MODEL__"
    assert data["code_model"] == "lmstudio/__LOCAL_LLM_MODEL_BUILDING__"
    assert data["personality"]["respond_probability"] == 0.0
    assert data["personality"]["initiate_probability"] == 0.0
    assert "ignore" in data["bot_responder"]
    assert "openrouter/" not in PROFILE_TEMPLATE.read_text()


def test_alpha_settings_are_single_bot_e2_non_verbal() -> None:
    settings = _parse_settings(SETTINGS_TEMPLATE.read_text())

    for key, expected in E2_CONTRACT.items():
        assert settings[key] == expected
    assert settings["profiles"] == ["./profiles/alpha-bot.json"]
    for key, expected in NON_VERBAL_SETTINGS.items():
        assert settings[key] == expected


def test_alpha_settings_only_change_profile_and_chat_surfaces_vs_stock() -> None:
    stock = _parse_settings(STOCK_SETTINGS_TEMPLATE.read_text())
    alpha = _parse_settings(SETTINGS_TEMPLATE.read_text())

    assert set(stock) == set(alpha)
    changed = {key for key in stock if stock[key] != alpha[key]}
    assert changed == {
        "profiles",
        "init_message",
        "chat_ingame",
        "narrate_behavior",
        "chat_bot_messages",
    }


def test_alpha_settings_lines_are_annotated_as_e7_1() -> None:
    src = SETTINGS_TEMPLATE.read_text()
    for key in (
        "profiles",
        "init_message",
        "only_chat_with",
        "speak",
        "chat_ingame",
        "narrate_behavior",
        "chat_bot_messages",
    ):
        assert re.search(rf'"{key}":.*//\s*E7-1:', src), f"{key} needs E7-1 rationale"
    assert "export default settings;" in src


def test_script_real_run_guards_and_staging_contract() -> None:
    src = SCRIPT.read_text()
    assert PINNED_SHA in src
    assert 'REQUIRED_NODE_MAJOR="20"' in src
    assert 'ALPHA_BOT_NAME="Alpha"' in src
    assert "MINECRAFT_BRIDGE_TOKEN is not set" in src
    assert "LOCAL_LLM_MODEL is not set" in src
    assert "No Mindcraft clone at" in src
    assert "not at the pinned commit" in src
    assert "setup-mindcraft.sh" in src
    assert "mindcraft-settings-alpha.js" in src
    assert "profiles/alpha-bot.json" in src
    assert "fork-src" in src
    assert "src/agent/bridge/python_bridge.js" in src
    assert "src/agent/commands/poll_errand_action.js" in src
    assert "LTAG E7-2 poll errand action" in src
    assert "pollErrandAction" in src
    assert "src/agent/commands/actions.js" in src
    assert "restore_clone_patches" in src
    assert "trap restore_clone_patches EXIT" in src
    assert "whitelist add ${ALPHA_BOT_NAME}" in src
    assert "JSON.parse(readFileSync" in src
    assert "JSON.stringify(profile" in src
    assert "openrouter/" not in src


def test_alpha_poll_errand_action_is_non_verbal_and_bridge_backed() -> None:
    src = POLL_ERRAND_ACTION.read_text()
    assert "'!pollErrand'" in src
    assert "service: 'errand'" in src
    assert "method: 'poll'" in src
    assert "payload: { agent_id: ALPHA_AGENT_ID }" in src
    assert "agentId: ALPHA_AGENT_ID" in src
    assert "agent_tier: 'errand'" in src
    assert "safe-idling" in src
    assert "openChat" not in src
    assert "openrouter" not in src.lower()


def test_docs_record_alpha_launch_and_lm_studio_evidence() -> None:
    text = ALPHA_DOC.read_text()
    assert "scripts/minecraft/connect-alpha-bot.sh" in text
    assert "pnpm mc:connect-alpha" in text
    assert "pnpm verify:mindcraft-alpha" in text
    assert "pnpm llm:local --list-only" in text
    assert "LOCAL_LLM_MODEL" in text
    assert "LOCAL_LLM_MODEL_BUILDING" in text
    assert f"{MC_HOST}:{MC_PORT}" in text
    assert "local Mac server" in text
    for key in NON_VERBAL_SETTINGS:
        assert key in text


def test_mindcraft_connect_cross_links_alpha_doc() -> None:
    assert "alpha-profile.md" in CONNECT_DOC.read_text()


def test_package_json_wires_alpha_scripts() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]
    assert scripts.get("mc:connect-alpha") == "scripts/minecraft/connect-alpha-bot.sh"
    assert (
        scripts.get("verify:mindcraft-alpha")
        == ".venv/bin/pytest tests/backend/test_minecraft_alpha_profile.py -v"
    )

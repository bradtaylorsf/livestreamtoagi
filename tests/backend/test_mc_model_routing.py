"""Tests for per-agent multi-model routing (issue #535, epic E3-3).

Decision 0003 (E1-R3 / #520) concluded Mindcraft routes a conversation-tier
``model`` and a distinct building-tier ``code_model`` per bot **natively — no
fork patch**. This issue verifies and documents that, scoped to TWO bots (all
nine production agents are E8 / E3-4).

These exercise only offline-safe paths:

* the two committed routing profile templates + the routing settings template,
* the launch script's ``--help`` / ``--verify`` / ``--dry-run`` modes (no clone,
  no network, no Node, no launch — same posture as
  ``test_minecraft_connect_stock_bot.py``),
* the documented production ``openrouter/`` reference ids resolving through
  ``core.llm_client`` (proves the profiles *mirror* ``MODEL_NAME_ALIASES`` /
  ``MODEL_REGISTRY``),
* preserve-no-regress: ``agents/vera`` and ``agents/aurora`` model assignments
  still resolve, unchanged, through the same alias/registry path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "verify-model-routing.sh"
SETTINGS_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings-routing.js"
PROFILE_A = REPO_ROOT / "scripts" / "minecraft" / "profiles" / "routing-bot-a.json"
PROFILE_B = REPO_ROOT / "scripts" / "minecraft" / "profiles" / "routing-bot-b.json"
ROUTING_DOC = REPO_ROOT / "docs" / "minecraft" / "model-routing.md"
CONNECT_DOC = REPO_ROOT / "docs" / "minecraft" / "mindcraft-connect.md"
DECISION_DOC = REPO_ROOT / "docs" / "decisions" / "0003-mindcraft-model-routing.md"
PACKAGE_JSON = REPO_ROOT / "package.json"
VERA_CONFIG = REPO_ROOT / "agents" / "vera" / "config.yaml"
AURORA_CONFIG = REPO_ROOT / "agents" / "aurora" / "config.yaml"

BOT_A_NAME = "RoutingBotA"
BOT_B_NAME = "RoutingBotB"
MC_HOST = "127.0.0.1"
MC_PORT = "25565"
MC_VERSION = "1.21.6"

# Documented production OpenRouter reference mapping (model-routing.md):
#   RoutingBotA mirrors agents/vera   — claude-haiku-4-5 chat / claude-sonnet-4-6 code
#   RoutingBotB mirrors agents/aurora — gemini-flash      chat / gemini-2.5-pro    code
# Stored here in Mindcraft's "openrouter/<provider>/<model>" string form.
PROD_REF = {
    BOT_A_NAME: {
        "mirrors": "vera",
        "model": "openrouter/anthropic/claude-haiku-4.5",
        "code_model": "openrouter/anthropic/claude-sonnet-4.6",
    },
    BOT_B_NAME: {
        "mirrors": "aurora",
        "model": "openrouter/google/gemini-flash",
        "code_model": "openrouter/google/gemini-2.5-pro",
    },
}


def _run(args, cwd: Path, extra_env: dict | None = None):
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


def _resolve_canonical(openrouter_id: str) -> str:
    """Resolve a bare ``provider/model`` id through the llm_client maps.

    Returns the canonical MODEL_REGISTRY name; raises AssertionError if the id
    does not alias into the registry (proving the doc/profile drifted from
    core/llm_client.py).
    """
    canonical = MODEL_NAME_ALIASES.get(openrouter_id, openrouter_id)
    assert canonical in MODEL_REGISTRY, (
        f"{openrouter_id!r} does not resolve into MODEL_REGISTRY "
        f"via MODEL_NAME_ALIASES (got {canonical!r})"
    )
    return canonical


# ── Script hygiene ──────────────────────────────────────────────────────────


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "verify-model-routing.sh must be chmod +x"


def test_bash_syntax_is_valid():
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean():
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_exits_zero_and_describes_usage():
    proc = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--verify" in proc.stdout
    assert "verify-model-routing.sh" in proc.stdout
    # Help prints only the comment header — never leak script source.
    assert "set -euo pipefail" not in proc.stdout
    assert 'MINDCRAFT_DIR="${MINDCRAFT_DIR' not in proc.stdout


def test_unknown_argument_is_rejected():
    proc = subprocess.run(["bash", str(SCRIPT), "--nope"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


@pytest.mark.parametrize("mode", ["--help", "--verify", "--dry-run"])
def test_static_modes_exit_zero_and_do_not_clone(mode, tmp_path):
    proc = _run([mode], tmp_path, {"MINDCRAFT_DIR": str(tmp_path / "mindcraft")})
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not (tmp_path / "mindcraft").exists(), "no clone in static modes"
    assert not (tmp_path / ".git").exists()


def test_verify_reports_two_bot_plan_without_network(tmp_path):
    proc = _run(["--verify"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert f"{MC_HOST}:{MC_PORT}" in out
    assert "auth=offline" in out
    assert BOT_A_NAME in out
    assert BOT_B_NAME in out
    assert "NO fork patch" in out
    assert "Static verify passed" in out


def test_dry_run_without_env_says_all_four_required(tmp_path):
    proc = _run(["--dry-run"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert "LLM_A_CHAT/LLM_A_CODE/LLM_B_CHAT/LLM_B_CODE unset" in out
    assert "pnpm llm:local --list-only" in out
    assert (
        "node main.js --profiles ./profiles/routing-bot-a.json ./profiles/routing-bot-b.json" in out
    )


def test_dry_run_with_env_substitutes_four_lmstudio_ids(tmp_path):
    proc = _run(
        ["--dry-run"],
        tmp_path,
        {
            "LLM_A_CHAT": "qwen3-8b",
            "LLM_A_CODE": "qwen3-30b",
            "LLM_B_CHAT": "llama3-8b",
            "LLM_B_CODE": "deepseek-coder",
        },
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert f"{BOT_A_NAME}  model: lmstudio/qwen3-8b   code_model: lmstudio/qwen3-30b" in out
    assert f"{BOT_B_NAME}  model: lmstudio/llama3-8b   code_model: lmstudio/deepseek-coder" in out
    assert "openrouter/" not in out


# ── Committed routing settings template ─────────────────────────────────────


def test_routing_settings_template_points_at_e2_with_two_profiles():
    src = SETTINGS_TEMPLATE.read_text()
    # E3-2 E2-server contract preserved verbatim.
    assert f'"minecraft_version": "{MC_VERSION}"' in src
    assert f'"host": "{MC_HOST}"' in src
    assert f'"port": {MC_PORT}' in src
    assert '"auth": "offline"' in src
    assert '"auto_open_ui": false' in src
    # The two E3-3 deltas, each flagged inline.
    assert '"./profiles/routing-bot-a.json"' in src
    assert '"./profiles/routing-bot-b.json"' in src
    assert '"log_all_prompts": true' in src
    assert "E3-3:" in src, "every E3-3 delta must be flagged inline"
    # stock-bot.json may appear in a "// … was [./profiles/stock-bot.json]"
    # delta comment (the same convention mindcraft-settings.js uses), but never
    # as an ACTIVE profiles entry — strip each line's comment before checking.
    for line in src.splitlines():
        code_part = line.split("//", 1)[0]
        assert "stock-bot.json" not in code_part, (
            f"stock-bot must not be an active profile entry: {line!r}"
        )
    # Still a valid Mindcraft-shaped settings module.
    assert src.strip().startswith("//") or "const settings = {" in src
    assert "export default settings;" in src


# ── (a) Committed routing profile templates ─────────────────────────────────


def test_profiles_are_lmstudio_local_only_distinct_and_chat_ne_code():
    sample = {
        "__LLM_A_CHAT__": "qwen3-8b",
        "__LLM_A_CODE__": "qwen3-30b",
        "__LLM_B_CHAT__": "llama3-8b",
        "__LLM_B_CODE__": "deepseek-coder",
    }

    parsed = {}
    for path in (PROFILE_A, PROFILE_B):
        raw = path.read_text()
        # Templates carry placeholders; substituting must yield valid JSON.
        substituted = raw
        for token, value in sample.items():
            substituted = substituted.replace(token, value)
        data = json.loads(substituted)
        parsed[path] = data

        assert data["model"].startswith("lmstudio/"), f"{path}: chat tier must be local"
        assert data["code_model"].startswith("lmstudio/"), f"{path}: code tier must be local"
        assert data["model"] != data["code_model"], (
            f"{path}: chat and code model must differ — that is the point of E3-3"
        )
        # Zero external spend — never an openrouter id, and no embedding (0003).
        assert "openrouter/" not in raw
        assert "embedding" not in data

    a, b = parsed[PROFILE_A], parsed[PROFILE_B]
    assert a["name"] == BOT_A_NAME
    assert b["name"] == BOT_B_NAME
    assert a["name"] != b["name"], "the two bots must use different names"
    # The four resolved tokens are not all identical.
    resolved = {a["model"], a["code_model"], b["model"], b["code_model"]}
    assert len(resolved) > 1, "the four routed models must not all be identical"


def test_profile_templates_carry_the_four_distinct_substitution_tokens():
    raw_a = PROFILE_A.read_text()
    raw_b = PROFILE_B.read_text()
    assert "__LLM_A_CHAT__" in raw_a and "__LLM_A_CODE__" in raw_a
    assert "__LLM_B_CHAT__" in raw_b and "__LLM_B_CODE__" in raw_b
    # A's tokens never leak into B's template and vice-versa.
    assert "__LLM_B_" not in raw_a
    assert "__LLM_A_" not in raw_b


# ── (b) Profiles mirror core/llm_client.py via the documented prod mapping ───


def test_documented_prod_openrouter_refs_resolve_into_model_registry():
    """The documented production openrouter/ ids alias into MODEL_REGISTRY.

    This is the "mirrors core/llm_client.py" acceptance criterion: the prod
    reference mapping documented in model-routing.md must resolve through
    MODEL_NAME_ALIASES, and chat must differ from code for each bot.
    """
    for bot, ref in PROD_REF.items():
        chat_id = ref["model"].removeprefix("openrouter/")
        code_id = ref["code_model"].removeprefix("openrouter/")
        chat_canonical = _resolve_canonical(chat_id)
        code_canonical = _resolve_canonical(code_id)
        assert chat_canonical != code_canonical, (
            f"{bot}: documented prod chat/code resolve to the same model "
            f"({chat_canonical}) — multi-model routing would be vacuous"
        )


def test_routing_doc_records_the_prod_openrouter_reference_mapping():
    text = ROUTING_DOC.read_text()
    for bot, ref in PROD_REF.items():
        assert bot in text, f"{bot} must be named in model-routing.md"
        assert ref["mirrors"] in text, f"{bot}'s mirrored agent must be documented"
        assert ref["model"] in text, f"{bot} prod chat ref {ref['model']} must be documented"
        assert ref["code_model"] in text, (
            f"{bot} prod code ref {ref['code_model']} must be documented"
        )


# ── (c) preserve-no-regress: agent model assignments unchanged ──────────────


@pytest.mark.parametrize(
    ("config_path", "bot"),
    [(VERA_CONFIG, BOT_A_NAME), (AURORA_CONFIG, BOT_B_NAME)],
)
def test_agent_model_assignments_resolve_unchanged_and_match_prod_ref(config_path, bot):
    """agents/<id>/config.yaml model assignments still resolve, unchanged.

    Also locks the documented prod reference to the actual agent config so the
    doc cannot silently drift from agents/vera + agents/aurora.
    """
    cfg = yaml.safe_load(config_path.read_text())
    conv = cfg["model_conversation"]
    build = cfg["model_building"]

    # Resolve through the SAME alias/registry path the prod refs use.
    conv_canonical = _resolve_canonical(conv)
    build_canonical = _resolve_canonical(build)
    assert conv_canonical != build_canonical, (
        f"{config_path}: conversation/building tier resolve to the same model"
    )

    # The documented prod reference for this bot must equal the agent's config.
    ref = PROD_REF[bot]
    assert ref["model"] == f"openrouter/{conv}", (
        f"{bot} prod chat ref drifted from {config_path} model_conversation"
    )
    assert ref["code_model"] == f"openrouter/{build}", (
        f"{bot} prod code ref drifted from {config_path} model_building"
    )


# ── Documentation wiring ────────────────────────────────────────────────────


def test_routing_doc_records_native_no_patch_and_evidence_checklist():
    text = ROUTING_DOC.read_text()
    assert "0003" in text, "must cite decision 0003"
    assert "no fork patch" in text.lower() or "no patch" in text.lower()
    assert "verify-model-routing.sh" in text
    assert "pnpm llm:local --list-only" in text
    assert "log_all_prompts" in text
    # LM Studio evidence checklist requirements.
    assert "LM Studio" in text
    assert "local Mac server" in text
    assert "!newAction" in text, "must show how to exercise the building tier"


def test_connect_doc_links_to_routing_doc():
    text = CONNECT_DOC.read_text()
    assert "model-routing.md" in text, "E3-2 doc must forward-ref the E3-3 doc"


def test_decision_0003_back_references_e3_3():
    text = DECISION_DOC.read_text()
    assert "#535" in text and "E3-3" in text, (
        "decision 0003 must record that E3-3/#535 verified it with no patch"
    )


def test_package_json_wires_mc_verify_routing():
    data = json.loads(PACKAGE_JSON.read_text())
    scripts = data["scripts"]
    assert scripts["mc:verify-routing"] == "scripts/minecraft/verify-model-routing.sh --verify"
    # The pytest entry follows the existing verify:mindcraft-* convention.
    assert "test_mc_model_routing.py" in scripts["verify:mindcraft-routing"]

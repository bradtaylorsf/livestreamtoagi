"""Tests for the Mindcraft profile generator (issue #536, epic E3-4).

`scripts/minecraft/gen_profiles.py` turns the single source of truth
(`agents/<id>/config.yaml`) into a Mindcraft profile. These tests prove:

* (a) vera's generated openrouter profile mirrors `agents/vera/config.yaml`
  exactly — the acceptance criterion, with **no hardcoded model strings**;
* (b) the profile is valid JSON of the minimal `{name,model,code_model}` shape;
* (c) vera's raw config values resolve through `core.llm_client`
  (same drift guard as `test_mc_model_routing._resolve_canonical`);
* (d) the lmstudio local-dev form is `lmstudio/`-only — zero external spend;
* (e) the CLI prints a valid profile to stdout;
* (f) every real agent (not `template`, not refused `management`) generates a
  valid profile — E8 readiness — and Management is explicitly refused while
  Alpha (the E7-1 vertical-slice agent) generates fine.

`scripts/` is not a Python package, so the module is loaded from its file path
via importlib.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.llm_client import MODEL_NAME_ALIASES, MODEL_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[2]
GEN_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "gen_profiles.py"
AGENTS_DIR = REPO_ROOT / "agents"
VERA_CONFIG = AGENTS_DIR / "vera" / "config.yaml"

PROFILE_KEYS = {"name", "model", "code_model"}


def _load_gen_module():
    spec = importlib.util.spec_from_file_location("mc_gen_profiles", GEN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


gen = _load_gen_module()


def _resolve_canonical(raw_id: str) -> str:
    """Same drift guard as test_mc_model_routing._resolve_canonical."""
    canonical = MODEL_NAME_ALIASES.get(raw_id, raw_id)
    assert canonical in MODEL_REGISTRY, (
        f"{raw_id!r} does not resolve into MODEL_REGISTRY (got {canonical!r})"
    )
    return canonical


def _real_agent_ids() -> list[str]:
    """Every agents/<id>/ with a config.yaml, minus template and management."""
    ids = []
    for child in sorted(AGENTS_DIR.iterdir()):
        if not child.is_dir() or not (child / "config.yaml").is_file():
            continue
        if child.name in gen.PSEUDO_AGENTS or child.name in gen.NON_BOT_AGENTS:
            continue
        ids.append(child.name)
    return ids


# ── (a) acceptance: vera's openrouter profile mirrors its config ────────────


def test_vera_openrouter_profile_matches_config():
    """Generated vera profile == agents/vera/config.yaml (no hardcoded ids)."""
    cfg = yaml.safe_load(VERA_CONFIG.read_text())
    profile = gen.build_profile("vera")  # default provider=openrouter

    assert profile["name"] == "Vera"
    assert profile["model"] == f"openrouter/{cfg['model_conversation']}"
    assert profile["code_model"] == f"openrouter/{cfg['model_building']}"
    assert set(profile) == PROFILE_KEYS, "profile must be exactly 3 keys"


# ── (b) valid JSON of the minimal shape ─────────────────────────────────────


def test_profile_is_valid_json():
    profile = gen.build_profile("vera")
    round_tripped = json.loads(json.dumps(profile, indent=4))
    assert round_tripped == profile
    assert set(round_tripped) == PROFILE_KEYS
    assert all(isinstance(v, str) and v for v in round_tripped.values())


# ── (c) vera's config resolves through core/llm_client (drift guard) ────────


def test_models_resolve_into_llm_registry():
    cfg = yaml.safe_load(VERA_CONFIG.read_text())
    conv_canonical = _resolve_canonical(cfg["model_conversation"])
    build_canonical = _resolve_canonical(cfg["model_building"])
    assert conv_canonical != build_canonical, (
        "vera conversation/building tiers must resolve to different models"
    )


def test_openrouter_drift_is_rejected(tmp_path):
    """An agent config whose model id is not in the registry must raise."""
    bogus = tmp_path / "agents" / "bogus"
    bogus.mkdir(parents=True)
    (bogus / "config.yaml").write_text(
        "id: bogus\nmodel_conversation: vendor/not-a-real-model\nmodel_building: vendor/also-fake\n"
    )
    with pytest.raises(ValueError, match="does not resolve into"):
        gen.build_profile("bogus", agents_dir=tmp_path / "agents")


# ── (d) lmstudio local-dev form is lmstudio/-only ───────────────────────────


def test_local_dev_profile_is_lmstudio_only():
    profile = gen.build_profile(
        "vera",
        provider="lmstudio",
        local_chat="qwen3-8b",
        local_code="qwen3-30b",
    )
    assert profile == {
        "name": "Vera",
        "model": "lmstudio/qwen3-8b",
        "code_model": "lmstudio/qwen3-30b",
    }
    assert "openrouter/" not in json.dumps(profile)


def test_lmstudio_code_falls_back_to_chat_id():
    profile = gen.build_profile("vera", provider="lmstudio", local_chat="solo-model")
    assert profile["model"] == "lmstudio/solo-model"
    assert profile["code_model"] == "lmstudio/solo-model"


def test_lmstudio_uses_env_fallback(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_MODEL", "env-chat")
    monkeypatch.setenv("LOCAL_LLM_MODEL_BUILDING", "env-build")
    profile = gen.build_profile("vera", provider="lmstudio")
    assert profile["model"] == "lmstudio/env-chat"
    assert profile["code_model"] == "lmstudio/env-build"


def test_lmstudio_without_any_chat_id_raises(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_MODEL", raising=False)
    monkeypatch.delenv("LOCAL_LLM_MODEL_BUILDING", raising=False)
    with pytest.raises(ValueError, match="needs a chat model id"):
        gen.build_profile("vera", provider="lmstudio")


# ── (e) CLI prints a valid profile to stdout ────────────────────────────────


def test_cli_stdout_emits_valid_profile():
    proc = subprocess.run(
        [sys.executable, str(GEN_SCRIPT), "vera"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    profile = json.loads(proc.stdout)
    cfg = yaml.safe_load(VERA_CONFIG.read_text())
    assert profile == {
        "name": "Vera",
        "model": f"openrouter/{cfg['model_conversation']}",
        "code_model": f"openrouter/{cfg['model_building']}",
    }


def test_cli_lmstudio_stdout():
    proc = subprocess.run(
        [
            sys.executable,
            str(GEN_SCRIPT),
            "alpha",
            "--provider",
            "lmstudio",
            "--local-chat",
            "qwen3-8b",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    profile = json.loads(proc.stdout)
    assert profile == {
        "name": "Alpha",
        "model": "lmstudio/qwen3-8b",
        "code_model": "lmstudio/qwen3-8b",
    }


def test_cli_writes_out_file(tmp_path):
    out = tmp_path / "vera.json"
    proc = subprocess.run(
        [sys.executable, str(GEN_SCRIPT), "vera", "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    written = json.loads(out.read_text())
    assert written["name"] == "Vera"
    assert set(written) == PROFILE_KEYS


def test_cli_unknown_agent_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, str(GEN_SCRIPT), "nope"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 1
    assert "No agent directory" in proc.stderr


# ── (f) E8 readiness + E1 policy bindings ───────────────────────────────────


@pytest.mark.parametrize("agent_id", _real_agent_ids())
def test_every_real_agent_generates_valid_json(agent_id):
    """Every real agent emits a valid 3-key profile from its own config."""
    profile = gen.build_profile(agent_id)
    cfg = yaml.safe_load((AGENTS_DIR / agent_id / "config.yaml").read_text())

    assert set(profile) == PROFILE_KEYS
    assert profile["name"] == agent_id.capitalize()
    assert profile["model"] == f"openrouter/{cfg['model_conversation']}"
    assert profile["code_model"] == f"openrouter/{cfg['model_building']}"
    # Round-trips as JSON with all-string values.
    assert json.loads(json.dumps(profile)) == profile


def test_management_profile_is_refused():
    """Management is a content filter, never a world bot (E1 / E7-5)."""
    with pytest.raises(ValueError, match="never a world bot"):
        gen.build_profile("management")
    # Also refused at the CLI.
    proc = subprocess.run(
        [sys.executable, str(GEN_SCRIPT), "management"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 1
    assert "never a world bot" in proc.stderr


def test_alpha_generates_single_tier_profile():
    """Alpha (E7-1 vertical-slice agent) generates; both tiers are its model."""
    cfg = yaml.safe_load((AGENTS_DIR / "alpha" / "config.yaml").read_text())
    profile = gen.build_profile("alpha")
    assert profile["name"] == "Alpha"
    # Alpha's config sets both tiers to the same model — expected.
    assert profile["model"] == f"openrouter/{cfg['model_conversation']}"
    assert profile["model"] == profile["code_model"]


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        gen.build_profile("vera", provider="ollama")

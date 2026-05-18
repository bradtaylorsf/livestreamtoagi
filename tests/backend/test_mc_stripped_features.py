"""Tests for stripped/disabled Mindcraft features (issue #537, epic E3-5).

E3-5 disables the Mindcraft features the Python "brain" already owns
(example/skill-doc retrieval, auto-narration, session memory, voice, vision),
**behind the reversible `settings.js` config flags** — never an irreversible
fork-core edit. Decision 0004 keeps Mindcraft's decentralized conversation, so
it must **not** be stripped.

These exercise only offline-safe paths (mirroring
``test_minecraft_connect_stock_bot.py`` / ``test_mc_model_routing.py``):

* the stripped settings template, asserted **structurally** against the E3-2
  stock template — the parsed settings object must differ in **exactly** the
  three documented keys and **no others**, with the E2 connect contract
  byte-preserved and ``chat_bot_messages`` deliberately kept;
* the launch script's ``--help`` / ``--verify`` / ``--dry-run`` modes (no clone,
  no network, no Node, no launch);
* the doc enumerates every disabled feature with rationale + reversibility +
  a decision 0003/0004 cross-reference;
* ``package.json`` wires ``verify:mindcraft-stripped`` and decisions 0003/0004
  back-reference E3-5.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "connect-stripped-bot.sh"
STRIPPED_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings-stripped.js"
STOCK_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "mindcraft-settings.js"
PROFILE_TEMPLATE = REPO_ROOT / "scripts" / "minecraft" / "profiles" / "stock-bot.json"
STRIPPED_DOC = REPO_ROOT / "docs" / "minecraft" / "mindcraft-stripped-features.md"
CONNECT_DOC = REPO_ROOT / "docs" / "minecraft" / "mindcraft-connect.md"
ROUTING_DOC = REPO_ROOT / "docs" / "minecraft" / "model-routing.md"
DECISION_0003 = REPO_ROOT / "docs" / "decisions" / "0003-mindcraft-model-routing.md"
DECISION_0004 = REPO_ROOT / "docs" / "decisions" / "0004-decentralized-conversation.md"
PACKAGE_JSON = REPO_ROOT / "package.json"

PINNED_SHA = "35be480b4cc0bca990278e6103a1426392559d96"
STOCK_BOT_NAME = "StockBot"
MC_HOST = "127.0.0.1"
MC_PORT = "25565"
MC_VERSION = "1.21.6"

# The complete, intentional set of value deltas vs. the E3-2 stock template.
# (stock value -> stripped value). The test below asserts the parsed settings
# objects differ in EXACTLY these keys and no others.
EXPECTED_VALUE_DELTAS = {
    "num_examples": (2, 0),
    "relevant_docs_count": (5, 0),
    "narrate_behavior": (True, False),
}
# E2 connect contract — must be byte-preserved AND equal these known values.
E2_CONTRACT = {
    "host": MC_HOST,
    "port": int(MC_PORT),
    "auth": "offline",
    "minecraft_version": MC_VERSION,
    "auto_open_ui": False,
    "profiles": ["./profiles/stock-bot.json"],
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


def _parse_settings(text: str) -> dict:
    """Parse a Mindcraft ``settings.js`` into a dict.

    Strips ``//`` line comments while respecting string state (so a ``//`` or
    ``https://`` inside a quoted value/comment can't truncate a real value),
    then drops trailing commas and ``json.loads`` the object literal. The file
    has no nested ``{}`` once comments are gone, so the outermost braces bound
    the object.
    """
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
    obj = re.sub(r",(\s*[}\]])", r"\1", m.group(1))  # drop trailing commas
    return json.loads(obj)


# ── Script hygiene (mirrors test_minecraft_connect_stock_bot.py) ─────────────


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "connect-stripped-bot.sh must be chmod +x"


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
    assert "connect-stripped-bot.sh" in proc.stdout
    # Help must print only the comment header — never leak script source.
    assert "set -euo pipefail" not in proc.stdout
    assert 'MINDCRAFT_DIR="${MINDCRAFT_DIR' not in proc.stdout


def test_unknown_argument_is_rejected():
    proc = subprocess.run(["bash", str(SCRIPT), "--nope"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


@pytest.mark.parametrize("mode", ["--help", "--verify", "--dry-run"])
def test_static_modes_exit_zero_and_do_not_clone(mode, tmp_path):
    """--help/--verify/--dry-run must be side-effect free: no clone, no dir."""
    proc = _run([mode], tmp_path, {"MINDCRAFT_DIR": str(tmp_path / "mindcraft")})
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert not (tmp_path / "mindcraft").exists(), "no clone in static modes"
    assert not (tmp_path / ".git").exists()


def test_verify_reports_disabled_flags_and_preserved_e2_target(tmp_path):
    proc = _run(["--verify"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert f"{MC_HOST}:{MC_PORT}" in out
    assert "auth=offline" in out
    assert "Static verify passed" in out
    # The disabled-feature flags are printed network-free.
    assert "num_examples=0" in out
    assert "relevant_docs_count=0" in out
    assert "narrate_behavior=false" in out
    # The deliberately-kept feature is called out (decision 0004).
    assert "Deliberately KEPT" in out
    assert "chat_bot_messages=true" in out


def test_dry_run_prints_resolved_e2_target_and_flags(tmp_path):
    proc = _run(["--dry-run"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    out = proc.stdout
    assert f"host:        {MC_HOST}" in out
    assert f"port:        {MC_PORT}" in out
    assert "auth:        offline" in out
    assert f"minecraft:   {MC_VERSION}" in out
    assert STOCK_BOT_NAME in out
    assert "runtime-version shim" in out
    assert "num_examples=0" in out
    # No model set in CI → must say it is required and how to list ids.
    assert "LOCAL_LLM_MODEL unset" in out
    assert "pnpm llm:local --list-only" in out


def test_dry_run_with_model_env_substitutes_lmstudio_ids(tmp_path):
    proc = _run(
        ["--dry-run"],
        tmp_path,
        {"LOCAL_LLM_MODEL": "qwen3-8b", "LOCAL_LLM_MODEL_BUILDING": "qwen3-30b"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "lmstudio/qwen3-8b" in proc.stdout
    assert "lmstudio/qwen3-30b" in proc.stdout
    assert "openrouter/" not in proc.stdout


def test_profile_staging_uses_json_escaping_not_sed_substitution():
    """Real launches must preserve model ids containing sed metacharacters."""
    src = SCRIPT.read_text()
    assert "JSON.parse(readFileSync" in src
    assert "JSON.stringify(profile" in src
    assert "profile.model = `lmstudio/${chatModel}`" in src
    assert "s|__LOCAL_LLM_MODEL__|${LLM_MODEL}|g" not in src
    assert "s|__LOCAL_LLM_MODEL_BUILDING__|${LLM_MODEL_BUILDING}|g" not in src


# ── The core contract: exactly these flags flip, and only these ─────────────


def test_stripped_template_flips_exactly_the_documented_flags_and_only_those():
    """Structural diff vs. the reviewed E3-2 stock template.

    Parsing both settings objects (comment-insensitive) and diffing keys is
    far stronger than line greps: it proves the value deltas are EXACTLY the
    three documented ones, that no key was added/removed, and that the E2
    connect contract is byte-preserved.
    """
    stock = _parse_settings(STOCK_TEMPLATE.read_text())
    stripped = _parse_settings(STRIPPED_TEMPLATE.read_text())

    # No key added or removed — same surface, only values may differ.
    assert set(stock) == set(stripped), (
        "stripped template must not add/remove settings keys; "
        f"only-in-stock={set(stock) - set(stripped)} "
        f"only-in-stripped={set(stripped) - set(stock)}"
    )

    # The set of keys whose value changed is EXACTLY the documented set.
    changed = {k for k in stock if stock[k] != stripped[k]}
    assert changed == set(EXPECTED_VALUE_DELTAS), (
        f"unexpected value deltas: changed={sorted(changed)}, "
        f"documented={sorted(EXPECTED_VALUE_DELTAS)}"
    )
    for key, (before, after) in EXPECTED_VALUE_DELTAS.items():
        assert stock[key] == before, f"E3-2 stock {key} should be {before!r}"
        assert stripped[key] == after, f"stripped {key} should be {after!r}"

    # E2 connect contract byte-preserved AND equal to the known values.
    for key, expected in E2_CONTRACT.items():
        assert stock[key] == expected, f"stock {key} drifted: {stock[key]!r}"
        assert stripped[key] == expected, (
            f"E2 contract key {key} must be preserved in the stripped "
            f"template (got {stripped[key]!r}, expected {expected!r})"
        )

    # Decentralized conversation deliberately NOT stripped (decision 0004).
    assert stock["chat_bot_messages"] is True
    assert stripped["chat_bot_messages"] is True, (
        "chat_bot_messages must stay true — decision 0004 keeps Mindcraft's "
        "decentralized conversation as the base; it is NOT a stripped feature"
    )


def test_stripped_template_carries_e3_5_inline_flags_with_rationale():
    """Every changed/affirmed line is annotated `E3-5:` with the decision it binds."""
    src = STRIPPED_TEMPLATE.read_text()
    # Value deltas — flagged on the setting line.
    assert re.search(r'"num_examples":\s*0,\s*//\s*E3-5:', src)
    assert re.search(r'"relevant_docs_count":\s*0,\s*//\s*E3-5:', src)
    assert re.search(r'"narrate_behavior":\s*false,\s*//\s*E3-5:', src)
    # Already-upstream-false, affirmed with an E3-5 rationale comment.
    assert re.search(r'"load_memory":\s*false,\s*//\s*E3-5:', src)
    assert re.search(r'"speak":\s*false,\s*//\s*E3-5:', src)
    assert re.search(r'"allow_vision":\s*false,\s*//\s*E3-5:', src)
    # The kept feature is annotated too (so a reader sees it was a choice).
    assert re.search(r'"chat_bot_messages":\s*true,\s*//\s*E3-5:', src)
    # Each binds to a decision record.
    assert "0003" in src and "0004" in src
    # Still a valid Mindcraft-shaped settings module.
    assert src.strip().startswith("//") or "const settings = {" in src
    assert "export default settings;" in src


def test_reused_stock_profile_is_lmstudio_local_only_with_fixed_name():
    """E3-5 reuses the committed stock profile unchanged — local-only, fixed name."""
    data = json.loads(PROFILE_TEMPLATE.read_text())
    assert data["name"] == STOCK_BOT_NAME
    assert data["model"].startswith("lmstudio/")
    assert data["code_model"].startswith("lmstudio/")
    assert "__LOCAL_LLM_MODEL__" in data["model"]
    assert "__LOCAL_LLM_MODEL_BUILDING__" in data["code_model"]
    raw = PROFILE_TEMPLATE.read_text()
    assert "openrouter/" not in raw
    assert "embedding" not in data


# ── Real-run guards exist as source (the bot isn't launched headlessly) ──────


def test_script_keeps_e2_contract_guards_and_real_run_refusals():
    src = SCRIPT.read_text()
    assert PINNED_SHA in src, "pinned commit SHA must be the baked-in default"
    assert 'REQUIRED_NODE_MAJOR="20"' in src, "Node 20 LTS pin (E1-R1)"
    assert "No Mindcraft clone at" in src
    assert "not at the pinned commit" in src
    assert "LOCAL_LLM_MODEL is not set" in src
    assert "setup-mindcraft.sh" in src, "must point users at the E3-1 installer"
    assert f'STOCK_BOT_NAME="{STOCK_BOT_NAME}"' in src
    assert "whitelist add ${STOCK_BOT_NAME}" in src
    assert "WHITELIST=false" in src
    # It must stage the STRIPPED template, not the stock one.
    assert "mindcraft-settings-stripped.js" in src
    assert 'SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-stripped.js"' in src
    # The verify path asserts the disabled flags AND the kept conversation.
    assert '"num_examples": 0,' in src
    assert '"relevant_docs_count": 0,' in src
    assert '"narrate_behavior": false,' in src
    assert '"chat_bot_messages": true,' in src


def test_script_stages_runtime_version_shim_and_restores_clone_source():
    """Same launch-time 1.21.6 protocol shim as connect-stock-bot.sh."""
    src = SCRIPT.read_text()
    assert "src/utils/mcdata.js" in src
    assert "LTAG E3-2 runtime version refresh" in src
    assert "mc_version = settings.minecraft_version;" in src
    assert "settings arrive after module import" in src
    assert "trap restore_mcdata_patch EXIT" in src
    assert "node main.js --profiles" in src
    assert "exec node main.js" not in src


# ── The documented list + rationale (primary acceptance criterion) ──────────


def test_doc_enumerates_every_disabled_feature_with_rationale_and_reversal():
    text = STRIPPED_DOC.read_text()
    # The script + verify command are documented.
    assert "scripts/minecraft/connect-stripped-bot.sh" in text
    assert "pnpm verify:mindcraft-stripped" in text
    # Every disabled/affirmed setting key is named in the doc.
    for key in (
        "num_examples",
        "relevant_docs_count",
        "narrate_behavior",
        "load_memory",
        "speak",
        "allow_vision",
    ):
        assert key in text, f"doc must enumerate disabled feature {key}"
    # Rationale: each binds to a decision record.
    assert "0003" in text and "0004" in text
    # Reversibility is documented (the acceptance criterion: reversible).
    assert "How to reverse" in text or "how to reverse" in text
    assert "reverse" in text.lower()
    # The deliberately-kept feature + its decision.
    assert "Deliberately KEPT" in text
    assert "chat_bot_messages" in text
    # The known persona/base_profile gap is explicitly deferred to E8/bridge.
    assert "base_profile" in text
    assert "E8" in text
    # E2 connect contract preserved is stated.
    assert f"{MC_HOST}:{MC_PORT}" in text
    assert "offline" in text
    assert "1.21.6" in text


def test_doc_cross_links_sibling_docs():
    text = STRIPPED_DOC.read_text()
    assert "mindcraft-connect.md" in text
    assert "model-routing.md" in text
    assert "fork-maintenance.md" in text


def test_sibling_docs_cross_link_the_stripped_doc():
    """Doc-sync: sibling docs must point at the new E3-5 doc (E3-3 precedent)."""
    assert "mindcraft-stripped-features.md" in CONNECT_DOC.read_text()
    assert "mindcraft-stripped-features.md" in ROUTING_DOC.read_text()


def test_decisions_back_reference_e3_5():
    """Mirrors decision 0003's existing 'Verified by E3-3 (#535)' note."""
    d0003 = DECISION_0003.read_text()
    d0004 = DECISION_0004.read_text()
    for txt in (d0003, d0004):
        assert "E3-5" in txt
        assert "#537" in txt
        assert "mindcraft-stripped-features.md" in txt


def test_package_json_wires_verify_mindcraft_stripped():
    data = json.loads(PACKAGE_JSON.read_text())
    cmd = data["scripts"]["verify:mindcraft-stripped"]
    assert "tests/backend/test_mc_stripped_features.py" in cmd

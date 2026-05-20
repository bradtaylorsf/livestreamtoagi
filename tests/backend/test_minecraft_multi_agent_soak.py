"""Static tests for the E8-8 multi-agent stability soak.

The live soak is intentionally not exercised in CI: it needs LM Studio, Paper,
the backend bridge, Java 21, Node 20, and a pinned Mindcraft checkout. These
tests verify the committed operator entrypoint, package targets, and acceptance
report structure without touching those services.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "soak.sh"
DOC = REPO_ROOT / "docs" / "minecraft" / "multi-agent-soak.md"
PACKAGE = REPO_ROOT / "package.json"

BOT_IDS = ("bridge", "alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok")
AGENT_IDS = ("alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok")


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ}
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_soak_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "soak.sh must be executable"


def test_soak_script_bash_syntax_is_valid() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_soak_script_shellcheck_clean() -> None:
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_is_operator_facing_and_source_free() -> None:
    proc = _run("--help")
    assert proc.returncode == 0
    assert "--duration-hours" in proc.stdout
    assert "LOCAL_LLM_MODEL" in proc.stdout
    assert "SOAK_AGENT_HOURLY_CAP_USD" in proc.stdout
    assert "logs/soak" in proc.stdout
    assert "set -euo pipefail" not in proc.stdout
    assert "run_cost_query()" not in proc.stdout


def test_unknown_argument_is_rejected() -> None:
    proc = _run("--nope")
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


def test_static_verify_passes_without_live_services() -> None:
    proc = _run("--verify")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Static soak verify passed" in proc.stdout


def test_dry_run_lists_all_bots_and_does_not_require_services() -> None:
    proc = _run("--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for bot in BOT_IDS:
        assert bot in proc.stdout
    assert "shared local clones" in proc.stdout
    assert "no services checked, no bots launched" in proc.stdout


def test_real_run_fails_closed_when_local_model_is_missing() -> None:
    proc = _run(
        env={
            "LOCAL_LLM_BASE_URL": "http://localhost:1234/v1",
            "LOCAL_LLM_MODEL": "",
            "LOCAL_LLM_MODEL_BUILDING": "",
            "MINECRAFT_BRIDGE_TOKEN": "",
        }
    )
    assert proc.returncode == 1
    assert "LOCAL_LLM_MODEL is not set" in proc.stderr


def test_script_uses_existing_launchers_and_isolated_mindcraft_clones() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for bot in BOT_IDS:
        assert f"connect-{bot}-bot.sh" in text
    assert "git clone --shared" in text
    assert "node_modules" in text


def test_script_records_cost_ledger_and_hourly_cap() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "cost_events" in text
    assert "SOAK_AGENT_HOURLY_CAP_USD" in text
    assert "max_hour_usd" in text
    for agent_id in AGENT_IDS:
        assert f"'{agent_id}'" in text


def test_package_json_exposes_soak_commands() -> None:
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    scripts = package["scripts"]
    assert scripts["mc:soak"] == "scripts/minecraft/soak.sh"
    assert scripts["verify:minecraft-soak"] == (
        ".venv/bin/pytest tests/backend/test_minecraft_multi_agent_soak.py -v"
    )


def test_report_documents_static_evidence_and_live_addendum_template() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "STATIC-EVIDENCE ONLY" in text
    assert "NO-GO for E8-9" in text
    assert "pnpm llm:local --list-only" in text
    assert "scripts/minecraft/soak.sh --duration-hours 2" in text
    assert "All connection attempts failed" in text
    assert "Live Run Addendum Template" in text
    assert "GO / NO-GO" in text


def test_report_names_failure_classes_and_observed_counters() -> None:
    text = DOC.read_text(encoding="utf-8")
    for failure_class in ("blocked", "timeout", "invalid", "unreachable", "bridge-down"):
        assert f"`{failure_class}`" in text
    for counter in (
        "Crashes / unrecovered exits",
        "Supervisor restarts",
        "Bridge drops",
        "Management interventions",
        "Per-agent token + USD spend",
        "Decentralized respond-vs-ignore ratio",
    ):
        assert counter in text

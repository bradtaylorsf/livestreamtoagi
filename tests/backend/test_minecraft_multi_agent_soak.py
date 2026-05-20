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
RUN_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "run-local-sim.sh"
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
    assert RUN_SCRIPT.is_file(), f"missing {RUN_SCRIPT}"
    assert os.access(RUN_SCRIPT, os.X_OK), "run-local-sim.sh must be executable"


def test_soak_script_bash_syntax_is_valid() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    proc = subprocess.run(["bash", "-n", str(RUN_SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_soak_script_shellcheck_clean() -> None:
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_is_operator_facing_and_source_free() -> None:
    proc = _run("--help")
    assert proc.returncode == 0
    assert "--duration-hours" in proc.stdout
    assert "--log-dir" in proc.stdout
    assert "LOCAL_LLM_MODEL" in proc.stdout
    assert "SOAK_AGENT_HOURLY_CAP_USD" in proc.stdout
    assert "SOAK_START_MINECRAFT_IF_DOWN" in proc.stdout
    assert "logs/soak" in proc.stdout
    assert "set -euo pipefail" not in proc.stdout
    assert "run_cost_query()" not in proc.stdout

    wrapper = subprocess.run(
        ["bash", str(RUN_SCRIPT), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert wrapper.returncode == 0
    assert "pnpm dev" in wrapper.stdout
    assert "Required in .env" in wrapper.stdout
    assert "MINECRAFT_BRIDGE_TOKEN" in wrapper.stdout
    assert "set -euo pipefail" not in wrapper.stdout


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
    assert "MindServer:     8080+ per bot" in proc.stdout
    assert "auto-start MC:  1" in proc.stdout
    assert "no services checked, no bots launched" in proc.stdout


def test_local_sim_wrapper_loads_env_and_delegates_to_soak_dry_run(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_BASE_URL=http://localhost:1234/v1",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "LOCAL_LLM_MODEL_BUILDING=google/gemma-4-26b-a4b",
                "EMBEDDING_PROVIDER=deterministic",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env={**os.environ, "ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Launching local Minecraft sim" in proc.stdout
    assert "duration:       0.25h" in proc.stdout
    assert "chat model:     google/gemma-4-e4b" in proc.stdout
    assert "build model:    google/gemma-4-26b-a4b" in proc.stdout
    assert "management review: disabled" in proc.stdout
    assert "init prompt:    set (" in proc.stdout
    assert "no services checked, no bots launched" in proc.stdout


def test_local_sim_wrapper_uses_mode_defaults_from_env(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
                "MC_SIM_SMOKE_HOURS=0.1",
                "MC_SIM_SOAK_HOURS=0.2",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env={**os.environ, "ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "duration:       0.1h" in proc.stdout


def test_local_sim_wrapper_can_keep_management_enabled(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
                "MC_SIM_DISABLE_MANAGEMENT=0",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env={**os.environ, "ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "management review: enabled" in proc.stdout


def test_local_sim_wrapper_accepts_pnpm_separator(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "--", "--dry-run"],
        cwd=REPO_ROOT,
        env={**os.environ, "ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "mode: --dry-run" in proc.stdout
    assert "no services checked, no bots launched" in proc.stdout


def test_log_dir_flag_overrides_soak_log_root() -> None:
    proc = _run("--log-dir", "/tmp/e8-8-soak", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "log root:       /tmp/e8-8-soak" in proc.stdout


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
    assert "SOAK_MINDSERVER_BASE_PORT + bot_index" in text
    assert 'export MINDSERVER_PORT="$mindserver_port"' in text


def test_script_auto_starts_minecraft_when_health_is_down() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SOAK_START_MINECRAFT_IF_DOWN" in text
    assert "SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS" in text
    assert "SOAK_INIT_MESSAGE" in text
    assert 'env SETTINGS_JSON=\'{"init_message":""}\'' in text
    assert 'if "$SCRIPT_DIR/health.sh" --quiet' in text
    assert '"$SCRIPT_DIR/supervise.sh"' in text
    assert "minecraft-supervisor.pid" in text
    assert "minecraft-supervisor-stdout.log" in text


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
    assert scripts["mc:sim"] == "scripts/minecraft/run-local-sim.sh"
    assert scripts["mc:sim:smoke"] == "scripts/minecraft/run-local-sim.sh smoke"
    assert scripts["mc:sim:soak"] == "scripts/minecraft/run-local-sim.sh soak"
    assert scripts["verify:minecraft-soak"] == (
        ".venv/bin/pytest tests/backend/test_minecraft_multi_agent_soak.py -v"
    )


def test_report_documents_static_evidence_and_live_addendum_template() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "PARTIAL LIVE STARTUP SMOKE" in text
    assert "NO-GO for E8-9" in text
    assert "0.02-hour live startup smoke" in text
    assert "SOAK_START_MINECRAFT_IF_DOWN=0" in text
    assert "google/gemma-4-26b-a4b" in text
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

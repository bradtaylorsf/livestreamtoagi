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
RUN_SIMULATION = REPO_ROOT / "scripts" / "run_simulation.py"
EASY_SETUP_SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "setup-easy-spawn.mjs"
DOC = REPO_ROOT / "docs" / "minecraft" / "multi-agent-soak.md"
ACTION_DOC = REPO_ROOT / "docs" / "minecraft" / "action-command-reliability.md"
TIMELINE_DOC = REPO_ROOT / "docs" / "minecraft" / "timeline-schema.md"
COHORT_REPORT = REPO_ROOT / "docs" / "minecraft" / "cohort-report.md"
PACKAGE = REPO_ROOT / "package.json"

BOT_IDS = ("bridge", "alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok")
AGENT_IDS = ("alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok")
SIM_BOTS_LINE = "bots:           alpha vera rex aurora pixel fork sentinel grok"
SOAK_BOTS_LINE = "bots:           bridge alpha vera rex aurora pixel fork sentinel grok"

_MINECRAFT_ENV_KEYS = {
    "CONVERSATION_MODE",
    "DIRECTOR_V2_GATE",
    "EMBEDDING_PROVIDER",
    "ENV_FILE",
    "LLM_PROVIDER",
    "MC_HOST",
    "MC_PORT",
    "SERVER_DIR",
    "SERVER_PORT",
    "WHITELIST",
    "WORLD_CONFIG",
}
_MINECRAFT_ENV_PREFIXES = ("LOCAL_LLM", "MC_HEARTBEAT", "MC_SIM", "MINECRAFT_", "SOAK_")


def _clean_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _MINECRAFT_ENV_KEYS and not key.startswith(_MINECRAFT_ENV_PREFIXES)
    }
    if overrides:
        env.update(overrides)
    return env


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = _clean_env(env)
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
    assert EASY_SETUP_SCRIPT.is_file(), f"missing {EASY_SETUP_SCRIPT}"
    assert os.access(EASY_SETUP_SCRIPT, os.X_OK), "setup-easy-spawn.mjs must be executable"


def test_soak_script_bash_syntax_is_valid() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    proc = subprocess.run(["bash", "-n", str(RUN_SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    proc = subprocess.run(
        ["node", "--check", str(EASY_SETUP_SCRIPT)], capture_output=True, text=True
    )
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
    assert "LOCAL_LLM_UPSTREAM_URL" in proc.stdout
    assert "MINECRAFT_LLM_QUEUE_PROXY" in proc.stdout
    assert "MINECRAFT_LLM_CONCURRENCY" in proc.stdout
    assert "SOAK_AGENT_HOURLY_CAP_USD" in proc.stdout
    assert "SOAK_START_MINECRAFT_IF_DOWN" in proc.stdout
    assert "SOAK_EASY_SPAWN" in proc.stdout
    assert "SOAK_MIN_INTENT_TO_COMMAND_RATIO" in proc.stdout
    assert "SOAK_MIN_PARSE_SUCCESS" in proc.stdout
    assert "SOAK_MIN_EXECUTION_RATE" in proc.stdout
    assert "SOAK_MIN_VERIFIED_SUCCESS" in proc.stdout
    assert "SOAK_RELIABILITY_FAIL_ON_VIOLATION" in proc.stdout
    assert "MC_SIM_BUILDER_PROVIDER" in proc.stdout
    assert "MC_SIM_BUILDER_OPENROUTER_MODEL" in proc.stdout
    assert "MC_SIM_BUILDER_MAX_CALLS_PER_RUN" in proc.stdout
    assert "MC_SIM_BUILD_COOLDOWN_SEC" in proc.stdout
    assert "MC_SIM_BUILD_ZONE_STRIDE" in proc.stdout
    assert "timeline.ndjson" in proc.stdout
    assert "timeline-totals.json" in proc.stdout
    assert "SOAK_MIN_MOVEMENT_PER_AGENT" in proc.stdout
    assert "SOAK_REQUIRE_BEHAVIOR_GATE" in proc.stdout
    assert "SOAK_MAX_RESTARTS_PER_AGENT" in proc.stdout
    assert "MC_HEARTBEAT_ENABLED" in proc.stdout
    assert "MC_HEARTBEAT_IDLE_MS" in proc.stdout
    assert "MC_HEARTBEAT_COOLDOWN_MS" in proc.stdout
    assert "MC_HEARTBEAT_STALE_ACTION_MS" in proc.stdout
    assert "MC_HEARTBEAT_MAX_NO_COMMAND" in proc.stdout
    assert "MC_SIM_MEMORY_CONTEXT_ENABLED" in proc.stdout
    assert "MC_SIM_MEMORY_RECALL_LIMIT" in proc.stdout
    assert "lower-level diagnostic harness" in proc.stdout
    assert "--verify-behavior" in proc.stdout
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
    assert "MC_SIM_EASY_MODE" in wrapper.stdout
    assert "MC_SIM_BUILD_MODE" in wrapper.stdout
    assert "MC_SIM_BUILDER_PROVIDER" in wrapper.stdout
    assert "MC_SIM_BUILDER_OPENROUTER_MODEL" in wrapper.stdout
    assert "MC_SIM_BUILDER_MAX_CALLS_PER_AGENT" in wrapper.stdout
    assert "MC_SIM_BUILD_COOLDOWN_SEC" in wrapper.stdout
    assert "MC_SIM_BUILD_CACHE_TTL_SEC" in wrapper.stdout
    assert "MC_SIM_BLOCK_EXECUTE_CODE_ACTIONS" in wrapper.stdout
    assert "MC_SIM_MIN_INTENT_TO_COMMAND_RATIO" in wrapper.stdout
    assert "MC_SIM_MIN_PARSE_SUCCESS" in wrapper.stdout
    assert "MC_SIM_MIN_EXECUTION_RATE" in wrapper.stdout
    assert "MC_SIM_MIN_VERIFIED_SUCCESS" in wrapper.stdout
    assert "MC_SIM_HEARTBEAT_IDLE_SEC" in wrapper.stdout
    assert "MC_SIM_HEARTBEAT_MAX_NO_COMMAND" in wrapper.stdout
    assert "MC_SIM_MEMORY_CONTEXT_ENABLED" in wrapper.stdout
    assert "MC_SIM_MEMORY_RECALL_LIMIT" in wrapper.stdout
    assert "lower-level Minecraft diagnostic" in wrapper.stdout
    assert "timeline.ndjson" in wrapper.stdout
    assert "set -euo pipefail" not in wrapper.stdout

    supervisor = subprocess.run(
        [".venv/bin/python", str(RUN_SIMULATION), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert supervisor.returncode == 0
    assert "--conversation-mode" in supervisor.stdout
    assert "--duration-hours" in supervisor.stdout
    assert "--minecraft-log-dir" in supervisor.stdout
    assert "--no-embodied-supervisor" in supervisor.stdout


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
    assert "temp local clones" in proc.stdout
    assert "work root:      <per-run temp>" in proc.stdout
    assert "MindServer:     8080+ per bot" in proc.stdout
    assert "LM queue:       enabled concurrency=1 upstream=http://localhost:1234/v1" in proc.stdout
    assert "conversation:   mode=embodied director_gate=0" in proc.stdout
    assert (
        "builder route:  provider=local fallback=fail openrouter_model=<unset> caps run=12 agent=3 usd=<unset>"
        in proc.stdout
    )
    assert (
        "build governor: max_per_agent=6 cooldown=300s zone_stride=12 cache_ttl=3600s"
        in proc.stdout
    )
    assert (
        "memory context: enabled=1 recall_limit=3 core_max=1500 recall_max=1200 exclude=management,alpha"
        in proc.stdout
    )
    assert "behavior:       require=1; movement>=5/agent" in proc.stdout
    assert "execute code:   allowed" in proc.stdout
    assert "auto-start MC:  1" in proc.stdout
    assert "keep MC alive:  0" in proc.stdout
    assert "easy spawn:     disabled" in proc.stdout
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
                "MC_SIM_HEARTBEAT_IDLE_SEC=12",
                "MC_SIM_HEARTBEAT_COOLDOWN_SEC=7",
                "MC_SIM_HEARTBEAT_STALE_ACTION_SEC=30",
                "MC_SIM_HEARTBEAT_MAX_NO_COMMAND=2",
                "MC_SIM_MEMORY_RECALL_LIMIT=2",
                "MC_SIM_MEMORY_CORE_MAX_CHARS=900",
                "MC_SIM_MEMORY_RECALL_MAX_CHARS=700",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Launching local Minecraft sim" in proc.stdout
    assert "duration:       0.25h" in proc.stdout
    assert "chat model:     google/gemma-4-e4b" in proc.stdout
    assert "build model:    google/gemma-4-26b-a4b" in proc.stdout
    assert "conversation mode: embodied" in proc.stdout
    assert "Director V2 gate: 0" in proc.stdout
    assert (
        "builder route: provider=local fallback=fail openrouter_model=<unset> caps run=12 agent=3 usd=<unset>"
        in proc.stdout
    )
    assert (
        "build governor: max_per_agent=6 cooldown=300s zone_stride=12 cache_ttl=3600s"
        in proc.stdout
    )
    assert "management review: disabled" in proc.stdout
    assert "build mode: single" in proc.stdout
    assert "private bot conversations: 1" in proc.stdout
    assert "slow sim actions: 1" in proc.stdout
    assert "execute code actions: 1" in proc.stdout
    assert "suppress action chat: 1" in proc.stdout
    assert "safe terrain actions: 1" in proc.stdout
    assert (
        "heartbeat: enabled=1 idle=12s cooldown=7s stale_action=30s max_no_command=2" in proc.stdout
    )
    assert (
        "memory context: enabled=1 recall_limit=2 core_max=900 recall_max=700 exclude=management,alpha"
        in proc.stdout
    )
    assert "easy mode: 1" in proc.stdout
    assert "keep MC server running: 1" in proc.stdout
    assert "minecraft: 127.0.0.1:25566" in proc.stdout
    assert "server dir:" in proc.stdout and "minecraft-server-easy" in proc.stdout
    assert "world config:" in proc.stdout and "world-easy.config" in proc.stdout
    assert "MindServer base port:" in proc.stdout
    assert (
        "reliability thresholds: intent>=0.6 parse>=0.8 execution>=0.7 verified>=0.5" in proc.stdout
    )
    assert (
        "reliability:    intent>=0.6 parse>=0.8 exec>=0.7 verified>=0.5 min_intents=5 fail=1"
        in proc.stdout
    )
    assert (
        "builder route:  provider=local fallback=fail openrouter_model=<unset> caps run=12 agent=3 usd=<unset>"
        in proc.stdout
    )
    assert "conversation:   mode=embodied director_gate=0" in proc.stdout
    assert (
        "build governor: max_per_agent=6 cooldown=300s zone_stride=12 cache_ttl=3600s"
        in proc.stdout
    )
    assert "private conv:   blocked (!startConversation/!endConversation)" in proc.stdout
    assert "slow actions:   blocked (!newAction/!observe/!navigate/plan actions)" in proc.stdout
    assert "execute code:   blocked (!executeCode)" in proc.stdout
    assert "safe terrain:   enabled" in proc.stdout
    assert (
        "heartbeat:      enabled=1 idle=12000ms cooldown=7000ms stale_action=30000ms max_no_command=2"
        in proc.stdout
    )
    assert (
        "memory context: enabled=1 recall_limit=2 core_max=900 recall_max=700 exclude=management,alpha"
        in proc.stdout
    )
    assert "easy spawn:     enabled" in proc.stdout
    assert "keep MC alive:  1" in proc.stdout
    assert SIM_BOTS_LINE in proc.stdout
    assert SOAK_BOTS_LINE not in proc.stdout
    assert "init prompt:    set (" in proc.stdout
    assert "no services checked, no bots launched" in proc.stdout


def test_local_sim_plan_mode_enables_plan_building_but_keeps_execute_code_blocked(
    tmp_path,
) -> None:
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
                "MC_SIM_BUILD_MODE=plan",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "build mode: plan" in proc.stdout
    assert "slow sim actions: 0" in proc.stdout
    assert "execute code actions: 1" in proc.stdout
    assert "slow actions:   allowed" in proc.stdout
    assert "safe terrain:   enabled" in proc.stdout
    assert "blocks !place/!break/!observe" in proc.stdout
    assert "execute code:   blocked (!executeCode)" in proc.stdout
    assert '!planAndBuild("small shared cabin")' in proc.stdout
    assert "Only the build owner should place blocks through !planAndBuild" in proc.stdout
    assert 'execute one visible command such as !placeHere("oak_log")' not in proc.stdout
    assert "do not wait for consensus before placing the first camp marker" not in proc.stdout
    assert "init prompt:    set (" in proc.stdout
    assert "init delivery:  after easy-spawn starter kit" in proc.stdout


def test_openrouter_builder_routing_fails_closed_when_config_is_missing(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
                "MC_SIM_BUILD_MODE=plan",
                "MC_SIM_BUILDER_PROVIDER=openrouter",
            ]
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 1
    assert "OpenRouter builder routing requires" in proc.stderr
    assert "MC_SIM_BUILDER_FALLBACK=local" in proc.stdout


def test_openrouter_builder_routing_can_fall_back_to_local_without_key(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
                "MC_SIM_BUILD_MODE=plan",
                "MC_SIM_BUILDER_PROVIDER=openrouter",
                "MC_SIM_BUILDER_FALLBACK=local",
            ]
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (
        "builder route: provider=openrouter fallback=local openrouter_model=<unset> caps run=12 agent=3 usd=<unset>"
        in proc.stdout
    )
    assert (
        "builder route:  provider=openrouter fallback=local openrouter_model=<unset> caps run=12 agent=3 usd=<unset>"
        in proc.stdout
    )


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
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "duration:       0.1h" in proc.stdout


def test_local_sim_wrapper_echoes_reliability_threshold_overrides(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
                "MC_SIM_MIN_INTENT_TO_COMMAND_RATIO=0.4",
                "MC_SIM_MIN_PARSE_SUCCESS=0.9",
                "MC_SIM_MIN_EXECUTION_RATE=0.8",
                "MC_SIM_MIN_VERIFIED_SUCCESS=0.7",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (
        "reliability thresholds: intent>=0.4 parse>=0.9 execution>=0.8 verified>=0.7" in proc.stdout
    )
    assert (
        "reliability:    intent>=0.4 parse>=0.9 exec>=0.8 verified>=0.7 min_intents=5 fail=1"
        in proc.stdout
    )


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
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "management review: enabled" in proc.stdout


def test_local_sim_wrapper_env_file_management_toggle_wins_over_pollution(tmp_path) -> None:
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
        env=_clean_env(
            {
                "ENV_FILE": str(env_file),
                "MC_SIM_DISABLE_MANAGEMENT": "1",
                "MINECRAFT_MANAGEMENT_REVIEW_MODE": "disabled",
            }
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "management review: enabled" in proc.stdout


def test_local_sim_wrapper_can_include_bridge_bot_when_requested(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
                "MC_SIM_INCLUDE_BRIDGE_BOT=1",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert SOAK_BOTS_LINE in proc.stdout


def test_local_sim_wrapper_can_allow_new_action_when_requested(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
                "MC_SIM_ALLOW_NEW_ACTION=1",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "slow sim actions: 0" in proc.stdout
    assert "slow actions:   allowed" in proc.stdout


def test_local_sim_wrapper_can_allow_action_chat_when_requested(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=lmstudio",
                "LOCAL_LLM_MODEL=google/gemma-4-e4b",
                "CONVERSATION_MODE=embodied",
                "MINECRAFT_BRIDGE_TOKEN=test-bridge-token",
                "MC_SIM_SUPPRESS_ACTION_CHAT=0",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["bash", str(RUN_SCRIPT), "smoke", "--dry-run"],
        cwd=REPO_ROOT,
        env=_clean_env({"ENV_FILE": str(env_file)}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "suppress action chat: 0" in proc.stdout


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
        env=_clean_env({"ENV_FILE": str(env_file)}),
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
    assert 'dest="$SOAK_WORK_ROOT/mindcraft-$bot"' in text
    assert 'printf \'%s\\n\' "$SOAK_WORK_ROOT" > "$RUN_DIR/worktrees.path"' in text
    assert "node_modules" in text
    assert "SOAK_MINDSERVER_BASE_PORT + bot_index" in text
    assert 'export MINDSERVER_PORT="$mindserver_port"' in text


def test_script_auto_starts_minecraft_when_health_is_down() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SOAK_START_MINECRAFT_IF_DOWN" in text
    assert "SOAK_WORK_ROOT" in text
    assert "SOAK_KEEP_WORKTREES" in text
    assert "SOAK_KEEP_MINECRAFT_RUNNING" in text
    assert "check_mindserver_ports_available" in text
    assert "signal_process_tree" in text
    assert "SOAK_MINECRAFT_BOOT_TIMEOUT_SECONDS" in text
    assert "SOAK_INIT_MESSAGE" in text
    assert "SOAK_SETTINGS_INIT_MESSAGE" in text
    assert "send_deferred_init_message" in text
    assert "easy spawn deferred init" in text
    assert "after_easy_spawn_starter_kit" in text
    assert "MC_SIM_BUILD_MODE" in text
    assert "export MC_SIM_BUILD_MODE" in text
    assert "build_mode=$MC_SIM_BUILD_MODE" in text
    assert "MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT" in text
    assert "apply_suppress_empty_init_chat_patch" in text
    assert "waiting for deferred init message" in text
    assert "suppress_empty_init_chat=$MINECRAFT_SUPPRESS_EMPTY_INIT_CHAT" in text
    assert "apply_director_tool_guard_patch" in text
    assert "Director V2 blocked unavailable command" in text
    assert "is not available for this Director V2 turn" in text
    assert "SOAK_BLOCK_PRIVATE_CONVERSATIONS" in text
    assert "SOAK_BLOCK_SLOW_SIM_ACTIONS" in text
    assert "SOAK_BLOCK_EXECUTE_CODE_ACTIONS" in text
    assert "MINECRAFT_LLM_QUEUE_PROXY" in text
    assert "MINECRAFT_LLM_CONCURRENCY" in text
    assert "lmstudio_queue_proxy.py" in text
    assert "settings_json_for_bot" in text
    assert "settings.init_message = ''" in text
    assert "settings.num_examples = 0" in text
    assert "settings.show_command_syntax = 'none'" in text
    assert "SOAK_SAFE_TERRAIN_ACTIONS" in text
    assert "SOAK_EASY_SPAWN" in text
    assert "SOAK_MIN_INTENT_TO_COMMAND_RATIO" in text
    assert "SOAK_RELIABILITY_FAIL_ON_VIOLATION" in text
    assert "analyze_action_reliability.py" in text
    assert "build_timeline.py" in text
    assert "action-reliability.md" in text
    assert "timeline.ndjson" in text
    assert "timeline-totals.json" in text
    assert "MC_HEARTBEAT_IDLE_MS" in text
    assert "MC_HEARTBEAT_MAX_NO_COMMAND" in text
    assert "heartbeat-halts.tsv" in text
    assert "heartbeat_counts" in text
    assert "heartbeat.halted" in text
    assert "max-no-command" in text
    assert "MC_TIMELINE_NDJSON" in text
    assert "MC_RUN_DIR" in text
    assert "setup-easy-spawn.mjs" in text
    assert "world-easy.config" in text
    assert "MINECRAFT_ALLOW_DESTRUCTIVE_PATHS" in text
    assert "apply_safe_terrain_patch" in text
    assert "allowDestructivePaths" in text
    assert "nonDestructiveMovements.canDig = false" in text
    assert "elbow_room: false" in text
    assert "item_collecting: false" in text
    assert "!startConversation" in text
    assert "!endConversation" in text
    assert "!newAction" in text
    assert "!observe" in text
    assert "!buildFromPlan" in text
    assert "!planAndBuild" in text
    assert "!executeCode" in text
    assert '"!place"' in text
    assert '"!break"' in text
    assert 'if "$SCRIPT_DIR/health.sh" --quiet' in text
    assert '"$SCRIPT_DIR/supervise.sh"' in text
    assert "minecraft-supervisor.pid" in text
    assert "minecraft-supervisor-stdout.log" in text


def test_easy_spawn_access_writer_is_offline_safe(tmp_path) -> None:
    proc = subprocess.run(
        ["node", str(EASY_SETUP_SCRIPT), "--write-access-only"],
        cwd=REPO_ROOT,
        env=_clean_env(
            {
                "SERVER_DIR": str(tmp_path / "easy-server"),
                "EASY_SETUP_PLAYERS": "Alpha Vera",
                "EASY_SETUP_OBSERVERS": "bradtaylorsf",
                "EASY_SETUP_OPERATORS": "bradtaylorsf",
            }
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    ops = json.loads((tmp_path / "easy-server" / "ops.json").read_text(encoding="utf-8"))
    whitelist = json.loads(
        (tmp_path / "easy-server" / "whitelist.json").read_text(encoding="utf-8")
    )
    assert {entry["name"] for entry in whitelist} >= {"WorldBuilder", "Alpha", "Vera"}
    assert any(
        entry["name"] == "WorldBuilder"
        and entry["level"] == 4
        and entry["bypassesPlayerLimit"] is True
        for entry in ops
    )
    assert any(entry["name"] == "bradtaylorsf" and entry["level"] == 4 for entry in ops)


def test_easy_spawn_script_builds_safe_starter_arena() -> None:
    text = EASY_SETUP_SCRIPT.read_text(encoding="utf-8")
    assert "/gamerule spawnRadius 0" in text
    assert "/gamerule drowningDamage false" in text
    assert "/gamerule fallDamage false" in text
    assert "/fill -24 64 -24 0 96 0 minecraft:air replace" in text
    assert "/fill 1 64 1 24 96 24 minecraft:air replace" in text
    assert "/fill -22 58 -22 22 62 22 minecraft:dirt replace" in text
    assert "/fill -23 64 -23 23 68 -23 minecraft:glass replace" in text
    assert "/fill -10 63 -5 10 63 1 minecraft:grass_block replace" in text
    assert "/fill -10 64 -5 10 68 1 minecraft:air replace" in text
    assert "/spawnpoint @a 0 64 -4" in text
    assert "[-8, 64, -4]" in text
    assert "[8, 64, -4]" in text
    assert "[6, 64, 0]" in text
    assert "[0, 64, 2]" not in text
    assert "EASY_SETUP_OBSERVERS" in text
    assert "EASY_SETUP_OPERATORS" in text
    assert "EASY_SETUP_SPECTATORS" in text
    assert "/gamemode spectator" in text
    assert "/clear @a" in text
    assert "minecraft:oak_log 32" in text
    assert "minecraft:oak_planks" in text
    assert "minecraft:stone_pickaxe 1" in text


def test_bridge_move_actions_respect_non_destructive_path_env() -> None:
    for relative in (
        "scripts/minecraft/fork-src/agent/commands/move_action.js",
        "scripts/minecraft/fork-src/agent/commands/navigate_action.js",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "MINECRAFT_ALLOW_DESTRUCTIVE_PATHS" in text
        assert "destructivePathsAllowed" in text
        assert "movements.canDig = false" in text
        assert "movements.allow1by1towers = false" in text


def test_script_records_cost_ledger_and_hourly_cap() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "cost_events" in text
    assert "SOAK_AGENT_HOURLY_CAP_USD" in text
    assert "max_hour_usd" in text
    for agent_id in AGENT_IDS:
        assert f"'{agent_id}'" in text


def test_script_defines_behavioral_acceptance_gate_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "compute_behavior_table()" in text
    assert "--verify-behavior" in text
    for agent_id in AGENT_IDS:
        assert agent_id in text
    for env_name in (
        "SOAK_MIN_MOVEMENT_PER_AGENT",
        "SOAK_MAX_DEATHS_PER_AGENT",
        "SOAK_MAX_STUCK_PER_AGENT",
        "SOAK_MAX_RESTARTS_PER_AGENT",
        "SOAK_MIN_PUBLIC_CHAT_COHORT",
        "SOAK_MIN_GATHER_OR_BUILD_COHORT",
        "SOAK_MIN_SHARED_ARTIFACTS",
        "SOAK_REQUIRE_BEHAVIOR_GATE",
    ):
        assert env_name in text
    assert (
        '"agent",\n    "spawn_safe",\n    "movement",\n    "public_chat",\n    "inter_agent_chat",'
        in text
    )
    assert '"restart_count",' in text
    assert "total_restarts" in text
    assert "behavior_gate_status" in text
    assert "Behavioral acceptance gate failed" in text
    assert "behavior.tsv" in text


def test_behavior_gate_verification_mode_fails_for_synthetic_threshold_miss(tmp_path) -> None:
    run_dir = tmp_path / "soak-run"
    bots_dir = run_dir / "bots"
    logs_dir = run_dir / "logs"
    bots_dir.mkdir(parents=True)
    logs_dir.mkdir()

    for index, agent_id in enumerate(AGENT_IDS):
        other = AGENT_IDS[(index + 1) % len(AGENT_IDS)]
        movement_count = 1 if agent_id == "alpha" else 5
        lines = [
            "Spawned at x=0 y=64 z=0",
            f"{agent_id}: ready to work with {other}",
        ]
        lines.extend(f"!move north {step}" for step in range(movement_count))
        if agent_id == "alpha":
            lines.append("!collectBlocks oak_log 1")
        if agent_id == "vera":
            lines.append('!placeHere("stone")')
        if agent_id == "rex":
            lines.append('!place("stone", {"x": 1, "y": 64, "z": 1}, "up")')
        (bots_dir / f"{agent_id}.log").write_text("\n".join(lines), encoding="utf-8")

    (logs_dir / "bridge.log").write_text(
        "vera and rex worked together on a shared camp marker\n",
        encoding="utf-8",
    )

    proc = _run(
        "--verify-behavior",
        str(run_dir),
        env={
            "SOAK_MIN_PUBLIC_CHAT_COHORT": "1",
            "SOAK_MIN_GATHER_OR_BUILD_COHORT": "1",
            "SOAK_MIN_SHARED_ARTIFACTS": "1",
            "SOAK_REQUIRE_BEHAVIOR_GATE": "1",
        },
    )

    assert proc.returncode == 1
    assert "Behavioral acceptance gate failed" in proc.stderr

    behavior_tsv = (run_dir / "behavior.tsv").read_text(encoding="utf-8")
    assert (
        "agent\tspawn_safe\tmovement\tpublic_chat\tinter_agent_chat\tgather\tbuild\tdeaths\t"
        "drownings\tstuck\tdig_holes\trestart_count\tbehavior_status"
    ) in behavior_tsv
    assert "alpha\t1\t1\t1\t1\t1\t0\t0\t0\t0\t0\t0\tfail" in behavior_tsv
    assert "vera\t1\t5\t1\t1\t0\t1\t0\t0\t0\t0\t0\tpass" in behavior_tsv

    summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
    assert "Behavioral acceptance" in summary
    assert "behavior_gate_status=fail" in summary
    assert "agent alpha movement expected >= 5 got 1" in summary


def test_behavior_gate_does_not_count_embodied_text_as_death(tmp_path) -> None:
    run_dir = tmp_path / "soak-run"
    bots_dir = run_dir / "bots"
    logs_dir = run_dir / "logs"
    bots_dir.mkdir(parents=True)
    logs_dir.mkdir()

    for index, agent_id in enumerate(AGENT_IDS):
        other = AGENT_IDS[(index + 1) % len(AGENT_IDS)]
        lines = [
            "Spawned at x=0 y=64 z=0",
            "Director context says to take another embodied action near spawn.",
            f"{agent_id}: ready to work with {other}",
        ]
        lines.extend(f"!move north {step}" for step in range(5))
        if agent_id == "rex":
            lines.append('!placeHere("stone")')
        (bots_dir / f"{agent_id}.log").write_text("\n".join(lines), encoding="utf-8")

    (logs_dir / "bridge.log").write_text(
        "rex and vera worked together on a shared camp marker\n",
        encoding="utf-8",
    )

    proc = _run(
        "--verify-behavior",
        str(run_dir),
        env={
            "SOAK_MIN_PUBLIC_CHAT_COHORT": "1",
            "SOAK_MIN_GATHER_OR_BUILD_COHORT": "1",
            "SOAK_MIN_SHARED_ARTIFACTS": "1",
            "SOAK_REQUIRE_BEHAVIOR_GATE": "1",
        },
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr

    behavior_tsv = (run_dir / "behavior.tsv").read_text(encoding="utf-8")
    assert "rex\t1\t5\t1\t1\t0\t1\t0\t0\t0\t0\t0\tpass" in behavior_tsv


def test_behavior_gate_counts_restarts_and_fails_repeated_pathstopped_restarts(tmp_path) -> None:
    run_dir = tmp_path / "soak-run"
    bots_dir = run_dir / "bots"
    logs_dir = run_dir / "logs"
    bots_dir.mkdir(parents=True)
    logs_dir.mkdir()

    for index, agent_id in enumerate(AGENT_IDS):
        other = AGENT_IDS[(index + 1) % len(AGENT_IDS)]
        lines = [
            "Spawned at x=0 y=64 z=0",
            f"{agent_id}: ready to work with {other}",
        ]
        lines.extend(f"!move north {step}" for step in range(5))
        if agent_id in {"vera", "rex"}:
            lines.append('!place("stone", {"x": 1, "y": 64, "z": 1}, "up")')
        if agent_id == "alpha":
            lines.extend(
                [
                    "2026-05-20T10:00:00Z Alpha PathStopped: Path was stopped before it could be completed",
                    "2026-05-20T10:00:01Z Alpha Exiting.",
                    "2026-05-20T10:00:30Z Alpha process exited with code 1",
                ]
            )
        (bots_dir / f"{agent_id}.log").write_text("\n".join(lines), encoding="utf-8")

    (logs_dir / "bridge.log").write_text(
        "vera and rex worked together on a shared camp marker\n",
        encoding="utf-8",
    )

    proc = _run(
        "--verify-behavior",
        str(run_dir),
        env={
            "SOAK_MAX_RESTARTS_PER_AGENT": "1",
            "SOAK_MIN_PUBLIC_CHAT_COHORT": "1",
            "SOAK_MIN_GATHER_OR_BUILD_COHORT": "1",
            "SOAK_MIN_SHARED_ARTIFACTS": "1",
            "SOAK_REQUIRE_BEHAVIOR_GATE": "1",
        },
    )

    assert proc.returncode == 1
    assert "agent alpha restarts expected <= 1 got 2" in proc.stderr
    assert "agent alpha repeated restarts within 300s" in proc.stderr

    behavior_tsv = (run_dir / "behavior.tsv").read_text(encoding="utf-8")
    assert "restart_count" in behavior_tsv
    assert "alpha\t1\t5\t1\t1\t0\t0\t0\t0\t0\t0\t2\tfail" in behavior_tsv

    totals = (run_dir / "behavior-totals.env").read_text(encoding="utf-8")
    assert "total_restarts=2" in totals
    assert "total_restart_recurrences=1" in totals


def test_behavior_gate_counts_heartbeat_halts_as_restart_failures(tmp_path) -> None:
    run_dir = tmp_path / "soak-run"
    bots_dir = run_dir / "bots"
    logs_dir = run_dir / "logs"
    bots_dir.mkdir(parents=True)
    logs_dir.mkdir()

    for index, agent_id in enumerate(AGENT_IDS):
        other = AGENT_IDS[(index + 1) % len(AGENT_IDS)]
        lines = [
            "Spawned at x=0 y=64 z=0",
            f"{agent_id}: ready to work with {other}",
            "!move north 0",
            "!move north 1",
            "!move north 2",
            "!move north 3",
            "!move north 4",
        ]
        if agent_id in {"vera", "rex"}:
            lines.append('!place("stone", {"x": 1, "y": 64, "z": 1}, "up")')
        if agent_id == "alpha":
            lines.append(
                "2026-05-20T10:00:00Z heartbeat.halted reason=max-no-command no_command_streak=3"
            )
        (bots_dir / f"{agent_id}.log").write_text("\n".join(lines), encoding="utf-8")

    (logs_dir / "bridge.log").write_text(
        "vera and rex worked together on a shared camp marker\n",
        encoding="utf-8",
    )

    proc = _run(
        "--verify-behavior",
        str(run_dir),
        env={
            "SOAK_MAX_RESTARTS_PER_AGENT": "0",
            "SOAK_MIN_PUBLIC_CHAT_COHORT": "1",
            "SOAK_MIN_GATHER_OR_BUILD_COHORT": "1",
            "SOAK_MIN_SHARED_ARTIFACTS": "1",
            "SOAK_REQUIRE_BEHAVIOR_GATE": "1",
        },
    )

    assert proc.returncode == 1
    assert "agent alpha restarts expected <= 0 got 1" in proc.stderr

    behavior_tsv = (run_dir / "behavior.tsv").read_text(encoding="utf-8")
    assert "alpha\t1\t5\t1\t1\t0\t0\t0\t0\t0\t0\t1\tfail" in behavior_tsv

    totals = (run_dir / "behavior-totals.env").read_text(encoding="utf-8")
    assert "total_restarts=1" in totals


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
    assert "minecraft-server-easy" in text
    assert "setup-easy-spawn.mjs" in text
    assert "google/gemma-4-26b-a4b" in text
    assert "pnpm llm:local --list-only" in text
    assert "scripts/minecraft/soak.sh --duration-hours 2" in text
    assert "All connection attempts failed" in text
    assert "Live Run Addendum Template" in text
    assert "GO / NO-GO" in text
    assert "Action-Command Reliability Gate" in text
    assert "Structured Timeline" in text
    assert "Multi-Agent Runtime Queues" in text
    assert "Builder-Plan Mode" in text
    assert "MINECRAFT_LLM_CONCURRENCY" in text
    assert "MC_SIM_BUILD_MODE=plan" in text
    assert "MC_SIM_BUILDER_PROVIDER=openrouter" in text
    assert "MC_SIM_BUILDER_MAX_CALLS_PER_RUN" in text
    assert "MC_SIM_BUILD_COOLDOWN_SEC" in text
    assert "build_plan.generation.skipped" in text
    assert "!planAndBuild" in text
    assert "SOAK_MIN_INTENT_TO_COMMAND_RATIO" in text
    assert "Action reliability result" in text
    assert "Behavioral gate result" in text
    assert "timeline.ndjson" in text
    assert "timeline-totals.json" in text
    assert "timeline-schema.md" in text

    assert ACTION_DOC.is_file()
    action_text = ACTION_DOC.read_text(encoding="utf-8")
    assert "## Methodology" in action_text
    assert "### Intent Detection" in action_text
    assert "### Parse Results" in action_text
    assert "### Execution Results" in action_text
    assert "### Verification Results" in action_text
    assert "## Live Run Evidence Template" in action_text

    assert TIMELINE_DOC.is_file()
    timeline_text = TIMELINE_DOC.read_text(encoding="utf-8")
    for event_type in (
        "chat.public",
        "llm.request",
        "llm.response",
        "llm.queue.enqueued",
        "llm.queue.started",
        "llm.queue.completed",
        "llm.queue.failed",
        "action.intent",
        "action.start",
        "action.queued",
        "action.started",
        "action.completed",
        "action.rejected_busy",
        "action.result",
        "inbox.queued",
        "inbox.turn_started",
        "inbox.turn_completed",
        "build_plan.generation.completed",
        "build_plan.generation.provider_failed",
        "build_plan.generation.budget_capped",
        "build_plan.generation.skipped",
        "build_plan.execution.completed",
        "heartbeat.fired",
        "heartbeat.skipped",
        "heartbeat.outcome",
        "heartbeat.halted",
        "state.sample",
        "error",
        "lifecycle",
    ):
        assert event_type in timeline_text
    assert "provider_reported" in timeline_text
    assert "estimated" in timeline_text
    assert "builder_usage" in timeline_text


def test_report_names_failure_classes_and_observed_counters() -> None:
    text = DOC.read_text(encoding="utf-8")
    for failure_class in ("blocked", "timeout", "invalid", "unreachable", "bridge-down"):
        assert f"`{failure_class}`" in text
    for failure_class in ("interrupted", "aborted"):
        assert f"`{failure_class}`" in text
    for counter in (
        "Crashes / unrecovered exits",
        "Supervisor restarts",
        "Bridge drops",
        "Management interventions",
        "Per-agent token + USD spend",
        "Decentralized respond-vs-ignore ratio",
        "Action-command reliability",
        "Behavioral acceptance",
        "Heartbeat halts",
    ):
        assert counter in text


def test_behavior_gate_docs_are_complete() -> None:
    soak_doc = DOC.read_text(encoding="utf-8")
    cohort_doc = COHORT_REPORT.read_text(encoding="utf-8")

    assert "## Behavioral Acceptance Gate" in soak_doc
    assert "behavior.tsv" in soak_doc
    for env_name in (
        "SOAK_MIN_MOVEMENT_PER_AGENT",
        "SOAK_MAX_DEATHS_PER_AGENT",
        "SOAK_MAX_STUCK_PER_AGENT",
        "SOAK_MAX_RESTARTS_PER_AGENT",
        "SOAK_MIN_PUBLIC_CHAT_COHORT",
        "SOAK_MIN_GATHER_OR_BUILD_COHORT",
        "SOAK_MIN_SHARED_ARTIFACTS",
        "SOAK_REQUIRE_BEHAVIOR_GATE",
    ):
        assert env_name in soak_doc
    assert "any unmet per-agent or cohort threshold is a NO-GO regardless" in soak_doc
    assert "process health alone" in cohort_doc
    assert "## Behavior Acceptance Table" in cohort_doc
    assert "| Behavioral Acceptance Gate |" in cohort_doc
    for agent_id in AGENT_IDS:
        assert f"| {agent_id.title()} |" in cohort_doc

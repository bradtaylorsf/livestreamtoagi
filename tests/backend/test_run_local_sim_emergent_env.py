"""Shell-level env assertions for MC_SIM_BUILD_MODE=emergent (E21-7c).

These invoke ``scripts/minecraft/run-local-sim.sh`` with ``MC_SIM_PRINT_ENV=1``,
which resolves the build mode + init message and exits 0 *before* the
LM Studio / Minecraft bridge checks. That lets us assert the operator default,
the emergent init seed, and the validator without a live local stack.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_LOCAL_SIM = REPO_ROOT / "scripts" / "minecraft" / "run-local-sim.sh"

# Phrases that drove the cabin-copycat loop and must never appear in emergent.
# Note: the copycat was driven by the CONCRETE example ("small shared cabin") plus
# the settlement scaffolding, not by planAndBuild itself. E21-7g re-allows a
# GENERIC planAndBuild placeholder in the seed so agents build real coherent
# structures (vs scattered !placeHere markers) while still inventing what to
# build — the concrete-cabin string stays forbidden to prevent copycat.
FORBIDDEN_PHRASES = (
    "small shared cabin",
    "Complete these settlement objectives in order",
    "Rotate the build owner",
)
# Task-board framing the emergent seed must teach (E21-7g manage_task loop).
REQUIRED_PHRASES = (
    "observe",
    "propose",
    "claim",
    "execute",
    "report",
    "task board",
    "!manageTask",
)

# Strip any inherited Minecraft env so a polluted parent shell cannot mask the
# script's own resolution (mirrors test_minecraft_director_acceptance_soak.py).
_ENV_KEYS = {"CONVERSATION_MODE", "ENV_FILE"}
_ENV_PREFIXES = ("LOCAL_LLM", "MC_HEARTBEAT", "MC_SIM", "MINECRAFT_", "SOAK_", "LLM_")


def _clean_env(overrides: dict[str, str]) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _ENV_KEYS and not key.startswith(_ENV_PREFIXES)
    }
    env.update(overrides)
    return env


def _stub_env_file(tmp_path: Path) -> Path:
    # The print-env hook exits before LLM_PROVIDER/LOCAL_LLM_MODEL checks, so the
    # file only needs to exist for load_env_file. Keep it intentionally minimal.
    env_file = tmp_path / ".env"
    env_file.write_text("EMBEDDING_PROVIDER=deterministic\n", encoding="utf-8")
    return env_file


def _print_env(
    mode: str, tmp_path: Path, overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = _clean_env(
        {
            "ENV_FILE": str(_stub_env_file(tmp_path)),
            "MC_SIM_PRINT_ENV": "1",
            **(overrides or {}),
        }
    )
    return subprocess.run(
        ["bash", str(RUN_LOCAL_SIM), mode],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _parse(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            parsed[key] = value
    return parsed


def test_soak_director_defaults_to_emergent(tmp_path: Path) -> None:
    proc = _print_env("soak-director", tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    parsed = _parse(proc.stdout)
    assert parsed["MC_SIM_BUILD_MODE"] == "emergent"

    init = parsed["SOAK_INIT_MESSAGE"]
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in init, f"forbidden phrase leaked into emergent seed: {phrase!r}"
    lowered = init.lower()
    for phrase in REQUIRED_PHRASES:
        assert phrase.lower() in lowered, f"missing emergent task-board cue: {phrase!r}"


def test_smoke_director_defaults_to_emergent(tmp_path: Path) -> None:
    proc = _print_env("smoke-director", tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _parse(proc.stdout)["MC_SIM_BUILD_MODE"] == "emergent"


def test_emergent_sets_no_settlement_owner_order_and_leaves_allowlist_unrestricted(
    tmp_path: Path,
) -> None:
    proc = _print_env("soak-director", tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    parsed = _parse(proc.stdout)
    assert parsed["MC_SIM_BUILD_MODE"] == "emergent"
    assert parsed["MC_SIM_SETTLEMENT_OWNER_ORDER"] == ""
    assert parsed["MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST"] == ""
    # Cooldown stays the only build throttle.
    assert parsed["MC_SIM_BUILD_COOLDOWN_SEC"] == "300"


def test_bare_soak_and_smoke_still_default_to_single(tmp_path: Path) -> None:
    for mode in ("soak", "smoke"):
        proc = _print_env(mode, tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert _parse(proc.stdout)["MC_SIM_BUILD_MODE"] == "single", mode


def test_explicit_build_mode_overrides_director_default(tmp_path: Path) -> None:
    # An explicit MC_SIM_BUILD_MODE wins over the emergent operator default and
    # settlement keeps its scripted init text (regression harness preserved).
    proc = _print_env("soak-director", tmp_path, {"MC_SIM_BUILD_MODE": "settlement"})

    assert proc.returncode == 0, proc.stdout + proc.stderr
    parsed = _parse(proc.stdout)
    assert parsed["MC_SIM_BUILD_MODE"] == "settlement"
    assert "Complete these settlement objectives in order" in parsed["SOAK_INIT_MESSAGE"]


def test_unknown_build_mode_exits_with_clear_message(tmp_path: Path) -> None:
    proc = _print_env("soak-director", tmp_path, {"MC_SIM_BUILD_MODE": "chaos"})

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "MC_SIM_BUILD_MODE must be single, plan, settlement, or emergent." in proc.stderr

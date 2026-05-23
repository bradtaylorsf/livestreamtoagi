"""Tests for deterministic Minecraft live eval profile resolution."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.minecraft.eval.live_profile import (
    BUILTIN_PROFILES,
    DEFAULT_PROFILE_NAME,
    EvalProfileError,
    list_profiles,
    parse_world_config,
    resolve_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FLAT_WORLD_CONFIG = REPO_ROOT / "scripts" / "minecraft" / "world-flat-eval.config"
WORLD_CONFIG = REPO_ROOT / "scripts" / "minecraft" / "world.config"
EASY_WORLD_CONFIG = REPO_ROOT / "scripts" / "minecraft" / "world-easy.config"

EXPECTED_FLAT_CONFIG = {
    "LEVEL_SEED": "livestreamtoagi-flat-eval-v1",
    "LEVEL_TYPE": "minecraft:flat",
    "LEVEL_NAME": "flat_eval_world",
    "GENERATE_STRUCTURES": "false",
    "SPAWN_PROTECTION": "0",
}


def test_default_profile_resolves_to_seeded_flat_eval_world() -> None:
    profile = resolve_profile(env={}, project_root=REPO_ROOT)

    assert profile.name == DEFAULT_PROFILE_NAME
    assert profile.world_config_path == FLAT_WORLD_CONFIG
    assert profile.server_dir == REPO_ROOT / "minecraft-server-flat-eval"
    assert profile.mc_host == "127.0.0.1"
    assert profile.mc_port == 25568
    assert profile.level_seed == "livestreamtoagi-flat-eval-v1"
    assert profile.level_type == "minecraft:flat"
    assert profile.level_name == "flat_eval_world"
    assert profile.generate_structures is False
    assert profile.spawn_protection == 0
    assert profile.keep_server_running is False
    assert list_profiles() == ("flat-eval",)


def test_parse_world_config_accepts_shipped_flat_eval_config() -> None:
    assert parse_world_config(FLAT_WORLD_CONFIG) == EXPECTED_FLAT_CONFIG


@pytest.mark.parametrize(
    "config_text",
    [
        (
            "LEVEL_SEED=livestreamtoagi-flat-eval-v1\n"
            "LEVEL_TYPE=minecraft:flat\n"
            "LEVEL_NAME=flat_eval_world\n"
            "GENERATE_STRUCTURES=false\n"
            "SPAWN_PROTECTION=0\n"
            "UNKNOWN=value\n"
        ),
        (
            "LEVEL_SEED=livestreamtoagi-flat-eval-v1\n"
            "LEVEL_TYPE=minecraft:flat\n"
            "LEVEL_NAME=\n"
            "GENERATE_STRUCTURES=false\n"
            "SPAWN_PROTECTION=0\n"
        ),
        (
            "LEVEL_SEED=$(uuidgen)\n"
            "LEVEL_TYPE=minecraft:flat\n"
            "LEVEL_NAME=flat_eval_world\n"
            "GENERATE_STRUCTURES=false\n"
            "SPAWN_PROTECTION=0\n"
        ),
        (
            "export LEVEL_SEED=livestreamtoagi-flat-eval-v1\n"
            "LEVEL_TYPE=minecraft:flat\n"
            "LEVEL_NAME=flat_eval_world\n"
            "GENERATE_STRUCTURES=false\n"
            "SPAWN_PROTECTION=0\n"
        ),
    ],
)
def test_parse_world_config_rejects_non_strict_lines(
    tmp_path: Path,
    config_text: str,
) -> None:
    config_path = tmp_path / "world.config"
    config_path.write_text(config_text, encoding="utf-8")

    with pytest.raises(EvalProfileError):
        parse_world_config(config_path)


def test_resolve_profile_honors_port_server_dir_and_keep_running_env_overrides() -> None:
    profile = resolve_profile(
        env={
            "MC_EVAL_LIVE_PORT": "26000",
            "MC_EVAL_LIVE_SERVER_DIR": "tmp/mc-eval-live",
            "MC_EVAL_LIVE_KEEP_RUNNING": "true",
        },
        project_root=REPO_ROOT,
    )

    assert profile.mc_port == 26000
    assert profile.server_dir == REPO_ROOT / "tmp" / "mc-eval-live"
    assert profile.keep_server_running is True


def test_resolve_profile_raises_for_unknown_profile() -> None:
    with pytest.raises(EvalProfileError, match="unknown Minecraft live eval profile"):
        resolve_profile("missing-profile", env={}, project_root=REPO_ROOT)


def test_resolve_profile_raises_for_profile_with_empty_level_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "empty-seed.config"
    config_path.write_text(
        "LEVEL_SEED=\n"
        "LEVEL_TYPE=minecraft:flat\n"
        "LEVEL_NAME=empty_seed_world\n"
        "GENERATE_STRUCTURES=false\n"
        "SPAWN_PROTECTION=0\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(
        BUILTIN_PROFILES,
        "empty-seed",
        replace(
            BUILTIN_PROFILES[DEFAULT_PROFILE_NAME],
            name="empty-seed",
            world_config_path=config_path,
        ),
    )

    with pytest.raises(EvalProfileError, match="LEVEL_SEED"):
        resolve_profile("empty-seed", env={}, project_root=REPO_ROOT)


def test_flat_eval_port_does_not_collide_with_normal_or_easy_world_defaults() -> None:
    assert WORLD_CONFIG.is_file()
    assert EASY_WORLD_CONFIG.is_file()

    profile = resolve_profile(env={}, project_root=REPO_ROOT)

    assert profile.mc_port == 25568
    assert profile.mc_port not in {25565, 25566}


def test_flat_eval_config_disables_structure_generation_for_deterministic_terrain() -> None:
    config = parse_world_config(FLAT_WORLD_CONFIG)
    profile = resolve_profile(env={}, project_root=REPO_ROOT)

    assert config["GENERATE_STRUCTURES"] == "false"
    assert profile.generate_structures is False

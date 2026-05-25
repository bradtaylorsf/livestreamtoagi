"""Tests for run-spec Minecraft world provisioning."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from core.minecraft.world_provisioner import provision_world
from core.models import RunMode, WorldConfig


def _script_dir(tmp_path: Path) -> Path:
    script_dir = tmp_path / "scripts" / "minecraft"
    script_dir.mkdir(parents=True)
    (script_dir / "restore.sh").write_text("#!/usr/bin/env bash\n")
    return script_dir


def test_experimental_custom_world_resets_from_run_spec_config(tmp_path: Path) -> None:
    server_dir = tmp_path / "minecraft-server"
    script_dir = _script_dir(tmp_path)
    custom_config = tmp_path / "custom-world.config"
    custom_config.write_text(
        "LEVEL_SEED=alpha-loop\n"
        "LEVEL_TYPE=minecraft:flat\n"
        "LEVEL_NAME=experiment-world\n"
        "GENERATE_STRUCTURES=false\n"
        "SPAWN_PROTECTION=0\n"
    )

    with patch("core.minecraft.world_provisioner.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        result = provision_world(
            WorldConfig(world_type="custom", world_config_path=str(custom_config)),
            RunMode.experimental,
            server_dir=server_dir,
            script_dir=script_dir,
            dry_run=False,
        )

    assert result.action == "reset_fresh"
    assert result.world_config_path == custom_config.resolve()
    assert result.level_name == "experiment-world"
    run.assert_called_once()
    args = run.call_args.args[0]
    assert args[-2:] == ["--reset", "--yes"]
    assert run.call_args.kwargs["env"]["SERVER_DIR"] == str(server_dir.resolve())
    assert run.call_args.kwargs["env"]["WORLD_CONFIG"] == str(custom_config.resolve())


def test_persistent_durable_world_reuses_existing_folder_without_reset(tmp_path: Path) -> None:
    server_dir = tmp_path / "minecraft-server"
    (server_dir / "durable-world").mkdir(parents=True)
    script_dir = _script_dir(tmp_path)

    with patch("core.minecraft.world_provisioner.subprocess.run") as run:
        result = provision_world(
            WorldConfig(
                world_type="default",
                seed=605,
                persistent=True,
                durable_world_id="durable-world",
            ),
            RunMode.persistent,
            server_dir=server_dir,
            script_dir=script_dir,
            dry_run=False,
        )

    assert result.action == "reuse_existing"
    assert result.persistent is True
    assert result.level_name == "durable-world"
    assert "LEVEL_NAME=durable-world" in result.world_config_path.read_text()
    run.assert_not_called()


def test_default_world_type_with_seed_writes_derived_config(tmp_path: Path) -> None:
    server_dir = tmp_path / "minecraft-server"
    script_dir = _script_dir(tmp_path)

    with patch("core.minecraft.world_provisioner.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        result = provision_world(
            WorldConfig(world_type="default", seed=12345),
            RunMode.experimental,
            server_dir=server_dir,
            script_dir=script_dir,
            dry_run=False,
        )

    text = result.world_config_path.read_text()
    assert result.action == "reset_fresh"
    assert "LEVEL_SEED=12345" in text
    assert "LEVEL_TYPE=minecraft:normal" in text
    assert "LEVEL_NAME=world" in text
    run.assert_called_once()


def test_persistent_world_refuses_to_create_missing_durable_folder(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Persistent runs do not reset"):
        provision_world(
            WorldConfig(persistent=True, durable_world_id="missing-world"),
            RunMode.persistent,
            server_dir=tmp_path / "minecraft-server",
            script_dir=_script_dir(tmp_path),
            dry_run=False,
        )

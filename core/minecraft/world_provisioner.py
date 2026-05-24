"""Provision Minecraft world configuration from a run spec."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.models import RunMode, WorldConfig

WORLD_KEYS = {
    "LEVEL_SEED",
    "LEVEL_TYPE",
    "LEVEL_NAME",
    "GENERATE_STRUCTURES",
    "SPAWN_PROTECTION",
}

LEVEL_TYPE_BY_WORLD_TYPE = {
    "default": "minecraft:normal",
    "flat": "minecraft:flat",
    "amplified": "minecraft:amplified",
}


@dataclass(frozen=True)
class WorldProvisionResult:
    """Resolved world config that start-server.sh/supervise.sh should use."""

    world_config_path: Path
    level_name: str
    run_mode: RunMode
    persistent: bool
    action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_config_path": str(self.world_config_path),
            "level_name": self.level_name,
            "run_mode": self.run_mode.value,
            "persistent": self.persistent,
            "action": self.action,
        }


def parse_world_config(path: Path) -> dict[str, str]:
    """Parse fixed KEY=VALUE world config lines without executing the file."""
    if not path.is_file():
        raise FileNotFoundError(f"world config not found: {path}")

    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.rstrip("\r")
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key in WORLD_KEYS:
            values[key] = value
    return values


def _project_root(script_dir: Path) -> Path:
    return script_dir.resolve().parents[1]


def _resolve_path(path: str, *, script_dir: Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    root_candidate = (_project_root(script_dir) / candidate).resolve()
    if root_candidate.exists() or path.startswith("scripts/"):
        return root_candidate
    return (Path.cwd() / candidate).resolve()


def _extra(world_config: WorldConfig, *names: str) -> Any:
    extras = world_config.model_extra or {}
    for name in names:
        if name in extras:
            return extras[name]
    return None


def _bool_config_value(value: Any, *, default: bool) -> str:
    if value is None:
        return "true" if default else "false"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def _level_name(world_config: WorldConfig, config_values: dict[str, str] | None = None) -> str:
    explicit = (
        world_config.durable_world_id
        or _extra(world_config, "level_name", "LEVEL_NAME")
        or (config_values or {}).get("LEVEL_NAME")
        or "world"
    )
    level_name = str(explicit).strip()
    if not level_name:
        raise ValueError("LEVEL_NAME resolved empty")
    return level_name


def _derived_values(world_config: WorldConfig) -> dict[str, str]:
    level_type = LEVEL_TYPE_BY_WORLD_TYPE.get(world_config.world_type)
    if level_type is None:
        raise ValueError(f"cannot derive world config for world_type={world_config.world_type!r}")

    seed = _extra(world_config, "level_seed", "LEVEL_SEED")
    if seed is None:
        seed = "" if world_config.seed is None else str(world_config.seed)

    spawn_protection = _extra(world_config, "spawn_protection", "SPAWN_PROTECTION")
    generate_structures = _extra(world_config, "generate_structures", "GENERATE_STRUCTURES")
    return {
        "LEVEL_SEED": str(seed),
        "LEVEL_TYPE": level_type,
        "LEVEL_NAME": _level_name(world_config),
        "GENERATE_STRUCTURES": _bool_config_value(generate_structures, default=True),
        "SPAWN_PROTECTION": str(0 if spawn_protection is None else spawn_protection),
    }


def _write_derived_world_config(world_config: WorldConfig, *, server_dir: Path) -> Path:
    server_dir.mkdir(parents=True, exist_ok=True)
    values = _derived_values(world_config)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix="run-world-",
        suffix=".config",
        dir=server_dir,
        delete=False,
    ) as handle:
        path = Path(handle.name)
        handle.write("# Generated from RunSpec.world by core.minecraft.world_provisioner.\n")
        for key in (
            "LEVEL_SEED",
            "LEVEL_TYPE",
            "LEVEL_NAME",
            "GENERATE_STRUCTURES",
            "SPAWN_PROTECTION",
        ):
            handle.write(f"{key}={values[key]}\n")
    return path


def _resolved_config_path(
    world_config: WorldConfig,
    *,
    server_dir: Path,
    script_dir: Path,
) -> Path:
    if world_config.world_type == "custom":
        return _resolve_path(str(world_config.world_config_path), script_dir=script_dir)
    return _write_derived_world_config(world_config, server_dir=server_dir)


def _run_restore_reset(
    *,
    restore_script: Path,
    server_dir: Path,
    world_config_path: Path,
) -> None:
    env = {
        **os.environ,
        "SERVER_DIR": str(server_dir),
        "WORLD_CONFIG": str(world_config_path),
    }
    proc = subprocess.run(
        ["bash", str(restore_script), "--reset", "--yes"],
        cwd=str(_project_root(restore_script.parent)),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            f"minecraft world reset failed with exit code {proc.returncode}: {detail}"
        )


def provision_world(
    world_config: WorldConfig,
    run_mode: RunMode,
    *,
    server_dir: Path,
    script_dir: Path,
    dry_run: bool,
) -> WorldProvisionResult:
    """Resolve and optionally reset/reuse the Minecraft world for a run."""
    if dry_run:
        config_path = (
            _resolve_path(str(world_config.world_config_path), script_dir=script_dir)
            if world_config.world_type == "custom"
            else script_dir / "world.config"
        )
        level_name = _level_name(
            world_config,
            parse_world_config(config_path) if config_path.is_file() else None,
        )
        return WorldProvisionResult(
            world_config_path=config_path,
            level_name=level_name,
            run_mode=run_mode,
            persistent=world_config.persistent or run_mode == RunMode.persistent,
            action="dry_run",
        )

    server_dir = server_dir.expanduser().resolve()
    script_dir = script_dir.expanduser().resolve()
    config_path = _resolved_config_path(world_config, server_dir=server_dir, script_dir=script_dir)
    config_values = parse_world_config(config_path)
    persistent = world_config.persistent or run_mode == RunMode.persistent
    level_name = _level_name(world_config, config_values)

    if persistent:
        world_dir = server_dir / level_name
        if not world_dir.is_dir():
            raise FileNotFoundError(
                f"persistent world folder not found: {world_dir}. "
                "Persistent runs do not reset or create durable worlds."
            )
        return WorldProvisionResult(
            world_config_path=config_path,
            level_name=level_name,
            run_mode=run_mode,
            persistent=True,
            action="reuse_existing",
        )

    _run_restore_reset(
        restore_script=script_dir / "restore.sh",
        server_dir=server_dir,
        world_config_path=config_path,
    )
    return WorldProvisionResult(
        world_config_path=config_path,
        level_name=level_name,
        run_mode=run_mode,
        persistent=False,
        action="reset_fresh",
    )

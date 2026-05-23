"""Deterministic Minecraft live eval profile resolution."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE_NAME = "flat-eval"

_WORLD_CONFIG_KEYS = frozenset(
    {
        "LEVEL_SEED",
        "LEVEL_TYPE",
        "LEVEL_NAME",
        "GENERATE_STRUCTURES",
        "SPAWN_PROTECTION",
    }
)
_ALLOWED_LEVEL_TYPES = frozenset(
    {
        "minecraft:flat",
        "minecraft:normal",
        "minecraft:large_biomes",
        "minecraft:amplified",
    }
)
_SHELL_TOKENS = ("$(", "${", "`", ";", "&&", "||", "|", "<", ">")


class EvalProfileError(ValueError):
    """Raised when a Minecraft live eval profile cannot be resolved."""


@dataclass(frozen=True, slots=True)
class EvalProfile:
    name: str
    world_config_path: Path
    server_dir: Path
    mc_host: str
    mc_port: int
    level_seed: str
    level_type: str
    level_name: str
    generate_structures: bool
    spawn_protection: int
    keep_server_running: bool


BUILTIN_PROFILES: dict[str, EvalProfile] = {
    DEFAULT_PROFILE_NAME: EvalProfile(
        name=DEFAULT_PROFILE_NAME,
        world_config_path=Path("scripts/minecraft/world-flat-eval.config"),
        server_dir=Path("minecraft-server-flat-eval"),
        mc_host="127.0.0.1",
        mc_port=25568,
        level_seed="livestreamtoagi-flat-eval-v1",
        level_type="minecraft:flat",
        level_name="flat_eval_world",
        generate_structures=False,
        spawn_protection=0,
        keep_server_running=False,
    )
}


def list_profiles() -> tuple[str, ...]:
    """Return available built-in live eval profile names."""

    return tuple(sorted(BUILTIN_PROFILES))


def parse_world_config(path: Path) -> dict[str, str]:
    """Parse a strict Minecraft world config KEY=VALUE file."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvalProfileError(f"cannot read world config {path}: {exc}") from exc

    config: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip("\r")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line != stripped or "=" not in line:
            raise EvalProfileError(
                f"invalid world config line {line_number} in {path}: expected KEY=VALUE"
            )
        if any(token in line for token in _SHELL_TOKENS):
            raise EvalProfileError(
                f"invalid world config line {line_number} in {path}: shell syntax is not allowed"
            )

        key, value = line.split("=", 1)
        if key not in _WORLD_CONFIG_KEYS:
            raise EvalProfileError(
                f"unknown world config key {key!r} on line {line_number} in {path}"
            )
        if value == "":
            raise EvalProfileError(
                f"blank world config value for {key} on line {line_number} in {path}"
            )
        config[key] = value

    missing = sorted(_WORLD_CONFIG_KEYS - config.keys())
    if missing:
        raise EvalProfileError(
            f"world config {path} is missing required key(s): {', '.join(missing)}"
        )
    return config


def resolve_profile(
    name: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    project_root: Path | None = None,
) -> EvalProfile:
    """Resolve a built-in live eval profile with supported env overrides."""

    root = (project_root or PROJECT_ROOT).resolve()
    resolved_env = os.environ if env is None else env
    profile_name = name if name is not None else resolved_env.get("MC_EVAL_LIVE_PROFILE")
    profile_name = profile_name or DEFAULT_PROFILE_NAME
    if profile_name not in BUILTIN_PROFILES:
        available = ", ".join(list_profiles())
        raise EvalProfileError(
            f"unknown Minecraft live eval profile {profile_name!r}; available: {available}"
        )

    template = BUILTIN_PROFILES[profile_name]
    world_config_path = _resolve_path(root, template.world_config_path)
    config = parse_world_config(world_config_path)

    level_seed = config["LEVEL_SEED"]
    if not level_seed:
        raise EvalProfileError(f"profile {profile_name!r} must define a non-empty LEVEL_SEED")
    level_type = config["LEVEL_TYPE"]
    if level_type not in _ALLOWED_LEVEL_TYPES:
        allowed = ", ".join(sorted(_ALLOWED_LEVEL_TYPES))
        raise EvalProfileError(
            f"profile {profile_name!r} has unsupported LEVEL_TYPE {level_type!r}; "
            f"allowed: {allowed}"
        )

    return EvalProfile(
        name=profile_name,
        world_config_path=world_config_path,
        server_dir=_resolve_server_dir(root, template, resolved_env),
        mc_host=template.mc_host,
        mc_port=_resolve_port(template, resolved_env),
        level_seed=level_seed,
        level_type=level_type,
        level_name=config["LEVEL_NAME"],
        generate_structures=_parse_bool(config["GENERATE_STRUCTURES"], "GENERATE_STRUCTURES"),
        spawn_protection=_parse_non_negative_int(
            config["SPAWN_PROTECTION"], "SPAWN_PROTECTION"
        ),
        keep_server_running=_resolve_keep_server_running(template, resolved_env),
    )


def _resolve_path(root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return root / path


def _resolve_port(template: EvalProfile, env: Mapping[str, str]) -> int:
    override = env.get("MC_EVAL_LIVE_PORT")
    if override is None:
        return template.mc_port
    port = _parse_non_negative_int(override, "MC_EVAL_LIVE_PORT")
    if port == 0 or port > 65535:
        raise EvalProfileError("MC_EVAL_LIVE_PORT must be between 1 and 65535")
    return port


def _resolve_server_dir(
    root: Path,
    template: EvalProfile,
    env: Mapping[str, str],
) -> Path:
    override = env.get("MC_EVAL_LIVE_SERVER_DIR")
    if override is None:
        return _resolve_path(root, template.server_dir)
    if not override:
        raise EvalProfileError("MC_EVAL_LIVE_SERVER_DIR cannot be blank")
    return _resolve_path(root, Path(override))


def _resolve_keep_server_running(
    template: EvalProfile,
    env: Mapping[str, str],
) -> bool:
    override = env.get("MC_EVAL_LIVE_KEEP_RUNNING")
    if override is None:
        return template.keep_server_running
    return _parse_bool(override, "MC_EVAL_LIVE_KEEP_RUNNING")


def _parse_bool(value: str, field_name: str) -> bool:
    normalized = value.casefold()
    if normalized == "true" or normalized == "1":
        return True
    if normalized == "false" or normalized == "0":
        return False
    raise EvalProfileError(f"{field_name} must be true or false")


def _parse_non_negative_int(value: str, field_name: str) -> int:
    if not value.isdecimal():
        raise EvalProfileError(f"{field_name} must be a non-negative integer")
    return int(value)

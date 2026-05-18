"""Tests for configurable world generation (issue #527, epic E2-2).

The committed ``scripts/minecraft/world.config`` is consumed by
``scripts/minecraft/start-server.sh`` to fill in the world-generation lines
of a freshly generated ``server.properties``. These tests exercise the
offline-safe ``--dry-run`` path only (no Java, no network): config parsing
and ``server.properties`` generation are fully verifiable that way.

Acceptance criterion under test: *changing the world config file produces a
different world on a fresh run* — i.e. a different seed/type/spawn lands
verbatim in the generated ``server.properties`` (which Minecraft uses to
generate the world on first boot).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "minecraft" / "start-server.sh"
WORLD_CONFIG = REPO_ROOT / "scripts" / "minecraft" / "world.config"

# The fixed allow-list the start script reads. Keep in sync with world.config
# and the parser in start-server.sh.
EXPECTED_KEYS = {
    "LEVEL_SEED",
    "LEVEL_TYPE",
    "LEVEL_NAME",
    "GENERATE_STRUCTURES",
    "SPAWN_PROTECTION",
}


def _run(args, server_dir: Path, extra_env: dict | None = None):
    """Run the start script with SERVER_DIR pointed at a temp dir."""
    env = {**os.environ, "SERVER_DIR": str(server_dir)}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def _parse_config(text: str) -> dict[str, str]:
    """Parse a world.config the same way the script does: KEY=VALUE lines,
    '#' comments and blanks ignored, last value for a key wins."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key and not key[0].isspace():
            out[key] = value
    return out


def test_world_config_exists_and_parses():
    assert WORLD_CONFIG.is_file(), f"missing {WORLD_CONFIG}"
    cfg = _parse_config(WORLD_CONFIG.read_text())
    # Every allow-listed key is present (LEVEL_SEED may be intentionally empty).
    assert EXPECTED_KEYS.issubset(cfg.keys()), (
        f"world.config missing keys: {EXPECTED_KEYS - set(cfg)}"
    )
    # Shipped safe defaults.
    assert cfg["LEVEL_SEED"] == ""  # empty → random world
    assert cfg["LEVEL_TYPE"] == "minecraft:normal"
    assert cfg["LEVEL_NAME"] == "world"
    assert cfg["GENERATE_STRUCTURES"] == "true"
    assert cfg["SPAWN_PROTECTION"] == "0"


def test_default_config_lands_in_generated_properties(tmp_path):
    server_dir = tmp_path / "mc"
    proc = _run(["--dry-run"], server_dir)

    assert proc.returncode == 0, proc.stderr + proc.stdout
    props = (server_dir / "server.properties").read_text()
    assert "level-type=minecraft:normal" in props
    assert "level-name=world" in props
    assert "generate-structures=true" in props
    assert "spawn-protection=0" in props
    # Empty seed → emitted as a bare key so Minecraft picks a random world.
    assert "level-seed=\n" in props


def test_custom_config_seed_type_spawn_appear_verbatim(tmp_path):
    server_dir = tmp_path / "mc"
    cfg = tmp_path / "world.config"
    cfg.write_text(
        "LEVEL_SEED=alpha-loop\n"
        "LEVEL_TYPE=minecraft:flat\n"
        "LEVEL_NAME=experiment-2\n"
        "GENERATE_STRUCTURES=false\n"
        "SPAWN_PROTECTION=16\n"
    )

    proc = _run(["--dry-run"], server_dir, {"WORLD_CONFIG": str(cfg)})

    assert proc.returncode == 0, proc.stderr + proc.stdout
    props = (server_dir / "server.properties").read_text()
    assert "level-seed=alpha-loop" in props
    assert "level-type=minecraft:flat" in props
    assert "level-name=experiment-2" in props
    assert "generate-structures=false" in props
    assert "spawn-protection=16" in props
    # The resolved world is also surfaced in the --dry-run preview.
    assert "seed=alpha-loop" in proc.stdout
    assert "minecraft:flat" in proc.stdout


def test_changing_a_config_value_changes_the_generated_world(tmp_path):
    """The acceptance criterion: a different config → a different world."""
    cfg = tmp_path / "world.config"

    cfg.write_text("LEVEL_SEED=first-seed\nLEVEL_TYPE=minecraft:normal\n")
    proc_a = _run(["--dry-run"], tmp_path / "a", {"WORLD_CONFIG": str(cfg)})
    props_a = (tmp_path / "a" / "server.properties").read_text()

    cfg.write_text("LEVEL_SEED=second-seed\nLEVEL_TYPE=minecraft:large_biomes\n")
    proc_b = _run(["--dry-run"], tmp_path / "b", {"WORLD_CONFIG": str(cfg)})
    props_b = (tmp_path / "b" / "server.properties").read_text()

    assert proc_a.returncode == 0 and proc_b.returncode == 0
    assert "level-seed=first-seed" in props_a
    assert "level-seed=second-seed" in props_b
    assert "level-type=minecraft:normal" in props_a
    assert "level-type=minecraft:large_biomes" in props_b
    # Same SERVER_DIR would be a no-op (Minecraft bakes the world); the
    # generated properties differ because each used a fresh dir.
    assert props_a != props_b


def test_existing_server_properties_still_not_clobbered(tmp_path):
    """The E2-1 no-clobber guarantee must survive the E2-2 changes, even
    with a custom WORLD_CONFIG set."""
    server_dir = tmp_path / "mc"
    server_dir.mkdir(parents=True)
    sentinel = "motd=do-not-touch\nlevel-seed=hand-edited\n"
    (server_dir / "server.properties").write_text(sentinel)

    cfg = tmp_path / "world.config"
    cfg.write_text("LEVEL_SEED=should-be-ignored\nLEVEL_TYPE=minecraft:flat\n")

    proc = _run(["--dry-run"], server_dir, {"WORLD_CONFIG": str(cfg)})

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert (server_dir / "server.properties").read_text() == sentinel
    assert "untouched" in proc.stdout


def test_missing_world_config_falls_back_to_safe_defaults(tmp_path):
    server_dir = tmp_path / "mc"
    proc = _run(
        ["--dry-run"],
        server_dir,
        {"WORLD_CONFIG": str(tmp_path / "does-not-exist.config")},
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "absent — using built-in safe defaults" in proc.stdout
    props = (server_dir / "server.properties").read_text()
    assert "level-type=minecraft:normal" in props
    assert "level-name=world" in props
    assert "generate-structures=true" in props
    assert "spawn-protection=0" in props

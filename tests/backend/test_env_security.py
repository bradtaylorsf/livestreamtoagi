"""Tests for .env security practices (#351)."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_env_in_gitignore():
    """Verify .env is listed in .gitignore."""
    gitignore = (ROOT / ".gitignore").read_text()
    # Must have a standalone .env entry (not just .env.local)
    lines = [line.strip() for line in gitignore.splitlines()]
    assert ".env" in lines, ".env must be in .gitignore"


def test_env_example_has_no_real_values():
    """Verify .env.example documents vars without real secrets."""
    env_example = (ROOT / ".env.example").read_text()
    for line in env_example.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key == "CONVERSATION_MODE" and value in {"director", "embodied", "director_v2"}:
            continue
        # Allow placeholder defaults (localhost URLs, 'devpassword', 'dev-*')
        if value and not any(
            p in value for p in ["localhost", "devpassword", "dev-", "development", "ws://"]
        ):
            raise AssertionError(f".env.example has a suspicious real value for {key}: {value!r}")


def test_env_example_documents_required_vars():
    """Verify .env.example includes all required env vars from CLAUDE.md."""
    env_example = (ROOT / ".env.example").read_text()
    required_vars = [
        "OPENROUTER_API_KEY",
        "TWITCH_CLIENT_ID",
        "TWITCH_CLIENT_SECRET",
        "TWITCH_BOT_TOKEN",
        "YOUTUBE_API_KEY",
        "PIXELLAB_API_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        "KILL_SWITCH_API_KEY",
        "ADMIN_PASSWORD",
    ]
    for var in required_vars:
        assert var in env_example, f"Required var {var} missing from .env.example"


def test_pre_commit_config_exists():
    """Verify pre-commit config exists and blocks .env commits."""
    config_path = ROOT / ".pre-commit-config.yaml"
    assert config_path.exists(), ".pre-commit-config.yaml must exist"
    content = config_path.read_text()
    assert "block-env-files" in content, "Pre-commit must include env file blocking hook"

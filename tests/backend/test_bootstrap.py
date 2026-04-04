"""Tests for core/bootstrap.py — shared service bootstrapping."""

import asyncio
import dataclasses
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_services_dataclass_importable():
    """Services dataclass can be imported from core.bootstrap."""
    from core.bootstrap import Services

    assert dataclasses.is_dataclass(Services)
    field_names = {f.name for f in dataclasses.fields(Services)}
    expected = {
        "db", "redis", "http_client", "agent_registry", "llm_client",
        "core_memory", "recall_memory", "archival_memory", "compactor",
        "context_assembler", "token_counter", "memory_repo", "transcript_repo",
        "event_bus", "overseer", "cost_repo", "config_loader",
    }
    assert expected.issubset(field_names), f"Missing fields: {expected - field_names}"


def test_bootstrap_services_importable():
    """bootstrap_services function can be imported."""
    from core.bootstrap import bootstrap_services

    assert asyncio.iscoroutinefunction(bootstrap_services)


def test_shutdown_services_importable():
    """shutdown_services function can be imported."""
    from core.bootstrap import shutdown_services

    assert asyncio.iscoroutinefunction(shutdown_services)


def test_init_core_memories_importable():
    """init_core_memories function can be imported."""
    from core.bootstrap import init_core_memories

    assert asyncio.iscoroutinefunction(init_core_memories)


def test_no_database_construction_in_scripts():
    """Acceptance: no direct Database() construction in scripts/ or core/main.py."""
    result = subprocess.run(
        ["grep", "-rn", "Database()", "scripts/", "core/main.py"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    # grep returns 1 when no match is found (which is what we want)
    assert result.returncode == 1, (
        f"Found direct Database() construction:\n{result.stdout}"
    )


def testmake_embedding_fn_warns_on_missing_api_key(caplog):
    """make_embedding_fn logs a warning when api_key is empty."""
    import logging

    import httpx

    from core.bootstrap import make_embedding_fn

    with caplog.at_level(logging.WARNING, logger="core.bootstrap"):
        make_embedding_fn(httpx.AsyncClient(), "")

    assert any(
        "OPENROUTER_API_KEY not set" in msg for msg in caplog.messages
    ), f"Expected warning about missing API key, got: {caplog.messages}"


def testmake_embedding_fn_no_warning_with_api_key(caplog):
    """make_embedding_fn does NOT warn when api_key is provided."""
    import logging

    import httpx

    from core.bootstrap import make_embedding_fn

    with caplog.at_level(logging.WARNING, logger="core.bootstrap"):
        make_embedding_fn(httpx.AsyncClient(), "sk-test-key")

    assert not any(
        "OPENROUTER_API_KEY not set" in msg for msg in caplog.messages
    ), f"Unexpected warning with valid API key: {caplog.messages}"


def test_no_dummy_embed_anywhere():
    """Acceptance: no _dummy_embed function anywhere in scripts/ or core/."""
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "_dummy_embed", "scripts/", "core/"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"Found _dummy_embed references:\n{result.stdout}"
    )

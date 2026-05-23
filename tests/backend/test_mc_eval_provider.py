"""Tests for Minecraft command eval provider configuration."""

from __future__ import annotations

from argparse import Namespace

import pytest

from core.llm_client import OPENROUTER_BASE_URL
from core.minecraft.eval.provider import ProviderConfigError, resolve_provider_config


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "provider": None,
        "model": None,
        "base_url": None,
        "api_key": None,
        "timeout": None,
        "max_tokens": None,
        "temperature": None,
        "dry_run": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_local_provider_uses_env_defaults_and_model_routing_overrides() -> None:
    config = resolve_provider_config(
        _args(),
        {
            "LOCAL_LLM_BASE_URL": "http://localhost:1234/v1/",
            "LOCAL_LLM_API_KEY": "local-secret",
            "LOCAL_LLM_MODEL": "qwen-local",
            "LOCAL_LLM_MODEL_BUILDING": "coder-local",
            "LOCAL_LLM_PASSTHROUGH_MODEL": "true",
        },
    )

    assert config.provider == "lmstudio"
    assert config.model == "qwen-local"
    assert config.base_url == "http://localhost:1234/v1"
    assert config.api_key_present is True
    assert config.local_model == "qwen-local"
    assert config.local_model_building == "coder-local"
    assert config.passthrough_model is True


def test_cli_flags_take_precedence_over_local_env() -> None:
    config = resolve_provider_config(
        _args(
            provider="openai-compatible",
            model="flag-model",
            base_url="http://flag-provider/v1",
            api_key="flag-secret",
            timeout=12,
            max_tokens=77,
            temperature=0,
        ),
        {
            "LLM_PROVIDER": "lmstudio",
            "LOCAL_LLM_BASE_URL": "http://env-provider/v1",
            "LOCAL_LLM_API_KEY": "env-secret",
            "LOCAL_LLM_MODEL": "env-model",
        },
    )

    assert config.provider == "openai-compatible"
    assert config.model == "flag-model"
    assert config.base_url == "http://flag-provider/v1"
    assert config.timeout == 12
    assert config.max_tokens == 77
    assert config.temperature == 0
    assert "flag-secret" not in repr(config)
    assert "flag-secret" not in str(config.public_metadata())


def test_openrouter_requires_api_key_and_explicit_model() -> None:
    with pytest.raises(ProviderConfigError, match="OPENROUTER_API_KEY"):
        resolve_provider_config(
            _args(provider="openrouter", model="openai/gpt-4o-mini"),
            {},
        )

    with pytest.raises(ProviderConfigError, match="--model"):
        resolve_provider_config(
            _args(provider="openrouter"),
            {"OPENROUTER_API_KEY": "or-secret"},
        )


def test_local_dry_run_allows_missing_model() -> None:
    config = resolve_provider_config(_args(dry_run=True), {})

    assert config.provider == "lmstudio"
    assert config.model == "dry-run-local-model"
    assert config.base_url == "http://localhost:1234/v1"


def test_openrouter_uses_env_key_and_does_not_expose_secret() -> None:
    config = resolve_provider_config(
        _args(provider="openrouter", model="openai/gpt-4o-mini"),
        {"OPENROUTER_API_KEY": "or-secret"},
    )

    assert config.provider == "openrouter"
    assert config.model == "openai/gpt-4o-mini"
    assert config.base_url == OPENROUTER_BASE_URL
    assert config.api_key_present is True
    assert "or-secret" not in repr(config)
    assert "or-secret" not in str(config.public_metadata())


def test_unknown_provider_raises_clear_error() -> None:
    with pytest.raises(ProviderConfigError, match="Unknown provider"):
        resolve_provider_config(
            _args(provider="not-real"),
            {"LOCAL_LLM_MODEL": "qwen-local"},
        )

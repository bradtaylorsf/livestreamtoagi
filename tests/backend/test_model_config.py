"""Tests for environment-driven model role resolution."""

from __future__ import annotations

import os

import pytest

from core.model_config import (
    AGENT_MODEL_DEFAULTS,
    LEGACY_BUILDING_MODEL,
    LEGACY_FAST_MODEL,
    agent_model_ref,
    model_ref,
    resolve_agent_model,
    resolve_internal_model,
    resolve_model_reference,
)


def _clear_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("LTAG_MODEL_"):
            monkeypatch.delenv(key, raising=False)


def test_internal_role_specific_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LTAG_MODEL_MANAGEMENT_FILTER", "google/gemini-flash")
    monkeypatch.setenv("LTAG_MODEL_FAST", "openai/gpt-4o-mini")

    assert resolve_internal_model("management_filter") == "google/gemini-flash"


def test_internal_role_falls_back_to_fast_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LTAG_MODEL_FAST", "openai/gpt-4o-mini")

    assert resolve_internal_model("topic_classifier") == "openai/gpt-4o-mini"


def test_building_role_falls_back_to_building_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LTAG_MODEL_BUILDING", "deepseek/deepseek-v3.2")

    assert resolve_internal_model("eval_engine") == "deepseek/deepseek-v3.2"


def test_agent_specific_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LTAG_MODEL_AGENT_REX_BUILDING", "deepseek/deepseek-v3.2")
    monkeypatch.setenv("LTAG_MODEL_BUILDING", "google/gemini-2.5-pro")

    assert resolve_agent_model("rex", "building") == "deepseek/deepseek-v3.2"


def test_agent_reference_resolves_to_default_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_model_env(monkeypatch)

    assert (
        resolve_model_reference(agent_model_ref("rex", "conversation"))
        == AGENT_MODEL_DEFAULTS["rex"]["conversation"]
    )


def test_configured_literal_is_used_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_env(monkeypatch)

    assert (
        resolve_internal_model("memory_summary", "google/gemini-flash")
        == "google/gemini-flash"
    )


def test_builtin_defaults_apply_when_no_env_or_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_model_env(monkeypatch)

    assert resolve_internal_model("memory_summary") == LEGACY_FAST_MODEL
    assert resolve_internal_model("eval_engine") == LEGACY_BUILDING_MODEL


def test_model_role_references_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LTAG_MODEL_MEMORY_SUMMARY", "openai/gpt-4o-mini")

    assert resolve_model_reference(model_ref("memory_summary")) == "openai/gpt-4o-mini"


def test_cyclic_model_references_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LTAG_MODEL_MEMORY_SUMMARY", model_ref("memory_summary"))

    with pytest.raises(ValueError, match="Cyclic model reference"):
        resolve_model_reference(model_ref("memory_summary"))

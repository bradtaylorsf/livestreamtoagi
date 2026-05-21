"""Tests for conversation run-mode selection."""

from __future__ import annotations

import pytest

from core.conversation_mode import get_conversation_mode, is_director_v2_run, is_embodied_run


def test_conversation_mode_defaults_to_director(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONVERSATION_MODE", raising=False)

    assert get_conversation_mode() == "director"
    assert is_embodied_run() is False
    assert is_director_v2_run() is False


def test_conversation_mode_embodied_enables_embodied_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "embodied")

    assert get_conversation_mode() == "embodied"
    assert is_embodied_run() is True
    assert is_director_v2_run() is False


def test_conversation_mode_director_v2_enables_prompt_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "director_v2")

    assert get_conversation_mode() == "director_v2"
    assert is_embodied_run() is False
    assert is_director_v2_run() is True


def test_conversation_mode_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "EmBoDiEd")

    assert get_conversation_mode() == "embodied"
    assert is_embodied_run() is True
    assert is_director_v2_run() is False


def test_conversation_mode_rejects_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "central-director")

    with pytest.raises(ValueError, match="CONVERSATION_MODE"):
        get_conversation_mode()

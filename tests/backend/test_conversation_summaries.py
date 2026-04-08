"""Tests for structured conversation record generation (#271)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.conversation_engine import ConversationEngine, _ActiveConversation
from core.conversation.energy import ConversationEnergy
from core.models import ConversationRecord
from tests.backend.conversation_helpers import make_conversation_config


# ── Helpers ───────────────────────────────────────────────────


def _make_active_conversation(
    history: list[dict[str, str]] | None = None,
) -> _ActiveConversation:
    cfg = make_conversation_config()
    conv = _ActiveConversation(
        conversation_id=uuid.uuid4(),
        trigger={"type": "idle"},
        energy=ConversationEnergy(cfg.energy),
        participants=["vera", "rex"],
    )
    conv.history = history or [
        {"role": "assistant", "speaker": "vera", "content": "Let's decide on a project."},
        {"role": "assistant", "speaker": "rex", "content": "I'll build the dashboard."},
        {"role": "assistant", "speaker": "vera", "content": "Great, I'll coordinate."},
    ]
    conv.turn_number = len(conv.history)
    conv.topics = ["projects", "planning"]
    return conv


def _make_engine(llm_response_content: str | None = None, llm_error: bool = False) -> ConversationEngine:
    """Build a minimal ConversationEngine with mocked dependencies."""
    mock_llm = AsyncMock()
    if llm_error:
        mock_llm.complete = AsyncMock(side_effect=Exception("LLM failed"))
    else:
        response = MagicMock()
        response.content = llm_response_content or json.dumps({
            "summary": "Summary text",
            "outcome": "Decided on dashboard",
            "key_decisions": ["Build dashboard"],
            "unresolved_tensions": [],
            "novel_information": [],
        })
        response.input_tokens = 10
        response.output_tokens = 20
        response.estimated_cost = "0.001"
        response.latency_ms = 100
        response.model = "claude-haiku-4-5"
        mock_llm.complete = AsyncMock(return_value=response)

    mock_config_loader = MagicMock()
    mock_config_loader.config = make_conversation_config()
    mock_config_loader.config_hash = "test"

    engine = ConversationEngine(
        config_loader=mock_config_loader,
        agent_registry=MagicMock(),
        event_bus=MagicMock(),
        llm_client=mock_llm,
        management=MagicMock(),
        context_assembler=MagicMock(),
        conversation_repo=MagicMock(),
        archival_memory=MagicMock(),
        proximity=MagicMock(),
        trigger_system=MagicMock(),
        selection_logger=MagicMock(),
    )
    return engine


# ── Tests ─────────────────────────────────────────────────────


class TestGenerateRichSummary:
    """_generate_conversation_record produces structured records with fallback."""

    @pytest.mark.asyncio
    async def test_produces_rich_summary_from_llm(self) -> None:
        llm_json = json.dumps({
            "summary": "Vera and Rex decided to build a dashboard.",
            "outcome": "Dashboard project approved",
            "key_decisions": ["Rex leads implementation"],
            "unresolved_tensions": ["Timeline unclear"],
            "novel_information": [],
        })
        engine = _make_engine(llm_response_content=llm_json)
        conv = _make_active_conversation()

        record = await engine._generate_conversation_record(conv, "fallback stub")
        assert isinstance(record, ConversationRecord)
        assert "dashboard" in record.summary.lower()
        assert record.key_decisions == ["Rex leads implementation"]
        engine._llm.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_stub_on_llm_failure(self) -> None:
        engine = _make_engine(llm_error=True)
        conv = _make_active_conversation()

        record = await engine._generate_conversation_record(conv, "metadata fallback")
        assert record.summary == "metadata fallback"
        assert record.topics == ["projects", "planning"]

    @pytest.mark.asyncio
    async def test_falls_back_to_stub_on_empty_response(self) -> None:
        engine = _make_engine(llm_response_content="   ")
        conv = _make_active_conversation()

        record = await engine._generate_conversation_record(conv, "metadata fallback")
        assert record.summary == "metadata fallback"

    @pytest.mark.asyncio
    async def test_prompt_contains_transcript(self) -> None:
        engine = _make_engine()
        conv = _make_active_conversation()

        await engine._generate_conversation_record(conv, "fallback")

        call_args = engine._llm.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        system_msg = messages[0]["content"]
        assert "key_decisions" in system_msg
        assert "unresolved_tensions" in system_msg
        assert "[vera]:" in system_msg or "vera" in system_msg

    @pytest.mark.asyncio
    async def test_uses_cheap_model(self) -> None:
        engine = _make_engine()
        conv = _make_active_conversation()

        await engine._generate_conversation_record(conv, "fallback")

        call_args = engine._llm.complete.call_args
        model = call_args.kwargs.get("model") or call_args[1].get("model")
        assert "haiku" in model.lower(), f"Should use cheap model, got {model}"

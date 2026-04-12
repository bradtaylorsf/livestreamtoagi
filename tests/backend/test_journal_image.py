"""Tests for journal illustration generation (tools/journal_image_tool.py)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.journal_image_tool import (
    AGENT_VISUAL_STYLES,
    IMAGEN_COST_PER_IMAGE,
    IMAGEN_MODEL,
    IMAGEN_SIZE,
    JournalImageGenerator,
    build_illustration_prompt,
)


# ── Prompt construction ───────────────────────────────────────────


class TestBuildIllustrationPrompt:
    def test_includes_pixel_art_directive(self):
        prompt = build_illustration_prompt("Today I built a house.", "rex")
        assert "Pixel art" in prompt
        assert "16-bit" in prompt

    def test_includes_agent_visual_style(self):
        prompt = build_illustration_prompt("Reflecting on budget.", "sentinel")
        assert "amber and gold" in prompt

    def test_includes_journal_content(self):
        content = "I had an incredible day painting murals on the wall."
        prompt = build_illustration_prompt(content, "aurora")
        assert "painting murals" in prompt

    def test_truncates_long_content(self):
        content = "x" * 300
        prompt = build_illustration_prompt(content, "vera")
        # Should include truncated content with ellipsis
        assert "..." in prompt
        # Full 300-char content should not be in prompt
        assert "x" * 300 not in prompt

    def test_unknown_agent_uses_neutral_style(self):
        prompt = build_illustration_prompt("Journal entry.", "unknown_agent")
        assert "neutral tones" in prompt

    def test_no_text_directive(self):
        prompt = build_illustration_prompt("Hello world.", "vera")
        assert "no text" in prompt

    def test_all_agents_have_styles(self):
        expected = {"vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok", "alpha", "management"}
        assert set(AGENT_VISUAL_STYLES.keys()) == expected


# ── Fallback behavior ─────────────────────────────────────────────


class TestFallbackBehavior:
    @pytest.mark.asyncio
    async def test_returns_none_when_api_key_not_configured(self):
        gen = JournalImageGenerator(api_key="", gcs_bucket="")
        result = await gen.generate("Some journal content", "vera")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        gen = JournalImageGenerator(api_key="test-key", gcs_bucket="test-bucket")
        with patch.object(gen, "_call_imagen_api", side_effect=Exception("API down")):
            result = await gen.generate("Content", "rex")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_api_returns_no_predictions(self):
        gen = JournalImageGenerator(api_key="test-key", gcs_bucket="")
        with patch.object(gen, "_call_imagen_api", return_value=None):
            result = await gen.generate("Content", "aurora")
        assert result is None

    @pytest.mark.asyncio
    async def test_is_configured_property(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_IMAGEN_API_KEY", raising=False)
        assert not JournalImageGenerator(api_key="").is_configured
        assert JournalImageGenerator(api_key="sk-123").is_configured


# ── Cost event logging ────────────────────────────────────────────


class TestCostLogging:
    @pytest.mark.asyncio
    async def test_logs_cost_event_on_success(self):
        cost_repo = AsyncMock()
        cost_repo.add_cost = AsyncMock()
        gen = JournalImageGenerator(
            api_key="test-key", gcs_bucket="", cost_repo=cost_repo
        )
        sim_id = uuid.uuid4()

        # Mock the API call and upload
        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with (
            patch.object(gen, "_call_imagen_api", return_value=fake_image),
        ):
            result = await gen.generate("My journal entry", "vera", simulation_id=sim_id)

        assert result is not None
        cost_repo.add_cost.assert_called_once()
        cost_event = cost_repo.add_cost.call_args[0][0]
        assert cost_event.cost_type == "imagen_generation"
        assert cost_event.amount == IMAGEN_COST_PER_IMAGE
        assert cost_event.details["model"] == IMAGEN_MODEL
        assert cost_event.details["size"] == IMAGEN_SIZE
        assert cost_event.simulation_id == sim_id

    @pytest.mark.asyncio
    async def test_no_cost_logged_when_no_cost_repo(self):
        gen = JournalImageGenerator(api_key="test-key", gcs_bucket="", cost_repo=None)
        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with patch.object(gen, "_call_imagen_api", return_value=fake_image):
            result = await gen.generate("Entry", "rex")
        # Should succeed without error even though no cost_repo
        assert result is not None


# ── Integration: full flow ────────────────────────────────────────


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_generate_returns_image_url(self):
        cost_repo = AsyncMock()
        gen = JournalImageGenerator(
            api_key="test-key", gcs_bucket="", cost_repo=cost_repo
        )

        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with patch.object(gen, "_call_imagen_api", return_value=fake_image):
            url = await gen.generate("A productive day coding.", "rex")

        # Without GCS bucket, falls back to data URI
        assert url is not None
        assert url.startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_generate_with_gcs_bucket(self):
        cost_repo = AsyncMock()
        gen = JournalImageGenerator(
            api_key="test-key", gcs_bucket="my-bucket", cost_repo=cost_repo
        )

        fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with (
            patch.object(gen, "_call_imagen_api", return_value=fake_image),
            patch.object(gen, "_upload_to_gcs", return_value="https://storage.googleapis.com/my-bucket/img.png") as mock_upload,
        ):
            url = await gen.generate("Entry", "aurora")

        assert url == "https://storage.googleapis.com/my-bucket/img.png"
        mock_upload.assert_called_once()

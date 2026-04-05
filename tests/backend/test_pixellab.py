"""Unit tests for the PixelLab API client."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.world.pixellab_client import (
    ALLOWED_AGENTS,
    MAX_CONCURRENCY,
    PixelLabClient,
)


@pytest.fixture()
def mock_cost_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.add_cost = AsyncMock(return_value=MagicMock(id=1))
    return repo


@pytest.fixture()
def style_guide_path(tmp_path):
    guide = tmp_path / "style_guide.txt"
    guide.write_text("Test style: 16-bit pixel art, 1px outline.")
    return guide


@pytest.fixture()
def assets_dir(tmp_path):
    d = tmp_path / "assets"
    d.mkdir()
    return d


@pytest.fixture()
def client(mock_cost_repo, style_guide_path, assets_dir) -> PixelLabClient:
    return PixelLabClient(
        api_key="test-key",
        cost_repo=mock_cost_repo,
        style_guide_path=style_guide_path,
        assets_dir=assets_dir,
    )


def _mock_api_response(image_url: str = "https://pixellab.ai/img/test.png"):
    """Create a mock httpx response for the PixelLab API."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"image_url": image_url}
    return resp


def _mock_image_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"\x89PNG\r\n\x1a\n"  # minimal PNG header
    resp.raise_for_status = MagicMock()
    return resp


class TestStyleGuide:
    """Style guide is automatically appended to every prompt."""

    async def test_style_guide_appended_to_prompt(self, client):
        """The style guide text must appear in the prompt sent to the API."""
        captured_payloads = []

        async def mock_post(url, json, headers):
            captured_payloads.append(json)
            return _mock_api_response()

        async def mock_get(url):
            return _mock_image_response()

        with patch("core.world.pixellab_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post = mock_post
            mock_http.get = mock_get
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            await client.generate_asset(
                prompt="A small desk",
                style="object",
                size="32x32",
                agent_id="aurora",
            )

        assert len(captured_payloads) == 1
        sent_prompt = captured_payloads[0]["prompt"]
        assert "Test style: 16-bit pixel art, 1px outline." in sent_prompt
        assert "A small desk" in sent_prompt


class TestCostTracking:
    """Every generation logs a cost event."""

    async def test_cost_logged_per_generation(self, client, mock_cost_repo):
        with patch("core.world.pixellab_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=_mock_api_response())
            mock_http.get = AsyncMock(return_value=_mock_image_response())
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            await client.generate_asset(
                prompt="A chair",
                style="object",
                size="32x32",
                agent_id="rex",
            )

        mock_cost_repo.add_cost.assert_called_once()
        cost_arg = mock_cost_repo.add_cost.call_args[0][0]
        assert cost_arg.agent_id == "rex"
        assert cost_arg.cost_type == "pixellab_generation"
        assert cost_arg.amount == Decimal("0.01")
        assert cost_arg.details["style"] == "object"


class TestCaching:
    """Identical prompts return cached results without calling the API."""

    async def test_cache_hit_returns_stored_asset(self, client):
        api_call_count = 0

        async def mock_post(url, json, headers):
            nonlocal api_call_count
            api_call_count += 1
            return _mock_api_response()

        with patch("core.world.pixellab_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post = mock_post
            mock_http.get = AsyncMock(return_value=_mock_image_response())
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result1 = await client.generate_asset(
                prompt="A lamp",
                style="object",
                size="32x32",
                agent_id="aurora",
            )
            result2 = await client.generate_asset(
                prompt="A lamp",
                style="object",
                size="32x32",
                agent_id="aurora",
            )

        assert api_call_count == 1
        assert result1["asset_id"] == result2["asset_id"]


class TestAccessRestriction:
    """Only allowed agents can generate assets."""

    async def test_disallowed_agent_raises_error(self, client):
        with pytest.raises(PermissionError, match="not allowed"):
            await client.generate_asset(
                prompt="A desk",
                style="object",
                size="32x32",
                agent_id="sentinel",
            )

    async def test_allowed_agents_accepted(self, client):
        """All agents in ALLOWED_AGENTS should pass access check."""
        for agent in ALLOWED_AGENTS:
            # Just test validation doesn't raise — no API call needed
            PixelLabClient._validate_access(agent)

    async def test_none_agent_id_allowed(self, client):
        """None agent_id (anonymous/bootstrap) should be allowed."""
        PixelLabClient._validate_access(None)


class TestBatchConcurrency:
    """Batch generation respects the Tier 2 concurrency limit."""

    async def test_batch_respects_concurrency_limit(self, client):
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def tracking_call_api(*args, **kwargs):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            try:
                await asyncio.sleep(0.01)  # simulate API latency
                return {"image_url": "https://pixellab.ai/img/test.png"}
            finally:
                async with lock:
                    current_concurrent -= 1

        client._call_api = tracking_call_api

        with patch.object(client, "_download_image", new_callable=AsyncMock):
            requests = [
                {
                    "prompt": f"Item {i}",
                    "style": "object",
                    "size": "32x32",
                    "agent_id": "aurora",
                }
                for i in range(15)
            ]
            results = await client.batch_generate(requests)

        assert len(results) == 15
        assert max_concurrent <= MAX_CONCURRENCY


class TestSpriteSheetValidation:
    """Sprite sheet size must fit within the 400x400 Tier 2 limit."""

    async def test_valid_sprite_sheet(self, client):
        """8 frames of 32x32 = 256x32, fits in 400x400."""
        with patch("core.world.pixellab_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=_mock_api_response())
            mock_http.get = AsyncMock(return_value=_mock_image_response())
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_http

            result = await client.generate_sprite_sheet(
                prompt="Walk cycle",
                frame_count=8,
                frame_size="32x32",
                agent_id="aurora",
            )

        assert "asset_id" in result

    async def test_oversized_sprite_sheet_rejected(self, client):
        """13 frames of 32x32 = 416x32, exceeds 400px width."""
        with pytest.raises(ValueError, match="Sprite sheet too wide"):
            await client.generate_sprite_sheet(
                prompt="Walk cycle",
                frame_count=13,
                frame_size="32x32",
                agent_id="aurora",
            )

    async def test_invalid_size_rejected(self, client):
        with pytest.raises(ValueError, match="exceeds Tier 2 max"):
            await client.generate_asset(
                prompt="Huge image",
                style="portrait",
                size="512x512",
                agent_id="aurora",
            )

    async def test_invalid_style_rejected(self, client):
        with pytest.raises(ValueError, match="Invalid style"):
            await client.generate_asset(
                prompt="A thing",
                style="watercolor",
                size="32x32",
                agent_id="aurora",
            )

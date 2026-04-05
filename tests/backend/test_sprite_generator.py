"""Unit tests for the sprite sheet generator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.world.sprite_generator import (
    AGENT_ANIMATIONS,
    ALPHA_ANIMATIONS,
    MAIN_AGENTS,
    SpriteGenerator,
)


@pytest.fixture()
def mock_pixellab(tmp_path):
    """Create a mock PixelLabClient."""
    call_count = 0

    async def fake_generate_asset(prompt, style, size, agent_id=None, **kw):
        nonlocal call_count
        call_count += 1
        path = tmp_path / "gen" / f"asset_{call_count}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG")
        return {
            "image_url": f"https://pixellab.ai/img/{call_count}.png",
            "asset_id": f"id_{call_count}",
            "local_path": str(path),
        }

    async def fake_generate_sprite_sheet(
        prompt, frame_count, frame_size, agent_id=None, **kw
    ):
        nonlocal call_count
        call_count += 1
        path = tmp_path / "gen" / f"sheet_{call_count}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG")
        return {
            "image_url": f"https://pixellab.ai/img/{call_count}.png",
            "asset_id": f"id_{call_count}",
            "local_path": str(path),
        }

    client = AsyncMock()
    client.generate_asset = AsyncMock(side_effect=fake_generate_asset)
    client.generate_sprite_sheet = AsyncMock(
        side_effect=fake_generate_sprite_sheet
    )
    return client


@pytest.fixture()
def sprites_dir(tmp_path):
    d = tmp_path / "sprites"
    d.mkdir()
    return d


@pytest.fixture()
def portraits_dir(tmp_path):
    d = tmp_path / "portraits"
    d.mkdir()
    return d


@pytest.fixture()
def generator(mock_pixellab, sprites_dir, portraits_dir):
    return SpriteGenerator(
        pixellab=mock_pixellab,
        sprites_dir=sprites_dir,
        portraits_dir=portraits_dir,
    )


class TestGenerateAgent:
    async def test_generates_sprite_sheet_for_agent(
        self, generator, mock_pixellab, sprites_dir
    ):
        meta = await generator.generate_agent("vera")
        assert meta["agent_id"] == "vera"
        assert meta["frame_size"] == 32
        assert meta["frame_count"] == len(AGENT_ANIMATIONS)
        assert "idle" in meta["animations"]
        assert "talking" in meta["animations"]
        mock_pixellab.generate_sprite_sheet.assert_called_once()

    async def test_metadata_written_to_disk(self, generator, sprites_dir):
        await generator.generate_agent("rex")
        metadata_path = sprites_dir / "rex" / "metadata.json"
        assert metadata_path.exists()
        meta = json.loads(metadata_path.read_text())
        assert meta["agent_id"] == "rex"

    async def test_skips_when_cached(
        self, generator, mock_pixellab, sprites_dir
    ):
        # Pre-create cache
        agent_dir = sprites_dir / "vera"
        agent_dir.mkdir(parents=True)
        meta = {"agent_id": "vera", "cached": True}
        (agent_dir / "metadata.json").write_text(json.dumps(meta))
        (agent_dir / "spritesheet.png").write_bytes(b"\x89PNG")

        result = await generator.generate_agent("vera")
        assert result["cached"] is True
        mock_pixellab.generate_sprite_sheet.assert_not_called()


class TestGenerateAlpha:
    async def test_generates_24x24_sprite_sheet(
        self, generator, mock_pixellab
    ):
        meta = await generator.generate_alpha()
        assert meta["agent_id"] == "alpha"
        assert meta["frame_size"] == 24
        assert meta["frame_count"] == len(ALPHA_ANIMATIONS)
        assert "idle" in meta["animations"]
        assert "sleeping" in meta["animations"]

    async def test_skips_when_cached(
        self, generator, mock_pixellab, sprites_dir
    ):
        agent_dir = sprites_dir / "alpha"
        agent_dir.mkdir(parents=True)
        meta = {"agent_id": "alpha", "cached": True}
        (agent_dir / "metadata.json").write_text(json.dumps(meta))
        (agent_dir / "spritesheet.png").write_bytes(b"\x89PNG")

        result = await generator.generate_alpha()
        assert result["cached"] is True
        mock_pixellab.generate_sprite_sheet.assert_not_called()


class TestGeneratePortrait:
    async def test_generates_portrait(
        self, generator, mock_pixellab, portraits_dir
    ):
        result = await generator.generate_portrait("vera")
        assert result["agent_id"] == "vera"
        mock_pixellab.generate_asset.assert_called_once()
        call_kwargs = mock_pixellab.generate_asset.call_args
        assert call_kwargs.kwargs.get("size") == "256x256" or (
            call_kwargs[1].get("size") == "256x256"
        )

    async def test_skips_cached_portrait(
        self, generator, mock_pixellab, portraits_dir
    ):
        (portraits_dir / "vera.png").write_bytes(b"\x89PNG")
        await generator.generate_portrait("vera")
        mock_pixellab.generate_asset.assert_not_called()


class TestGenerateAll:
    async def test_generates_all_8_entities(self, generator, mock_pixellab):
        results = await generator.generate_all()
        # 7 main agents + 1 alpha = 8
        assert len(results) == 8
        agent_ids = [r["agent_id"] for r in results]
        for agent_id in MAIN_AGENTS:
            assert agent_id in agent_ids
        assert "alpha" in agent_ids

    async def test_generates_portraits_for_main_agents(
        self, generator, mock_pixellab
    ):
        await generator.generate_all()
        # 7 sprite sheets + 1 alpha sheet = 8 sprite_sheet calls
        assert mock_pixellab.generate_sprite_sheet.call_count == 8
        # 7 portraits = 7 generate_asset calls
        assert mock_pixellab.generate_asset.call_count == 7


class TestCacheCheck:
    def test_not_cached_initially(self, generator):
        assert generator.is_cached("vera") is False

    def test_cached_when_files_exist(self, generator, sprites_dir):
        agent_dir = sprites_dir / "vera"
        agent_dir.mkdir(parents=True)
        (agent_dir / "metadata.json").write_text("{}")
        (agent_dir / "spritesheet.png").write_bytes(b"\x89PNG")
        assert generator.is_cached("vera") is True

    def test_portrait_not_cached_initially(self, generator):
        assert generator.is_portrait_cached("vera") is False

    def test_portrait_cached_when_exists(self, generator, portraits_dir):
        (portraits_dir / "vera.png").write_bytes(b"\x89PNG")
        assert generator.is_portrait_cached("vera") is True

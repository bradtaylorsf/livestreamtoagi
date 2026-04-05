"""Unit tests for the office tile generator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.world.office_generator import OfficeGenerator


@pytest.fixture()
def mock_pixellab(tmp_path):
    """Create a mock PixelLabClient."""
    client = AsyncMock()
    client.generate_asset = AsyncMock(
        side_effect=lambda prompt, style, size, agent_id=None, **kw: {
            "image_url": "https://pixellab.ai/img/test.png",
            "asset_id": "abc123",
            "local_path": str(tmp_path / "assets" / "abc123.png"),
        }
    )
    return client


@pytest.fixture()
def layout_path(tmp_path):
    """Create a minimal office layout for testing."""
    layout = {
        "grid": {"width": 10, "height": 8, "tile_size": 32},
        "tile_types": {
            "floor": {"id": 1, "prompt": "Floor tile", "collision": False},
            "wall": {"id": 2, "prompt": "Wall tile", "collision": True},
            "desk": {"id": 3, "prompt": "Desk tile", "collision": True},
            "chair": {"id": 4, "prompt": "Chair tile", "collision": False},
        },
        "areas": {
            "desk_vera": {"x": 2, "y": 2, "width": 2, "height": 1},
            "meeting_area": {"x": 6, "y": 2, "width": 3, "height": 2},
        },
    }
    path = tmp_path / "office_layout.json"
    path.write_text(json.dumps(layout))
    return path


@pytest.fixture()
def output_dir(tmp_path):
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture()
def generator(mock_pixellab, layout_path, output_dir):
    return OfficeGenerator(
        pixellab=mock_pixellab,
        layout_path=layout_path,
        output_dir=output_dir,
    )


class TestLoadLayout:
    def test_loads_layout_json(self, generator):
        layout = generator.load_layout()
        assert layout["grid"]["width"] == 10
        assert layout["grid"]["height"] == 8
        assert "floor" in layout["tile_types"]

    def test_areas_defined(self, generator):
        layout = generator.load_layout()
        assert "desk_vera" in layout["areas"]
        assert "meeting_area" in layout["areas"]


class TestCacheCheck:
    def test_not_cached_when_empty(self, generator):
        assert generator.is_cached() is False

    def test_cached_when_all_tiles_and_tilemap_exist(
        self, generator, output_dir
    ):
        # Create tilemap.json and all tile PNGs
        layout = generator.load_layout()
        (output_dir / "tilemap.json").write_text("{}")
        for tile_key in layout["tile_types"]:
            (output_dir / f"{tile_key}.png").write_bytes(b"\x89PNG")
        assert generator.is_cached() is True

    def test_not_cached_when_tile_missing(self, generator, output_dir):
        layout = generator.load_layout()
        (output_dir / "tilemap.json").write_text("{}")
        # Only create some tiles
        (output_dir / "floor.png").write_bytes(b"\x89PNG")
        assert generator.is_cached() is False


class TestGenerate:
    async def test_generates_tiles_via_pixellab(
        self, generator, mock_pixellab, output_dir
    ):
        # Mock that the generated file exists at the local_path
        async def fake_generate(prompt, style, size, agent_id=None, **kw):
            # Create the file at expected location
            tile_key = prompt.split()[0].lower()  # rough extraction
            path = output_dir / f"abc_{tile_key}.png"
            path.write_bytes(b"\x89PNG")
            return {"image_url": "https://test.png", "local_path": str(path)}

        mock_pixellab.generate_asset = AsyncMock(side_effect=fake_generate)
        tilemap = await generator.generate()

        assert "layers" in tilemap
        assert "tilesets" in tilemap
        assert len(tilemap["layers"]) == 3  # ground, furniture, collision
        assert tilemap["width"] == 10
        assert tilemap["height"] == 8

    async def test_skips_generation_when_cached(
        self, generator, output_dir, mock_pixellab
    ):
        # Pre-create all cached files
        layout = generator.load_layout()
        tilemap_data = {"cached": True, "layers": [], "tilesets": []}
        (output_dir / "tilemap.json").write_text(json.dumps(tilemap_data))
        for tile_key in layout["tile_types"]:
            (output_dir / f"{tile_key}.png").write_bytes(b"\x89PNG")

        result = await generator.generate()
        assert result["cached"] is True
        mock_pixellab.generate_asset.assert_not_called()

    async def test_tilemap_has_areas_in_pixels(self, generator, output_dir):
        # Pre-create tile files so _assemble_tilemap runs
        layout = generator.load_layout()
        for tile_key in layout["tile_types"]:
            (output_dir / f"{tile_key}.png").write_bytes(b"\x89PNG")

        tilemap = await generator.generate()
        areas = tilemap.get("areas", {})
        assert "desk_vera" in areas
        # desk_vera at grid (2,2) with tile_size 32 = pixel (64, 64)
        assert areas["desk_vera"]["x"] == 64
        assert areas["desk_vera"]["y"] == 64


class TestAssembleTilemap:
    def test_walls_on_perimeter(self, generator):
        layout = generator.load_layout()
        tilemap = generator._assemble_tilemap(layout, {})
        ground = tilemap["layers"][0]["data"]
        w = tilemap["width"]
        # Top-left corner is wall (id=2)
        assert ground[0] == 2
        # Interior tile is floor (id=1)
        assert ground[w + 1] == 1

    def test_collision_layer_marks_walls(self, generator):
        layout = generator.load_layout()
        tilemap = generator._assemble_tilemap(layout, {})
        collision = tilemap["layers"][2]["data"]
        w = tilemap["width"]
        # Perimeter has collision
        assert collision[0] == 1
        # Interior floor has no collision
        assert collision[w + 1] == 0

    def test_furniture_placed_in_areas(self, generator):
        layout = generator.load_layout()
        tilemap = generator._assemble_tilemap(layout, {})
        furniture = tilemap["layers"][1]["data"]
        w = tilemap["width"]
        # desk_vera at (2,2) should have desk tile (id=3)
        assert furniture[2 * w + 2] == 3

    def test_tilesets_list(self, generator):
        layout = generator.load_layout()
        tilemap = generator._assemble_tilemap(layout, {})
        tilesets = tilemap["tilesets"]
        names = [ts["name"] for ts in tilesets]
        assert "floor" in names
        assert "wall" in names
        assert "desk" in names

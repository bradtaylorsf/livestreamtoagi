"""Office tile generator using PixelLab for asset creation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.world.pixellab_client import PixelLabClient

logger = logging.getLogger(__name__)

OFFICE_LAYOUT_PATH = Path("config/office_layout.json")
OUTPUT_DIR = Path("frontend/assets/tilesets/office")


class OfficeGenerator:
    """Generates office tileset and tilemap from layout definition via PixelLab."""

    def __init__(
        self,
        pixellab: PixelLabClient,
        layout_path: Path = OFFICE_LAYOUT_PATH,
        output_dir: Path = OUTPUT_DIR,
    ) -> None:
        self._pixellab = pixellab
        self._layout_path = layout_path
        self._output_dir = output_dir

    def load_layout(self) -> dict[str, Any]:
        """Load and return the office layout JSON."""
        return json.loads(self._layout_path.read_text())

    def is_cached(self) -> bool:
        """Check if tilemap and all tile images already exist."""
        tilemap_path = self._output_dir / "tilemap.json"
        if not tilemap_path.exists():
            return False
        layout = self.load_layout()
        for tile_key in layout["tile_types"]:
            if not (self._output_dir / f"{tile_key}.png").exists():
                return False
        return True

    async def generate(self) -> dict[str, Any]:
        """Generate office tiles and assemble tilemap.

        Skips generation if cache is warm. Returns the tilemap dict.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)
        layout = self.load_layout()

        if self.is_cached():
            logger.info("Office tiles cached, skipping generation")
            return json.loads((self._output_dir / "tilemap.json").read_text())

        tile_size = layout["grid"]["tile_size"]

        # Generate each unique tile type via PixelLab
        tile_assets: dict[str, dict[str, Any]] = {}
        for tile_key, tile_def in layout["tile_types"].items():
            tile_path = self._output_dir / f"{tile_key}.png"
            if tile_path.exists():
                logger.info("Tile %s already cached", tile_key)
                tile_assets[tile_key] = {"local_path": str(tile_path)}
                continue

            size_str = f"{tile_size}x{tile_size}"
            result = await self._pixellab.generate_asset(
                prompt=tile_def["prompt"],
                style="tileset",
                size=size_str,
                agent_id="system",
            )
            # Move to expected path
            src = Path(result["local_path"])
            if src != tile_path:
                src.rename(tile_path)
            tile_assets[tile_key] = {"local_path": str(tile_path)}
            logger.info("Generated tile: %s", tile_key)

        tilemap = self._assemble_tilemap(layout, tile_assets)

        tilemap_path = self._output_dir / "tilemap.json"
        tilemap_path.write_text(json.dumps(tilemap, indent=2))
        logger.info("Tilemap written to %s", tilemap_path)

        return tilemap

    def _assemble_tilemap(
        self,
        layout: dict[str, Any],
        tile_assets: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a Tiled-compatible tilemap JSON from layout and assets."""
        grid = layout["grid"]
        w, h = grid["width"], grid["height"]
        tile_size = grid["tile_size"]
        tile_types = layout["tile_types"]
        areas = layout["areas"]

        # Build tile ID lookup
        tile_ids: dict[str, int] = {k: v["id"] for k, v in tile_types.items()}

        # Initialize layers with zeros
        ground = [0] * (w * h)
        furniture = [0] * (w * h)
        collision = [0] * (w * h)

        # Fill ground with floor
        floor_id = tile_ids["floor"]
        wall_id = tile_ids["wall"]
        for y in range(h):
            for x in range(w):
                idx = y * w + x
                if x == 0 or x == w - 1 or y == 0 or y == h - 1:
                    ground[idx] = wall_id
                    collision[idx] = 1
                else:
                    ground[idx] = floor_id

        # Place furniture from areas
        area_tile_map = {
            "desk_vera": "desk",
            "desk_rex": "desk",
            "desk_aurora": "desk",
            "desk_pixel": "desk",
            "desk_fork": "desk",
            "desk_sentinel": "desk",
            "desk_grok": "desk",
            "meeting_area": "meeting_table",
            "whiteboard": "whiteboard",
            "coffee_machine": "coffee_machine",
            "workshop": "workshop_bench",
        }

        for area_name, area_def in areas.items():
            tile_key = area_tile_map.get(area_name)
            if not tile_key:
                continue
            tid = tile_ids.get(tile_key, 0)
            is_collision = tile_types.get(tile_key, {}).get("collision", False)
            ax, ay = area_def["x"], area_def["y"]
            aw, ah = area_def["width"], area_def["height"]
            for dy in range(ah):
                for dx in range(aw):
                    px, py = ax + dx, ay + dy
                    if 0 <= px < w and 0 <= py < h:
                        idx = py * w + px
                        furniture[idx] = tid
                        if is_collision:
                            collision[idx] = 1

        # Add chairs next to desks (one tile south of desk area center)
        chair_id = tile_ids.get("chair", 0)
        for area_name, area_def in areas.items():
            if not area_name.startswith("desk_"):
                continue
            cx = area_def["x"] + area_def["width"] // 2
            cy = area_def["y"] + area_def["height"]
            if 0 <= cx < w and 0 <= cy < h:
                furniture[cy * w + cx] = chair_id

        # Tilesets list for Phaser
        tilesets = [
            {
                "name": tile_key,
                "image": f"{tile_key}.png",
                "tilewidth": tile_size,
                "tileheight": tile_size,
                "firstgid": tile_def["id"],
                "tilecount": 1,
                "imagewidth": tile_size,
                "imageheight": tile_size,
            }
            for tile_key, tile_def in tile_types.items()
        ]

        return {
            "width": w,
            "height": h,
            "tilewidth": tile_size,
            "tileheight": tile_size,
            "orientation": "orthogonal",
            "tilesets": tilesets,
            "layers": [
                {
                    "name": "ground",
                    "type": "tilelayer",
                    "width": w,
                    "height": h,
                    "data": ground,
                },
                {
                    "name": "furniture",
                    "type": "tilelayer",
                    "width": w,
                    "height": h,
                    "data": furniture,
                },
                {
                    "name": "collision",
                    "type": "tilelayer",
                    "width": w,
                    "height": h,
                    "data": collision,
                },
            ],
            "areas": {
                name: {
                    "x": a["x"] * tile_size,
                    "y": a["y"] * tile_size,
                    "width": a["width"] * tile_size,
                    "height": a["height"] * tile_size,
                }
                for name, a in areas.items()
            },
        }

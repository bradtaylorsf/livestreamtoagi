"""PixelLab API client for generating pixel art assets."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from core.models import CostEventCreate

if TYPE_CHECKING:
    from core.repos.cost_repo import CostRepo

logger = logging.getLogger(__name__)

STYLE_OPTIONS = frozenset(
    {"tileset", "sprite", "sprite_sheet", "object", "decoration", "portrait"}
)

SIZE_OPTIONS: dict[str, tuple[int, int]] = {
    "16x16": (16, 16),
    "32x32": (32, 32),
    "64x64": (64, 64),
    "128x128": (128, 128),
    "256x256": (256, 256),
}

MAX_DIMENSION = 400  # Tier 2 plan limit
MAX_CONCURRENCY = 10  # Tier 2 concurrent generation limit
ALLOWED_AGENTS = frozenset({"aurora", "rex", "system"})

PIXELLAB_API_URL = "https://api.pixellab.ai/v1/generate"
# TODO: PixelLab is subscription-based (Tier 2 plan) — no per-call cost from API.
# This amortized estimate should be replaced with real plan cost / generation count
# once we have usage data. See also: PixelLab MCP tools for actual API structure.
COST_PER_GENERATION = Decimal("0.01")


class PixelLabError(Exception):
    """Raised when PixelLab API returns an error."""


class PixelLabClient:
    """Client for generating pixel art assets via the PixelLab API.

    Handles style guide injection, caching, cost tracking, access control,
    and rate limiting (Tier 2: 10 concurrent generations, 400x400 max).
    """

    def __init__(
        self,
        api_key: str,
        cost_repo: CostRepo,
        style_guide_path: str | Path = "config/pixellab_style_guide.txt",
        assets_dir: str | Path = "assets",
    ) -> None:
        self._api_key = api_key
        self._cost_repo = cost_repo
        self._assets_dir = Path(assets_dir)
        self._assets_dir.mkdir(parents=True, exist_ok=True)

        self._style_guide = Path(style_guide_path).read_text().strip()

        self._cache: dict[str, dict[str, Any]] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    @property
    def style_guide(self) -> str:
        return self._style_guide

    async def generate_asset(
        self,
        prompt: str,
        style: str,
        size: str,
        palette: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate a single pixel art asset.

        Returns dict with keys: image_url, asset_id, local_path.
        """
        self._validate_access(agent_id)
        self._validate_style(style)
        width, height = self._validate_size(size)

        full_prompt = f"{prompt}\n\nStyle guide: {self._style_guide}"
        cache_key = self._cache_key(full_prompt, style, size, palette)

        if cache_key in self._cache:
            logger.info("Cache hit for asset %s", cache_key[:12])
            return self._cache[cache_key]

        async with self._semaphore:
            result = await self._call_api(
                full_prompt, style, width, height, palette
            )

        asset_id = cache_key[:16]
        local_path = self._assets_dir / f"{asset_id}.png"

        await self._download_image(result["image_url"], local_path)

        await self._log_cost(agent_id, prompt, style, size)

        entry = {
            "image_url": result["image_url"],
            "asset_id": asset_id,
            "local_path": str(local_path),
        }
        self._cache[cache_key] = entry
        return entry

    async def generate_sprite_sheet(
        self,
        prompt: str,
        frame_count: int,
        frame_size: str,
        palette: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate a sprite sheet with multiple frames.

        Validates that frame_count * frame_width and frame_height
        both fit within the 400x400 Tier 2 limit.
        """
        frame_w, frame_h = self._validate_size(frame_size)
        total_width = frame_count * frame_w
        if total_width > MAX_DIMENSION:
            raise ValueError(
                f"Sprite sheet too wide: {frame_count} frames * {frame_w}px = "
                f"{total_width}px (max {MAX_DIMENSION}px)"
            )
        if frame_h > MAX_DIMENSION:
            raise ValueError(
                f"Frame height {frame_h}px exceeds max {MAX_DIMENSION}px"
            )

        total_size = f"{total_width}x{frame_h}"
        sheet_prompt = (
            f"{prompt}\nSprite sheet: {frame_count} frames, "
            f"each {frame_size}, arranged horizontally"
        )
        return await self.generate_asset(
            sheet_prompt, "sprite_sheet", total_size, palette, agent_id
        )

    async def batch_generate(
        self, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Generate multiple assets concurrently (respects Tier 2 limit).

        Each request dict should have keys matching generate_asset params:
        prompt, style, size, and optionally palette, agent_id.
        """
        tasks = [self.generate_asset(**req) for req in requests]
        return list(await asyncio.gather(*tasks))

    # ── Validation ──────────────────────────────────────────

    @staticmethod
    def _validate_access(agent_id: str | None) -> None:
        if agent_id is not None and agent_id not in ALLOWED_AGENTS:
            raise PermissionError(
                f"Agent '{agent_id}' is not allowed to generate assets. "
                f"Allowed: {sorted(ALLOWED_AGENTS)}"
            )

    @staticmethod
    def _validate_style(style: str) -> None:
        if style not in STYLE_OPTIONS:
            raise ValueError(
                f"Invalid style '{style}'. Valid: {sorted(STYLE_OPTIONS)}"
            )

    @staticmethod
    def _validate_size(size: str) -> tuple[int, int]:
        if size in SIZE_OPTIONS:
            return SIZE_OPTIONS[size]
        # Support computed sizes like "256x32" from sprite sheet generation
        try:
            w_str, h_str = size.split("x")
            w, h = int(w_str), int(h_str)
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"Invalid size '{size}'. Supported: {sorted(SIZE_OPTIONS)} "
                f"or WxH format"
            ) from exc
        if w > MAX_DIMENSION or h > MAX_DIMENSION:
            raise ValueError(
                f"Size {size} exceeds Tier 2 max {MAX_DIMENSION}x{MAX_DIMENSION}"
            )
        if w <= 0 or h <= 0:
            raise ValueError(f"Size dimensions must be positive: {size}")
        return w, h

    # ── Internal helpers ────────────────────────────────────

    @staticmethod
    def _cache_key(
        prompt: str, style: str, size: str, palette: str | None
    ) -> str:
        raw = f"{prompt}|{style}|{size}|{palette or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _call_api(
        self,
        prompt: str,
        style: str,
        width: int,
        height: int,
        palette: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "style": style,
            "width": width,
            "height": height,
        }
        if palette:
            payload["palette"] = palette

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                PIXELLAB_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )

        if resp.status_code != 200:
            raise PixelLabError(
                f"PixelLab API error {resp.status_code}: {resp.text}"
            )
        return resp.json()

    async def _download_image(self, url: str, path: Path) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        path.write_bytes(resp.content)

    async def _log_cost(
        self,
        agent_id: str | None,
        prompt: str,
        style: str,
        size: str,
    ) -> None:
        await self._cost_repo.add_cost(
            CostEventCreate(
                agent_id=agent_id or "system",
                cost_type="pixellab_generation",
                amount=COST_PER_GENERATION,
                details={"prompt": prompt, "style": style, "size": size},
            )
        )

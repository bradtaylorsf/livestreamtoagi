"""Headless BlueMap screenshot capture for ``RefinementLoop`` (issue #875).

The refinement loop's vision-comparison step needs an actual screenshot of
the built structure to score against the source blueprint image. We use
the BlueMap Paper plugin: drop the plugin into ``minecraft-server/plugins/``,
restart the server, and BlueMap exposes a live HTTP web map at
``http://localhost:8100``. This module drives a headless Chromium via
Playwright to load a deterministic permalink URL centered on the build,
waits for the BlueMap canvas to render, and captures a PNG.

Two pure helpers — :func:`compute_script_extents` and
:func:`_build_permalink_url` — are unit-testable without Playwright. The
async :func:`capture_build_screenshot` is the production entry point.

See ``docker/minecraft-server/README.md`` for plugin installation steps.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable

from core.minecraft.build_script import BuildScript

logger = logging.getLogger(__name__)

ScreenshotFn = Callable[[BuildScript], Awaitable[bytes]]

DEFAULT_BLUEMAP_WORLD = "world"
DEFAULT_BLUEMAP_ZOOM = 4
DEFAULT_BLUEMAP_TIMEOUT_SECONDS = 15.0
DEFAULT_VIEWPORT = (1280, 720)


def compute_script_extents(script: BuildScript) -> tuple[int, int, int, int, int, int]:
    """Return ``(min_x, min_y, min_z, max_x, max_y, max_z)`` over ``script.commands``.

    Falls back to a 1×1×1 box at ``script.origin`` when the script has no
    placement commands (only ``wait`` entries, etc.) so callers always get
    valid coordinates to aim the camera at.
    """
    xs: list[int] = []
    ys: list[int] = []
    zs: list[int] = []
    for cmd in script.commands:
        if cmd.kind == "wait":
            continue
        xs.append(cmd.position.x)
        ys.append(cmd.position.y)
        zs.append(cmd.position.z)
        if cmd.region_to is not None:
            xs.append(cmd.region_to.x)
            ys.append(cmd.region_to.y)
            zs.append(cmd.region_to.z)
    if not xs:
        ox, oy, oz = script.origin.x, script.origin.y, script.origin.z
        return ox, oy, oz, ox, oy, oz
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _script_centroid(script: BuildScript) -> tuple[int, int, int]:
    min_x, min_y, min_z, max_x, max_y, max_z = compute_script_extents(script)
    return (
        (min_x + max_x) // 2,
        (min_y + max_y) // 2,
        (min_z + max_z) // 2,
    )


def _build_permalink_url(
    *,
    bluemap_url: str,
    world_name: str,
    cx: int,
    cy: int,
    cz: int,
    zoom: int,
) -> str:
    """Construct a deterministic BlueMap permalink hash URL.

    The hash format roughly follows BlueMap's web-app convention:
    ``#world:flat:x,y,z:zoom:tiltX:rotX:rotY:rotZ:perspective``. We use
    ``flat`` perspective so the camera shows an isometric-style top-down
    view that compares cleanly against the source blueprint image.
    """
    base = bluemap_url.rstrip("/")
    return f"{base}/#{world_name}:flat:{cx},{cy},{cz}:{zoom}:0:0:0:0:flat"


async def capture_build_screenshot(
    *,
    script: BuildScript,
    bluemap_url: str,
    world_name: str = DEFAULT_BLUEMAP_WORLD,
    zoom: int = DEFAULT_BLUEMAP_ZOOM,
    timeout_seconds: float = DEFAULT_BLUEMAP_TIMEOUT_SECONDS,
    viewport: tuple[int, int] = DEFAULT_VIEWPORT,
) -> bytes:
    """Open BlueMap centered on the build, capture a PNG of the canvas.

    Imported lazily so unit tests can exercise the URL/centroid helpers
    without requiring Playwright. Raises ``RuntimeError`` if Playwright
    is not installed.
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed; install via `uv pip install -e \".[render]\"`"
        ) from exc

    cx, cy, cz = _script_centroid(script)
    url = _build_permalink_url(
        bluemap_url=bluemap_url,
        world_name=world_name,
        cx=cx,
        cy=cy,
        cz=cz,
        zoom=zoom,
    )
    width, height = viewport

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport={"width": width, "height": height})
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded")
                # BlueMap renders into a <canvas> inside .bluemap-container.
                # We wait for the canvas selector but fall back to a small
                # delay if BlueMap's class name differs across versions.
                try:
                    await page.wait_for_selector(
                        "canvas",
                        timeout=int(timeout_seconds * 1000),
                        state="attached",
                    )
                except Exception:
                    logger.warning(
                        "BlueMap canvas not detected at %s within %ss; capturing anyway",
                        url,
                        timeout_seconds,
                    )
                shot: bytes = await page.screenshot(type="png", full_page=False)
                return shot
            finally:
                await context.close()
        finally:
            await browser.close()


def bluemap_screenshot_fn_from_env() -> ScreenshotFn | None:
    """Return a ``ScreenshotFn`` if ``BLUEMAP_URL`` is set, else ``None``.

    Reads:
      - ``BLUEMAP_URL`` (required) — e.g. ``http://localhost:8100``
      - ``BLUEMAP_WORLD`` (optional, default ``world``)
      - ``BLUEMAP_ZOOM`` (optional, default ``4``)
      - ``BLUEMAP_TIMEOUT_SECONDS`` (optional, default ``15``)
    """
    url = os.environ.get("BLUEMAP_URL", "").strip()
    if not url:
        return None
    world = os.environ.get("BLUEMAP_WORLD", DEFAULT_BLUEMAP_WORLD).strip() or DEFAULT_BLUEMAP_WORLD
    try:
        zoom = int(os.environ.get("BLUEMAP_ZOOM", str(DEFAULT_BLUEMAP_ZOOM)))
    except ValueError:
        logger.warning("BLUEMAP_ZOOM is not an int; using default %d", DEFAULT_BLUEMAP_ZOOM)
        zoom = DEFAULT_BLUEMAP_ZOOM
    try:
        timeout_seconds = float(
            os.environ.get("BLUEMAP_TIMEOUT_SECONDS", str(DEFAULT_BLUEMAP_TIMEOUT_SECONDS))
        )
    except ValueError:
        logger.warning(
            "BLUEMAP_TIMEOUT_SECONDS is not a float; using default %s",
            DEFAULT_BLUEMAP_TIMEOUT_SECONDS,
        )
        timeout_seconds = DEFAULT_BLUEMAP_TIMEOUT_SECONDS

    async def _fn(script: BuildScript) -> bytes:
        return await capture_build_screenshot(
            script=script,
            bluemap_url=url,
            world_name=world,
            zoom=zoom,
            timeout_seconds=timeout_seconds,
        )

    return _fn


__all__ = [
    "DEFAULT_BLUEMAP_TIMEOUT_SECONDS",
    "DEFAULT_BLUEMAP_WORLD",
    "DEFAULT_BLUEMAP_ZOOM",
    "ScreenshotFn",
    "bluemap_screenshot_fn_from_env",
    "capture_build_screenshot",
    "compute_script_extents",
]

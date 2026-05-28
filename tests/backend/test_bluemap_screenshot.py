"""Tests for ``core.minecraft.bluemap_screenshot`` (issue #875).

Covers the pure helpers (extents, centroid, permalink URL) plus the
async ``capture_build_screenshot`` flow via a fake Playwright injected
through ``sys.modules``. A live integration smoke is gated on
``BLUEMAP_URL`` + ``MC_LIVE_RCON_HOST`` so headless CI lanes skip it.
"""

from __future__ import annotations

import os
import sys
import types
from typing import Any

import pytest

from core.agents.build_intent import SizeClass, StructureType
from core.minecraft.bluemap_screenshot import (
    DEFAULT_BLUEMAP_WORLD,
    _build_permalink_url,
    bluemap_screenshot_fn_from_env,
    capture_build_screenshot,
    compute_script_extents,
)
from core.minecraft.build_plan import Position3D
from core.minecraft.build_script import BuildCommand, BuildScript


def _make_script(commands: list[BuildCommand], *, origin: Position3D | None = None) -> BuildScript:
    return BuildScript(
        intent_id="test-intent",
        structure_type=StructureType.cabin,
        size_class=SizeClass.small,
        origin=origin or Position3D(x=10, y=64, z=20),
        commands=commands,
        materials_manifest={},
        total_blocks=0,
        estimated_seconds=0.0,
        source_plan_hash="hash",
        compiler_version=1,
    )


# ─── Pure helpers ─────────────────────────────────────────────────


def test_compute_script_extents_from_setblock_and_fill() -> None:
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=64, z=0),
                block_type="stone",
            ),
            BuildCommand(
                kind="fill",
                position=Position3D(x=4, y=64, z=4),
                region_to=Position3D(x=8, y=68, z=8),
                block_type="oak_planks",
            ),
            # wait commands must be ignored.
            BuildCommand(
                kind="wait",
                position=Position3D(x=999, y=999, z=999),
                wait_seconds=0.1,
            ),
        ]
    )
    assert compute_script_extents(script) == (0, 64, 0, 8, 68, 8)


def test_compute_script_extents_falls_back_to_origin_when_no_blocks() -> None:
    script = _make_script(
        [
            BuildCommand(
                kind="wait",
                position=Position3D(x=0, y=0, z=0),
                wait_seconds=0.1,
            ),
        ],
        origin=Position3D(x=5, y=70, z=15),
    )
    assert compute_script_extents(script) == (5, 70, 15, 5, 70, 15)


def test_build_permalink_url_is_deterministic() -> None:
    url = _build_permalink_url(
        bluemap_url="http://localhost:8100/",
        world_name="world",
        cx=10,
        cy=64,
        cz=20,
        zoom=4,
    )
    assert url == "http://localhost:8100/#world:flat:10,64,20:4:0:0:0:0:flat"

    # Trailing slash on the base must not double up.
    url2 = _build_permalink_url(
        bluemap_url="http://localhost:8100",
        world_name="overworld",
        cx=-3,
        cy=72,
        cz=128,
        zoom=2,
    )
    assert url2 == "http://localhost:8100/#overworld:flat:-3,72,128:2:0:0:0:0:flat"


# ─── Env-driven factory ───────────────────────────────────────────


def test_bluemap_screenshot_fn_from_env_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BLUEMAP_URL", raising=False)
    assert bluemap_screenshot_fn_from_env() is None


def test_bluemap_screenshot_fn_from_env_returns_callable_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLUEMAP_URL", "http://localhost:8100")
    fn = bluemap_screenshot_fn_from_env()
    assert fn is not None
    assert callable(fn)


# ─── async capture flow with fake Playwright ──────────────────────


class _FakePage:
    def __init__(self) -> None:
        self.last_url: str | None = None

    async def goto(self, url: str, *, wait_until: str = "load") -> None:
        self.last_url = url

    async def wait_for_selector(self, selector: str, *, timeout: int, state: str) -> None:
        return None

    async def screenshot(self, **_: Any) -> bytes:
        return b"\x89PNG\r\n\x1a\nFAKE-CANVAS"


class _FakeContext:
    def __init__(self) -> None:
        self.page = _FakePage()
        self.closed = False

    async def new_page(self) -> _FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self) -> None:
        self.context = _FakeContext()
        self.closed = False

    async def new_context(self, *, viewport: dict[str, int]) -> _FakeContext:
        return self.context

    async def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self) -> None:
        self.browser = _FakeBrowser()

    async def launch(self, *, headless: bool) -> _FakeBrowser:
        return self.browser


class _FakePlaywrightCM:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()

    async def __aenter__(self) -> _FakePlaywrightCM:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _install_fake_playwright(monkeypatch: pytest.MonkeyPatch) -> _FakePlaywrightCM:
    cm = _FakePlaywrightCM()

    def async_playwright() -> _FakePlaywrightCM:
        return cm

    module = types.ModuleType("playwright")
    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = async_playwright  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)
    return cm


@pytest.mark.asyncio
async def test_capture_build_screenshot_returns_canvas_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cm = _install_fake_playwright(monkeypatch)
    script = _make_script(
        [
            BuildCommand(
                kind="fill",
                position=Position3D(x=10, y=64, z=20),
                region_to=Position3D(x=18, y=70, z=28),
                block_type="oak_log",
            ),
        ],
        origin=Position3D(x=10, y=64, z=20),
    )

    result = await capture_build_screenshot(
        script=script,
        bluemap_url="http://localhost:8100",
        world_name=DEFAULT_BLUEMAP_WORLD,
        zoom=3,
        timeout_seconds=0.01,
    )

    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    # Centroid of (10..18, 64..70, 20..28) = (14, 67, 24)
    assert cm.chromium.browser.context.page.last_url == (
        "http://localhost:8100/#world:flat:14,67,24:3:0:0:0:0:flat"
    )
    assert cm.chromium.browser.context.closed is True
    assert cm.chromium.browser.closed is True


@pytest.mark.asyncio
async def test_capture_build_screenshot_raises_when_playwright_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ensure import fails.
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=0, z=0),
                block_type="stone",
            )
        ]
    )
    with pytest.raises(RuntimeError, match="playwright is not installed"):
        await capture_build_screenshot(script=script, bluemap_url="http://localhost:8100")


# ─── Optional live smoke ──────────────────────────────────────────


@pytest.mark.skipif(
    not (os.environ.get("MC_LIVE_RCON_HOST") and os.environ.get("BLUEMAP_URL")),
    reason="set MC_LIVE_RCON_HOST and BLUEMAP_URL to run against a real server+map",
)
@pytest.mark.asyncio
async def test_live_bluemap_screenshot_is_png() -> None:  # pragma: no cover - live path
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=64, z=0),
                block_type="stone",
            )
        ]
    )
    result = await capture_build_screenshot(
        script=script,
        bluemap_url=os.environ["BLUEMAP_URL"],
    )
    assert result.startswith(b"\x89PNG\r\n\x1a\n")

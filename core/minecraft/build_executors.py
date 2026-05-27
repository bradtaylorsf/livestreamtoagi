"""Build executors for the ``RefinementLoop`` (issue #874).

A build executor is any ``async def __call__(script: BuildScript) -> bytes``
matching the ``BuildExecutor`` protocol in
:mod:`core.minecraft.build_refinement_loop`. The default
``screenshotting_build_executor`` is a placeholder that just returns a
1×1 PNG; the loop is therefore meaningless without a real executor.

This module provides :class:`RconBuildExecutor`, which connects to a live
Minecraft server via RCON, sends each compiled :class:`BuildCommand`, and
returns a screenshot (or the default placeholder if no screenshot hook is
wired — issue #875 plugs that in).

Two helpers — :func:`normalize_block` and :func:`command_to_minecraft` —
are exported here so ``scripts/build_in_minecraft.py`` and the executor
share one normalizer (no drift between CLI and agent paths).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from core.minecraft.build_refinement_loop import DEFAULT_BUILD_EXECUTOR_PNG
from core.minecraft.build_script import BuildCommand, BuildScript

logger = logging.getLogger(__name__)


def normalize_block(name: str | None) -> str:
    """Convert any block-name shape into a Minecraft snake_case id.

    Gemini sometimes emits display names like ``"Stone Bricks"`` or
    ``"Dark Oak Planks"``. Minecraft commands need ``stone_bricks`` /
    ``dark_oak_planks``. We also drop any leading ``minecraft:`` so the
    caller can add it back consistently.
    """
    if not name:
        return "stone"
    n = name.strip().lower()
    if n.startswith("minecraft:"):
        n = n.split(":", 1)[1]
    n = n.replace(" ", "_").replace("-", "_")
    while "__" in n:
        n = n.replace("__", "_")
    return n


def command_to_minecraft(cmd: BuildCommand) -> str | None:
    """Translate one ``BuildCommand`` into a Minecraft command string.

    Returns ``None`` for ``wait`` (handled separately) and for unsupported
    kinds the caller cannot meaningfully translate.
    """
    pos = cmd.position
    if cmd.kind == "setblock":
        block = normalize_block(cmd.block_type)
        return f"/setblock {pos.x} {pos.y} {pos.z} minecraft:{block}"
    if cmd.kind == "fill":
        if cmd.region_to is None:
            return None
        block = normalize_block(cmd.block_type)
        return (
            f"/fill {pos.x} {pos.y} {pos.z} "
            f"{cmd.region_to.x} {cmd.region_to.y} {cmd.region_to.z} "
            f"minecraft:{block}"
        )
    if cmd.kind == "wait":
        return None
    # Structure blocks are placement-by-id; the bot bridge expects a setblock
    # of a structure_block then activation. The CLI placeholder uses a
    # structure_void marker so the chain doesn't crash.
    return f"/setblock {pos.x} {pos.y} {pos.z} minecraft:structure_void"


def async_safe_mcrcon_class() -> type:
    """Return an ``mcrcon.MCRcon``-compatible class safe for worker threads.

    Upstream ``mcrcon.MCRcon.__init__`` calls
    ``signal.signal(signal.SIGALRM, ...)`` unconditionally on non-Windows
    platforms. ``signal.signal`` raises ``ValueError: signal only works in
    main thread of the main interpreter`` when invoked off the main
    thread on macOS Python 3.13 — which is exactly what
    :meth:`RconBuildExecutor.__call__` does via ``asyncio.to_thread``
    (issue #885).

    We import ``MCRcon`` through ``sys.modules`` so the test suite's
    ``monkeypatch.setitem(sys.modules, "mcrcon", ...)`` shim still works.
    The fake class used in tests has no ``_read`` method to override; we
    return it unchanged because it never installs a signal handler.

    For the real ``mcrcon.MCRcon`` we return a subclass that:

    * Re-implements ``__init__`` to mirror the parent's attribute setup
      without the ``signal.signal`` call.
    * Re-implements ``_read`` to use ``socket.settimeout`` instead of
      ``signal.alarm`` so the timeout works in any thread.
    """
    from mcrcon import MCRcon  # type: ignore[import-not-found]

    if not hasattr(MCRcon, "_read"):
        return MCRcon

    class _AsyncSafeMCRcon(MCRcon):  # type: ignore[misc, valid-type]
        def __init__(
            self,
            host: str,
            password: str,
            port: int = 25575,
            tlsmode: int = 0,
            timeout: int = 5,
        ) -> None:
            self.host = host
            self.password = password
            self.port = port
            self.tlsmode = tlsmode
            self.timeout = timeout

        def _read(self, length: int) -> bytes:
            if self.socket is not None and self.timeout:
                self.socket.settimeout(float(self.timeout))
            data = b""
            while len(data) < length:
                chunk = self.socket.recv(length - len(data))
                if not chunk:
                    break
                data += chunk
            return data

    return _AsyncSafeMCRcon


ScreenshotFn = Callable[[BuildScript], Awaitable[bytes]]


class RconBuildExecutor:
    """Execute a ``BuildScript`` against a live Minecraft server via RCON.

    Instantiated by :func:`core.bootstrap.make_refinement_loop` when
    ``RCON_HOST`` / ``RCON_PASSWORD`` are present in the environment, so
    agent-invoked ``propose_new_building`` calls actually place blocks.
    Headless sims without a live server keep using the placeholder.
    """

    def __init__(
        self,
        *,
        rcon_host: str,
        rcon_port: int = 25575,
        rcon_password: str,
        throttle_ms: int = 100,
        screenshot_fn: ScreenshotFn | None = None,
        timeout_seconds: int = 10,
        auto_ground: bool = True,
        foundation: str = "cobblestone",
        terrain_scan_y_start: int = 320,
        terrain_scan_y_floor: int = -64,
    ) -> None:
        self._host = rcon_host
        self._port = rcon_port
        self._password = rcon_password
        self._throttle_ms = max(0, throttle_ms)
        self._screenshot_fn = screenshot_fn
        self._timeout = timeout_seconds
        self._auto_ground = auto_ground
        self._foundation = foundation
        self._terrain_y_start = terrain_scan_y_start
        self._terrain_y_floor = terrain_scan_y_floor

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    async def __call__(self, script: BuildScript) -> bytes:
        sent, skipped = await asyncio.to_thread(self._send_all_sync, script)
        logger.info(
            "RconBuildExecutor: sent=%d skipped=%d host=%s:%d intent=%s",
            sent,
            skipped,
            self._host,
            self._port,
            script.intent_id,
        )
        if self._screenshot_fn is not None:
            try:
                return await self._screenshot_fn(script)
            except Exception:
                logger.exception(
                    "screenshot_fn failed for intent %s; returning placeholder",
                    script.intent_id,
                )
                return DEFAULT_BUILD_EXECUTOR_PNG
        return DEFAULT_BUILD_EXECUTOR_PNG

    def _send_all_sync(self, script: BuildScript) -> tuple[int, int]:
        """Open the RCON connection once and stream every command.

        ``mcrcon`` is synchronous, so this runs in a thread off the
        event loop. ``wait`` commands are converted to a blocking sleep
        because the connection must stay open.

        When ``auto_ground`` is enabled, the first thing we do on the
        open connection is a terrain query at the script's origin column
        to compute the y-offset and emit foundation /fill commands.
        """
        import time as _time

        MCRcon = async_safe_mcrcon_class()

        sent = 0
        skipped = 0
        throttle_seconds = self._throttle_ms / 1000.0
        with MCRcon(self._host, self._password, port=self._port, timeout=self._timeout) as mcr:
            final_script, foundation_cmds = self._apply_auto_ground(script, mcr)
            for foundation in foundation_cmds:
                bare = foundation[1:] if foundation.startswith("/") else foundation
                try:
                    resp = mcr.command(bare)
                    sent += 1
                    logger.debug("RCON foundation -> %s | resp=%r", bare[:120], resp[:160])
                    if resp and "error" in resp.lower():
                        logger.warning("RCON response error: %s", resp.strip()[:200])
                    if throttle_seconds:
                        _time.sleep(throttle_seconds)
                except Exception:
                    logger.exception("RCON foundation command failed: %s", bare[:120])
                    skipped += 1

            for cmd in final_script.commands:
                if cmd.kind == "wait":
                    if cmd.wait_seconds:
                        _time.sleep(cmd.wait_seconds)
                    continue
                text = command_to_minecraft(cmd)
                if text is None:
                    skipped += 1
                    continue
                bare = text[1:] if text.startswith("/") else text
                try:
                    resp = mcr.command(bare)
                    sent += 1
                    logger.debug("RCON cmd -> %s | resp=%r", bare[:120], resp[:160])
                    if resp and "error" in resp.lower():
                        logger.warning("RCON response error: %s", resp.strip()[:200])
                    if throttle_seconds:
                        _time.sleep(throttle_seconds)
                except Exception:
                    logger.exception("RCON command failed: %s", bare[:120])
                    skipped += 1
        return sent, skipped

    def _apply_auto_ground(self, script: BuildScript, mcr: object) -> tuple[BuildScript, list[str]]:
        """Resolve terrain and return (shifted_script, foundation_commands).

        Returns ``(script, [])`` when ``auto_ground`` is disabled so the
        original behavior is preserved byte-for-byte.
        """
        if not self._auto_ground:
            return script, []
        from core.minecraft.terrain import auto_ground_script, make_rcon_block_matcher

        matcher = make_rcon_block_matcher(mcr)
        return auto_ground_script(
            script,
            matcher,
            foundation=self._foundation,
            y_start=self._terrain_y_start,
            y_floor=self._terrain_y_floor,
        )


def rcon_executor_from_env() -> RconBuildExecutor | None:
    """Return an :class:`RconBuildExecutor` if RCON env vars are set, else ``None``.

    Reads ``RCON_HOST`` (required), ``RCON_PASSWORD`` (required), and
    ``RCON_PORT`` (defaults to 25575). Returning ``None`` means the
    caller should keep the placeholder executor — headless sims without
    a live Minecraft stay functional.

    When ``BLUEMAP_URL`` is also set the executor receives a screenshot
    function that captures the live BlueMap canvas after each build
    (issue #875), so the refinement loop's comparison step gets a real
    PNG of the built structure instead of the placeholder.
    """
    host = os.environ.get("RCON_HOST", "").strip()
    password = os.environ.get("RCON_PASSWORD", "")
    if not host or not password:
        return None
    try:
        port = int(os.environ.get("RCON_PORT", "25575"))
    except ValueError:
        logger.warning("RCON_PORT is not an int; falling back to 25575")
        port = 25575
    from core.minecraft.bluemap_screenshot import bluemap_screenshot_fn_from_env

    screenshot_fn = bluemap_screenshot_fn_from_env()
    if screenshot_fn is not None:
        logger.info("RconBuildExecutor: BlueMap screenshot capture enabled")
    return RconBuildExecutor(
        rcon_host=host,
        rcon_port=port,
        rcon_password=password,
        screenshot_fn=screenshot_fn,
    )


__all__ = [
    "RconBuildExecutor",
    "ScreenshotFn",
    "async_safe_mcrcon_class",
    "command_to_minecraft",
    "normalize_block",
    "rcon_executor_from_env",
]

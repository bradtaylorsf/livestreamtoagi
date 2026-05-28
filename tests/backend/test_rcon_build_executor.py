"""Tests for ``RconBuildExecutor`` (issue #874).

Covers:

* Block-name normalization and command translation.
* The executor sends each :class:`BuildCommand` over a mocked
  ``mcrcon.MCRcon`` context manager, with the correct ordering and
  no leading slash.
* ``wait`` commands are honored, unsupported kinds are skipped, and
  throttling is applied.
* ``screenshot_fn`` is awaited when provided; otherwise the deterministic
  placeholder PNG is returned (so #875 can plug in a real screenshot
  later without changing the call site).
* ``rcon_executor_from_env`` returns None when env vars are missing and
  ``make_refinement_loop`` falls back to the placeholder executor.
* Optional live integration smoke (skipped without ``MC_LIVE_RCON_HOST``).
"""

from __future__ import annotations

import os
import sys
import types
from typing import Any

import pytest

from core.agents.build_intent import SizeClass, StructureType
from core.minecraft.build_executors import (
    RconBuildExecutor,
    async_safe_mcrcon_class,
    command_to_minecraft,
    normalize_block,
    rcon_executor_from_env,
)
from core.minecraft.build_plan import Position3D
from core.minecraft.build_refinement_loop import DEFAULT_BUILD_EXECUTOR_PNG
from core.minecraft.build_script import BuildCommand, BuildScript


def _make_script(commands: list[BuildCommand]) -> BuildScript:
    return BuildScript(
        intent_id="test-intent",
        structure_type=StructureType.cabin,
        size_class=SizeClass.small,
        origin=Position3D(x=0, y=64, z=0),
        commands=commands,
        materials_manifest={},
        total_blocks=0,
        estimated_seconds=0.0,
        source_plan_hash="hash",
        compiler_version=1,
    )


class _FakeMCRcon:
    """Drop-in stand-in for ``mcrcon.MCRcon``.

    Records every ``command()`` call. Used as ``mcrcon.MCRcon = _FakeMCRcon``
    so the unit tests can run without a live server.
    """

    instances: list[_FakeMCRcon] = []

    def __init__(self, host: str, password: str, port: int = 25575, timeout: int = 10) -> None:
        self.host = host
        self.password = password
        self.port = port
        self.timeout = timeout
        self.commands: list[str] = []
        self.responses: dict[str, str] = {}
        self.entered = False
        self.exited = False
        _FakeMCRcon.instances.append(self)

    def __enter__(self) -> _FakeMCRcon:
        self.entered = True
        return self

    def __exit__(self, *exc: Any) -> None:
        self.exited = True

    def command(self, text: str) -> str:
        self.commands.append(text)
        return self.responses.get(text, "")


@pytest.fixture
def fake_mcrcon(monkeypatch: pytest.MonkeyPatch) -> type[_FakeMCRcon]:
    _FakeMCRcon.instances.clear()
    module = types.ModuleType("mcrcon")
    module.MCRcon = _FakeMCRcon  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcrcon", module)
    return _FakeMCRcon


# ─── Pure-function translator tests ────────────────────────────────


def test_normalize_block_strips_namespace_and_canonicalizes() -> None:
    assert normalize_block("Stone Bricks") == "stone_bricks"
    assert normalize_block("minecraft:Dark Oak Planks") == "dark_oak_planks"
    assert normalize_block("dark-oak-log") == "dark_oak_log"
    assert normalize_block(None) == "stone"
    assert normalize_block("") == "stone"
    # Collapses doubled underscores from awkward inputs.
    assert normalize_block("Stone  Bricks") == "stone_bricks"


def test_command_to_minecraft_setblock_fill_wait_unsupported() -> None:
    setblock = BuildCommand(
        kind="setblock",
        position=Position3D(x=1, y=2, z=3),
        block_type="Stone Bricks",
    )
    assert command_to_minecraft(setblock) == "/setblock 1 2 3 minecraft:stone_bricks"

    fill = BuildCommand(
        kind="fill",
        position=Position3D(x=0, y=0, z=0),
        region_to=Position3D(x=2, y=2, z=2),
        block_type="oak_planks",
    )
    assert command_to_minecraft(fill) == "/fill 0 0 0 2 2 2 minecraft:oak_planks"

    fill_no_region = BuildCommand(
        kind="fill",
        position=Position3D(x=0, y=0, z=0),
        block_type="oak_planks",
    )
    assert command_to_minecraft(fill_no_region) is None

    wait = BuildCommand(kind="wait", position=Position3D(x=0, y=0, z=0), wait_seconds=0.1)
    assert command_to_minecraft(wait) is None

    structure = BuildCommand(
        kind="structure",
        position=Position3D(x=10, y=10, z=10),
        structure_id="village/plains",
    )
    # Structure kind falls back to a structure_void marker placeholder.
    assert command_to_minecraft(structure) == "/setblock 10 10 10 minecraft:structure_void"


# ─── RconBuildExecutor behavior tests ──────────────────────────────


@pytest.mark.asyncio
async def test_executor_sends_translated_commands_without_leading_slash(
    fake_mcrcon: type[_FakeMCRcon],
) -> None:
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=1, y=2, z=3),
                block_type="Stone Bricks",
            ),
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=0, z=0),
                region_to=Position3D(x=2, y=2, z=2),
                block_type="oak_planks",
            ),
        ]
    )
    executor = RconBuildExecutor(
        rcon_host="127.0.0.1",
        rcon_port=25575,
        rcon_password="pw",
        throttle_ms=0,
        auto_ground=False,
    )

    result = await executor(script)

    assert result == DEFAULT_BUILD_EXECUTOR_PNG
    assert len(fake_mcrcon.instances) == 1
    inst = fake_mcrcon.instances[0]
    assert inst.host == "127.0.0.1"
    assert inst.port == 25575
    assert inst.password == "pw"
    assert inst.entered and inst.exited
    assert inst.commands == [
        "setblock 1 2 3 minecraft:stone_bricks",
        "fill 0 0 0 2 2 2 minecraft:oak_planks",
    ]


@pytest.mark.asyncio
async def test_executor_skips_unsupported_and_honors_wait(
    fake_mcrcon: type[_FakeMCRcon],
) -> None:
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=0, z=0),
                block_type="dirt",
            ),
            BuildCommand(kind="wait", position=Position3D(x=0, y=0, z=0), wait_seconds=0.01),
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=0, z=0),
                block_type="oak_planks",
            ),  # no region_to → translator returns None → skipped
        ]
    )
    executor = RconBuildExecutor(
        rcon_host="127.0.0.1",
        rcon_password="pw",
        throttle_ms=0,
        auto_ground=False,
    )

    await executor(script)

    inst = fake_mcrcon.instances[0]
    assert inst.commands == ["setblock 0 0 0 minecraft:dirt"]


@pytest.mark.asyncio
async def test_executor_returns_screenshot_when_provided(
    fake_mcrcon: type[_FakeMCRcon],
) -> None:
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=0, z=0),
                block_type="dirt",
            )
        ]
    )

    received: dict[str, Any] = {}

    async def screenshot(s: BuildScript) -> bytes:
        received["script"] = s
        return b"\x89PNG-from-bluemap"

    executor = RconBuildExecutor(
        rcon_host="127.0.0.1",
        rcon_password="pw",
        screenshot_fn=screenshot,
        throttle_ms=0,
        auto_ground=False,
    )

    result = await executor(script)
    assert result == b"\x89PNG-from-bluemap"
    # The executor passes the script through to the screenshot fn so
    # BlueMap can derive the camera target from the build's coordinates.
    assert received["script"] is script


@pytest.mark.asyncio
async def test_executor_returns_placeholder_when_screenshot_fn_raises(
    fake_mcrcon: type[_FakeMCRcon],
) -> None:
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=0, z=0),
                block_type="dirt",
            )
        ]
    )

    async def screenshot(_: BuildScript) -> bytes:
        raise RuntimeError("bluemap unreachable")

    executor = RconBuildExecutor(
        rcon_host="127.0.0.1",
        rcon_password="pw",
        screenshot_fn=screenshot,
        throttle_ms=0,
        auto_ground=False,
    )

    result = await executor(script)
    # Build commands still ran; the failure only neutralizes the screenshot.
    assert result == DEFAULT_BUILD_EXECUTOR_PNG


@pytest.mark.asyncio
async def test_executor_logs_warning_on_error_response(
    fake_mcrcon: type[_FakeMCRcon], caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    # Pre-arm responses for the next instance constructed during executor run.
    original_init = _FakeMCRcon.__init__

    def init_with_responses(self: _FakeMCRcon, *args: Any, **kw: Any) -> None:
        original_init(self, *args, **kw)
        self.responses = {"setblock 0 0 0 minecraft:bedrock": "Error: missing permission"}

    fake_mcrcon.__init__ = init_with_responses  # type: ignore[assignment, method-assign]
    try:
        script = _make_script(
            [
                BuildCommand(
                    kind="setblock",
                    position=Position3D(x=0, y=0, z=0),
                    block_type="bedrock",
                )
            ]
        )
        executor = RconBuildExecutor(
            rcon_host="127.0.0.1",
            rcon_password="pw",
            throttle_ms=0,
            auto_ground=False,
        )
        with caplog.at_level(logging.WARNING, logger="core.minecraft.build_executors"):
            await executor(script)
        assert any("RCON response error" in m for m in caplog.messages)
    finally:
        fake_mcrcon.__init__ = original_init  # type: ignore[method-assign]


# ─── Env-driven factory + bootstrap selection ──────────────────────


def test_rcon_executor_from_env_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RCON_HOST", raising=False)
    monkeypatch.delenv("RCON_PASSWORD", raising=False)
    monkeypatch.delenv("RCON_PORT", raising=False)
    assert rcon_executor_from_env() is None


def test_rcon_executor_from_env_constructs_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RCON_HOST", "mc.example.com")
    monkeypatch.setenv("RCON_PASSWORD", "secret")
    monkeypatch.setenv("RCON_PORT", "26000")
    executor = rcon_executor_from_env()
    assert isinstance(executor, RconBuildExecutor)
    assert executor.host == "mc.example.com"
    assert executor.port == 26000


def test_rcon_executor_from_env_invalid_port_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RCON_HOST", "mc.example.com")
    monkeypatch.setenv("RCON_PASSWORD", "secret")
    monkeypatch.setenv("RCON_PORT", "not-a-number")
    monkeypatch.delenv("BLUEMAP_URL", raising=False)
    executor = rcon_executor_from_env()
    assert isinstance(executor, RconBuildExecutor)
    assert executor.port == 25575


def test_rcon_executor_from_env_wires_bluemap_when_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RCON_HOST", "mc.example.com")
    monkeypatch.setenv("RCON_PASSWORD", "secret")
    monkeypatch.setenv("BLUEMAP_URL", "http://localhost:8100")
    executor = rcon_executor_from_env()
    assert isinstance(executor, RconBuildExecutor)
    # Private attribute — but this is the production wiring under test.
    assert executor._screenshot_fn is not None


def test_rcon_executor_from_env_omits_bluemap_when_url_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RCON_HOST", "mc.example.com")
    monkeypatch.setenv("RCON_PASSWORD", "secret")
    monkeypatch.delenv("BLUEMAP_URL", raising=False)
    executor = rcon_executor_from_env()
    assert isinstance(executor, RconBuildExecutor)
    assert executor._screenshot_fn is None


def test_make_refinement_loop_uses_rcon_executor_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.bootstrap import make_refinement_loop
    from core.minecraft.build_executors import RconBuildExecutor as _RconExec

    monkeypatch.setenv("OPENAI_API_KEY", "stub")
    monkeypatch.setenv("GOOGLE_API_KEY", "stub")
    monkeypatch.setenv("RCON_HOST", "mc.example.com")
    monkeypatch.setenv("RCON_PASSWORD", "pw")
    monkeypatch.delenv("RCON_PORT", raising=False)

    loop = make_refinement_loop()
    assert loop is not None
    # _build_executor is private; assert by attribute access since the
    # production wiring is what the test is guarding.
    assert isinstance(loop._build_executor, _RconExec)


def test_make_refinement_loop_uses_placeholder_when_rcon_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.bootstrap import make_refinement_loop
    from core.minecraft.build_refinement_loop import screenshotting_build_executor

    monkeypatch.setenv("OPENAI_API_KEY", "stub")
    monkeypatch.setenv("GOOGLE_API_KEY", "stub")
    monkeypatch.delenv("RCON_HOST", raising=False)
    monkeypatch.delenv("RCON_PASSWORD", raising=False)

    loop = make_refinement_loop()
    assert loop is not None
    assert loop._build_executor is screenshotting_build_executor


# ─── auto-ground integration ───────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_auto_ground_shifts_origin_and_prepends_foundation(
    fake_mcrcon: type[_FakeMCRcon],
) -> None:
    """``auto_ground=True`` issues terrain queries then foundation fills before the build."""

    # Pre-arm the next MCRcon instance with terrain responses.
    original_init = _FakeMCRcon.__init__

    def init_with_responses(self: _FakeMCRcon, *args: Any, **kw: Any) -> None:
        original_init(self, *args, **kw)
        # All "execute if block ... air" queries return "Test passed"
        # except at y=70 → simulates grass at y=70.
        def _command(text: str) -> str:
            self.commands.append(text)
            if text.startswith("execute if block 0 70 0"):
                # any non-air check at y=70 passes for stone
                if "minecraft:stone" in text:
                    return "Test passed"
                return "Test failed"
            if text.startswith("execute if block "):
                # everything else above terrain is air, below is stone
                parts = text.split()
                y = int(parts[4])
                if y > 70:
                    return "Test passed" if "minecraft:air" in text else "Test failed"
                if "minecraft:stone" in text:
                    return "Test passed"
                return "Test failed"
            return ""

        self.command = _command  # type: ignore[method-assign]

    fake_mcrcon.__init__ = init_with_responses  # type: ignore[assignment, method-assign]
    try:
        script = _make_script(
            [
                BuildCommand(
                    kind="fill",
                    position=Position3D(x=0, y=80, z=0),
                    region_to=Position3D(x=4, y=84, z=4),
                    block_type="oak_planks",
                ),
            ],
        )
        # Override origin so dy is non-zero.
        script = script.model_copy(update={"origin": Position3D(x=0, y=80, z=0)})

        executor = RconBuildExecutor(
            rcon_host="127.0.0.1",
            rcon_password="pw",
            throttle_ms=0,
            auto_ground=True,
            foundation="cobblestone",
            terrain_scan_y_start=120,
            terrain_scan_y_floor=0,
        )

        await executor(script)

        inst = fake_mcrcon.instances[0]
        # Last command should be the shifted build command (origin 80 → 71,
        # dy=-9 → build's fill runs from 71..75).
        build_cmds = [c for c in inst.commands if c.startswith("fill 0 ")]
        assert any(c == "fill 0 71 0 4 75 4 minecraft:oak_planks" for c in build_cmds)
    finally:
        fake_mcrcon.__init__ = original_init  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_executor_auto_ground_disabled_skips_terrain_queries(
    fake_mcrcon: type[_FakeMCRcon],
) -> None:
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=64, z=0),
                block_type="dirt",
            )
        ]
    )
    executor = RconBuildExecutor(
        rcon_host="127.0.0.1",
        rcon_password="pw",
        throttle_ms=0,
        auto_ground=False,
    )

    await executor(script)

    inst = fake_mcrcon.instances[0]
    # No "execute if block" queries should appear when auto_ground is off.
    assert not any(c.startswith("execute if block") for c in inst.commands)
    assert inst.commands == ["setblock 0 64 0 minecraft:dirt"]


# ─── #886 multi-fill streaming regression ─────────────────────────


def test_executor_default_throttle_is_protective_for_paper() -> None:
    """Default ``throttle_ms`` must be ≥100ms.

    Regression for #886: at 30ms throttle, multi-/fill BuildScripts sent
    back-to-back over RCON only materialized the first fill on Paper —
    later fills landed at Paper's command queue faster than its tick loop
    could process them and got dropped silently (no "error" in the RCON
    response). 100ms ≈ 2 ticks at 20tps, which is what the field testing
    in the issue confirmed is enough headroom for ``/fill`` to settle.
    """
    executor = RconBuildExecutor(rcon_host="127.0.0.1", rcon_password="pw")
    assert executor._throttle_ms >= 100


@pytest.mark.asyncio
async def test_executor_streams_every_layer_of_multi_fill_build(
    fake_mcrcon: type[_FakeMCRcon],
) -> None:
    """Regression for #886: every ``/fill`` in a multi-layer BuildScript
    must reach the fake RCON connection, not just the first one. Before the
    fix the executor reported ``sent=50 skipped=0`` but only the first
    ``/fill`` actually materialized in the world; this test pins the
    pre-network-layer invariant that all commands are dispatched in order
    with no silent drops.
    """
    fills = [
        BuildCommand(
            kind="fill",
            position=Position3D(x=0, y=y, z=0),
            region_to=Position3D(x=4, y=y, z=4),
            block_type=mat,
        )
        for y, mat in [
            (64, "stone_bricks"),
            (68, "stone_bricks"),
            (72, "oak_planks"),
            (77, "dark_oak_planks"),
        ]
    ]
    script = _make_script(fills)
    executor = RconBuildExecutor(
        rcon_host="127.0.0.1",
        rcon_password="pw",
        throttle_ms=0,
        auto_ground=False,
    )

    await executor(script)

    inst = fake_mcrcon.instances[0]
    assert inst.commands == [
        "fill 0 64 0 4 64 4 minecraft:stone_bricks",
        "fill 0 68 0 4 68 4 minecraft:stone_bricks",
        "fill 0 72 0 4 72 4 minecraft:oak_planks",
        "fill 0 77 0 4 77 4 minecraft:dark_oak_planks",
    ]


def test_auto_ground_shifts_every_layer_not_just_first() -> None:
    """Regression for #886 (suspected root cause 1): the auto-ground shift
    must be applied to every command's y, not just the first one.

    Constructs a 4-layer BuildScript at y=80/84/88/92 with origin y=80,
    runs ``auto_ground_script`` with a matcher that reports terrain_top=63
    (so dy = -16), and asserts every fill ends up shifted by exactly -16.
    """
    from core.minecraft.terrain import auto_ground_script

    fills = [
        BuildCommand(
            kind="fill",
            position=Position3D(x=0, y=y, z=0),
            region_to=Position3D(x=4, y=y, z=4),
            block_type="oak_planks",
        )
        for y in (80, 84, 88, 92)
    ]
    script = _make_script(fills).model_copy(update={"origin": Position3D(x=0, y=80, z=0)})

    def matcher(x: int, y: int, z: int, block_or_tag: str) -> bool:
        # Air above y=63, stone at y=63, anything below also stone.
        if "air" in block_or_tag:
            return y > 63
        if "minecraft:stone" in block_or_tag:
            return y <= 63
        return False

    shifted, foundation_cmds = auto_ground_script(script, matcher)

    # dy = (63 + 1) - 80 = -16; every command's y should drop by 16.
    shifted_ys = [cmd.position.y for cmd in shifted.commands]
    assert shifted_ys == [64, 68, 72, 76]
    region_ys = [cmd.region_to.y for cmd in shifted.commands if cmd.region_to is not None]
    assert region_ys == [64, 68, 72, 76]
    assert shifted.origin.y == 64
    # Foundation perimeter spans terrain_top+1 (=64) to base_y-1 (=63) → empty.
    # (base_y after shift is the new lowest command y, which equals terrain_top+1.)
    assert foundation_cmds == []


# ─── #885 async-safe MCRcon regression ────────────────────────────


def test_async_safe_mcrcon_class_returns_real_mcrcon_subclass() -> None:
    """The helper subclasses the real ``mcrcon.MCRcon`` rather than returning it raw.

    Subclassing is what lets us override ``__init__`` and ``_read`` to skip
    the SIGALRM install that crashes on macOS in worker threads (#885).
    """
    import mcrcon

    cls = async_safe_mcrcon_class()
    assert cls is not mcrcon.MCRcon
    assert issubclass(cls, mcrcon.MCRcon)


def test_async_safe_mcrcon_init_does_not_install_signal_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing the wrapper must not call ``signal.signal(SIGALRM, ...)``."""
    import signal as _signal

    calls: list[tuple[int, Any]] = []

    real_signal = _signal.signal

    def spy(signum: int, handler: Any) -> Any:
        calls.append((signum, handler))
        return real_signal(signum, handler)

    monkeypatch.setattr(_signal, "signal", spy)

    cls = async_safe_mcrcon_class()
    cls("127.0.0.1", "pw", port=25575, timeout=5)

    # Real mcrcon.MCRcon would record (SIGALRM, timeout_handler) here.
    assert not any(sig == _signal.SIGALRM for sig, _ in calls), (
        f"async-safe wrapper unexpectedly installed signal handler: {calls}"
    )


def test_async_safe_mcrcon_constructs_in_non_main_thread() -> None:
    """Regression: ``asyncio.to_thread`` runs ``_send_all_sync`` (and thus the
    MCRcon constructor) in a worker thread. The upstream class crashes there
    on macOS with ``ValueError: signal only works in main thread of the main
    interpreter`` — our wrapper must not.
    """
    import threading

    cls = async_safe_mcrcon_class()
    errors: list[BaseException] = []

    def construct() -> None:
        try:
            cls("127.0.0.1", "pw", port=25575, timeout=5)
        except BaseException as exc:  # noqa: BLE001 — capture for assertion
            errors.append(exc)

    t = threading.Thread(target=construct)
    t.start()
    t.join()

    assert not errors, f"async-safe MCRcon raised in worker thread: {errors!r}"


@pytest.mark.asyncio
async def test_executor_runs_from_event_loop_without_signal_error(
    fake_mcrcon: type[_FakeMCRcon],
) -> None:
    """``await executor(script)`` must succeed when called from an asyncio
    event loop. ``asyncio.to_thread`` dispatches ``_send_all_sync`` to a
    worker thread; the SIGALRM install in upstream mcrcon would raise here
    before #885."""
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=64, z=0),
                block_type="stone",
            )
        ]
    )
    executor = RconBuildExecutor(
        rcon_host="127.0.0.1",
        rcon_password="pw",
        throttle_ms=0,
        auto_ground=False,
    )

    # Must not raise ValueError("signal only works in main thread...").
    await executor(script)


# ─── Optional live smoke (skipped without env var) ─────────────────


@pytest.mark.skipif(
    not os.environ.get("MC_LIVE_RCON_HOST"),
    reason="set MC_LIVE_RCON_HOST/_PORT/_PASSWORD to run against a real server",
)
@pytest.mark.asyncio
async def test_live_rcon_one_block_setblock() -> None:  # pragma: no cover - live path
    host = os.environ["MC_LIVE_RCON_HOST"]
    port = int(os.environ.get("MC_LIVE_RCON_PORT", "25575"))
    password = os.environ["MC_LIVE_RCON_PASSWORD"]
    script = _make_script(
        [
            BuildCommand(
                kind="setblock",
                position=Position3D(x=0, y=64, z=0),
                block_type="stone",
            )
        ]
    )
    executor = RconBuildExecutor(
        rcon_host=host, rcon_port=port, rcon_password=password, throttle_ms=0
    )
    # Should not raise; we don't assert response content because servers
    # differ in their setblock acknowledgements.
    await executor(script)


@pytest.mark.skipif(
    not os.environ.get("MC_LIVE_RCON_HOST"),
    reason="set MC_LIVE_RCON_HOST/_PORT/_PASSWORD to run against a real server",
)
@pytest.mark.asyncio
async def test_live_rcon_multi_layer_fill_materializes_every_layer() -> None:  # pragma: no cover - live path
    """Live regression for #886: every layer of a multi-fill build must
    place blocks. Pre-fix this test would have placed only the y=64 layer.

    The test reserves a 4×4 footprint at a configurable origin (default
    (200,64,200), well clear of spawn), wipes it to air, runs the executor,
    then issues ``execute if block`` checks at the center of each layer.
    """
    from core.minecraft.build_executors import async_safe_mcrcon_class

    host = os.environ["MC_LIVE_RCON_HOST"]
    port = int(os.environ.get("MC_LIVE_RCON_PORT", "25575"))
    password = os.environ["MC_LIVE_RCON_PASSWORD"]
    origin_x = int(os.environ.get("MC_LIVE_TEST_X", "200"))
    origin_z = int(os.environ.get("MC_LIVE_TEST_Z", "200"))

    layers = [
        (64, "stone_bricks"),
        (68, "stone_bricks"),
        (72, "oak_planks"),
        (77, "dark_oak_planks"),
    ]

    # Wipe the test footprint to air first so we don't false-positive on
    # leftover blocks from a previous run.
    MCRcon = async_safe_mcrcon_class()
    with MCRcon(host, password, port=port, timeout=10) as mcr:
        mcr.command(
            f"fill {origin_x} 60 {origin_z} {origin_x + 4} 80 {origin_z + 4} minecraft:air"
        )

    script = _make_script(
        [
            BuildCommand(
                kind="fill",
                position=Position3D(x=origin_x, y=y, z=origin_z),
                region_to=Position3D(x=origin_x + 4, y=y, z=origin_z + 4),
                block_type=mat,
            )
            for y, mat in layers
        ]
    )
    script = script.model_copy(
        update={"origin": Position3D(x=origin_x, y=layers[0][0], z=origin_z)}
    )

    executor = RconBuildExecutor(
        rcon_host=host,
        rcon_port=port,
        rcon_password=password,
        auto_ground=False,
    )
    await executor(script)

    # Probe the center of each layer.
    cx, cz = origin_x + 2, origin_z + 2
    with MCRcon(host, password, port=port, timeout=10) as mcr:
        for y, mat in layers:
            resp = mcr.command(f"execute if block {cx} {y} {cz} minecraft:{mat}")
            assert "passed" in (resp or "").lower(), (
                f"layer y={y} did not materialize: {resp!r}"
            )

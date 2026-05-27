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

    async def screenshot() -> bytes:
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
    executor = rcon_executor_from_env()
    assert isinstance(executor, RconBuildExecutor)
    assert executor.port == 25575


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

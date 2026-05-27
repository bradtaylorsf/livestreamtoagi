"""Tests for ``scripts/build_in_minecraft.py`` auto-ground path (issue #873)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from core.agents.build_intent import SizeClass, StructureType
from core.minecraft.build_plan import Position3D
from core.minecraft.build_script import BuildCommand, BuildScript


class _FakeMCRcon:
    """In-memory ``mcrcon.MCRcon`` stand-in with controllable terrain."""

    instances: list[_FakeMCRcon] = []
    terrain_top: int = 70  # y of the highest non-air block at the queried column

    def __init__(self, host: str, password: str, port: int = 25575, timeout: int = 10) -> None:
        self.host = host
        self.password = password
        self.port = port
        self.timeout = timeout
        self.commands: list[str] = []
        _FakeMCRcon.instances.append(self)

    def __enter__(self) -> _FakeMCRcon:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def command(self, text: str) -> str:
        self.commands.append(text)
        if text.startswith("execute if block "):
            parts = text.split()
            # parts: ["execute", "if", "block", x, y, z, block_or_tag]
            try:
                y = int(parts[4])
            except (IndexError, ValueError):
                return "Test failed"
            block = parts[6]
            if y > _FakeMCRcon.terrain_top:
                # everything above terrain is air; the air-loop should pass
                return "Test passed" if "air" in block else "Test failed"
            if y == _FakeMCRcon.terrain_top:
                return "Test passed" if block == "minecraft:stone" else "Test failed"
            # below terrain: also stone, but the scan stops at terrain_top
            return "Test passed" if block == "minecraft:stone" else "Test failed"
        return ""


@pytest.fixture(autouse=True)
def reset_fake_mcrcon(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeMCRcon.instances.clear()
    _FakeMCRcon.terrain_top = 70
    module = types.ModuleType("mcrcon")
    module.MCRcon = _FakeMCRcon  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcrcon", module)


def _script(origin_y: int) -> BuildScript:
    return BuildScript(
        intent_id="cli-test",
        structure_type=StructureType.watchtower,
        size_class=SizeClass.small,
        origin=Position3D(x=0, y=origin_y, z=0),
        commands=[
            BuildCommand(
                kind="fill",
                position=Position3D(x=0, y=origin_y, z=0),
                region_to=Position3D(x=4, y=origin_y + 4, z=4),
                block_type="oak_planks",
            ),
        ],
        materials_manifest={},
        total_blocks=0,
        estimated_seconds=0.0,
        source_plan_hash="h",
        compiler_version=1,
    )


@pytest.mark.asyncio
async def test_cli_send_rcon_with_auto_ground_shifts_origin() -> None:
    from scripts.build_in_minecraft import _send_rcon

    _FakeMCRcon.terrain_top = 70
    script = _script(origin_y=80)

    sent, skipped, final_script = await _send_rcon(
        script,
        host="127.0.0.1",
        port=25575,
        password="pw",
        throttle_ms=0,
        auto_ground=True,
        foundation="cobblestone",
    )

    assert skipped == 0
    assert final_script.origin.y == 71  # terrain_top + 1
    # The shifted build fill should appear in the recorded commands.
    cmds = _FakeMCRcon.instances[0].commands
    assert any(c == "fill 0 71 0 4 75 4 minecraft:oak_planks" for c in cmds)
    # Original y=80 fill must NOT appear — proves the script was rewritten.
    assert not any("fill 0 80" in c for c in cmds)


@pytest.mark.asyncio
async def test_cli_send_rcon_no_auto_ground_uses_literal_y() -> None:
    from scripts.build_in_minecraft import _send_rcon

    _FakeMCRcon.terrain_top = 70
    script = _script(origin_y=80)

    sent, skipped, final_script = await _send_rcon(
        script,
        host="127.0.0.1",
        port=25575,
        password="pw",
        throttle_ms=0,
        auto_ground=False,
    )

    assert skipped == 0
    assert final_script.origin.y == 80  # unchanged
    cmds = _FakeMCRcon.instances[0].commands
    # No terrain queries should have been issued.
    assert not any(c.startswith("execute if block") for c in cmds)
    # Original y=80 fill should appear unchanged.
    assert any(c == "fill 0 80 0 4 84 4 minecraft:oak_planks" for c in cmds)


def test_cli_argparser_exposes_auto_ground_and_foundation() -> None:
    """``--auto-ground / --no-auto-ground`` and ``--foundation`` are wired in."""
    import argparse
    from unittest.mock import patch

    from scripts.build_in_minecraft import main

    # Parse defaults to confirm the flags exist; we intercept the actual
    # main_async coroutine so we don't need an OPENAI_API_KEY etc.
    captured: dict[str, argparse.Namespace] = {}

    async def fake_main_async(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    with (
        patch("scripts.build_in_minecraft.main_async", fake_main_async),
        patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "x", "GOOGLE_API_KEY": "y"},
            clear=False,
        ),
        patch("sys.argv", ["build_in_minecraft.py", "--concept", "Test", "--dry-run"]),
        patch("sys.exit") as fake_exit,
    ):
        main()

    fake_exit.assert_called_once_with(0)
    args = captured["args"]
    assert args.auto_ground is True
    assert args.foundation == "cobblestone"

    captured.clear()
    with (
        patch("scripts.build_in_minecraft.main_async", fake_main_async),
        patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "x", "GOOGLE_API_KEY": "y"},
            clear=False,
        ),
        patch(
            "sys.argv",
            [
                "build_in_minecraft.py",
                "--concept",
                "Test",
                "--dry-run",
                "--no-auto-ground",
                "--foundation",
                "stone_bricks",
            ],
        ),
        patch("sys.exit") as fake_exit2,
    ):
        main()

    fake_exit2.assert_called_once_with(0)
    args = captured["args"]
    assert args.auto_ground is False
    assert args.foundation == "stone_bricks"

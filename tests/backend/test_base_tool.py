"""Tests for tools/base.py — BaseTool.run() orchestration and parse_json utility."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.base import BaseTool, parse_json


# ── parse_json ───────────────────────────────────────────────


class TestParseJson:
    def test_valid_json(self) -> None:
        assert parse_json('{"a": 1}', {}) == {"a": 1}

    def test_valid_json_list(self) -> None:
        assert parse_json('[1, 2, 3]', []) == [1, 2, 3]

    def test_none_returns_default(self) -> None:
        assert parse_json(None, "fallback") == "fallback"

    def test_invalid_json_returns_default(self) -> None:
        assert parse_json("not-json{{{", []) == []

    def test_empty_string_returns_default(self) -> None:
        assert parse_json("", 42) == 42

    def test_truncated_json_returns_default(self) -> None:
        assert parse_json('{"key": "val', {"fallback": True}) == {"fallback": True}


# ── BaseTool.run() orchestration ─────────────────────────────


class _DummyTool(BaseTool):
    name = "dummy"
    description = "test tool"
    parameters: dict = {}

    def __init__(self, return_val: dict | None = None, raise_exc: Exception | None = None):
        self._return_val = return_val or {"status": "ok"}
        self._raise_exc = raise_exc

    async def execute(self, **kwargs) -> dict:
        if self._raise_exc:
            raise self._raise_exc
        return self._return_val


class TestBaseToolRun:
    async def test_run_returns_execute_result(self) -> None:
        tool = _DummyTool(return_val={"status": "ok", "data": 42})
        result = await tool.run(agent_id="rex")
        assert result == {"status": "ok", "data": 42}

    async def test_run_persists_artifact(self) -> None:
        repo = AsyncMock()
        tool = _DummyTool()
        tool.artifact_repo = repo

        await tool.run(agent_id="rex")

        # Give the fire-and-forget task a chance to execute
        await asyncio.sleep(0.05)
        repo.save_artifact.assert_called_once()
        artifact = repo.save_artifact.call_args[0][0]
        assert artifact.agent_id == "rex"
        assert artifact.tool_name == "dummy"
        assert artifact.status == "executed"

    async def test_run_emits_artifact_created_event(self) -> None:
        bus = AsyncMock()
        tool = _DummyTool()
        tool.artifact_repo = AsyncMock()
        tool.event_bus = bus

        await tool.run(agent_id="rex")
        await asyncio.sleep(0.05)

        bus.emit.assert_called()
        # Find the ARTIFACT_CREATED call
        from core.event_bus import EventType
        calls = [c for c in bus.emit.call_args_list if c[0][0] == EventType.ARTIFACT_CREATED]
        assert len(calls) >= 1

    async def test_run_sets_error_status_on_exception(self) -> None:
        repo = AsyncMock()
        tool = _DummyTool(raise_exc=RuntimeError("boom"))
        tool.artifact_repo = repo

        with pytest.raises(RuntimeError, match="boom"):
            await tool.run(agent_id="rex")

        await asyncio.sleep(0.05)
        artifact = repo.save_artifact.call_args[0][0]
        assert artifact.status == "failed"
        assert artifact.tool_output == {"error": "boom"}

    async def test_run_sets_error_status_for_error_result(self) -> None:
        repo = AsyncMock()
        tool = _DummyTool(return_val={"status": "error", "reason": "bad input"})
        tool.artifact_repo = repo

        result = await tool.run(agent_id="rex")
        assert result["status"] == "error"

        await asyncio.sleep(0.05)
        artifact = repo.save_artifact.call_args[0][0]
        assert artifact.status == "error"

    async def test_run_emits_simulation_error_on_failure(self) -> None:
        bus = AsyncMock()
        tool = _DummyTool(return_val={"status": "error", "reason": "bad"})
        tool.artifact_repo = AsyncMock()
        tool.event_bus = bus

        await tool.run(agent_id="rex")
        await asyncio.sleep(0.05)

        from core.event_bus import EventType
        error_calls = [c for c in bus.emit.call_args_list if c[0][0] == EventType.SIMULATION_ERROR]
        assert len(error_calls) >= 1

    async def test_internal_data_moves_to_artifact_metadata(self) -> None:
        repo = AsyncMock()
        tool = _DummyTool(return_val={
            "status": "ok",
            "data": "visible",
            "_internal": {"secret": "hidden"},
        })
        tool.artifact_repo = repo

        result = await tool.run(agent_id="rex")
        # The return happens before finally block strips _internal,
        # but the artifact should have _internal in metadata
        assert result["data"] == "visible"

        await asyncio.sleep(0.05)
        artifact = repo.save_artifact.call_args[0][0]
        assert artifact.metadata.get("_internal") == {"secret": "hidden"}
        # Artifact tool_output should not have _internal
        assert "_internal" not in artifact.tool_output

    async def test_run_sets_simulated_status(self) -> None:
        repo = AsyncMock()
        tool = _DummyTool(return_val={"status": "ok", "simulated": True})
        tool.artifact_repo = repo

        await tool.run(agent_id="rex")
        await asyncio.sleep(0.05)

        artifact = repo.save_artifact.call_args[0][0]
        assert artifact.status == "simulated"

    async def test_abstract_execute_enforced(self) -> None:
        with pytest.raises(TypeError):
            class BadTool(BaseTool):
                name = "bad"
                description = "bad"
                parameters = {}
            BadTool()  # type: ignore[abstract]

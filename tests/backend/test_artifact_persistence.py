"""Tests for artifact persistence: models, repo, and BaseTool.run() wrapper."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models import (
    ARTIFACT_TYPE_MAP,
    PENDING_APPROVAL_TOOLS,
    Artifact,
    ArtifactCreate,
)
from core.repos.artifact_repo import ArtifactRepo
from tools.base import BaseTool

# ── Helpers ────────────────────────────────────────────────────


def make_mock_db() -> MagicMock:
    db = MagicMock()
    db.fetch = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value="INSERT 0 1")
    return db


def make_artifact_row(**overrides: Any) -> dict:
    base = {
        "id": uuid.uuid4(),
        "simulation_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "agent_id": "rex",
        "tool_name": "web_search",
        "tool_input": '{"query": "python async"}',
        "tool_output": '{"results": []}',
        "artifact_type": "web_search",
        "status": "executed",
        "metadata": '{"execution_time_ms": 42}',
        "created_at": datetime(2026, 4, 3, 12, 0),
    }
    base.update(overrides)
    return base


class DummyTool(BaseTool):
    name = "dummy_tool"
    description = "A tool for testing"
    parameters: dict[str, Any] = {}

    def __init__(self, result: dict[str, Any] | None = None, *, raise_exc: bool = False) -> None:
        self._result = result or {"status": "ok"}
        self._raise_exc = raise_exc

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if self._raise_exc:
            raise RuntimeError("boom")
        return self._result


# ── Model Tests ────────────────────────────────────────────────


class TestArtifactModels:
    def test_artifact_type_map_covers_key_tools(self) -> None:
        expected = {
            "draft_social_post",
            "draft_email",
            "execute_code",
            "web_search",
            "fetch_url",
            "generate_tilemap",
            "create_poll",
            "recall_memory",
            "update_core_memory",
            "retrieve_transcript",
            "dispatch_alpha",
            "propose_self_modification",
            "view_evolution_log",
            "send_message",
        }
        assert set(ARTIFACT_TYPE_MAP.keys()) == expected

    def test_pending_approval_tools(self) -> None:
        assert {"draft_social_post", "draft_email"} == PENDING_APPROVAL_TOOLS

    def test_artifact_create_defaults(self) -> None:
        a = ArtifactCreate(
            agent_id="rex",
            tool_name="web_search",
            artifact_type="web_search",
        )
        assert a.status == "executed"
        assert a.simulation_id is None
        assert a.metadata is None

    def test_artifact_from_attributes(self) -> None:
        row = make_artifact_row(
            tool_input={"query": "test"},
            tool_output={"results": []},
            metadata={"execution_time_ms": 10},
        )
        a = Artifact(**row)
        assert a.agent_id == "rex"
        assert a.tool_input == {"query": "test"}


# ── ArtifactRepo Tests ─────────────────────────────────────────


class TestArtifactRepo:
    async def test_save_artifact(self) -> None:
        db = make_mock_db()
        row = make_artifact_row()
        db.fetchrow.return_value = row
        repo = ArtifactRepo(db)

        create = ArtifactCreate(
            simulation_id=row["simulation_id"],
            agent_id="rex",
            tool_name="web_search",
            tool_input={"query": "python async"},
            tool_output={"results": []},
            artifact_type="web_search",
        )
        result = await repo.save_artifact(create)
        assert result.agent_id == "rex"
        assert result.tool_name == "web_search"
        db.fetchrow.assert_awaited_once()
        sql = db.fetchrow.call_args[0][0]
        assert "INSERT INTO artifacts" in sql

    async def test_get_artifacts_by_simulation(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = [make_artifact_row(), make_artifact_row(agent_id="aurora")]
        repo = ArtifactRepo(db)

        sim_id = uuid.uuid4()
        results = await repo.get_artifacts_by_simulation(sim_id)
        assert len(results) == 2
        sql = db.fetch.call_args[0][0]
        assert "simulation_id = $1" in sql

    async def test_get_artifacts_by_simulation_with_filters(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = [make_artifact_row()]
        repo = ArtifactRepo(db)

        sim_id = uuid.uuid4()
        results = await repo.get_artifacts_by_simulation(
            sim_id, agent_id="rex", artifact_type="web_search",
        )
        assert len(results) == 1
        sql = db.fetch.call_args[0][0]
        assert "agent_id = $2" in sql
        assert "artifact_type = $3" in sql

    async def test_get_artifacts_by_agent(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = [make_artifact_row()]
        repo = ArtifactRepo(db)

        results = await repo.get_artifacts_by_agent("rex")
        assert len(results) == 1
        sql = db.fetch.call_args[0][0]
        assert "agent_id = $1" in sql
        assert "LIMIT $2" in sql

    async def test_get_artifacts_by_agent_with_type(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = []
        repo = ArtifactRepo(db)

        results = await repo.get_artifacts_by_agent("rex", artifact_type="web_search")
        assert results == []
        sql = db.fetch.call_args[0][0]
        assert "artifact_type = $2" in sql

    async def test_get_artifacts_by_type(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = [make_artifact_row()]
        repo = ArtifactRepo(db)

        results = await repo.get_artifacts_by_type("web_search")
        assert len(results) == 1

    async def test_get_artifacts_by_type_with_simulation(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = []
        repo = ArtifactRepo(db)

        sim_id = uuid.uuid4()
        results = await repo.get_artifacts_by_type("web_search", simulation_id=sim_id)
        assert results == []
        sql = db.fetch.call_args[0][0]
        assert "simulation_id = $2" in sql


# ── BaseTool.run() Wrapper Tests ───────────────────────────────


class TestBaseToolRun:
    async def test_run_returns_execute_result(self) -> None:
        tool = DummyTool(result={"data": "hello"})
        result = await tool.run(agent_id="rex")
        assert result == {"data": "hello"}

    async def test_run_persists_artifact_when_repo_set(self) -> None:
        tool = DummyTool(result={"status": "ok"})
        tool.artifact_repo = AsyncMock(spec=ArtifactRepo)
        tool.artifact_repo.save_artifact = AsyncMock()

        result = await tool.run(agent_id="rex", simulation_id=uuid.uuid4())
        assert result == {"status": "ok"}

        # Let the background task complete
        await asyncio.sleep(0.05)
        tool.artifact_repo.save_artifact.assert_awaited_once()
        call_arg = tool.artifact_repo.save_artifact.call_args[0][0]
        assert isinstance(call_arg, ArtifactCreate)
        assert call_arg.agent_id == "rex"
        assert call_arg.tool_name == "dummy_tool"
        assert call_arg.status == "executed"

    async def test_run_does_not_persist_without_repo(self) -> None:
        tool = DummyTool()
        assert tool.artifact_repo is None
        result = await tool.run(agent_id="rex")
        assert result == {"status": "ok"}

    async def test_run_sets_pending_approval_for_social_post(self) -> None:
        tool = DummyTool(result={"draft": "Hello world!"})
        tool.name = "draft_social_post"
        tool.artifact_repo = AsyncMock(spec=ArtifactRepo)
        tool.artifact_repo.save_artifact = AsyncMock()

        await tool.run(agent_id="aurora")
        await asyncio.sleep(0.05)
        call_arg = tool.artifact_repo.save_artifact.call_args[0][0]
        assert call_arg.status == "pending_approval"
        assert call_arg.artifact_type == "social_post"

    async def test_run_sets_pending_approval_for_email(self) -> None:
        tool = DummyTool(result={"draft": "Dear user..."})
        tool.name = "draft_email"
        tool.artifact_repo = AsyncMock(spec=ArtifactRepo)
        tool.artifact_repo.save_artifact = AsyncMock()

        await tool.run(agent_id="pixel")
        await asyncio.sleep(0.05)
        call_arg = tool.artifact_repo.save_artifact.call_args[0][0]
        assert call_arg.status == "pending_approval"
        assert call_arg.artifact_type == "email"

    async def test_run_enriches_code_execution_metadata(self) -> None:
        tool = DummyTool(result={
            "status": "ok",
            "stdout": "Hello\n",
            "stderr": "",
            "exit_code": 0,
        })
        tool.name = "execute_code"
        tool.artifact_repo = AsyncMock(spec=ArtifactRepo)
        tool.artifact_repo.save_artifact = AsyncMock()

        await tool.run(agent_id="rex")
        await asyncio.sleep(0.05)
        call_arg = tool.artifact_repo.save_artifact.call_args[0][0]
        assert call_arg.artifact_type == "code_execution"
        assert call_arg.metadata["stdout"] == "Hello\n"
        assert call_arg.metadata["stderr"] == ""
        assert call_arg.metadata["exit_code"] == 0
        assert "execution_time_ms" in call_arg.metadata

    async def test_run_persists_failed_status_on_exception(self) -> None:
        tool = DummyTool(raise_exc=True)
        tool.artifact_repo = AsyncMock(spec=ArtifactRepo)
        tool.artifact_repo.save_artifact = AsyncMock()

        with pytest.raises(RuntimeError, match="boom"):
            await tool.run(agent_id="rex")

        await asyncio.sleep(0.05)
        call_arg = tool.artifact_repo.save_artifact.call_args[0][0]
        assert call_arg.status == "failed"
        assert call_arg.tool_output is None

    async def test_run_passes_simulation_and_conversation_ids(self) -> None:
        sim_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        tool = DummyTool()
        tool.artifact_repo = AsyncMock(spec=ArtifactRepo)
        tool.artifact_repo.save_artifact = AsyncMock()

        await tool.run(agent_id="vera", simulation_id=sim_id, conversation_id=conv_id)
        await asyncio.sleep(0.05)
        call_arg = tool.artifact_repo.save_artifact.call_args[0][0]
        assert call_arg.simulation_id == sim_id
        assert call_arg.conversation_id == conv_id

    async def test_run_stores_tool_input(self) -> None:
        tool = DummyTool()
        tool.artifact_repo = AsyncMock(spec=ArtifactRepo)
        tool.artifact_repo.save_artifact = AsyncMock()

        await tool.run(agent_id="rex", query="python async")
        await asyncio.sleep(0.05)
        call_arg = tool.artifact_repo.save_artifact.call_args[0][0]
        assert call_arg.tool_input == {"query": "python async"}

    async def test_run_unknown_tool_uses_name_as_type(self) -> None:
        tool = DummyTool()
        tool.name = "some_new_tool"
        tool.artifact_repo = AsyncMock(spec=ArtifactRepo)
        tool.artifact_repo.save_artifact = AsyncMock()

        await tool.run(agent_id="rex")
        await asyncio.sleep(0.05)
        call_arg = tool.artifact_repo.save_artifact.call_args[0][0]
        assert call_arg.artifact_type == "some_new_tool"


# ── Integration: get_core_tools wires artifact_repo ────────────


class TestToolsWiring:
    def test_get_core_tools_sets_artifact_repo(self) -> None:
        from tools import get_core_tools

        event_bus = AsyncMock()
        redis_client = AsyncMock()
        artifact_repo = AsyncMock(spec=ArtifactRepo)

        tools = get_core_tools(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="rex",
            artifact_repo=artifact_repo,
        )
        for tool in tools:
            assert tool.artifact_repo is artifact_repo

    def test_get_core_tools_no_artifact_repo(self) -> None:
        from tools import get_core_tools

        event_bus = AsyncMock()
        redis_client = AsyncMock()

        tools = get_core_tools(
            event_bus=event_bus,
            redis_client=redis_client,
            agent_id="rex",
        )
        for tool in tools:
            assert tool.artifact_repo is None

    def test_get_memory_tools_sets_artifact_repo(self) -> None:
        from tools import get_memory_tools

        recall_mgr = AsyncMock()
        archival_mgr = AsyncMock()
        core_mgr = AsyncMock()
        artifact_repo = AsyncMock(spec=ArtifactRepo)

        tools = get_memory_tools(
            recall_manager=recall_mgr,
            archival_manager=archival_mgr,
            core_manager=core_mgr,
            agent_id="rex",
            artifact_repo=artifact_repo,
        )
        for tool in tools:
            assert tool.artifact_repo is artifact_repo

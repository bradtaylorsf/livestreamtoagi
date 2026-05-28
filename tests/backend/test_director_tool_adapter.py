"""Tests for Director V2 callable backend tool adapter."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.minecraft.director.tool_adapter import DirectorToolAdapter
from core.tool_executor import execute_director_tool_call
from tools.audience_tools import SendChatMessageTool
from tools.base import BaseTool
from tools.memory_tools import RecallMemoryTool
from tools.messaging import SendMessageTool
from tools.revenue_tools import DraftEmailTool, DraftSocialPostTool
from tools.task_management import ManageTaskTool
from tools.web_tools import FetchUrlTool


def _adapter_for(tools: dict[str, BaseTool]) -> tuple[DirectorToolAdapter, MagicMock]:
    builder = MagicMock(return_value=tools)
    adapter = DirectorToolAdapter(SimpleNamespace(), tool_builder=builder)
    return adapter, builder


async def test_director_adapter_invokes_memory_tool_end_to_end() -> None:
    recall_manager = MagicMock()
    recall_manager.retrieve_recall_memories = AsyncMock(return_value=["remember the mine"])
    tool = RecallMemoryTool(recall_manager=recall_manager, agent_id="pixel")
    adapter, _builder = _adapter_for({"recall_memory": tool})

    result = await adapter.invoke(
        "pixel",
        "recall_memory",
        {"query": "mine", "limit": 1},
    )

    assert result == {"status": "ok", "memories": ["remember the mine"]}
    recall_manager.retrieve_recall_memories.assert_awaited_once_with(
        "pixel",
        "mine",
        limit=1,
        simulation_id=None,
    )


async def test_director_adapter_invokes_fetch_url_with_mocked_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body>Mocked body for Director</body></html>",
            request=request,
        )

    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    redis = MagicMock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tool = FetchUrlTool(
        event_bus=event_bus,
        redis_client=redis,
        agent_id="pixel",
        http_client=client,
    )
    adapter, _builder = _adapter_for({"fetch_url": tool})

    try:
        with patch("tools.web_tools._dns_resolves_to_private", AsyncMock(return_value=False)):
            result = await adapter.invoke(
                "pixel",
                "fetch_url",
                {"url": "https://example.com/page"},
            )
    finally:
        await client.aclose()

    assert result["status"] == "ok"
    assert result["url"] == "https://example.com/page"
    assert result["content"] == "Mocked body for Director"
    event_bus.emit.assert_awaited_once()


async def test_director_adapter_invokes_task_tool_and_writes_shared_state() -> None:
    shared_state = MagicMock()
    shared_state.add_task = AsyncMock()
    tool = ManageTaskTool(shared_state=shared_state, agent_id="rex")
    adapter, _builder = _adapter_for({"manage_task": tool})

    result = await adapter.invoke(
        "rex",
        "manage_task",
        {"action": "create_task", "title": "Build a safe bridge"},
    )

    assert result["status"] == "ok"
    assert result["title"] == "Build a safe bridge"
    # Default create_task posts an open, unowned proposal others can claim.
    assert result["owner"] is None
    shared_state.add_task.assert_awaited_once()
    task = shared_state.add_task.call_args.args[0]
    assert task.title == "Build a safe bridge"
    assert task.owner is None


async def test_director_adapter_invokes_internal_send_message_tool() -> None:
    event_bus = MagicMock()
    event_bus.emit = AsyncMock(return_value={"event_id": "evt-1"})
    tool = SendMessageTool(event_bus=event_bus, agent_id="vera")
    adapter, _builder = _adapter_for({"send_message": tool})

    result = await adapter.invoke(
        "vera",
        "send_message",
        {"to": "rex", "message": "Status?", "tone": "professional"},
    )

    assert result == {"status": "sent", "event_id": "evt-1", "to": "rex"}
    event_bus.emit.assert_awaited_once()


async def test_director_adapter_keeps_social_and_email_tools_pending_approval() -> None:
    redis = MagicMock()
    redis.set = AsyncMock()
    social = DraftSocialPostTool(redis_client=redis, agent_id="pixel")
    email = DraftEmailTool(redis_client=redis, agent_id="pixel")
    adapter, _builder = _adapter_for(
        {
            "draft_social_post": social,
            "draft_email": email,
        }
    )

    social_result = await adapter.invoke(
        "pixel",
        "draft_social_post",
        {"platform": "twitter", "content": "A Minecraft scene update"},
    )
    email_result = await adapter.invoke(
        "pixel",
        "draft_email",
        {"to": "viewer@example.com", "subject": "Update", "body": "Draft only"},
    )

    assert social_result["status"] == "pending_approval"
    assert social_result["tool_result"]["status"] == "pending_human_review"
    assert email_result["status"] == "pending_approval"
    assert email_result["tool_result"]["status"] == "pending_human_review"
    assert redis.set.await_count == 2


async def test_director_adapter_holds_public_chat_without_emitting() -> None:
    management = MagicMock()
    management.review = AsyncMock()
    event_bus = MagicMock()
    event_bus.emit = AsyncMock()
    redis = MagicMock()
    redis.rpush = AsyncMock()
    redis.ltrim = AsyncMock()
    tool = SendChatMessageTool(
        management=management,
        event_bus=event_bus,
        redis_client=redis,
        agent_id="pixel",
    )
    adapter, builder = _adapter_for({"send_chat_message": tool})

    result = await adapter.invoke(
        "pixel",
        "send_chat_message",
        {"message": "Public chat draft"},
    )

    assert result["status"] == "pending_approval"
    assert result["reason"] == "public_tool_requires_human_approval"
    builder.assert_not_called()
    management.review.assert_not_called()
    event_bus.emit.assert_not_called()
    redis.rpush.assert_not_called()


async def test_director_adapter_rejects_execute_code_before_bridge_issue_lands() -> None:
    adapter, builder = _adapter_for({})

    result = await adapter.invoke(
        "rex",
        "execute_code",
        {"language": "python", "code": "print('nope')"},
    )

    assert result["status"] == "rejected"
    assert result["classification"] == "deferred"
    assert result["linked_issue"] == "#560"
    builder.assert_not_called()


async def test_director_adapter_rejects_retired_generate_tilemap() -> None:
    adapter, builder = _adapter_for({})

    result = await adapter.invoke(
        "rex",
        "generate_tilemap",
        {"name": "old", "code": "print({})", "description": "legacy"},
    )

    assert result["status"] == "rejected"
    assert result["classification"] == "retired"
    assert result["linked_issue"] == "#619"
    builder.assert_not_called()


async def test_director_adapter_rejects_unknown_tool_name() -> None:
    adapter, builder = _adapter_for({})

    result = await adapter.invoke("rex", "unknown_backend_tool", {})

    assert result == {
        "status": "rejected",
        "reason": "unknown_tool",
        "tool_name": "unknown_backend_tool",
    }
    builder.assert_not_called()


async def test_director_adapter_emits_tool_call_timeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SOAK_RUN_DIR", str(tmp_path))
    adapter, builder = _adapter_for({})

    result = await adapter.invoke("rex", "unknown_backend_tool", {}, scene_id="scene-tool-1")

    assert result["status"] == "rejected"
    builder.assert_not_called()
    path = tmp_path / "timeline-raw" / "director_v2.ndjson"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    record = records[-1]
    assert record["event_type"] == "director.tool.call"
    assert record["agent"] == "rex"
    assert record["trace_id"] == "scene-tool-1"
    assert record["payload"]["tool_name"] == "unknown_backend_tool"
    assert record["payload"]["scene_id"] == "scene-tool-1"
    assert record["payload"]["ok"] is False
    assert record["payload"]["latency_ms"] >= 0


def test_available_tools_only_returns_callable_now_tools() -> None:
    callable_tool = MagicMock()
    callable_tool.name = "send_message"
    approval_tool = MagicMock()
    approval_tool.name = "draft_email"
    adapter, _builder = _adapter_for(
        {
            "send_message": callable_tool,
            "draft_email": approval_tool,
            "execute_code": MagicMock(),
            "get_world_state": MagicMock(),
        }
    )

    assert adapter.available_tools_for("vera") == ["send_message"]


async def test_execute_director_tool_call_returns_tool_role_message() -> None:
    adapter = MagicMock()
    adapter.invoke = AsyncMock(return_value={"status": "ok", "value": 1})

    message = await execute_director_tool_call(
        adapter,
        "vera",
        "send_message",
        {"to": "group", "message": "Done"},
        tool_call_id="call-1",
        scene_id="scene-1",
    )

    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call-1"
    assert json.loads(message["content"]) == {"status": "ok", "value": 1}
    adapter.invoke.assert_awaited_once()

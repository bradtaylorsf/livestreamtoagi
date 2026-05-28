"""Tests for core agent tools: send_message, get_world_state, get_audience_status."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools import (
    BaseTool,
    GetAudienceStatusTool,
    GetWorldStateTool,
    SendMessageTool,
    ToolRegistry,
    get_core_tools,
)
from tools.messaging import VALID_TONES

# --- Fixtures ---


@pytest.fixture
def event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.emit = AsyncMock(
        return_value={"event_id": "evt-123", "event_type": "agent_speak", "data": {}}
    )
    return bus


@pytest.fixture
def redis_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def send_message(event_bus: AsyncMock) -> SendMessageTool:
    return SendMessageTool(event_bus=event_bus, agent_id="rex")


@pytest.fixture
def get_world_state(redis_client: AsyncMock) -> GetWorldStateTool:
    return GetWorldStateTool(redis_client=redis_client)


@pytest.fixture
def get_audience_status(redis_client: AsyncMock) -> GetAudienceStatusTool:
    return GetAudienceStatusTool(redis_client=redis_client)


# --- BaseTool interface conformance ---


class TestToolInterface:
    """All tools must conform to the CrewAI tool interface."""

    def test_send_message_has_required_attrs(self, send_message: SendMessageTool) -> None:
        assert isinstance(send_message, BaseTool)
        assert send_message.name == "send_message"
        assert isinstance(send_message.description, str)
        assert isinstance(send_message.parameters, dict)
        assert "to" in send_message.parameters
        assert "message" in send_message.parameters
        assert "tone" in send_message.parameters

    def test_get_world_state_has_required_attrs(
        self, get_world_state: GetWorldStateTool
    ) -> None:
        assert isinstance(get_world_state, BaseTool)
        assert get_world_state.name == "get_world_state"
        assert isinstance(get_world_state.description, str)
        assert isinstance(get_world_state.parameters, dict)

    def test_get_audience_status_has_required_attrs(
        self, get_audience_status: GetAudienceStatusTool
    ) -> None:
        assert isinstance(get_audience_status, BaseTool)
        assert get_audience_status.name == "get_audience_status"
        assert isinstance(get_audience_status.description, str)
        assert isinstance(get_audience_status.parameters, dict)


# --- SendMessageTool ---


class TestSendMessage:
    async def test_routes_to_correct_target(
        self, send_message: SendMessageTool, event_bus: AsyncMock
    ) -> None:
        result = await send_message.execute(
            to="aurora", message="Hello Aurora!", tone="casual"
        )

        assert result["status"] == "sent"
        assert result["to"] == "aurora"
        assert result["event_id"] == "evt-123"

    async def test_emits_agent_speak_event(
        self, send_message: SendMessageTool, event_bus: AsyncMock
    ) -> None:
        await send_message.execute(to="vera", message="Status update", tone="professional")

        event_bus.emit.assert_called_once()
        call_args = event_bus.emit.call_args
        assert call_args[0][0] == "agent_speak"

        data = call_args[0][1]
        assert data["from_agent"] == "rex"
        assert data["to"] == "vera"
        assert data["message"] == "Status update"
        assert data["tone"] == "professional"
        assert "timestamp" in data

    async def test_sends_to_group(
        self, send_message: SendMessageTool, event_bus: AsyncMock
    ) -> None:
        result = await send_message.execute(
            to="group", message="Everyone listen up!", tone="urgent"
        )

        assert result["to"] == "group"
        data = event_bus.emit.call_args[0][1]
        assert data["to"] == "group"

    async def test_defaults_to_casual_tone(
        self, send_message: SendMessageTool, event_bus: AsyncMock
    ) -> None:
        await send_message.execute(to="fork", message="Hey")

        data = event_bus.emit.call_args[0][1]
        assert data["tone"] == "casual"

    async def test_rejects_invalid_tone(self, send_message: SendMessageTool) -> None:
        with pytest.raises(ValueError, match="Invalid tone"):
            await send_message.execute(to="vera", message="Hi", tone="angry")

    def test_valid_tones_match_spec(self) -> None:
        expected = {"casual", "urgent", "professional", "dramatic", "sarcastic"}
        assert expected == VALID_TONES


# --- GetWorldStateTool ---


class TestGetWorldState:
    async def test_returns_expected_structure(
        self, get_world_state: GetWorldStateTool, redis_client: AsyncMock
    ) -> None:
        agents = [{"id": "rex", "position": {"x": 10, "y": 20}, "status": "idle"}]
        tasks = [{"id": 1, "name": "Build library", "assignee": "rex"}]
        events = [{"type": "agent_speak", "summary": "Rex greeted Aurora"}]
        budget = {"spent": 12.50, "remaining": 87.50}

        redis_client.get = AsyncMock(
            side_effect=lambda key: {
                "world:agents": json.dumps(agents),
                "world:active_tasks": json.dumps(tasks),
                "world:recent_events": json.dumps(events),
                "world:budget": json.dumps(budget),
            }.get(key)
        )

        result = await get_world_state.execute()

        assert result["agents"] == agents
        assert result["active_tasks"] == tasks
        assert result["recent_events"] == events
        assert result["budget"] == budget

    async def test_returns_defaults_when_redis_empty(
        self, get_world_state: GetWorldStateTool, redis_client: AsyncMock
    ) -> None:
        redis_client.get = AsyncMock(return_value=None)

        result = await get_world_state.execute()

        assert result["agents"] == []
        assert result["active_tasks"] == []
        assert result["recent_events"] == []
        assert result["budget"] == {"spent": 0.0, "remaining": 0.0}

    async def test_handles_invalid_json_gracefully(
        self, get_world_state: GetWorldStateTool, redis_client: AsyncMock
    ) -> None:
        redis_client.get = AsyncMock(return_value="not-json{{{")

        result = await get_world_state.execute()

        assert result["agents"] == []
        assert result["active_tasks"] == []


# --- GetAudienceStatusTool ---


class TestGetAudienceStatus:
    async def test_returns_expected_structure(
        self, get_audience_status: GetAudienceStatusTool, redis_client: AsyncMock
    ) -> None:
        chat = [{"user": "viewer1", "message": "Hello!"}]
        polls = [{"id": "poll-1", "title": "What should Rex build?", "options": ["A", "B"]}]

        redis_client.get = AsyncMock(
            side_effect=lambda key: {
                "audience:viewer_count": "142",
                "audience:active_polls": json.dumps(polls),
            }.get(key)
        )
        redis_client.lrange = AsyncMock(return_value=[json.dumps(chat[0])])

        result = await get_audience_status.execute()

        assert result["viewer_count"] == 142
        assert result["recent_chat_messages"] == chat
        assert result["active_polls"] == polls

    async def test_returns_defaults_when_redis_empty(
        self, get_audience_status: GetAudienceStatusTool, redis_client: AsyncMock
    ) -> None:
        redis_client.get = AsyncMock(return_value=None)
        redis_client.lrange = AsyncMock(return_value=[])

        result = await get_audience_status.execute()

        assert result["viewer_count"] == 0
        assert result["recent_chat_messages"] == []
        assert result["active_polls"] == []

    async def test_handles_non_numeric_viewer_count(
        self, get_audience_status: GetAudienceStatusTool, redis_client: AsyncMock
    ) -> None:
        redis_client.get = AsyncMock(
            side_effect=lambda key: {
                "audience:viewer_count": "not-a-number",
                "audience:active_polls": None,
            }.get(key)
        )
        redis_client.lrange = AsyncMock(return_value=[])

        result = await get_audience_status.execute()
        assert result["viewer_count"] == 0


# --- ToolRegistry ---


class TestToolRegistry:
    def test_register_and_get(self, event_bus: AsyncMock) -> None:
        tool = SendMessageTool(event_bus=event_bus, agent_id="rex")
        registry = ToolRegistry()
        registry.register(tool)

        assert registry.get("send_message") is tool
        assert registry.get("nonexistent") is None

    def test_all_returns_copy(self, event_bus: AsyncMock) -> None:
        tool = SendMessageTool(event_bus=event_bus, agent_id="rex")
        registry = ToolRegistry()
        registry.register(tool)

        all_tools = registry.all()
        assert "send_message" in all_tools
        all_tools.pop("send_message")
        assert registry.get("send_message") is tool  # original unaffected

    def test_names(self, event_bus: AsyncMock, redis_client: AsyncMock) -> None:
        # Rex only sees tools he's authorized for (filtering removes
        # create_poll, draft_social_post, draft_email, web_search, fetch_url)
        registry = ToolRegistry()
        for tool in get_core_tools(
            event_bus, redis_client, agent_id="rex",
            alliance_manager=MagicMock(),
            character_spawner=MagicMock(),
            voting_manager=MagicMock(),
        ):
            registry.register(tool)

        names = registry.names()
        assert sorted(names) == [
            "claim_ownership",
            "execute_code",
            "get_audience_status",
            "get_ownership",
            "get_poll_results",
            "get_world_state",
            "leave_alliance",
            "list_my_claims",
            "propose_alliance",
            "propose_build",
            "propose_character",
            "propose_new_building",
            "release_ownership",
            "send_message",
            "view_alliances",
            "vote_alliance",
            "vote_character",
        ]

    def test_get_core_tools_returns_all_three(
        self, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        # Vera sees tools she's authorized for (filtering removes
        # execute_code, draft_social_post, fetch_url)
        tools = get_core_tools(
            event_bus, redis_client, agent_id="vera",
            alliance_manager=MagicMock(),
            character_spawner=MagicMock(),
            voting_manager=MagicMock(),
        )
        assert len(tools) == 21

        tool_names = {t.name for t in tools}
        assert tool_names == {
            "send_message",
            "get_world_state",
            "get_audience_status",
            "get_poll_results",
            "create_poll",
            "draft_email",
            "check_post_performance",
            "check_email_responses",
            "web_search",
            "propose_character",
            "vote_character",
            "propose_alliance",
            "vote_alliance",
            "leave_alliance",
            "view_alliances",
            "propose_build",
            "propose_new_building",
            "claim_ownership",
            "release_ownership",
            "get_ownership",
            "list_my_claims",
        }

        for tool in tools:
            assert isinstance(tool, BaseTool)

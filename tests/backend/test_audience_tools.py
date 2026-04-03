"""Tests for audience communication tools: send_chat, create_poll, get_poll_results."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from core.models import ContentReviewResult
from tools.audience_tools import CreatePollTool, GetPollResultsTool, SendChatMessageTool

# --- Fixtures ---


@pytest.fixture
def event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.emit = AsyncMock(
        return_value={"event_id": "evt-456", "event_type": "poll_created", "data": {}}
    )
    return bus


@pytest.fixture
def redis_client() -> AsyncMock:
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock()
    client.rpush = AsyncMock()
    client.ltrim = AsyncMock()
    client.lrange = AsyncMock(return_value=[])
    return client


@pytest.fixture
def overseer() -> AsyncMock:
    mock = AsyncMock()
    mock.review = AsyncMock(
        return_value=ContentReviewResult(approved=True, reason="OK", severity=1)
    )
    return mock


@pytest.fixture
def send_chat(
    overseer: AsyncMock, event_bus: AsyncMock, redis_client: AsyncMock
) -> SendChatMessageTool:
    return SendChatMessageTool(
        overseer=overseer, event_bus=event_bus, redis_client=redis_client, agent_id="pixel"
    )


@pytest.fixture
def create_poll(redis_client: AsyncMock, event_bus: AsyncMock) -> CreatePollTool:
    return CreatePollTool(redis_client=redis_client, event_bus=event_bus, agent_id="vera")


@pytest.fixture
def get_poll_results(redis_client: AsyncMock, event_bus: AsyncMock) -> GetPollResultsTool:
    return GetPollResultsTool(redis_client=redis_client, event_bus=event_bus)


# --- SendChatMessageTool ---


class TestSendChatMessage:
    async def test_passes_through_overseer_filter(
        self, send_chat: SendChatMessageTool, overseer: AsyncMock
    ) -> None:
        await send_chat.execute(message="Hello chat!")

        overseer.review.assert_called_once_with("pixel", "Hello chat!")

    async def test_rejected_by_overseer_returns_error(
        self, overseer: AsyncMock, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        overseer.review = AsyncMock(
            return_value=ContentReviewResult(approved=False, reason="Blocked content", severity=3)
        )
        tool = SendChatMessageTool(
            overseer=overseer, event_bus=event_bus, redis_client=redis_client, agent_id="pixel"
        )

        result = await tool.execute(message="bad message")

        assert result["status"] == "rejected"
        assert "Blocked content" in result["reason"]
        redis_client.rpush.assert_not_called()

    async def test_unauthorized_agent_rejected(
        self, overseer: AsyncMock, event_bus: AsyncMock, redis_client: AsyncMock
    ) -> None:
        tool = SendChatMessageTool(
            overseer=overseer, event_bus=event_bus, redis_client=redis_client, agent_id="rex"
        )

        result = await tool.execute(message="Hello!")

        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]
        overseer.review.assert_not_called()

    async def test_successful_send(
        self, send_chat: SendChatMessageTool, redis_client: AsyncMock, event_bus: AsyncMock
    ) -> None:
        result = await send_chat.execute(message="GG everyone!")

        assert result["status"] == "sent"
        assert result["message"] == "GG everyone!"
        assert result["agent"] == "pixel"
        redis_client.rpush.assert_called_once()
        redis_client.ltrim.assert_called_once_with("audience:recent_chat", -50, -1)
        event_bus.emit.assert_called_once()

    async def test_allowed_agents(self) -> None:
        assert {"pixel", "sentinel", "vera"} == SendChatMessageTool.ALLOWED_AGENTS


# --- CreatePollTool ---


class TestCreatePoll:
    async def test_rejects_if_active_poll_exists(
        self, create_poll: CreatePollTool, redis_client: AsyncMock
    ) -> None:
        redis_client.get = AsyncMock(return_value="existing-poll-id")

        result = await create_poll.execute(
            title="What to build?", options=["Library", "Garden"]
        )

        assert result["status"] == "rejected"
        assert "active poll" in result["reason"].lower()

    async def test_validates_too_few_options(self, create_poll: CreatePollTool) -> None:
        result = await create_poll.execute(title="Pick one", options=["Only"])

        assert result["status"] == "rejected"
        assert "2-5" in result["reason"]

    async def test_validates_too_many_options(self, create_poll: CreatePollTool) -> None:
        result = await create_poll.execute(
            title="Pick one", options=["A", "B", "C", "D", "E", "F"]
        )

        assert result["status"] == "rejected"
        assert "2-5" in result["reason"]

    async def test_unauthorized_agent_rejected(
        self, redis_client: AsyncMock, event_bus: AsyncMock
    ) -> None:
        tool = CreatePollTool(redis_client=redis_client, event_bus=event_bus, agent_id="rex")

        result = await tool.execute(title="What?", options=["A", "B"])

        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]

    async def test_successful_creation(
        self, create_poll: CreatePollTool, redis_client: AsyncMock, event_bus: AsyncMock
    ) -> None:
        result = await create_poll.execute(
            title="What should Rex build?", options=["Library", "Garden", "Tavern"]
        )

        assert result["status"] == "created"
        assert "poll_id" in result

        # Verify Redis storage
        assert redis_client.set.call_count == 2  # poll data + poll:active

        # Verify event emission
        event_bus.emit.assert_called_once()
        call_args = event_bus.emit.call_args
        assert call_args[0][0] == "poll_created"
        assert call_args[0][1]["title"] == "What should Rex build?"

    async def test_allowed_agents(self) -> None:
        assert {"vera", "pixel"} == CreatePollTool.ALLOWED_AGENTS


# --- GetPollResultsTool ---


class TestGetPollResults:
    async def test_calculates_percentages_correctly(
        self, get_poll_results: GetPollResultsTool, redis_client: AsyncMock, event_bus: AsyncMock
    ) -> None:
        poll_data = {
            "poll_id": "poll-1",
            "title": "What to build?",
            "options": [
                {"name": "Library", "votes": 10},
                {"name": "Garden", "votes": 20},
                {"name": "Tavern", "votes": 70},
            ],
        }
        redis_client.get = AsyncMock(return_value=json.dumps(poll_data))

        result = await get_poll_results.execute(poll_id="poll-1")

        assert result["status"] == "ok"
        assert result["total_votes"] == 100
        assert result["winner"] == "Tavern"
        assert result["options"][0] == {"name": "Library", "votes": 10, "percentage": 10.0}
        assert result["options"][1] == {"name": "Garden", "votes": 20, "percentage": 20.0}
        assert result["options"][2] == {"name": "Tavern", "votes": 70, "percentage": 70.0}

    async def test_handles_poll_not_found(
        self, get_poll_results: GetPollResultsTool, redis_client: AsyncMock
    ) -> None:
        redis_client.get = AsyncMock(return_value=None)

        result = await get_poll_results.execute(poll_id="nonexistent")

        assert result["status"] == "not_found"

    async def test_handles_zero_votes(
        self, get_poll_results: GetPollResultsTool, redis_client: AsyncMock
    ) -> None:
        poll_data = {
            "poll_id": "poll-2",
            "title": "Empty poll",
            "options": [
                {"name": "A", "votes": 0},
                {"name": "B", "votes": 0},
            ],
        }
        redis_client.get = AsyncMock(return_value=json.dumps(poll_data))

        result = await get_poll_results.execute(poll_id="poll-2")

        assert result["total_votes"] == 0
        assert result["winner"] is None
        assert result["options"][0]["percentage"] == 0.0

    async def test_emits_poll_result_event(
        self, get_poll_results: GetPollResultsTool, redis_client: AsyncMock, event_bus: AsyncMock
    ) -> None:
        poll_data = {
            "poll_id": "poll-3",
            "title": "Test",
            "options": [{"name": "X", "votes": 5}, {"name": "Y", "votes": 15}],
        }
        redis_client.get = AsyncMock(return_value=json.dumps(poll_data))

        await get_poll_results.execute(poll_id="poll-3")

        event_bus.emit.assert_called_once()
        call_args = event_bus.emit.call_args
        assert call_args[0][0] == "poll_result"
        assert call_args[0][1]["poll_id"] == "poll-3"

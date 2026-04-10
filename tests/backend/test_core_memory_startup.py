"""Tests for core memory initialization at app startup."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bootstrap import init_core_memories
from core.memory.core_memory import CoreMemoryManager
from core.memory.token_counter import TokenCounter
from core.models import CoreMemory

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def token_counter() -> TokenCounter:
    return TokenCounter()


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_core_memory = AsyncMock(return_value=None)
    repo.upsert_core_memory = AsyncMock()
    return repo


@pytest.fixture
def core_memory_mgr(mock_repo: AsyncMock, token_counter: TokenCounter) -> CoreMemoryManager:
    return CoreMemoryManager(mock_repo, token_counter)


@pytest.fixture
def mock_registry() -> MagicMock:
    """Registry with 9 agents matching the show's cast."""
    agent_ids = [
        "vera", "rex", "aurora", "pixel", "fork",
        "sentinel", "grok", "management", "alpha",
    ]
    agents = []
    for aid in agent_ids:
        agent = MagicMock()
        agent.id = aid
        agent.display_name = aid.capitalize()
        agent.model_conversation = f"model-{aid}"
        agents.append(agent)
    registry = MagicMock()
    registry.get_all_agents.return_value = agents
    return registry


# ── Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_core_memories_initializes_all_agents(
    mock_registry: MagicMock,
    core_memory_mgr: CoreMemoryManager,
    mock_repo: AsyncMock,
) -> None:
    """All 9 agents should get core memory when none exists."""
    initialized = await init_core_memories(mock_registry, core_memory_mgr)
    assert len(initialized) == 9
    assert set(initialized) == {
        "vera", "rex", "aurora", "pixel", "fork",
        "sentinel", "grok", "management", "alpha",
    }
    assert mock_repo.upsert_core_memory.call_count == 9


@pytest.mark.asyncio
async def test_init_core_memories_skips_existing(
    mock_registry: MagicMock,
    core_memory_mgr: CoreMemoryManager,
    mock_repo: AsyncMock,
) -> None:
    """Agents with existing core memory should not be re-initialized."""
    # Return a CoreMemory record for vera and rex, None for others
    from datetime import datetime
    existing = {"vera", "rex"}

    def _make_record(agent_id: str) -> CoreMemory:
        return CoreMemory(
            agent_id=agent_id, content="existing", token_count=100,
            version=1, last_updated=datetime(2026, 4, 1),
        )

    async def fake_get(agent_id: str, **kwargs):
        if agent_id in existing:
            return _make_record(agent_id)
        return None

    mock_repo.get_core_memory.side_effect = fake_get

    initialized = await init_core_memories(mock_registry, core_memory_mgr)
    assert "vera" not in initialized
    assert "rex" not in initialized
    assert len(initialized) == 7


@pytest.mark.asyncio
async def test_init_core_memories_identity_string(
    mock_registry: MagicMock,
    core_memory_mgr: CoreMemoryManager,
    mock_repo: AsyncMock,
) -> None:
    """Identity string should use display_name and model_conversation."""
    # Only have one agent to simplify assertion
    agent = MagicMock()
    agent.id = "rex"
    agent.display_name = "Rex"
    agent.model_conversation = "claude-haiku-4.5"
    mock_registry.get_all_agents.return_value = [agent]

    await init_core_memories(mock_registry, core_memory_mgr)

    # Check the content passed to upsert
    call_args = mock_repo.upsert_core_memory.call_args
    content = call_args[0][1]  # second positional arg is content
    assert "I am Rex." in content
    assert "claude-haiku-4.5" in content


# ── Acceptance: initialization lives in startup, not CLI scripts ──


def test_no_init_core_memories_in_cli_scripts() -> None:
    """init_core_memories should not be called in CLI scripts."""
    result = subprocess.run(
        [
            "grep", "-n", "init_core_memories",
            "scripts/watch_conversations.py", "scripts/test_agent.py",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"Found init_core_memories in CLI scripts:\n{result.stdout}"
    )


def test_no_ensure_core_memory_in_cli_scripts() -> None:
    """_ensure_core_memory helper should not exist in CLI scripts."""
    result = subprocess.run(
        ["grep", "-n", "_ensure_core_memory", "scripts/test_agent.py"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"Found _ensure_core_memory in test_agent.py:\n{result.stdout}"
    )


def test_init_core_memories_in_startup() -> None:
    """init_core_memories should be called in core/main.py or core/bootstrap.py."""
    result = subprocess.run(
        ["grep", "-n", "init_core_memories", "core/main.py"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "init_core_memories not found in core/main.py"
    )

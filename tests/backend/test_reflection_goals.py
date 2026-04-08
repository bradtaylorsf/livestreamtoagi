"""Tests for autonomous goal generation during reflection (#269)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.memory.reflection import ReflectionManager
from core.models import JournalEntry


def _make_llm_response(content: str):
    """Create a fake LLM response."""
    return MagicMock(content=content)


def _make_agent_config(agent_id: str = "rex"):
    """Create a fake agent config."""
    cfg = MagicMock()
    cfg.id = agent_id
    cfg.display_name = "Rex"
    cfg.role = "Engineer/Builder"
    cfg.chattiness = 0.5
    cfg.initiative = 0.6
    cfg.system_prompt = "You are Rex, the pragmatic builder who loves engineering."
    cfg.model_building = "claude-sonnet-4-6"
    return cfg


def _make_goal_legacy(goal: str, priority: int = 3, status: str = "pending"):
    """Create a fake goal in legacy format."""
    g = MagicMock()
    g.id = "goal-abc"
    g.goal = goal
    g.priority = priority
    g.status = status
    return g


def _make_state(**kwargs):
    """Create a fake agent state."""
    defaults = {
        "agent_id": "rex",
        "energy": 0.7,
        "satisfaction": 0.5,
        "boredom": 0.2,
        "frustration": 0.1,
        "social_need": 0.3,
        "creative_need": 0.3,
        "recognition_need": 0.2,
    }
    defaults.update(kwargs)
    state = MagicMock()
    for k, v in defaults.items():
        setattr(state, k, v)
    return state


def _make_reflection_manager(
    *,
    goal_count: int = 2,
    goal_texts: list[str] | None = None,
    state_overrides: dict | None = None,
    llm_goal_response: str | None = None,
):
    """Build a ReflectionManager with mocked dependencies."""
    memory_repo = AsyncMock()
    memory_repo.get_recent_recall_memories = AsyncMock(return_value=[])
    memory_repo.update_importance_score = AsyncMock()
    memory_repo.create_journal_entry = AsyncMock(return_value=JournalEntry(
        id=1, agent_id="rex", reflection_type="6hour", content="Journal.", token_count=5,
    ))
    memory_repo.create_proposal = AsyncMock()

    llm_client = AsyncMock()
    core_memory_mgr = AsyncMock()
    core_memory_mgr.get_core_memory = AsyncMock(return_value="Some core memory.")
    core_memory_mgr.get_token_count = AsyncMock(return_value=100)

    token_counter = MagicMock()
    token_counter.count_tokens = MagicMock(return_value=50)

    agent_registry = MagicMock()
    agent_registry.get_agent = MagicMock(return_value=_make_agent_config())

    goal_manager = AsyncMock()
    goals = goal_texts or ["Existing goal 1", "Existing goal 2"]
    goal_manager.get_goals = AsyncMock(
        return_value=[_make_goal_legacy(g) for g in goals[:goal_count]]
    )
    goal_manager.add_goal = AsyncMock(return_value=_make_goal_legacy("New goal"))

    state_manager = AsyncMock()
    state_manager.get_state = AsyncMock(
        return_value=_make_state(**(state_overrides or {}))
    )
    state_manager.format_state_for_context = MagicMock(
        return_value="Energy: 0.7, Boredom: 0.2"
    )
    state_manager.snapshot_to_db = AsyncMock()

    # Default LLM response for goal generation
    if llm_goal_response is None:
        llm_goal_response = json.dumps({
            "goals": [
                {"goal": "Build a new API endpoint", "category": "creative", "priority": 2},
                {"goal": "Review Fork's code critique", "category": "competitive", "priority": 3},
            ]
        })

    # LLM returns different things for different calls:
    # 1st call: 6-hour reflection analysis
    # 2nd call: goal generation
    # 3rd call: journal entry
    reflection_response = json.dumps({
        "importance_scores": {},
        "promotions": [],
    })
    llm_client.complete = AsyncMock(side_effect=[
        _make_llm_response(reflection_response),
        _make_llm_response(llm_goal_response),
        _make_llm_response("Journal entry for today."),
    ])

    mgr = ReflectionManager(
        memory_repo=memory_repo,
        llm_client=llm_client,
        core_memory_mgr=core_memory_mgr,
        token_counter=token_counter,
        agent_registry=agent_registry,
        goal_manager=goal_manager,
        agent_state_manager=state_manager,
    )

    return mgr, goal_manager, state_manager, llm_client


@pytest.mark.asyncio
async def test_6hour_reflection_generates_goals():
    """6-hour reflection generates new goals via LLM."""
    mgr, goal_manager, _, llm_client = _make_reflection_manager()

    # Mock recall memories to make reflection non-trivial
    mgr._repo.get_recent_recall_memories = AsyncMock(return_value=[
        MagicMock(id=1, event_type="conversation", summary="Discussed building plans"),
    ])

    result = await mgr.run_6hour_reflection("rex")

    # Goal generation should have been called
    assert goal_manager.add_goal.call_count == 2
    # Verify first goal call
    first_call = goal_manager.add_goal.call_args_list[0]
    assert first_call.kwargs["agent_id"] == "rex"
    assert first_call.kwargs["source"] == "reflection"
    assert first_call.kwargs["category"] == "creative"


@pytest.mark.asyncio
async def test_goal_dedup_prevents_duplicates():
    """Dedup check in add_goal prevents creating similar goals."""
    from core.agent_goals import _is_similar_goal

    assert _is_similar_goal("Build a prototype", "build a prototype")
    assert _is_similar_goal("Build a prototype", "Build a prototype for the team")
    assert not _is_similar_goal("Build a prototype", "Review the budget")
    assert _is_similar_goal(
        "Create a reading nook in the office",
        "create a reading nook in the office area",
    )


@pytest.mark.asyncio
async def test_state_influences_priority():
    """High boredom should boost creative goal priority to 1."""
    mgr, goal_manager, _, _ = _make_reflection_manager(
        state_overrides={"boredom": 0.8},
        llm_goal_response=json.dumps({
            "goals": [
                {"goal": "Paint a mural", "category": "creative", "priority": 3},
            ]
        }),
    )
    mgr._repo.get_recent_recall_memories = AsyncMock(return_value=[
        MagicMock(id=1, event_type="conversation", summary="Felt bored"),
    ])

    await mgr.run_6hour_reflection("rex")

    # Creative goal should have been boosted to priority 1 due to high boredom
    assert goal_manager.add_goal.call_count == 1
    call = goal_manager.add_goal.call_args_list[0]
    assert call.kwargs["priority"] == 1  # Boosted from 3 to 1


@pytest.mark.asyncio
async def test_goal_cap_respected():
    """Skip goal generation when agent already has 8+ active goals."""
    mgr, goal_manager, _, _ = _make_reflection_manager(
        goal_count=9,
        goal_texts=[f"Goal {i}" for i in range(9)],
    )
    mgr._repo.get_recent_recall_memories = AsyncMock(return_value=[
        MagicMock(id=1, event_type="conversation", summary="Busy day"),
    ])

    await mgr.run_6hour_reflection("rex")

    # add_goal should NOT have been called for goal generation
    assert goal_manager.add_goal.call_count == 0


@pytest.mark.asyncio
async def test_invalid_llm_response_handled_gracefully():
    """Goal generation handles malformed LLM responses without crashing."""
    mgr, goal_manager, _, _ = _make_reflection_manager(
        llm_goal_response="Not valid JSON at all",
    )
    mgr._repo.get_recent_recall_memories = AsyncMock(return_value=[
        MagicMock(id=1, event_type="conversation", summary="Test"),
    ])

    # Should not raise
    result = await mgr.run_6hour_reflection("rex")
    assert result is not None
    # No goals should have been created from invalid response
    assert goal_manager.add_goal.call_count == 0


@pytest.mark.asyncio
async def test_frustration_boosts_competitive_goals():
    """High frustration boosts competitive goal priority."""
    mgr, goal_manager, _, _ = _make_reflection_manager(
        state_overrides={"frustration": 0.8},
        llm_goal_response=json.dumps({
            "goals": [
                {"goal": "Outperform Fork on code review", "category": "competitive", "priority": 4},
            ]
        }),
    )
    mgr._repo.get_recent_recall_memories = AsyncMock(return_value=[
        MagicMock(id=1, event_type="conversation", summary="Frustrated"),
    ])

    await mgr.run_6hour_reflection("rex")

    assert goal_manager.add_goal.call_count == 1
    call = goal_manager.add_goal.call_args_list[0]
    assert call.kwargs["priority"] == 1  # Boosted due to high frustration


@pytest.mark.asyncio
async def test_category_validated():
    """Invalid category is normalized to 'personal'."""
    mgr, goal_manager, _, _ = _make_reflection_manager(
        llm_goal_response=json.dumps({
            "goals": [
                {"goal": "Do something weird", "category": "invalid_cat", "priority": 3},
            ]
        }),
    )
    mgr._repo.get_recent_recall_memories = AsyncMock(return_value=[
        MagicMock(id=1, event_type="conversation", summary="Test"),
    ])

    await mgr.run_6hour_reflection("rex")

    assert goal_manager.add_goal.call_count == 1
    call = goal_manager.add_goal.call_args_list[0]
    assert call.kwargs["category"] == "personal"

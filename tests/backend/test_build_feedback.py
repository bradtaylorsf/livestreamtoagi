"""Tests for embodied build-quality feedback records."""

from __future__ import annotations

from core.embodiment.build_feedback import (
    build_feedback_from_attempt,
    format_build_feedback,
    is_build_action_payload,
)


def test_build_feedback_marks_complete_attempt() -> None:
    plan = {
        "agent_id": "Rex",
        "action_id": "build-1",
        "goal": "Build a two-block marker",
        "tool": "buildFromPlan",
        "steps": [
            {"operation": "place", "x": 1, "y": 64, "z": 1, "block_type": "oak_log"},
            {"operation": "place", "x": 1, "y": 65, "z": 1, "block_type": "oak_log"},
        ],
    }
    perception = {
        "agent_id": "rex",
        "observations": [
            {"x": 1, "y": 64, "z": 1, "after_block": "oak_log"},
            {"x": 1, "y": 65, "z": 1, "after_block": "minecraft:oak_log"},
        ],
    }

    feedback = build_feedback_from_attempt(plan, perception, [{"detail": "completion=1"}])

    assert feedback["attempt_id"] == "build-1"
    assert feedback["agent_id"] == "rex"
    assert feedback["classification"] == "complete"
    assert feedback["completion"] == 1.0
    assert feedback["intended"]["count"] == 2
    assert feedback["present"]["count"] == 2
    assert feedback["missing"]["count"] == 0
    assert feedback["suggested_next_step"] == "Plan complete; continue with the next goal."


def test_build_feedback_reports_missing_blocks_and_repair_step() -> None:
    plan = {
        "agent_id": "rex",
        "action_id": "build-2",
        "goal": "Finish a corner",
        "tool": "buildFromPlan",
        "steps": [
            {"operation": "place", "x": 2, "y": 64, "z": 2, "block_type": "cobblestone"},
            {"operation": "place", "x": 2, "y": 65, "z": 2, "block_type": "cobblestone"},
        ],
    }
    perception = {
        "agent_id": "rex",
        "observations": [{"x": 2, "y": 64, "z": 2, "after_block": "air"}],
    }

    feedback = build_feedback_from_attempt(plan, perception, [{"detail": "completion=0"}])

    assert feedback["classification"] == "needs_repair"
    assert feedback["present"]["count"] == 0
    assert feedback["missing"]["count"] == 2
    assert "x=2, y=64, z=2" in feedback["suggested_next_step"]


def test_build_feedback_reports_unexpected_blocks() -> None:
    plan = {
        "agent_id": "pixel",
        "action_id": "build-3",
        "goal": "Place one lantern",
        "tool": "planAndBuild",
        "steps": [{"operation": "place", "x": 3, "y": 64, "z": 3, "block_type": "lantern"}],
    }
    perception = {
        "agent_id": "pixel",
        "observations": [
            {"x": 3, "y": 64, "z": 3, "after_block": "lantern"},
            {"x": 4, "y": 64, "z": 3, "after_block": "dirt", "unexpected": True},
        ],
    }

    feedback = build_feedback_from_attempt(plan, perception, [{"detail": "completion=1"}])

    assert feedback["classification"] == "cleanup_needed"
    assert feedback["unexpected"]["count"] == 1
    assert "Remove or reconcile unexpected block" in feedback["suggested_next_step"]


def test_build_feedback_reports_unsafe_conditions_first() -> None:
    plan = {
        "agent_id": "fork",
        "action_id": "build-4",
        "goal": "Extend a safe platform",
        "tool": "buildFromPlan",
        "steps": [{"operation": "place", "x": 5, "y": 64, "z": 5, "block_type": "stone"}],
    }
    perception = {
        "agent_id": "fork",
        "observations": [
            {"x": 5, "y": 64, "z": 5, "after_block": "air"},
            {"type": "lava", "x": 5, "y": 63, "z": 5, "unsafe": True},
        ],
    }

    feedback = build_feedback_from_attempt(plan, perception, [{"detail": "completion=0"}])

    assert feedback["classification"] == "unsafe"
    assert feedback["unsafe"]["count"] == 1
    assert feedback["missing"]["count"] == 1
    assert "Address unsafe build condition" in feedback["suggested_next_step"]


def test_build_feedback_action_detection_and_memory_text() -> None:
    assert is_build_action_payload(
        {
            "agent_id": "rex",
            "action_id": "build-5",
            "detail": "partial: intended=4; present=3; missing=1; completion=0.75",
        }
    )

    feedback = build_feedback_from_attempt(
        {"agent_id": "rex", "action_id": "build-5", "goal": "Repair wall"},
        {"agent_id": "rex", "observations": []},
        [{"detail": "partial: intended=4; present=3; missing=1; completion=0.75"}],
    )
    rendered = format_build_feedback(feedback)

    assert "- completion: 75%" in rendered
    assert "- suggested_next_step: Repair missing intended block or step" in rendered

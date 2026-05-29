"""Tests for the Layer-1 infrastructure prompt — the emergent work loop (#908)."""

from __future__ import annotations

from core.system_prompt import INFRASTRUCTURE_PROMPT


def test_infrastructure_prompt_names_manage_task_and_loop_actions() -> None:
    """The loop must be taught by tool name with the real manage_task action names."""
    assert "manage_task" in INFRASTRUCTURE_PROMPT
    for action in ("list_tasks", "create_task", "claim_task", "update_status"):
        assert action in INFRASTRUCTURE_PROMPT, f"missing manage_task action {action!r}"


def test_infrastructure_prompt_spells_out_five_step_loop() -> None:
    """Observe → propose → claim → execute → report should all appear as steps."""
    lower = INFRASTRUCTURE_PROMPT.lower()
    for step in ("observe", "propose", "claim", "execute", "report"):
        assert step in lower, f"missing loop step {step!r}"


def test_infrastructure_prompt_states_headless_approval_rule() -> None:
    """Layer-1 must state the D3 headless rule: claiming IS the approval, no gate."""
    lower = INFRASTRUCTURE_PROMPT.lower()
    assert "claiming an in-progress task is the approval" in lower
    assert "no consensus" in lower or "no audience" in lower

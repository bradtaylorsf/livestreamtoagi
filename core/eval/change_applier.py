"""Change applier — writes proposed changes to DB as new config versions.

Takes validated proposals from the EvalAnalyzer and applies them as
new versioned entries in the agent_prompt_versions and
conversation_param_versions tables.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from core.models import ProposedChange

if TYPE_CHECKING:
    import uuid

    from core.repos.config_version_repo import ConfigVersionRepo

logger = logging.getLogger(__name__)

# Safety limits
MAX_PARAM_DELTA = 0.1


class ChangeApplier:
    """Applies prompt/param changes as new DB versions."""

    def __init__(self, config_version_repo: ConfigVersionRepo) -> None:
        self._repo = config_version_repo

    async def apply(
        self,
        proposals: list[ProposedChange],
        eval_run_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Apply tunable changes as new DB versions.

        Returns a summary of what was applied.
        """
        applied_count = 0
        skipped_count = 0
        details: list[str] = []

        # Group prompt changes by agent
        prompt_changes: dict[str, list[ProposedChange]] = {}
        param_changes: dict[str, list[ProposedChange]] = {}
        config_changes: list[ProposedChange] = []

        for p in proposals:
            if p.type == "prompt_change" and p.agent_id:
                prompt_changes.setdefault(p.agent_id, []).append(p)
            elif p.type == "param_change" and p.agent_id:
                param_changes.setdefault(p.agent_id, []).append(p)
            elif p.type == "conversation_config_change":
                config_changes.append(p)
            # technical_issue proposals are handled separately

        # Apply prompt changes
        for agent_id, changes in prompt_changes.items():
            try:
                await self._apply_prompt_changes(agent_id, changes, eval_run_id)
                applied_count += len(changes)
                details.append(f"Prompt changes for {agent_id}: {len(changes)}")
            except Exception:
                logger.exception("Failed to apply prompt changes for %s", agent_id)
                skipped_count += len(changes)

        # Apply param changes
        for agent_id, changes in param_changes.items():
            try:
                await self._apply_param_changes(agent_id, changes, eval_run_id)
                applied_count += len(changes)
                details.append(f"Param changes for {agent_id}: {len(changes)}")
            except Exception:
                logger.exception("Failed to apply param changes for %s", agent_id)
                skipped_count += len(changes)

        # Apply conversation config changes
        if config_changes:
            try:
                await self._apply_config_changes(config_changes, eval_run_id)
                applied_count += len(config_changes)
                details.append(f"Conversation config changes: {len(config_changes)}")
            except Exception:
                logger.exception("Failed to apply conversation config changes")
                skipped_count += len(config_changes)

        return {
            "applied": applied_count,
            "skipped": skipped_count,
            "details": details,
        }

    async def _apply_prompt_changes(
        self,
        agent_id: str,
        changes: list[ProposedChange],
        eval_run_id: uuid.UUID,
    ) -> None:
        """Apply prompt changes as a new version."""
        current = await self._repo.get_active_prompt(agent_id)
        if current is None:
            logger.warning("No active prompt for %s, skipping", agent_id)
            return

        new_prompt = current.system_prompt
        for change in changes:
            if change.current_text and change.proposed_text:
                new_prompt = new_prompt.replace(change.current_text, change.proposed_text)
            elif change.proposed_text:
                # Append to the relevant section
                new_prompt = new_prompt + "\n" + change.proposed_text

        reasons = "; ".join(c.reasoning for c in changes if c.reasoning)

        version = await self._repo.insert_prompt_version(
            agent_id,
            system_prompt=new_prompt,
            behaviors=current.behaviors,
            config_params=current.config_params,
            change_reason=reasons[:500],
            source="eval_loop",
            eval_run_id=eval_run_id,
        )
        await self._repo.set_active_prompt_version(agent_id, version.version)

    async def _apply_param_changes(
        self,
        agent_id: str,
        changes: list[ProposedChange],
        eval_run_id: uuid.UUID,
    ) -> None:
        """Apply parameter changes as a new version."""
        current = await self._repo.get_active_prompt(agent_id)
        if current is None:
            logger.warning("No active prompt for %s, skipping", agent_id)
            return

        new_params = copy.deepcopy(current.config_params)
        for change in changes:
            if change.param_path and change.proposed_value is not None:
                # Enforce safety rail
                current_val = new_params.get(change.param_path)
                if isinstance(current_val, (int, float)) and isinstance(change.proposed_value, (int, float)):
                    delta = abs(change.proposed_value - current_val)
                    if delta > MAX_PARAM_DELTA:
                        direction = 1 if change.proposed_value > current_val else -1
                        change.proposed_value = current_val + (direction * MAX_PARAM_DELTA)

                new_params[change.param_path] = change.proposed_value

        reasons = "; ".join(c.reasoning for c in changes if c.reasoning)

        version = await self._repo.insert_prompt_version(
            agent_id,
            system_prompt=current.system_prompt,
            behaviors=current.behaviors,
            config_params=new_params,
            change_reason=reasons[:500],
            source="eval_loop",
            eval_run_id=eval_run_id,
        )
        await self._repo.set_active_prompt_version(agent_id, version.version)

    async def _apply_config_changes(
        self,
        changes: list[ProposedChange],
        eval_run_id: uuid.UUID,
    ) -> None:
        """Apply conversation config changes as a new version."""
        current = await self._repo.get_active_conversation_params()
        if current is None:
            logger.warning("No active conversation params, skipping")
            return

        new_params = copy.deepcopy(current.params)
        for change in changes:
            if change.param_path and change.proposed_value is not None:
                # Navigate nested path (e.g., "selection_weights.time_since_spoke")
                _set_nested(new_params, change.param_path, change.proposed_value)

        reasons = "; ".join(c.reasoning for c in changes if c.reasoning)

        version = await self._repo.insert_conversation_param_version(
            params=new_params,
            change_reason=reasons[:500],
            source="eval_loop",
            eval_run_id=eval_run_id,
        )
        await self._repo.set_active_conversation_version(version.version)


def _set_nested(d: dict, path: str, value: Any) -> None:
    """Set a value in a nested dict using dot-separated path."""
    keys = path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value

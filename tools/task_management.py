"""ManageTaskTool — lets agents create, claim, update, and list shared tasks."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from .base import BaseTool

if TYPE_CHECKING:
    from core.shared_state import SharedWorkingState


class ManageTaskTool(BaseTool):
    """Create, claim, update status, and list tasks on the shared task board."""

    name = "manage_task"
    description = (
        "Manage the shared task board. Actions: list_tasks, create_task, "
        "claim_task, update_status. Use this to coordinate work with other agents. "
        "create_task posts an OPEN, unowned proposal that any agent can claim "
        "(pass claim=true to claim it for yourself on creation). claim_task is "
        "first-claim-wins: exactly one agent wins a contested task and the loser "
        "is told who took it. In headless runs there is no audience, so claiming "
        "an in-progress task IS the approval — claiming auto-approves the work; "
        "there is no consensus or audience gate."
    )
    parameters = {
        "action": {
            "type": "string",
            "description": "One of: list_tasks, create_task, claim_task, update_status",
            "enum": ["list_tasks", "create_task", "claim_task", "update_status"],
        },
        "title": {
            "type": "string",
            "description": "Task title (required for create_task)",
            "optional": True,
        },
        "claim": {
            "type": "boolean",
            "description": (
                "create_task only: immediately claim the new task for yourself "
                "(owner=you, in_progress); default false = open proposal others can claim."
            ),
            "optional": True,
        },
        "task_id": {
            "type": "string",
            "description": "Task ID (required for claim_task and update_status)",
            "optional": True,
        },
        "status": {
            "type": "string",
            "description": "New status (required for update_status): pending, in_progress, done, blocked",
            "enum": ["pending", "in_progress", "done", "blocked"],
            "optional": True,
        },
        "blocked_reason": {
            "type": "string",
            "description": "Reason for blocking (optional, used with status=blocked)",
            "optional": True,
        },
    }

    def __init__(
        self,
        shared_state: SharedWorkingState,
        agent_id: str = "unknown",
    ) -> None:
        self._shared_state = shared_state
        self._agent_id = agent_id

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "list_tasks")

        if action == "list_tasks":
            return await self._list_tasks()
        elif action == "create_task":
            title = kwargs.get("title")
            if not title:
                return {"status": "error", "reason": "title is required for create_task"}
            return await self._create_task(title, claim=bool(kwargs.get("claim", False)))
        elif action == "claim_task":
            task_id = kwargs.get("task_id")
            if not task_id:
                return {"status": "error", "reason": "task_id is required for claim_task"}
            return await self._claim_task(task_id)
        elif action == "update_status":
            task_id = kwargs.get("task_id")
            status = kwargs.get("status")
            if not task_id or not status:
                return {"status": "error", "reason": "task_id and status are required"}
            return await self._update_status(
                task_id,
                status,
                kwargs.get("blocked_reason"),
            )
        else:
            return {"status": "error", "reason": f"Unknown action: {action}"}

    async def _list_tasks(self) -> dict[str, Any]:
        tasks = await self._shared_state.get_tasks()
        return {
            "status": "ok",
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "owner": t.owner,
                    "status": t.status,
                    "blocked_reason": t.blocked_reason,
                }
                for t in tasks
            ],
        }

    async def _create_task(self, title: str, claim: bool = False) -> dict[str, Any]:
        from core.shared_state import SharedTask

        task_id = f"task-{uuid.uuid4().hex[:8]}"
        if claim:
            # Claim-on-create convenience: self-owned, immediately in progress.
            task = SharedTask(
                id=task_id,
                title=title,
                owner=self._agent_id,
                status="in_progress",
            )
        else:
            # Default: open, unowned proposal any agent can claim.
            task = SharedTask(id=task_id, title=title)
        await self._shared_state.add_task(task)
        return {"status": "ok", "task_id": task_id, "title": title, "owner": task.owner}

    async def _claim_task(self, task_id: str) -> dict[str, Any]:
        """Atomically claim a task (first-claim-wins).

        In headless runs there is no audience, so claiming an in-progress task IS
        the approval — claiming auto-approves the work; there is no consensus or
        audience gate. The loser of a contested claim is told who took it.
        """
        result = await self._shared_state.claim_task(task_id, self._agent_id)
        status = result.get("status")
        if status == "ok":
            return {"status": "ok", "task_id": task_id, "new_owner": self._agent_id}
        if status == "already_claimed":
            return {
                "status": "already_claimed",
                "task_id": task_id,
                "owner": result.get("owner"),
            }
        return {"status": "error", "reason": f"Task {task_id!r} not found"}

    async def _update_status(
        self,
        task_id: str,
        status: str,
        blocked_reason: str | None,
    ) -> dict[str, Any]:
        found = await self._shared_state.update_task_status(task_id, status, blocked_reason)
        if not found:
            return {"status": "error", "reason": f"Task {task_id!r} not found"}
        return {"status": "ok", "task_id": task_id, "new_status": status}

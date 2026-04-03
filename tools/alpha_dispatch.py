"""Alpha dispatch tool — send Alpha (the wolf) on small errands."""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.models import CostEventCreate

from .base import BaseTool

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.llm_client import LLMClient
    from core.repos.cost_repo import CostRepo

logger = logging.getLogger(__name__)

# Alpha uses DeepSeek V3.2 via OpenRouter
ALPHA_MODEL = "deepseek/deepseek-v3.2"

# Hard timeout for Alpha tasks
ALPHA_TIMEOUT_SECONDS = 60

# Fallback cost estimate when Alpha times out or errors before LLM responds
ALPHA_FALLBACK_COST = Decimal("0.005")

# System prompt constraining Alpha's capabilities
ALPHA_SYSTEM_PROMPT = (
    "You are Alpha, a fast wolf assistant. You can only: "
    "search the web for information, perform simple calculations, "
    "and fetch/summarize data. Respond concisely with the result. "
    "If the task is outside your abilities, say so briefly."
)

# All agents that may dispatch Alpha (everyone except Alpha itself)
ALLOWED_AGENTS = frozenset(
    {"vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"}
)


class DispatchAlphaTool(BaseTool):
    """Send Alpha (the wolf) on a small errand with a 60-second time limit."""

    name = "dispatch_alpha"
    description = "Send Alpha the wolf on a quick errand (web search, calculations, data fetch)"
    parameters: dict[str, Any] = {
        "task": {"type": "string", "description": "What Alpha should do"},
        "urgency": {
            "type": "string",
            "description": "when_free (default) or now",
            "enum": ["when_free", "now"],
        },
    }

    def __init__(
        self,
        event_bus: EventBus,
        agent_id: str,
        llm_client: LLMClient,
        cost_repo: CostRepo | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id
        self._llm_client = llm_client
        self._cost_repo = cost_repo

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        task: str = kwargs.get("task", "")

        # Alpha cannot dispatch itself
        if self._agent_id == "alpha":
            return {
                "status": "rejected",
                "reason": "Alpha cannot dispatch itself",
            }

        if self._agent_id not in ALLOWED_AGENTS:
            return {
                "status": "rejected",
                "reason": f"Agent {self._agent_id!r} not authorized",
            }

        if not task.strip():
            return {"status": "error", "reason": "Task cannot be empty"}

        task_id = str(uuid.uuid4())

        # Emit dispatch event — wolf runs off screen
        await self._event_bus.emit(
            "alpha_dispatch",
            {"from": self._agent_id, "task": task, "status": "running", "task_id": task_id},
        )

        # Call LLM with timeout
        try:
            response = await asyncio.wait_for(
                self._llm_client.complete(
                    messages=[
                        {"role": "system", "content": ALPHA_SYSTEM_PROMPT},
                        {"role": "user", "content": task},
                    ],
                    model=ALPHA_MODEL,
                    agent_id="alpha",
                    timeout=ALPHA_TIMEOUT_SECONDS,
                    max_tokens=512,
                ),
                timeout=ALPHA_TIMEOUT_SECONDS,
            )
            result = response.content
            cost = response.estimated_cost
            status = "success"
        except TimeoutError:
            result = "Alpha took too long and came back confused"
            cost = ALPHA_FALLBACK_COST
            status = "confused"
            logger.warning("Alpha dispatch timed out for task: %s", task[:100])
        except Exception as exc:
            result = f"Alpha got confused: {exc}"
            cost = ALPHA_FALLBACK_COST
            status = "confused"
            logger.error("Alpha dispatch failed: %s", exc)

        # Emit return event — wolf comes back
        await self._event_bus.emit(
            "alpha_return",
            {"result": result, "status": status, "task_id": task_id},
        )

        # Track cost
        if self._cost_repo is not None:
            await self._cost_repo.add_cost(
                CostEventCreate(
                    agent_id="alpha",
                    cost_type="alpha_dispatch",
                    amount=cost,
                    details={
                        "dispatched_by": self._agent_id,
                        "task": task[:200],
                        "status": status,
                    },
                )
            )

        return {
            "task_id": task_id,
            "status": status,
            "result": result,
        }

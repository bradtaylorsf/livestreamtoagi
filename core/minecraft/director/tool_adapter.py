"""Director V2 adapter for invoking selected backend tools."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from core.llm_client import agent_cost_context
from core.minecraft.director.timeline import emit_director_timeline_event
from core.minecraft.director.tool_parity import (
    TOOL_PARITY,
    ToolClassification,
    ToolParityEntry,
    is_approval_gated,
    is_callable_now,
)
from core.tool_executor import build_agent_tools

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

    from core.bootstrap import Services
    from core.civilization.conflict import ConflictLedger
    from core.civilization.diplomacy import DiplomacyLedger
    from core.civilization.ownership import OwnershipLedger
    from core.civilization.theft import TheftLedger
    from core.civilization.trade import TradeLedger
    from core.simulation.decision_logger import DecisionLogger
    from core.simulation.embodiment import EmbodimentExecutor
    from tools.base import BaseTool

ToolBuilder = Callable[..., dict[str, "BaseTool"]]

logger = logging.getLogger(__name__)

_HELD_PUBLIC_TOOLS = frozenset({"send_chat_message", "create_poll"})


class DirectorToolAdapter:
    """Restrict and invoke backend tools from selected Minecraft scene turns."""

    def __init__(
        self,
        services: Services,
        *,
        tool_builder: ToolBuilder = build_agent_tools,
        simulation_mode: bool = False,
        embodiment_executor: EmbodimentExecutor | None = None,
        sim_folder: Path | None = None,
        ownership_ledger: OwnershipLedger | None = None,
        trade_ledger: TradeLedger | None = None,
        theft_ledger: TheftLedger | None = None,
        diplomacy_ledger: DiplomacyLedger | None = None,
        conflict_ledger: ConflictLedger | None = None,
        decision_logger: DecisionLogger | None = None,
    ) -> None:
        self._services = services
        self._tool_builder = tool_builder
        self._simulation_mode = simulation_mode
        self._embodiment_executor = embodiment_executor
        self._sim_folder = sim_folder
        self._ownership_ledger = ownership_ledger
        self._trade_ledger = trade_ledger
        self._theft_ledger = theft_ledger
        self._diplomacy_ledger = diplomacy_ledger
        self._conflict_ledger = conflict_ledger
        self._decision_logger = decision_logger

    def available_tools_for(self, agent_id: str) -> list[str]:
        """Return callable-now tools present in the agent's backend registry."""

        tools = self._build_tools(agent_id)
        return sorted(name for name in tools if is_callable_now(name))

    async def invoke(
        self,
        agent_id: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        simulation_id: UUID | None = None,
        conversation_id: UUID | None = None,
        scene_id: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a Director-approved backend tool or return a typed rejection."""

        started = time.perf_counter()
        args = dict(arguments or {})
        entry = TOOL_PARITY.get(tool_name)
        if entry is None:
            result = {
                "status": "rejected",
                "reason": "unknown_tool",
                "tool_name": tool_name,
            }
            self._log_tool_call(
                agent_id,
                tool_name,
                None,
                result,
                simulation_id,
                scene_id,
                started_at=started,
            )
            return result

        if not (is_callable_now(tool_name) or is_approval_gated(tool_name)):
            result = self._not_callable_result(entry)
            self._log_tool_call(
                agent_id,
                tool_name,
                entry.classification,
                result,
                simulation_id,
                scene_id,
                started_at=started,
            )
            return result

        if is_approval_gated(tool_name) and tool_name in _HELD_PUBLIC_TOOLS:
            result = {
                "status": "pending_approval",
                "reason": "public_tool_requires_human_approval",
                "tool_name": tool_name,
                "classification": entry.classification,
            }
            self._log_tool_call(
                agent_id,
                tool_name,
                entry.classification,
                result,
                simulation_id,
                scene_id,
                started_at=started,
            )
            return result

        tools = self._build_tools(agent_id)
        tool = tools.get(tool_name)
        if tool is None:
            result = {
                "status": "rejected",
                "reason": "tool_not_available_for_agent",
                "tool_name": tool_name,
                "classification": entry.classification,
            }
            if entry.linked_issue is not None:
                result["linked_issue"] = entry.linked_issue
            self._log_tool_call(
                agent_id,
                tool_name,
                entry.classification,
                result,
                simulation_id,
                scene_id,
                started_at=started,
            )
            return result

        error_class = None
        try:
            logger.debug("Director V2 executing tool %s for %s", tool_name, agent_id)
            with agent_cost_context(agent_id):
                result = await tool.run(
                    agent_id=agent_id,
                    simulation_id=simulation_id,
                    conversation_id=conversation_id,
                    **args,
                )
        except Exception as exc:
            logger.warning("Director V2 tool %s failed for %s: %s", tool_name, agent_id, exc)
            error_class = exc.__class__.__name__
            result = {"status": "error", "reason": str(exc)}

        if is_approval_gated(tool_name):
            result = self._approval_result(entry, result)

        self._log_tool_call(
            agent_id,
            tool_name,
            entry.classification,
            result,
            simulation_id,
            scene_id,
            started_at=started,
            error_class=error_class,
        )
        return result

    def _build_tools(self, agent_id: str) -> dict[str, BaseTool]:
        return self._tool_builder(
            agent_id,
            self._services,
            self._simulation_mode,
            embodiment_executor=self._embodiment_executor,
            sim_folder=self._sim_folder,
            ownership_ledger=self._ownership_ledger,
            trade_ledger=self._trade_ledger,
            theft_ledger=self._theft_ledger,
            diplomacy_ledger=self._diplomacy_ledger,
            conflict_ledger=self._conflict_ledger,
            decision_logger=self._decision_logger,
        )

    @staticmethod
    def _not_callable_result(entry: ToolParityEntry) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "rejected",
            "reason": "not_callable_in_director_v2",
            "tool_name": entry.name,
            "classification": entry.classification,
        }
        if entry.linked_issue is not None:
            result["linked_issue"] = entry.linked_issue
        if entry.minecraft_replacement is not None:
            result["minecraft_replacement"] = entry.minecraft_replacement
        return result

    @staticmethod
    def _approval_result(entry: ToolParityEntry, tool_result: dict[str, Any]) -> dict[str, Any]:
        status = tool_result.get("status")
        if status in {"error", "rejected", "rate_limited", "not_found"}:
            return tool_result
        return {
            "status": "pending_approval",
            "tool_name": entry.name,
            "classification": entry.classification,
            "tool_result": tool_result,
        }

    @staticmethod
    def _log_tool_call(
        agent_id: str,
        tool_name: str,
        classification: ToolClassification | None,
        result: Mapping[str, Any],
        simulation_id: UUID | None,
        scene_id: str | None,
        *,
        started_at: float,
        error_class: str | None = None,
    ) -> None:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        status = str(result.get("status", "unknown"))
        if error_class is None and status in {"error", "rejected"}:
            reason = result.get("reason")
            error_class = str(reason).strip() if reason else status
        payload = {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "classification": classification,
            "status": status,
            "simulation_id": str(simulation_id) if simulation_id else None,
            "scene_id": scene_id,
            "ok": status not in {"error", "rejected"},
            "latency_ms": latency_ms,
            "error_class": error_class,
        }
        logger.info("director_tool_call %s", json.dumps(payload, sort_keys=True))
        emit_director_timeline_event(
            "director.tool.call",
            payload,
            agent_id=agent_id,
            trace_id=scene_id,
        )

"""Conversation selection logger — records every speaker selection decision.

Logs selection results, interrupt attempts, and energy changes to the database
for tuning and diagnostics. Supports JSONL export for offline analysis.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from core.models import (
    AgentEnergyLogCreate,
    EnergyLogCreate,
    InterruptLogCreate,
    SelectionLog,
    SelectionLogCreate,
)

if TYPE_CHECKING:
    import uuid

    from core.models import LoggingConfig, SelectionResult
    from core.repos.conversation_repo import ConversationRepo

logger = logging.getLogger(__name__)


class SelectionLogger:
    """Records speaker selection decisions, interrupts, and energy changes."""

    def __init__(
        self,
        repo: ConversationRepo,
        config: LoggingConfig,
        simulation_id: uuid.UUID | None = None,
    ) -> None:
        self.repo = repo
        self.config = config
        self.simulation_id = simulation_id

    async def log_selection(
        self,
        conversation_id: uuid.UUID,
        turn_number: int,
        result: SelectionResult,
        previous_speaker_id: str | None,
        active_agents: list[str],
        conversation_energy: float,
        trigger_type: str,
        config_hash: str,
    ) -> None:
        """Log a speaker selection decision and any interrupt attempts."""
        if not self.config.log_every_selection:
            return

        entry = SelectionLogCreate(
            conversation_id=conversation_id,
            turn_number=turn_number,
            selected_agent_id=result.selected_agent_id,
            was_interrupt=result.was_interrupt,
            agent_scores=result.score_breakdown,
            detected_topic=result.detected_topic,
            previous_speaker_id=previous_speaker_id,
            conversation_energy=conversation_energy,
            active_agents=active_agents,
            trigger_type=trigger_type,
            config_hash=config_hash,
            simulation_id=self.simulation_id,
        )
        await self.repo.log_selection(entry)

        for attempt in result.interrupt_attempts:
            await self.log_interrupt(
                conversation_id=conversation_id,
                attempting_agent=attempt.attempting_agent_id,
                would_have_spoken=attempt.would_have_spoken_id,
                score=attempt.interrupt_score,
                threshold=attempt.threshold,
                succeeded=attempt.succeeded,
                reason=attempt.reason,
            )

    async def log_interrupt(
        self,
        conversation_id: uuid.UUID,
        attempting_agent: str,
        would_have_spoken: str,
        score: float,
        threshold: float,
        succeeded: bool,
        reason: str | None = None,
    ) -> None:
        """Log an interrupt attempt (success or failure)."""
        if not self.config.log_interrupts:
            return

        entry = InterruptLogCreate(
            conversation_id=conversation_id,
            attempting_agent_id=attempting_agent,
            would_have_spoken_id=would_have_spoken,
            interrupt_score=score,
            threshold_at_time=threshold,
            succeeded=succeeded,
            reason=reason,
            simulation_id=self.simulation_id,
        )
        await self.repo.log_interrupt(entry)

    async def log_energy(
        self,
        conversation_id: uuid.UUID,
        turn_number: int,
        changes: dict,
    ) -> None:
        """Log energy changes for a conversation turn."""
        if not self.config.log_energy_changes:
            return

        entry = EnergyLogCreate(
            conversation_id=conversation_id,
            turn_number=turn_number,
            changes=changes,
            simulation_id=self.simulation_id,
        )
        await self.repo.log_energy(entry)

    async def log_agent_energy(
        self,
        *,
        conversation_id: uuid.UUID,
        turn_number: int,
        simulation_id: uuid.UUID,
        agent_energies: dict[str, float],
    ) -> None:
        """Persist one ``agent_energy_log`` row per active participant.

        Conversation energy is shared across active participants today, so we
        write the same value for every agent in ``agent_energies``. The
        timeline endpoint groups by agent_id at read time.
        """
        if not agent_energies:
            return
        entries = [
            AgentEnergyLogCreate(
                simulation_id=simulation_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                turn_number=turn_number,
                energy=float(energy),
            )
            for agent_id, energy in agent_energies.items()
        ]
        await self.repo.log_agent_energy_bulk(entries)

    async def cleanup(self, retention_days: int | None = None) -> None:
        """Delete logs older than retention_days."""
        days = retention_days if retention_days is not None else self.config.retention_days
        await self.repo.cleanup_old_logs(days)

    @staticmethod
    def export_jsonl(records: list[SelectionLog]) -> str:
        """Serialize selection logs to JSONL format (one JSON object per line)."""
        lines = []
        for record in records:
            lines.append(json.dumps(record.model_dump(), default=str))
        return "\n".join(lines)

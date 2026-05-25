"""Memory snapshot export and import for pre-loaded simulation state.

Supports exporting a simulation's memory state to a portable JSON format,
and restoring it to seed new simulations with established agent memories.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from core.database import Database
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.memory.token_counter import TokenCounter
    from core.repos.memory_repo import MemoryRepo
    from core.repos.relationship_repo import RelationshipRepo

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1

# Mirrors the agent_goals CHECK constraints (see migrations 018, 023, 030).
# Snapshot inputs outside these sets get normalized so the seed insert does
# not violate the DB constraints.
_ALLOWED_GOAL_SOURCES = {"self", "assigned", "eval_loop", "reflection", "dream"}
_ALLOWED_GOAL_CATEGORIES = {"creative", "social", "economic", "personal", "competitive"}


# ── Snapshot schema models ────────────────────────────────────


class AgentSnapshot(BaseModel):
    """Memory state for a single agent."""

    core_memory: str = ""
    recall_memories: list[dict[str, Any]] = Field(default_factory=list)
    journal_entries: list[dict[str, Any]] = Field(default_factory=list)


class AgentStateSeedSnapshot(BaseModel):
    """Embodied internal state for a single agent."""

    energy: float = 0.7
    satisfaction: float = 0.5
    boredom: float = 0.2
    frustration: float = 0.0
    creativity: float = 0.5
    social_need: float = 0.5
    focus: float = 0.5


class AgentAccountSeedSnapshot(BaseModel):
    """Embodied budget/account state for a single agent."""

    balance: float = 0.0
    weekly_allocation: float = 0.0
    total_earned: float = 0.0
    total_spent: float = 0.0


class AgentGoalSeedSnapshot(BaseModel):
    """Seeded goal state for a single agent."""

    goal: str
    priority: int = 5
    status: str = "active"
    source: str = "snapshot"
    category: str | None = None
    progress_notes: str | None = None


class MemorySnapshot(BaseModel):
    """Complete memory snapshot for a simulation."""

    version: int = SNAPSHOT_VERSION
    source_simulation_id: str | None = None
    snapshot_at: str = ""
    agents: dict[str, AgentSnapshot] = Field(default_factory=dict)
    agent_states: dict[str, AgentStateSeedSnapshot] = Field(default_factory=dict)
    agent_accounts: dict[str, AgentAccountSeedSnapshot] = Field(default_factory=dict)
    agent_goals: dict[str, list[AgentGoalSeedSnapshot]] = Field(default_factory=dict)
    relationships: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class RestoreResult:
    """Summary of a snapshot restore operation."""

    agents_restored: list[str] = field(default_factory=list)
    core_memories_restored: int = 0
    recall_memories_restored: int = 0
    journal_entries_restored: int = 0
    relationships_restored: int = 0
    goals_restored: int = 0
    agent_states_restored: int = 0
    agent_accounts_restored: int = 0
    warnings: list[str] = field(default_factory=list)


# ── Exporter ──────────────────────────────────────────────────


class MemorySnapshotExporter:
    """Export simulation memory state to a portable JSON format."""

    def __init__(
        self,
        *,
        db: Database,
        memory_repo: MemoryRepo,
        relationship_repo: RelationshipRepo | None = None,
    ) -> None:
        self._db = db
        self._memory_repo = memory_repo
        self._relationship_repo = relationship_repo

    async def export(
        self,
        simulation_id: str,
        agents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export all memory state for a simulation.

        Args:
            simulation_id: UUID of the simulation to export.
            agents: Optional list of agent IDs to filter to.

        Returns:
            Dict matching the MemorySnapshot schema.
        """
        import uuid as uuid_mod

        sim_uuid = uuid_mod.UUID(simulation_id)
        snapshot = MemorySnapshot(
            source_simulation_id=simulation_id,
            snapshot_at=datetime.now(UTC).isoformat(),
        )

        # Get agents from simulation record, falling back to core_memory table
        all_agent_ids = await self._get_agent_ids(sim_uuid)
        if agents:
            all_agent_ids = [a for a in all_agent_ids if a in agents]

        for agent_id in all_agent_ids:
            agent_snap = AgentSnapshot()

            # Core memory
            core_mem = await self._memory_repo.get_core_memory(agent_id, simulation_id=sim_uuid)
            if core_mem:
                agent_snap.core_memory = core_mem.content

            # Recall memories (paginated retrieval)
            recall_mems_raw, _ = await self._memory_repo.get_recall_memories_paginated(
                agent_id,
                limit=500,
                simulation_id=sim_uuid,
            )
            recall_mems = recall_mems_raw
            for mem in recall_mems:
                agent_snap.recall_memories.append(
                    {
                        "summary": mem.summary,
                        "importance_score": mem.importance_score,
                        "event_type": mem.event_type,
                        "participants": mem.participants,
                        "embedding": mem.embedding,
                    }
                )

            # Journal entries
            entries, _ = await self._memory_repo.get_journal_entries(
                agent_id, limit=500, simulation_id=sim_uuid
            )
            for entry in entries:
                agent_snap.journal_entries.append(
                    {
                        "reflection_type": entry.reflection_type,
                        "content": entry.content,
                        "token_count": entry.token_count,
                    }
                )

            snapshot.agents[agent_id] = agent_snap

        # Relationships
        if self._relationship_repo:
            try:
                relationships = await self._relationship_repo.get_social_graph(sim_uuid)
                for rel in relationships:
                    snapshot.relationships.append(
                        {
                            "agent": rel.agent_id,
                            "target": rel.target_agent_id,
                            "sentiment": float(rel.sentiment_score)
                            if rel.sentiment_score
                            else None,
                            "trust": float(rel.trust_score) if rel.trust_score else None,
                            "interaction_count": rel.interaction_count,
                            "summary": rel.relationship_summary,
                        }
                    )
            except Exception:
                logger.warning("Failed to export relationships", exc_info=True)

        return snapshot.model_dump()

    async def _get_agent_ids(self, sim_uuid: Any = None) -> list[str]:
        """Get agent IDs scoped to the simulation.

        Tries the simulation record's agents_participated first,
        then falls back to all agents with core memory.
        """
        if sim_uuid is not None:
            row = await self._db.fetchrow(
                "SELECT agents_participated FROM simulations WHERE id = $1",
                sim_uuid,
            )
            if row and row["agents_participated"]:
                return sorted(row["agents_participated"])

        # Fallback: all agents with core memory
        rows = await self._db.fetch("SELECT DISTINCT agent_id FROM core_memory ORDER BY agent_id")
        return [r["agent_id"] for r in rows]


# ── Importer ──────────────────────────────────────────────────


class MemorySnapshotImporter:
    """Restore memory state from a snapshot."""

    def __init__(
        self,
        *,
        db: Database,
        memory_repo: MemoryRepo,
        core_memory_mgr: CoreMemoryManager,
        recall_memory_mgr: RecallMemoryManager,
        relationship_repo: RelationshipRepo | None = None,
        embedding_fn: Callable[[str], Coroutine[Any, Any, list[float]]] | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._db = db
        self._memory_repo = memory_repo
        self._core_memory = core_memory_mgr
        self._recall_memory = recall_memory_mgr
        self._relationship_repo = relationship_repo
        self._embedding_fn = embedding_fn
        self._token_counter = token_counter

    async def restore(
        self,
        snapshot_data: dict[str, Any],
        *,
        simulation_id: str | None = None,
        agents: list[str] | None = None,
        clear_first: bool = False,
    ) -> RestoreResult:
        """Restore memory state from a snapshot.

        Args:
            snapshot_data: Dict matching MemorySnapshot schema.
            simulation_id: Target simulation ID for relationships.
            agents: Optional list to filter which agents to restore.
            clear_first: If True, clear existing state before restore.

        Returns:
            RestoreResult with counts and warnings.
        """
        import uuid as uuid_mod

        snapshot = MemorySnapshot(**snapshot_data)
        result = RestoreResult()
        sim_uuid = uuid_mod.UUID(simulation_id) if simulation_id else None

        if snapshot.version not in (1, 2, 3):
            result.warnings.append(
                f"Snapshot version {snapshot.version} != expected {SNAPSHOT_VERSION}"
            )

        agent_ids = list(snapshot.agents.keys())
        if agents:
            agent_ids = [a for a in agent_ids if a in agents]

        for agent_id in agent_ids:
            agent_snap = snapshot.agents[agent_id]

            if clear_first:
                await self._clear_agent_state(agent_id, simulation_id=sim_uuid)

            # Restore core memory
            if agent_snap.core_memory:
                try:
                    if self._token_counter:
                        token_count = self._token_counter.count_tokens(agent_snap.core_memory)
                    else:
                        # Fallback: rough estimate (~1.3 tokens per word)
                        token_count = max(1, int(len(agent_snap.core_memory.split()) * 1.3))
                    await self._memory_repo.upsert_core_memory(
                        agent_id,
                        agent_snap.core_memory,
                        token_count,
                        reason="snapshot_restore",
                        simulation_id=sim_uuid,
                    )
                    result.core_memories_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Failed to restore core memory for {agent_id}: {exc}")

            # Restore recall memories
            for mem_data in agent_snap.recall_memories:
                try:
                    embedding = mem_data.get("embedding")
                    if not embedding and self._embedding_fn:
                        embedding = await self._embedding_fn(mem_data["summary"])
                    if not embedding:
                        result.warnings.append(
                            f"Skipping recall memory for {agent_id}: no embedding"
                        )
                        continue

                    from core.models import RecallMemoryCreate

                    await self._memory_repo.add_recall(
                        RecallMemoryCreate(
                            agent_id=agent_id,
                            summary=mem_data["summary"],
                            embedding=embedding,
                            event_type=mem_data.get("event_type"),
                            participants=mem_data.get("participants"),
                            importance_score=mem_data.get("importance_score", 0.5),
                            simulation_id=sim_uuid,
                        )
                    )
                    result.recall_memories_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Failed to restore recall memory for {agent_id}: {exc}")

            # Restore journal entries
            for entry_data in agent_snap.journal_entries:
                try:
                    from core.models import JournalEntryCreate

                    await self._memory_repo.create_journal_entry(
                        JournalEntryCreate(
                            agent_id=agent_id,
                            reflection_type=entry_data.get("reflection_type", "snapshot"),
                            content=entry_data["content"],
                            token_count=entry_data.get("token_count", 0),
                            simulation_id=sim_uuid,
                        )
                    )
                    result.journal_entries_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Failed to restore journal entry for {agent_id}: {exc}")

            result.agents_restored.append(agent_id)

        # Restore embodied state used by Minecraft/runtime context.
        if sim_uuid is not None:
            for agent_id, state in snapshot.agent_states.items():
                if agents and agent_id not in agents:
                    continue
                try:
                    await self._db.execute(
                        """INSERT INTO agent_internal_state
                           (agent_id, energy, satisfaction, boredom, frustration,
                            social_need, creative_need, simulation_id)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                           ON CONFLICT (agent_id, simulation_id)
                           DO UPDATE SET energy = $2, satisfaction = $3, boredom = $4,
                                         frustration = $5, social_need = $6,
                                         creative_need = $7""",
                        agent_id,
                        state.energy,
                        state.satisfaction,
                        state.boredom,
                        state.frustration,
                        state.social_need,
                        state.creativity,
                        sim_uuid,
                    )
                    result.agent_states_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Failed to restore agent state for {agent_id}: {exc}")

            for agent_id, account in snapshot.agent_accounts.items():
                if agents and agent_id not in agents:
                    continue
                try:
                    await self._db.execute(
                        """INSERT INTO agent_accounts
                           (agent_id, balance, weekly_allocation, total_earned,
                            total_spent, simulation_id)
                           VALUES ($1, $2, $3, $4, $5, $6)
                           ON CONFLICT (agent_id, simulation_id)
                           DO UPDATE SET balance = $2, weekly_allocation = $3,
                                         total_earned = $4, total_spent = $5""",
                        agent_id,
                        account.balance,
                        account.weekly_allocation,
                        account.total_earned,
                        account.total_spent,
                        sim_uuid,
                    )
                    result.agent_accounts_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Failed to restore account for {agent_id}: {exc}")

            for agent_id, goals in snapshot.agent_goals.items():
                if agents and agent_id not in agents:
                    continue
                for goal in goals:
                    source = goal.source if goal.source in _ALLOWED_GOAL_SOURCES else "assigned"
                    category = goal.category if goal.category in _ALLOWED_GOAL_CATEGORIES else None
                    try:
                        await self._db.execute(
                            """INSERT INTO agent_goals
                               (agent_id, goal, priority, status, source, category,
                                progress_notes, simulation_id)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                            agent_id,
                            goal.goal,
                            goal.priority,
                            goal.status,
                            source,
                            category,
                            goal.progress_notes,
                            sim_uuid,
                        )
                        result.goals_restored += 1
                    except Exception as exc:
                        result.warnings.append(f"Failed to restore goal for {agent_id}: {exc}")

        # Restore relationships
        if simulation_id and self._relationship_repo and snapshot.relationships:
            for rel_data in snapshot.relationships:
                agent = rel_data.get("agent", "")
                target = rel_data.get("target", "")
                if agents and (agent not in agents or target not in agents):
                    continue
                try:
                    await self._relationship_repo.upsert(
                        sim_uuid,
                        agent,
                        target,
                        sentiment_score=rel_data.get("sentiment"),
                        trust_score=rel_data.get("trust"),
                        interaction_count=rel_data.get("interaction_count", 0),
                        relationship_summary=rel_data.get("summary"),
                    )
                    result.relationships_restored += 1
                except Exception as exc:
                    result.warnings.append(
                        f"Failed to restore relationship {agent}->{target}: {exc}"
                    )

        return result

    async def _clear_agent_state(self, agent_id: str, simulation_id: Any | None = None) -> None:
        """Clear existing memory state for an agent.

        When ``simulation_id`` is provided, scope the delete to that
        simulation namespace; otherwise clear all rows for the agent (legacy
        behavior used by snapshot restore without a target simulation).
        """
        try:
            if simulation_id is not None:
                await self._db.execute(
                    "DELETE FROM recall_memory WHERE agent_id = $1 AND simulation_id = $2",
                    agent_id,
                    simulation_id,
                )
                await self._db.execute(
                    "DELETE FROM journal_entries WHERE agent_id = $1 AND simulation_id = $2",
                    agent_id,
                    simulation_id,
                )
                await self._db.execute(
                    "DELETE FROM agent_internal_state WHERE agent_id = $1 AND simulation_id = $2",
                    agent_id,
                    simulation_id,
                )
                await self._db.execute(
                    "DELETE FROM agent_accounts WHERE agent_id = $1 AND simulation_id = $2",
                    agent_id,
                    simulation_id,
                )
                await self._db.execute(
                    "DELETE FROM agent_goals WHERE agent_id = $1 AND simulation_id = $2",
                    agent_id,
                    simulation_id,
                )
            else:
                await self._db.execute("DELETE FROM recall_memory WHERE agent_id = $1", agent_id)
                await self._db.execute("DELETE FROM journal_entries WHERE agent_id = $1", agent_id)
                await self._db.execute(
                    "DELETE FROM agent_internal_state WHERE agent_id = $1",
                    agent_id,
                )
                await self._db.execute("DELETE FROM agent_accounts WHERE agent_id = $1", agent_id)
                await self._db.execute("DELETE FROM agent_goals WHERE agent_id = $1", agent_id)
            # Don't delete core_memory — it will be overwritten
        except Exception:
            logger.warning("Failed to clear state for %s", agent_id, exc_info=True)

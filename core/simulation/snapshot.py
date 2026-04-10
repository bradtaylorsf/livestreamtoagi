"""Complete simulation snapshot — export/import all simulation state.

Extends the memory-only snapshot system to cover world state, goals,
internal state, accounts, and relationships for full simulation cloning.
"""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 2


# ── Schema models ──────────────────────────────────────────────


class AgentStateSnapshot(BaseModel):
    """Internal state for a single agent."""

    energy: float = 0.7
    satisfaction: float = 0.5
    boredom: float = 0.2
    frustration: float = 0.0
    creativity: float = 0.5
    social_need: float = 0.5
    focus: float = 0.5
    extra: dict[str, Any] = Field(default_factory=dict)


class AgentAccountSnapshot(BaseModel):
    """Budget/account state for a single agent."""

    balance: float = 0.0
    weekly_allocation: float = 0.0
    total_earned: float = 0.0
    total_spent: float = 0.0


class AgentGoalSnapshot(BaseModel):
    """Single goal for an agent."""

    goal: str
    priority: int = 5
    status: str = "active"
    source: str = "snapshot"
    category: str | None = None
    progress_notes: str | None = None


class WorldChunkSnapshot(BaseModel):
    """Single world chunk."""

    name: str
    x_offset: int = 0
    y_offset: int = 0
    width: int = 16
    height: int = 16
    tile_data: Any = None
    objects: Any = None
    built_by: str | None = None
    description: str | None = None
    tileset_url: str | None = None


class RelationshipSnapshot(BaseModel):
    """Single relationship between two agents."""

    agent: str
    target: str
    sentiment: float | None = None
    trust: float | None = None
    interaction_count: int = 0
    summary: str | None = None


class AgentMemorySnapshot(BaseModel):
    """Memory state for a single agent."""

    core_memory: str = ""
    recall_memories: list[dict[str, Any]] = Field(default_factory=list)
    journal_entries: list[dict[str, Any]] = Field(default_factory=list)


class SimulationSnapshot(BaseModel):
    """Complete simulation state snapshot."""

    version: int = SNAPSHOT_VERSION
    source_simulation_id: str | None = None
    snapshot_at: str = ""
    agents: dict[str, AgentMemorySnapshot] = Field(default_factory=dict)
    agent_states: dict[str, AgentStateSnapshot] = Field(default_factory=dict)
    agent_accounts: dict[str, AgentAccountSnapshot] = Field(default_factory=dict)
    agent_goals: dict[str, list[AgentGoalSnapshot]] = Field(default_factory=dict)
    world_chunks: list[WorldChunkSnapshot] = Field(default_factory=list)
    relationships: list[RelationshipSnapshot] = Field(default_factory=list)


@dataclass
class SnapshotRestoreResult:
    """Summary of a complete snapshot restore."""

    simulation_id: str = ""
    agents_restored: list[str] = field(default_factory=list)
    core_memories_restored: int = 0
    recall_memories_restored: int = 0
    journal_entries_restored: int = 0
    relationships_restored: int = 0
    goals_restored: int = 0
    agent_states_restored: int = 0
    agent_accounts_restored: int = 0
    world_chunks_restored: int = 0
    warnings: list[str] = field(default_factory=list)


# ── Exporter ──────────────────────────────────────────────────


class SimulationSnapshotExporter:
    """Export complete simulation state to portable JSON."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def export(
        self,
        simulation_id: str,
        agents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export all state for a simulation.

        Uses REPEATABLE READ isolation to ensure a consistent snapshot
        even if the simulation is actively running during export.
        """
        sim_uuid = uuid_mod.UUID(simulation_id)
        snapshot = SimulationSnapshot(
            source_simulation_id=simulation_id,
            snapshot_at=datetime.now(UTC).isoformat(),
        )

        # Get agent list
        all_agent_ids = await self._get_agent_ids(sim_uuid)
        if agents:
            all_agent_ids = [a for a in all_agent_ids if a in agents]

        # Use REPEATABLE READ isolation for consistent snapshot reads.
        # This ensures all SELECT queries see a single consistent point-in-time,
        # even if the simulation is actively writing data during export.
        async with self._db.acquire() as conn:
            await conn.execute(
                "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            try:
                await self._export_state(conn, sim_uuid, all_agent_ids, snapshot)
            finally:
                await conn.execute("COMMIT")

        return snapshot.model_dump()

    async def _export_state(
        self,
        conn: Any,
        sim_uuid: uuid_mod.UUID,
        all_agent_ids: list[str],
        snapshot: SimulationSnapshot,
    ) -> None:
        """Export all state tables using the provided connection for consistency."""
        agent_id_set = set(all_agent_ids)

        # Export memories per agent
        for agent_id in all_agent_ids:
            agent_snap = AgentMemorySnapshot()

            # Core memory
            row = await conn.fetchrow(
                "SELECT content FROM core_memory WHERE agent_id = $1 AND simulation_id = $2",
                agent_id, sim_uuid,
            )
            if row:
                agent_snap.core_memory = row["content"]

            # Recall memories
            rows = await conn.fetch(
                """SELECT summary, importance_score, event_type, participants,
                          embedding, timestamp, recalled_count
                   FROM recall_memory WHERE agent_id = $1 AND simulation_id = $2
                   ORDER BY timestamp DESC LIMIT 500""",
                agent_id, sim_uuid,
            )
            for r in rows:
                emb = r["embedding"]
                if isinstance(emb, str):
                    emb = [float(x) for x in emb.strip("[]").split(",")]
                agent_snap.recall_memories.append({
                    "summary": r["summary"],
                    "importance_score": r["importance_score"],
                    "event_type": r["event_type"],
                    "participants": r["participants"],
                    "embedding": emb,
                    "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                    "recalled_count": r["recalled_count"] or 0,
                })

            # Journal entries
            rows = await conn.fetch(
                """SELECT reflection_type, content, token_count
                   FROM journal_entries WHERE agent_id = $1 AND simulation_id = $2
                   ORDER BY created_at DESC LIMIT 500""",
                agent_id, sim_uuid,
            )
            for r in rows:
                agent_snap.journal_entries.append({
                    "reflection_type": r["reflection_type"],
                    "content": r["content"],
                    "token_count": r["token_count"],
                })

            snapshot.agents[agent_id] = agent_snap

        # Export agent internal state
        rows = await conn.fetch(
            "SELECT * FROM agent_internal_state WHERE simulation_id = $1",
            sim_uuid,
        )
        for r in rows:
            d = dict(r)
            aid = d["agent_id"]
            if aid not in agent_id_set:
                continue
            snapshot.agent_states[aid] = AgentStateSnapshot(
                energy=float(d.get("energy", 0.7)),
                satisfaction=float(d.get("satisfaction", 0.5)),
                boredom=float(d.get("boredom", 0.2)),
                frustration=float(d.get("frustration", 0.0)),
                creativity=float(d.get("creativity", 0.5)),
                social_need=float(d.get("social_need", 0.5)),
                focus=float(d.get("focus", 0.5)),
            )

        # Export agent accounts
        rows = await conn.fetch(
            "SELECT * FROM agent_accounts WHERE simulation_id = $1",
            sim_uuid,
        )
        for r in rows:
            d = dict(r)
            aid = d["agent_id"]
            if aid not in agent_id_set:
                continue
            snapshot.agent_accounts[aid] = AgentAccountSnapshot(
                balance=float(d.get("balance", 0)),
                weekly_allocation=float(d.get("weekly_allocation", 0)),
                total_earned=float(d.get("total_earned", 0)),
                total_spent=float(d.get("total_spent", 0)),
            )

        # Export agent goals
        rows = await conn.fetch(
            """SELECT agent_id, goal, priority, status, source, category, progress_notes
               FROM agent_goals WHERE simulation_id = $1
               ORDER BY agent_id, priority""",
            sim_uuid,
        )
        for r in rows:
            aid = r["agent_id"]
            if aid not in agent_id_set:
                continue
            if aid not in snapshot.agent_goals:
                snapshot.agent_goals[aid] = []
            snapshot.agent_goals[aid].append(AgentGoalSnapshot(
                goal=r["goal"],
                priority=r["priority"],
                status=r["status"],
                source=r["source"],
                category=r["category"],
                progress_notes=r["progress_notes"],
            ))

        # Export world chunks
        rows = await conn.fetch(
            "SELECT * FROM world_chunks WHERE simulation_id = $1 ORDER BY id",
            sim_uuid,
        )
        for r in rows:
            d = dict(r)
            for key in ("tile_data", "objects"):
                if isinstance(d.get(key), str):
                    d[key] = json.loads(d[key])
            snapshot.world_chunks.append(WorldChunkSnapshot(
                name=d.get("name", ""),
                x_offset=d.get("x_offset", 0),
                y_offset=d.get("y_offset", 0),
                width=d.get("width", 16),
                height=d.get("height", 16),
                tile_data=d.get("tile_data"),
                objects=d.get("objects"),
                built_by=d.get("built_by"),
                description=d.get("description"),
                tileset_url=d.get("tileset_url"),
            ))

        # Export relationships
        rows = await conn.fetch(
            """SELECT agent_id, target_agent_id, sentiment_score, trust_score,
                      interaction_count, relationship_summary
               FROM agent_relationships WHERE simulation_id = $1""",
            sim_uuid,
        )
        for r in rows:
            agent = r["agent_id"]
            target = r["target_agent_id"]
            if agent not in agent_id_set or target not in agent_id_set:
                continue
            snapshot.relationships.append(RelationshipSnapshot(
                agent=agent,
                target=target,
                sentiment=float(r["sentiment_score"]) if r["sentiment_score"] else None,
                trust=float(r["trust_score"]) if r["trust_score"] else None,
                interaction_count=r["interaction_count"],
                summary=r["relationship_summary"],
            ))

    async def _get_agent_ids(self, sim_uuid: uuid_mod.UUID) -> list[str]:
        """Get agent IDs for a simulation.

        Falls back to querying core_memory if agents_participated is empty.
        NOTE: The fallback excludes agents that never wrote core_memory
        (e.g. Management, Alpha in some scenarios). For complete agent lists,
        ensure agents_participated is set on the simulation record.
        """
        row = await self._db.fetchrow(
            "SELECT agents_participated FROM simulations WHERE id = $1",
            sim_uuid,
        )
        if row and row["agents_participated"]:
            return sorted(row["agents_participated"])
        rows = await self._db.fetch(
            "SELECT DISTINCT agent_id FROM core_memory WHERE simulation_id = $1 ORDER BY agent_id",
            sim_uuid,
        )
        return [r["agent_id"] for r in rows]


# ── Importer ──────────────────────────────────────────────────


class SimulationSnapshotImporter:
    """Restore complete simulation state from a snapshot."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def restore(
        self,
        snapshot_data: dict[str, Any],
        target_simulation_id: str,
        *,
        agents: list[str] | None = None,
        clear_first: bool = False,
    ) -> SnapshotRestoreResult:
        """Restore all state from a snapshot into a target simulation."""
        snapshot = SimulationSnapshot(**snapshot_data)
        result = SnapshotRestoreResult(simulation_id=target_simulation_id)
        sim_uuid = uuid_mod.UUID(target_simulation_id)

        if snapshot.version not in (1, 2):
            result.warnings.append(
                f"Snapshot version {snapshot.version} != expected {SNAPSHOT_VERSION}"
            )

        agent_ids = list(snapshot.agents.keys())
        if agents:
            agent_ids = [a for a in agent_ids if a in agents]

        if clear_first:
            await self._clear_simulation_state(sim_uuid, agent_ids)

        # Restore memories
        for agent_id in agent_ids:
            agent_snap = snapshot.agents.get(agent_id)
            if not agent_snap:
                continue

            # Core memory
            if agent_snap.core_memory:
                try:
                    # Rough heuristic (~1.3 tokens per word). Intentionally approximate
                    # to avoid importing TokenCounter; restored memories may have slightly
                    # different token counts than the original.
                    token_count = int(len(agent_snap.core_memory.split()) * 1.3)
                    await self._db.execute(
                        """INSERT INTO core_memory
                           (agent_id, content, token_count, version, simulation_id)
                           VALUES ($1, $2, $3, 1, $4)
                           ON CONFLICT (agent_id, simulation_id)
                           DO UPDATE SET content = $2, token_count = $3,
                                     version = core_memory.version + 1,
                                     last_updated = NOW()""",
                        agent_id, agent_snap.core_memory, token_count, sim_uuid,
                    )
                    result.core_memories_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Core memory for {agent_id}: {exc}")

            # Recall memories
            for mem in agent_snap.recall_memories:
                try:
                    embedding = mem.get("embedding")
                    if not embedding:
                        result.warnings.append(f"Skipping recall for {agent_id}: no embedding")
                        continue
                    emb_str = "[" + ",".join(f"{v:.10f}" for v in embedding) + "]"
                    # Preserve original timestamp if available
                    ts = None
                    if mem.get("timestamp"):
                        ts = datetime.fromisoformat(mem["timestamp"])
                    await self._db.execute(
                        """INSERT INTO recall_memory
                           (agent_id, summary, embedding, event_type, participants,
                            importance_score, simulation_id, timestamp, recalled_count)
                           VALUES ($1, $2, $3::vector, $4, $5, $6, $7,
                                   COALESCE($8, NOW()), $9)""",
                        agent_id, mem["summary"], emb_str,
                        mem.get("event_type"), mem.get("participants"),
                        mem.get("importance_score", 0.5), sim_uuid,
                        ts, mem.get("recalled_count", 0),
                    )
                    result.recall_memories_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Recall for {agent_id}: {exc}")

            # Journal entries
            for entry in agent_snap.journal_entries:
                try:
                    await self._db.execute(
                        """INSERT INTO journal_entries
                           (agent_id, reflection_type, content, token_count, simulation_id)
                           VALUES ($1, $2, $3, $4, $5)""",
                        agent_id, entry.get("reflection_type", "snapshot"),
                        entry["content"], entry.get("token_count", 0), sim_uuid,
                    )
                    result.journal_entries_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Journal for {agent_id}: {exc}")

            result.agents_restored.append(agent_id)

        # Restore agent internal state
        for agent_id, state in snapshot.agent_states.items():
            if agents and agent_id not in agents:
                continue
            try:
                await self._db.execute(
                    """INSERT INTO agent_internal_state
                       (agent_id, energy, satisfaction, boredom, frustration,
                        creativity, social_need, focus, simulation_id)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                       ON CONFLICT (agent_id, simulation_id)
                       DO UPDATE SET energy = $2, satisfaction = $3, boredom = $4,
                                     frustration = $5, creativity = $6,
                                     social_need = $7, focus = $8""",
                    agent_id, state.energy, state.satisfaction, state.boredom,
                    state.frustration, state.creativity, state.social_need,
                    state.focus, sim_uuid,
                )
                result.agent_states_restored += 1
            except Exception as exc:
                result.warnings.append(f"Agent state for {agent_id}: {exc}")

        # Restore agent accounts
        for agent_id, acct in snapshot.agent_accounts.items():
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
                    agent_id, acct.balance, acct.weekly_allocation,
                    acct.total_earned, acct.total_spent, sim_uuid,
                )
                result.agent_accounts_restored += 1
            except Exception as exc:
                result.warnings.append(f"Account for {agent_id}: {exc}")

        # Restore goals
        for agent_id, goals in snapshot.agent_goals.items():
            if agents and agent_id not in agents:
                continue
            for g in goals:
                try:
                    await self._db.execute(
                        """INSERT INTO agent_goals
                           (agent_id, goal, priority, status, source, category,
                            progress_notes, simulation_id)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                        agent_id, g.goal, g.priority, g.status, g.source,
                        g.category, g.progress_notes, sim_uuid,
                    )
                    result.goals_restored += 1
                except Exception as exc:
                    result.warnings.append(f"Goal for {agent_id}: {exc}")

        # Restore world chunks
        for chunk in snapshot.world_chunks:
            try:
                td = json.dumps(chunk.tile_data) if chunk.tile_data else None
                objs = json.dumps(chunk.objects) if chunk.objects else None
                await self._db.execute(
                    """INSERT INTO world_chunks
                       (name, x_offset, y_offset, width, height, tile_data,
                        objects, built_by, description, tileset_url, simulation_id)
                       VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb,
                               $8, $9, $10, $11)""",
                    chunk.name, chunk.x_offset, chunk.y_offset,
                    chunk.width, chunk.height, td, objs,
                    chunk.built_by, chunk.description, chunk.tileset_url, sim_uuid,
                )
                result.world_chunks_restored += 1
            except Exception as exc:
                result.warnings.append(f"World chunk '{chunk.name}': {exc}")

        # Restore relationships
        for rel in snapshot.relationships:
            agent = rel.agent
            target = rel.target
            if agents and (agent not in agents or target not in agents):
                continue
            try:
                await self._db.execute(
                    """INSERT INTO agent_relationships
                       (agent_id, target_agent_id, sentiment_score, trust_score,
                        interaction_count, relationship_summary, simulation_id)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       ON CONFLICT (agent_id, target_agent_id, simulation_id)
                       DO UPDATE SET sentiment_score = $3, trust_score = $4,
                                     interaction_count = $5, relationship_summary = $6""",
                    agent, target, rel.sentiment, rel.trust,
                    rel.interaction_count, rel.summary, sim_uuid,
                )
                result.relationships_restored += 1
            except Exception as exc:
                result.warnings.append(f"Relationship {agent}->{target}: {exc}")

        return result

    async def _clear_simulation_state(
        self, sim_uuid: uuid_mod.UUID, agent_ids: list[str]
    ) -> None:
        """Clear existing state for agents in the target simulation."""
        # Tables with agent_id + simulation_id scope
        agent_tables = (
            "recall_memory", "journal_entries", "agent_goals",
            "core_memory", "agent_internal_state", "agent_accounts",
        )
        for agent_id in agent_ids:
            for table in agent_tables:
                try:
                    await self._db.execute(
                        f"DELETE FROM {table} WHERE agent_id = $1 AND simulation_id = $2",  # noqa: S608
                        agent_id, sim_uuid,
                    )
                except Exception:
                    logger.warning("Failed to clear %s for %s", table, agent_id, exc_info=True)
        # Clear agent relationships (uses agent_id, not just simulation_id)
        try:
            await self._db.execute(
                "DELETE FROM agent_relationships WHERE simulation_id = $1",
                sim_uuid,
            )
        except Exception:
            logger.warning("Failed to clear agent_relationships", exc_info=True)
        # Clear world chunks for this simulation
        try:
            await self._db.execute(
                "DELETE FROM world_chunks WHERE simulation_id = $1", sim_uuid,
            )
        except Exception:
            logger.warning("Failed to clear world_chunks", exc_info=True)

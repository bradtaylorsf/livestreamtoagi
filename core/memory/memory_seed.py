"""Apply a memory_seed config to a freshly created simulation.

Three modes:
- ``none``: write blank core_memory v1 for every agent and ensure no recall
  rows exist for the new simulation_id namespace.
- ``inherit``: copy core + recall from the source simulation's most-recent
  state into the target simulation.
- ``custom``: load a JSON/YAML snapshot file mapping agent_id -> core_memory
  + recall entries and bulk-apply them.
"""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from core.memory.snapshot import (
    MemorySnapshot,
    MemorySnapshotExporter,
    MemorySnapshotImporter,
    RestoreResult,
)
from core.models import MemorySeedConfig

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    from core.agent_registry import AgentRegistry
    from core.database import Database
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.recall_memory import RecallMemoryManager
    from core.memory.token_counter import TokenCounter
    from core.repos.memory_repo import MemoryRepo
    from core.repos.relationship_repo import RelationshipRepo

logger = logging.getLogger(__name__)


class MemorySeedApplier:
    """Apply a MemorySeedConfig to a target simulation."""

    def __init__(
        self,
        *,
        db: Database,
        memory_repo: MemoryRepo,
        core_memory_mgr: CoreMemoryManager,
        recall_memory_mgr: RecallMemoryManager,
        agent_registry: AgentRegistry,
        token_counter: TokenCounter | None = None,
        relationship_repo: RelationshipRepo | None = None,
        embedding_fn: Callable[[str], Coroutine[Any, Any, list[float]]] | None = None,
    ) -> None:
        self._db = db
        self._memory_repo = memory_repo
        self._core_memory = core_memory_mgr
        self._recall_memory = recall_memory_mgr
        self._agents = agent_registry
        self._token_counter = token_counter
        self._relationship_repo = relationship_repo
        self._embedding_fn = embedding_fn

    async def apply(
        self,
        config: MemorySeedConfig,
        target_simulation_id: uuid_mod.UUID,
    ) -> RestoreResult:
        if config.mode == "none":
            return await self._apply_none(target_simulation_id)
        if config.mode == "inherit":
            assert config.inherit_from is not None
            return await self._apply_inherit(config.inherit_from, target_simulation_id)
        if config.mode == "custom":
            assert config.custom_file is not None
            return await self._apply_custom(config.custom_file, target_simulation_id)
        raise ValueError(f"Unknown memory_seed mode: {config.mode!r}")

    async def _apply_none(self, target_sim_id: uuid_mod.UUID) -> RestoreResult:
        result = RestoreResult()
        # Make sure no recall rows exist for this fresh sim namespace.
        await self._db.execute(
            "DELETE FROM recall_memory WHERE simulation_id = $1",
            target_sim_id,
        )
        for agent in self._agents.get_all_agents():
            try:
                token_count = self._count_tokens("")
                await self._memory_repo.upsert_core_memory(
                    agent.id,
                    "",
                    token_count,
                    reason="memory_seed_none",
                    simulation_id=target_sim_id,
                )
                result.core_memories_restored += 1
                result.agents_restored.append(agent.id)
            except Exception as exc:
                result.warnings.append(f"Failed to write blank core memory for {agent.id}: {exc}")
        return result

    async def _apply_inherit(
        self,
        source_simulation_id: str,
        target_sim_id: uuid_mod.UUID,
    ) -> RestoreResult:
        try:
            source_uuid = uuid_mod.UUID(source_simulation_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"memory_seed inherit_from is not a valid UUID: {source_simulation_id!r}"
            ) from exc

        row = await self._db.fetchrow("SELECT id FROM simulations WHERE id = $1", source_uuid)
        if row is None:
            raise ValueError(
                f"memory_seed inherit_from simulation not found: {source_simulation_id}"
            )

        exporter = MemorySnapshotExporter(
            db=self._db,
            memory_repo=self._memory_repo,
            relationship_repo=self._relationship_repo,
        )
        snapshot_data = await exporter.export(source_simulation_id)
        # Force the importer to apply at our target simulation_id.
        importer = self._build_importer()
        return await importer.restore(
            snapshot_data,
            simulation_id=str(target_sim_id),
            clear_first=True,
        )

    async def _apply_custom(
        self,
        file_path: str,
        target_sim_id: uuid_mod.UUID,
    ) -> RestoreResult:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"memory_seed custom_file not found: {file_path}")

        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            raw = yaml.safe_load(text)
        else:
            raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError(f"memory_seed custom_file must be a mapping, got {type(raw).__name__}")

        # Validate against the snapshot schema (extra fields ignored).
        snapshot = MemorySnapshot(**raw)

        known_ids = {a.id for a in self._agents.get_all_agents()}
        unknown = [aid for aid in snapshot.agents if aid not in known_ids]
        if unknown:
            raise ValueError(
                f"memory_seed custom_file references unknown agent_ids: "
                f"{sorted(unknown)} (known: {sorted(known_ids)})"
            )

        importer = self._build_importer()
        return await importer.restore(
            snapshot.model_dump(),
            simulation_id=str(target_sim_id),
            clear_first=True,
        )

    def _build_importer(self) -> MemorySnapshotImporter:
        return MemorySnapshotImporter(
            db=self._db,
            memory_repo=self._memory_repo,
            core_memory_mgr=self._core_memory,
            recall_memory_mgr=self._recall_memory,
            relationship_repo=self._relationship_repo,
            embedding_fn=self._embedding_fn,
            token_counter=self._token_counter,
        )

    def _count_tokens(self, content: str) -> int:
        if self._token_counter is not None:
            return self._token_counter.count_tokens(content)
        return max(1, int(len(content.split()) * 1.3))

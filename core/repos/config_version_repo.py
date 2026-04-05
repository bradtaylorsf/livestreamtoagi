"""Repository for versioned agent config and conversation parameters."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from core.models import AgentPromptVersion, ConversationParamVersion, ActiveConfig

if TYPE_CHECKING:
    import uuid

    from core.database import Database

logger = logging.getLogger(__name__)


class ConfigVersionRepo:
    """CRUD operations for versioned agent configs and conversation params."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ── Agent prompt versions ────────────────────────────────

    async def get_active_prompt(self, agent_id: str) -> AgentPromptVersion | None:
        """Get the active prompt version for an agent."""
        row = await self.db.fetchrow(
            """SELECT apv.* FROM agent_prompt_versions apv
               JOIN active_config ac ON ac.agent_id = apv.agent_id
                   AND ac.prompt_version = apv.version
               WHERE apv.agent_id = $1""",
            agent_id,
        )
        if row is None:
            return None
        return AgentPromptVersion(**_parse_jsonb_row(dict(row)))

    async def get_prompt_version(
        self, agent_id: str, version: int
    ) -> AgentPromptVersion | None:
        """Get a specific prompt version."""
        row = await self.db.fetchrow(
            """SELECT * FROM agent_prompt_versions
               WHERE agent_id = $1 AND version = $2""",
            agent_id,
            version,
        )
        if row is None:
            return None
        return AgentPromptVersion(**_parse_jsonb_row(dict(row)))

    async def get_prompt_history(
        self, agent_id: str, *, limit: int = 20
    ) -> list[AgentPromptVersion]:
        """Get version history for an agent's prompts."""
        rows = await self.db.fetch(
            """SELECT * FROM agent_prompt_versions
               WHERE agent_id = $1
               ORDER BY version DESC
               LIMIT $2""",
            agent_id,
            limit,
        )
        return [AgentPromptVersion(**_parse_jsonb_row(dict(r))) for r in rows]

    async def insert_prompt_version(
        self,
        agent_id: str,
        *,
        system_prompt: str,
        behaviors: dict[str, Any],
        config_params: dict[str, Any],
        change_reason: str | None = None,
        source: str = "manual",
        eval_run_id: uuid.UUID | None = None,
    ) -> AgentPromptVersion:
        """Insert a new prompt version (auto-increments version number)."""
        # Get next version number
        current_max = await self.db.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM agent_prompt_versions WHERE agent_id = $1",
            agent_id,
        )
        next_version = current_max + 1

        row = await self.db.fetchrow(
            """INSERT INTO agent_prompt_versions
               (agent_id, version, system_prompt, behaviors, config_params,
                change_reason, source, eval_run_id)
               VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)
               RETURNING *""",
            agent_id,
            next_version,
            system_prompt,
            json.dumps(behaviors),
            json.dumps(config_params),
            change_reason,
            source,
            eval_run_id,
        )
        return AgentPromptVersion(**_parse_jsonb_row(dict(row)))

    async def set_active_prompt_version(
        self, agent_id: str, version: int
    ) -> None:
        """Point the active config to a specific prompt version."""
        await self.db.execute(
            """INSERT INTO active_config (agent_id, prompt_version, conversation_param_version)
               VALUES ($1, $2, 1)
               ON CONFLICT (agent_id)
               DO UPDATE SET prompt_version = $2""",
            agent_id,
            version,
        )

    async def rollback_prompt(self, agent_id: str, version: int) -> None:
        """Rollback to a previous prompt version (just updates the pointer)."""
        # Verify the version exists
        exists = await self.db.fetchval(
            "SELECT 1 FROM agent_prompt_versions WHERE agent_id = $1 AND version = $2",
            agent_id,
            version,
        )
        if not exists:
            raise ValueError(
                f"Version {version} not found for agent {agent_id}"
            )
        await self.set_active_prompt_version(agent_id, version)

    # ── Conversation param versions ──────────────────────────

    async def get_active_conversation_params(self) -> ConversationParamVersion | None:
        """Get the active conversation params version.

        Uses the conversation_param_version from any active_config row
        (they should all agree).
        """
        row = await self.db.fetchrow(
            """SELECT cpv.* FROM conversation_param_versions cpv
               JOIN active_config ac ON ac.conversation_param_version = cpv.version
               LIMIT 1"""
        )
        if row is None:
            return None
        return ConversationParamVersion(**_parse_jsonb_row(dict(row)))

    async def get_conversation_param_version(
        self, version: int
    ) -> ConversationParamVersion | None:
        """Get a specific conversation param version."""
        row = await self.db.fetchrow(
            "SELECT * FROM conversation_param_versions WHERE version = $1",
            version,
        )
        if row is None:
            return None
        return ConversationParamVersion(**_parse_jsonb_row(dict(row)))

    async def get_conversation_param_history(
        self, *, limit: int = 20
    ) -> list[ConversationParamVersion]:
        """Get version history for conversation params."""
        rows = await self.db.fetch(
            """SELECT * FROM conversation_param_versions
               ORDER BY version DESC
               LIMIT $1""",
            limit,
        )
        return [ConversationParamVersion(**_parse_jsonb_row(dict(r))) for r in rows]

    async def insert_conversation_param_version(
        self,
        *,
        params: dict[str, Any],
        change_reason: str | None = None,
        source: str = "manual",
        eval_run_id: uuid.UUID | None = None,
    ) -> ConversationParamVersion:
        """Insert a new conversation param version."""
        current_max = await self.db.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM conversation_param_versions"
        )
        next_version = current_max + 1

        row = await self.db.fetchrow(
            """INSERT INTO conversation_param_versions
               (version, params, change_reason, source, eval_run_id)
               VALUES ($1, $2::jsonb, $3, $4, $5)
               RETURNING *""",
            next_version,
            json.dumps(params),
            change_reason,
            source,
            eval_run_id,
        )
        return ConversationParamVersion(**_parse_jsonb_row(dict(row)))

    async def set_active_conversation_version(self, version: int) -> None:
        """Update all active_config rows to point to a conversation param version."""
        await self.db.execute(
            "UPDATE active_config SET conversation_param_version = $1",
            version,
        )

    async def rollback_conversation_params(self, version: int) -> None:
        """Rollback to a previous conversation param version."""
        exists = await self.db.fetchval(
            "SELECT 1 FROM conversation_param_versions WHERE version = $1",
            version,
        )
        if not exists:
            raise ValueError(f"Conversation param version {version} not found")
        await self.set_active_conversation_version(version)

    # ── Active config ────────────────────────────────────────

    async def get_active_config(self, agent_id: str) -> ActiveConfig | None:
        """Get the active config pointer for an agent."""
        row = await self.db.fetchrow(
            "SELECT * FROM active_config WHERE agent_id = $1",
            agent_id,
        )
        if row is None:
            return None
        return ActiveConfig(**dict(row))

    async def get_all_active_configs(self) -> list[ActiveConfig]:
        """Get all active config pointers."""
        rows = await self.db.fetch("SELECT * FROM active_config ORDER BY agent_id")
        return [ActiveConfig(**dict(r)) for r in rows]


def _parse_jsonb_row(row: dict) -> dict:
    """Parse JSONB string fields into dicts."""
    for key in ("behaviors", "config_params", "params"):
        val = row.get(key)
        if isinstance(val, str):
            row[key] = json.loads(val)
    return row

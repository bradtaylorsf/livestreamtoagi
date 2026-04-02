"""CoreMemoryManager — CRUD for Tier 1 core memory with token limits and versioning."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import CoreMemory, CoreMemoryHistory
    from core.repos.memory_repo import MemoryRepo

    from .token_counter import TokenCounter

TOKEN_LIMIT = 3000

VALID_SECTIONS = frozenset(
    {"relationships", "key_learnings", "goals", "running_jokes"}
)

# Maps update section names → markdown heading text
_SECTION_HEADINGS: dict[str, str] = {
    "relationships": "My relationships",
    "key_learnings": "Key learnings",
    "goals": "Current goals",
    "running_jokes": "Running jokes / lore",
}

CORE_MEMORY_TEMPLATE = """\
## My Core Memory (last updated: {date})

### Who I am
{identity}

### My relationships
- Vera: Not yet established
- Rex: Not yet established
- Aurora: Not yet established
- Pixel: Not yet established
- Fork: Not yet established
- Sentinel: Not yet established
- Grok: Not yet established
- Alpha: Not yet established
- The Overseer: Not yet established

### Key learnings
- No learnings recorded yet

### Current goals
- No goals set yet

### Running jokes / lore
- No running jokes yet
"""


class CoreMemoryExceededError(Exception):
    """Raised when an update would push core memory over the token limit."""


class InvalidSectionError(ValueError):
    """Raised when an invalid section name is provided."""


class CoreMemoryManager:
    """Manages Tier 1 core memory: CRUD, token counting, and version tracking."""

    def __init__(self, memory_repo: MemoryRepo, token_counter: TokenCounter) -> None:
        self._repo = memory_repo
        self._tc = token_counter

    async def get_core_memory(self, agent_id: str) -> str | None:
        """Return the full core memory markdown string, or None if not found."""
        record = await self._repo.get_core_memory(agent_id)
        return record.content if record else None

    async def update_core_memory(
        self,
        agent_id: str,
        section: str,
        content: str,
        reason: str,
    ) -> CoreMemory:
        """Update a specific section of an agent's core memory.

        Raises InvalidSectionError for unknown sections.
        Raises CoreMemoryExceededError if the result exceeds TOKEN_LIMIT.
        """
        if section not in VALID_SECTIONS:
            raise InvalidSectionError(
                f"Invalid section {section!r}. Must be one of: {sorted(VALID_SECTIONS)}"
            )

        record = await self._repo.get_core_memory(agent_id)
        if record is None:
            raise ValueError(f"No core memory found for agent {agent_id!r}")

        new_content = _replace_section(record.content, section, content)

        token_count = self._tc.count_tokens(new_content)
        if token_count > TOKEN_LIMIT:
            raise CoreMemoryExceededError(
                f"Update would result in {token_count} tokens "
                f"(limit: {TOKEN_LIMIT})"
            )

        return await self._repo.upsert_core_memory(
            agent_id, new_content, token_count, reason
        )

    async def get_token_count(self, agent_id: str) -> int:
        """Return the stored token count for an agent's core memory."""
        record = await self._repo.get_core_memory(agent_id)
        if record is None:
            raise ValueError(f"No core memory found for agent {agent_id!r}")
        return record.token_count

    async def get_history(
        self, agent_id: str, limit: int = 50
    ) -> list[CoreMemoryHistory]:
        """Return version history for an agent's core memory."""
        history = await self._repo.get_core_memory_history(agent_id)
        return history[:limit]

    async def initialize_agent_memory(
        self, agent_id: str, identity: str
    ) -> CoreMemory:
        """Create initial core memory from template with identity filled in."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = CORE_MEMORY_TEMPLATE.format(date=date_str, identity=identity)
        token_count = self._tc.count_tokens(content)
        return await self._repo.upsert_core_memory(
            agent_id, content, token_count, "initial_creation"
        )


# ── Markdown section helpers ───────────────────────────────────────

# Pattern to match ### headings and their content (up to next ### or end)
_SECTION_RE = re.compile(
    r"(### (?P<heading>[^\n]+)\n)(?P<body>.*?)(?=\n### |\Z)",
    re.DOTALL,
)


def _replace_section(full_content: str, section: str, new_body: str) -> str:
    """Replace the body of a markdown ### section, preserving all other sections."""
    target_heading = _SECTION_HEADINGS[section]

    def replacer(m: re.Match[str]) -> str:
        if m.group("heading").strip() == target_heading:
            return m.group(1) + new_body.rstrip("\n") + "\n"
        return m.group(0)

    result = _SECTION_RE.sub(replacer, full_content)
    if result == full_content:
        raise ValueError(f"Section heading '### {target_heading}' not found in content")
    return result

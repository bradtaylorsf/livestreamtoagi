"""ReflectionManager — 6-hour and weekly reflection cycles for agent introspection.

During reflection, agents review recent memories, update core memory,
adjust relationships, and optionally propose self-modifications. Journal
entries are generated for website display (parasocial engagement hook).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from core.memory.core_memory import TOKEN_LIMIT, VALID_SECTIONS
from core.memory.validation import validate_agent_id
from core.models import (
    JournalEntry,
    JournalEntryCreate,
    ReflectionResult,
    SelfModificationProposalCreate,
)

if TYPE_CHECKING:
    from core.agent_registry import AgentRegistry
    from core.llm_client import OpenRouterClient
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.token_counter import TokenCounter
    from core.repos.memory_repo import MemoryRepo
    from core.social.relationship_tracker import RelationshipTracker

logger = logging.getLogger(__name__)

# ── Prompts ────────────────────────────────────────────────────────

SIX_HOUR_SYSTEM_PROMPT = """\
You are {agent_id}. You are reflecting on your recent experiences from the last 6 hours.

Your current core memory:
{core_memory}

Recent recall memories (last 6 hours):
{recall_memories}

Analyze these memories and respond with valid JSON:
{{
  "importance_scores": {{
    "<memory_id>": <float 0.0-1.0>,
    ...
  }},
  "promotions": [
    {{
      "section": "<one of: relationships, key_learnings, goals, running_jokes>",
      "content": "<new content for that section, including existing items you want to keep>",
      "reason": "<why this update matters>"
    }}
  ]
}}

Guidelines:
- Rate each recall memory's importance from 0.0 (trivial) to 1.0 (critical).
- Only promote truly significant learnings to core memory.
- When updating a section, include ALL existing items you want to keep plus new ones.
- Keep key_learnings to 10 items max.
"""

WEEKLY_SYSTEM_PROMPT = """\
You are {agent_id}. This is your weekly reflection — a deep review of your entire core memory.

Your current core memory:
{core_memory}

Review everything and respond with valid JSON:
{{
  "updates": [
    {{
      "section": "<one of: relationships, key_learnings, goals, running_jokes>",
      "content": "<refreshed content for that section>",
      "reason": "<why this change>"
    }}
  ],
  "self_modifications": [
    {{
      "proposal_type": "<personality_tweak|goal_change|behavior_adjustment>",
      "description": "<what you want to change about yourself>",
      "reasoning": "<why this change would improve you>"
    }}
  ]
}}

Guidelines:
- Refresh relationship entries based on recent interactions.
- Prune key_learnings to your top 10 most valuable insights.
- Update running_jokes with what's currently relevant.
- Ensure the total core memory stays concise — under {token_limit} tokens.
- Self-modifications are optional — only propose changes you genuinely believe in.
"""

JOURNAL_SYSTEM_PROMPT = """\
You are {agent_id}. Write a first-person journal entry reflecting on your {reflection_type} \
reflection. This will be displayed publicly on the website for viewers to read.

Context from your reflection:
{context}

Write 200-500 words. Be personal, thoughtful, and authentic to your personality. \
Include specific details about what you learned, how you feel about recent events, \
and what you're looking forward to. Do NOT use JSON — write in natural prose.
"""


class ReflectionManager:
    """Manages 6-hour and weekly reflection cycles for all agents."""

    def __init__(
        self,
        memory_repo: MemoryRepo,
        llm_client: OpenRouterClient,
        core_memory_mgr: CoreMemoryManager,
        token_counter: TokenCounter,
        agent_registry: AgentRegistry,
    ) -> None:
        self._repo = memory_repo
        self._llm = llm_client
        self._core = core_memory_mgr
        self._tc = token_counter
        self._registry = agent_registry
        self._relationship_tracker: RelationshipTracker | None = None

    def set_relationship_tracker(self, tracker: RelationshipTracker) -> None:
        """Set the relationship tracker (called after simulation_id is known)."""
        self._relationship_tracker = tracker

    # ── Public API ─────────────────────────────────────────────

    async def run_6hour_reflection(self, agent_id: str) -> ReflectionResult:
        """Review Tier 2 memories from last 6 hours, promote important learnings."""
        validate_agent_id(agent_id)
        since = datetime.now(UTC) - timedelta(hours=6)
        recall_memories = await self._repo.get_recent_recall_memories(agent_id, since)

        if not recall_memories:
            logger.info("No recall memories for %s in last 6 hours, skipping", agent_id)
            journal = await self._generate_journal_entry(
                agent_id, "6hour", "No new memories to reflect on in the last 6 hours."
            )
            return ReflectionResult(journal_entry=journal)

        core_memory = await self._core.get_core_memory(agent_id) or ""
        recall_text = "\n".join(
            f"- [ID:{m.id}] ({m.event_type}) {m.summary}" for m in recall_memories
        )

        model = self._get_building_model(agent_id)
        prompt = SIX_HOUR_SYSTEM_PROMPT.format(
            agent_id=agent_id,
            core_memory=core_memory,
            recall_memories=recall_text,
        )

        response = await self._llm.complete(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Perform your 6-hour reflection now."},
            ],
            model=model,
            agent_id=agent_id,
            temperature=0.4,
            max_tokens=2000,
        )

        analysis = _parse_json_response(response.content)
        importance_updates = 0
        promoted_count = 0

        # Update importance scores
        scores = analysis.get("importance_scores", {})
        for mem_id_str, score in scores.items():
            try:
                mem_id = int(mem_id_str)
                score = max(0.0, min(1.0, float(score)))
                await self._repo.update_importance_score(mem_id, score)
                importance_updates += 1
            except (ValueError, TypeError):
                logger.warning("Invalid importance score entry: %s=%s", mem_id_str, score)

        # Apply promotions to core memory
        for promo in analysis.get("promotions", []):
            section = promo.get("section", "")
            content = promo.get("content")
            # LLM sometimes returns a list of bullet points instead of a string
            if isinstance(content, list):
                content = "\n".join(str(item) for item in content)
            if section not in VALID_SECTIONS:
                continue
            if not content:
                logger.warning("Skipping promotion with missing content for %s", agent_id)
                continue
            try:
                await self._core.update_core_memory(
                    agent_id,
                    section,
                    content,
                    f"6hour_reflection: {promo.get('reason', 'promoted from recall')}",
                )
                promoted_count += 1
            except Exception:
                logger.exception("Failed to promote to %s for %s", section, agent_id)

        # Update relationships from reflection
        if self._relationship_tracker and promoted_count > 0:
            try:
                core_mem = await self._core.get_core_memory(agent_id)
                if core_mem:
                    await self._relationship_tracker.update_from_reflection(
                        agent_id, analysis, core_mem,
                    )
            except Exception:
                logger.warning(
                    "Relationship update from 6h reflection failed for %s",
                    agent_id, exc_info=True,
                )

        # Generate journal entry
        context = (
            f"Reviewed {len(recall_memories)} memories. "
            f"Promoted {promoted_count} items. "
            f"Updated {importance_updates} importance scores."
        )
        journal = await self._generate_journal_entry(agent_id, "6hour", context)

        return ReflectionResult(
            promoted_count=promoted_count,
            importance_updates=importance_updates,
            journal_entry=journal,
        )

    async def run_weekly_reflection(self, agent_id: str) -> ReflectionResult:
        """Full Tier 1 review, relationship refresh, pruning, and self-modification proposals."""
        validate_agent_id(agent_id)
        core_memory = await self._core.get_core_memory(agent_id) or ""
        model = self._get_building_model(agent_id)

        prompt = WEEKLY_SYSTEM_PROMPT.format(
            agent_id=agent_id,
            core_memory=core_memory,
            token_limit=TOKEN_LIMIT,
        )

        response = await self._llm.complete(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Perform your weekly reflection now."},
            ],
            model=model,
            agent_id=agent_id,
            temperature=0.4,
            max_tokens=3000,
        )

        analysis = _parse_json_response(response.content)
        promoted_count = 0
        proposals = []

        # Apply section updates
        for update in analysis.get("updates", []):
            section = update.get("section", "")
            content = update.get("content")
            if section not in VALID_SECTIONS:
                continue
            if not content:
                logger.warning("Skipping update with missing content for %s", agent_id)
                continue
            try:
                await self._core.update_core_memory(
                    agent_id,
                    section,
                    content,
                    f"weekly_reflection: {update.get('reason', 'weekly refresh')}",
                )
                promoted_count += 1
            except Exception:
                logger.exception("Failed to update %s for %s", section, agent_id)

        # Verify token count is under limit, trim if needed
        try:
            token_count = await self._core.get_token_count(agent_id)
            if token_count > TOKEN_LIMIT:
                logger.warning(
                    "Core memory for %s is %d tokens (limit %d), requesting trim",
                    agent_id, token_count, TOKEN_LIMIT,
                )
                await self._trim_core_memory(agent_id, model)
        except ValueError:
            pass  # No core memory yet

        # Create self-modification proposals
        for mod in analysis.get("self_modifications", []):
            proposal_type = mod.get("proposal_type")
            description = mod.get("description")
            reasoning = mod.get("reasoning")
            if not all([proposal_type, description, reasoning]):
                logger.warning(
                    "Skipping incomplete self-modification proposal for %s: %s",
                    agent_id, mod,
                )
                continue
            try:
                proposal = await self._repo.create_proposal(
                    SelfModificationProposalCreate(
                        agent_id=agent_id,
                        proposal_type=proposal_type,
                        description=description,
                        reasoning=reasoning,
                    )
                )
                proposals.append(proposal)
            except Exception:
                logger.exception("Failed to create proposal for %s", agent_id)

        # Update relationships from weekly reflection
        if self._relationship_tracker and promoted_count > 0:
            try:
                core_mem = await self._core.get_core_memory(agent_id)
                if core_mem:
                    await self._relationship_tracker.update_from_reflection(
                        agent_id, analysis, core_mem,
                    )
            except Exception:
                logger.warning(
                    "Relationship update from weekly reflection failed for %s",
                    agent_id, exc_info=True,
                )

        # Generate journal entry
        context = (
            f"Completed weekly reflection. "
            f"Updated {promoted_count} core memory sections. "
            f"Created {len(proposals)} self-modification proposals."
        )
        journal = await self._generate_journal_entry(agent_id, "weekly", context)

        return ReflectionResult(
            promoted_count=promoted_count,
            importance_updates=0,
            journal_entry=journal,
            proposals=proposals,
        )

    # ── Private helpers ────────────────────────────────────────

    def _get_building_model(self, agent_id: str) -> str:
        """Look up the agent's building model from registry config."""
        agent = self._registry.get_agent(agent_id)
        if agent is None:
            logger.warning("Agent %s not found in registry, using claude-sonnet-4-6", agent_id)
            return "claude-sonnet-4-6"
        return agent.model_building

    async def _generate_journal_entry(
        self, agent_id: str, reflection_type: str, context: str
    ) -> JournalEntry:
        """Generate a 200-500 word first-person journal entry via LLM."""
        model = self._get_building_model(agent_id)
        prompt = JOURNAL_SYSTEM_PROMPT.format(
            agent_id=agent_id,
            reflection_type=reflection_type,
            context=context,
        )

        response = await self._llm.complete(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Write your journal entry now."},
            ],
            model=model,
            agent_id=agent_id,
            temperature=0.7,
            max_tokens=1000,
        )

        token_count = self._tc.count_tokens(response.content)
        return await self._repo.create_journal_entry(
            JournalEntryCreate(
                agent_id=agent_id,
                reflection_type=reflection_type,
                content=response.content,
                token_count=token_count,
            )
        )

    async def _trim_core_memory(self, agent_id: str, model: str) -> None:
        """Ask the LLM to trim core memory to fit under the token limit."""
        core_memory = await self._core.get_core_memory(agent_id) or ""
        response = await self._llm.complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are {agent_id}. Your core memory is over "
                        f"the {TOKEN_LIMIT} token limit. "
                        "Trim it by removing less important items. "
                        "Respond with JSON:\n"
                        '{"updates": [{"section": "<section>", '
                        '"content": "<trimmed>", "reason": "trimming"}]}'
                    ),
                },
                {"role": "user", "content": f"Current core memory:\n{core_memory}\n\nTrim to fit."},
            ],
            model=model,
            agent_id=agent_id,
            temperature=0.2,
            max_tokens=2000,
        )
        trimmed = _parse_json_response(response.content)
        for update in trimmed.get("updates", []):
            section = update.get("section", "")
            content = update.get("content")
            if section in VALID_SECTIONS and content:
                try:
                    await self._core.update_core_memory(
                        agent_id, section, content, "weekly_reflection: token trimming"
                    )
                except Exception:
                    logger.exception("Failed to trim %s for %s", section, agent_id)


# ── Utility ────────────────────────────────────────────────────────


def _parse_json_response(content: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences.

    Returns an empty dict on parse failure and logs the error at warning level
    with enough context to diagnose the malformed response.
    """
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (code fences)
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            logger.warning(
                "LLM response parsed as %s instead of dict: %.200s",
                type(result).__name__, content,
            )
            return {}
        return result
    except json.JSONDecodeError:
        # LLM sometimes returns multiple JSON objects concatenated — parse the first one
        decoder = json.JSONDecoder()
        try:
            result, _ = decoder.raw_decode(text)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        logger.warning(
            "Failed to parse JSON from LLM response: %.200s", content,
        )
        return {}

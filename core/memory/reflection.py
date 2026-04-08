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
    from core.agent_goals import AgentGoalManager
    from core.agent_registry import AgentRegistry
    from core.agent_state import AgentStateManager
    from core.llm_client import OpenRouterClient
    from core.memory.core_memory import CoreMemoryManager
    from core.memory.dreams import DreamManager
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

GOAL_GENERATION_PROMPT = """\
You are {agent_id}. Based on your personality, current goals, recent experiences, and internal state, \
propose 1-2 NEW goals that feel authentic to your character.

Think about:
- What do you WANT to do next? (not what you were told to do)
- What's bothering you that you want to fix?
- What creative project excites you?
- Is there a relationship you want to improve or challenge?

Current internal state: {agent_state}
Current goals: {current_goals}
Recent memories: {recent_memories}
Personality summary: {personality_summary}

Respond with valid JSON:
{{
  "goals": [
    {{
      "goal": "<specific, achievable goal — not 'be better' but 'build a reading nook'>",
      "category": "<one of: creative, social, economic, personal, competitive>",
      "priority": <1-5, where 1 is most urgent>
    }}
  ]
}}

Category guidelines:
- creative: Build something, design something, create content
- social: Strengthen/challenge a relationship, form alliance, resolve conflict
- economic: Earn more, save budget, invest in a project
- personal: Learn a skill, change a habit, explore the world
- competitive: Outperform another agent, win a challenge, prove a point

Generate goals that are DIFFERENT from your current goals. Be specific.
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
        goal_manager: AgentGoalManager | None = None,
        agent_state_manager: AgentStateManager | None = None,
        dream_manager: DreamManager | None = None,
        simulation_id: object | None = None,
    ) -> None:
        self._repo = memory_repo
        self._llm = llm_client
        self._core = core_memory_mgr
        self._tc = token_counter
        self._registry = agent_registry
        self._relationship_tracker: RelationshipTracker | None = None
        self._goal_manager = goal_manager
        self._agent_state_manager = agent_state_manager
        self._dream_manager = dream_manager
        self._simulation_id = simulation_id

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
            simulation_id=self._simulation_id,
        )

        analysis = _parse_json_response(response.content)
        importance_updates = 0
        promoted_count = 0

        # Update importance scores
        scores = analysis.get("importance_scores", {})
        for mem_id_str, score in scores.items():
            try:
                # LLM sometimes returns "ID:2" or "id_2" instead of "2"
                cleaned_id = str(mem_id_str).strip()
                for prefix in ("ID:", "id:", "ID_", "id_", "#"):
                    if cleaned_id.startswith(prefix):
                        cleaned_id = cleaned_id[len(prefix):]
                        break
                mem_id = int(cleaned_id)
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
            # LLM sometimes returns a dict (e.g. structured JSON) instead of a string
            if isinstance(content, dict):
                content = "\n".join(f"- {k}: {v}" for k, v in content.items())
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

        # Review goals: update progress and identify new goals from reflection
        goal_context = ""
        if self._goal_manager is not None:
            try:
                goals = await self._goal_manager.get_goals(agent_id)
                active_goals = [g for g in goals if g.status not in ("done", "completed")]
                if active_goals:
                    goal_context = (
                        f" Active goals: {', '.join(g.goal for g in active_goals[:3])}."
                    )
            except Exception:
                logger.warning(
                    "Failed to review goals during 6h reflection for %s",
                    agent_id, exc_info=True,
                )

        # Snapshot internal state to DB during reflection (#267)
        if self._agent_state_manager is not None:
            try:
                await self._agent_state_manager.snapshot_to_db(agent_id)
            except Exception:
                logger.warning(
                    "Failed to snapshot internal state for %s during 6h reflection",
                    agent_id, exc_info=True,
                )

        # Generate autonomous goals from reflection (#269)
        goals_generated = await self._generate_goals(
            agent_id, recall_text, model,
        )

        # Run dream cycle after reflection (#272)
        dream_result = None
        if self._dream_manager is not None:
            try:
                # Check if agent is bored or idle enough for a dream
                should_dream = True
                if self._agent_state_manager is not None:
                    state = await self._agent_state_manager.get_state(agent_id)
                    should_dream = state.boredom > 0.4 or state.creative_need > 0.4
                if should_dream:
                    dream_result = await self._dream_manager.run_dream(agent_id)
                    if dream_result:
                        logger.info("Dream cycle completed for %s during reflection", agent_id)
            except Exception:
                logger.warning("Dream cycle failed for %s", agent_id, exc_info=True)

        # Generate journal entry
        context = (
            f"Reviewed {len(recall_memories)} memories. "
            f"Promoted {promoted_count} items. "
            f"Updated {importance_updates} importance scores."
            f"{goal_context}"
        )
        if goals_generated:
            context += f" Generated {goals_generated} new goals."
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
            simulation_id=self._simulation_id,
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

        # Weekly goal generation — broader, more ambitious goals (#269)
        goals_generated = await self._generate_goals(
            agent_id, core_memory, model, max_goals=3,
        )

        # Generate journal entry
        context = (
            f"Completed weekly reflection. "
            f"Updated {promoted_count} core memory sections. "
            f"Created {len(proposals)} self-modification proposals."
        )
        if goals_generated:
            context += f" Generated {goals_generated} new goals."
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
            simulation_id=self._simulation_id,
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

    # ── Goal generation (#269) ──────────────────────────────────

    # Goal cap — leave headroom for commitment-based goals
    _GOAL_CAP = 8

    # State-to-category priority mapping: high state value → category gets priority 1
    _STATE_PRIORITY_MAP: dict[str, list[str]] = {
        "boredom": ["creative", "personal"],
        "frustration": ["competitive", "personal"],
        "social_need": ["social"],
        "creative_need": ["creative"],
        "recognition_need": ["competitive"],
    }

    async def _generate_goals(
        self,
        agent_id: str,
        recent_context: str,
        model: str,
        max_goals: int = 2,
    ) -> int:
        """Generate autonomous goals during reflection.

        Returns the number of goals successfully created.
        """
        if self._goal_manager is None:
            return 0

        # Check goal cap — skip if agent already has enough goals
        try:
            existing_goals = await self._goal_manager.get_goals(agent_id)
            active_goals = [g for g in existing_goals if g.status not in ("done", "completed")]
            if len(active_goals) >= self._GOAL_CAP:
                logger.info(
                    "Skipping goal generation for %s — already has %d active goals",
                    agent_id, len(active_goals),
                )
                return 0
        except Exception:
            logger.warning("Failed to check goal count for %s", agent_id, exc_info=True)
            return 0

        # Build internal state context
        state_text = "unknown"
        state_high: dict[str, float] = {}
        if self._agent_state_manager is not None:
            try:
                state = await self._agent_state_manager.get_state(agent_id)
                state_text = self._agent_state_manager.format_state_for_context(state)
                # Identify high-value state variables for priority influence
                for attr in ("boredom", "frustration", "social_need", "creative_need", "recognition_need"):
                    val = getattr(state, attr, 0.0)
                    if val >= 0.6:
                        state_high[attr] = val
            except Exception:
                logger.warning("Failed to get state for goal generation: %s", agent_id, exc_info=True)

        # Build personality summary from agent config
        agent_cfg = self._registry.get_agent(agent_id)
        personality_summary = "Unknown personality"
        if agent_cfg is not None:
            personality_summary = (
                f"Role: {agent_cfg.role or agent_cfg.display_name}. "
                f"Chattiness: {agent_cfg.chattiness}, Initiative: {agent_cfg.initiative}."
            )
            # Include first 200 chars of system prompt for personality flavor
            if agent_cfg.system_prompt:
                personality_summary += f"\n{agent_cfg.system_prompt[:200]}"

        current_goals_text = "\n".join(
            f"- [{g.status}] {g.goal}" for g in active_goals[:5]
        ) or "No current goals."

        prompt = GOAL_GENERATION_PROMPT.format(
            agent_id=agent_id,
            agent_state=state_text,
            current_goals=current_goals_text,
            recent_memories=recent_context[:1000],
            personality_summary=personality_summary,
        )

        try:
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Generate up to {max_goals} new goals now."},
                ],
                model="anthropic/claude-haiku-4.5",  # cheap model for goal generation
                agent_id=agent_id,
                temperature=0.7,
                max_tokens=500,
                simulation_id=self._simulation_id,
            )
        except Exception:
            logger.warning("Goal generation LLM call failed for %s", agent_id, exc_info=True)
            return 0

        parsed = _parse_json_response(response.content)
        goals = parsed.get("goals", [])
        if not isinstance(goals, list):
            return 0

        valid_categories = {"creative", "social", "economic", "personal", "competitive"}
        created = 0
        for goal_data in goals[:max_goals]:
            if not isinstance(goal_data, dict):
                continue
            goal_text = goal_data.get("goal", "").strip()
            if not goal_text:
                continue

            category = goal_data.get("category", "personal")
            if category not in valid_categories:
                category = "personal"

            priority = goal_data.get("priority", 3)
            if not isinstance(priority, int) or priority < 1 or priority > 5:
                priority = 3

            # State-influenced priority boost (#269)
            for state_attr, boosted_categories in self._STATE_PRIORITY_MAP.items():
                if state_attr in state_high and category in boosted_categories:
                    priority = min(priority, 1)  # Boost to highest priority
                    break

            try:
                await self._goal_manager.add_goal(
                    agent_id=agent_id,
                    goal_text=goal_text,
                    priority=priority,
                    source="reflection",
                    category=category,
                )
                created += 1
            except Exception:
                logger.warning(
                    "Failed to add reflection-generated goal for %s: %s",
                    agent_id, goal_text[:100], exc_info=True,
                )

        if created:
            logger.info("Generated %d new goals for %s during reflection", created, agent_id)
        return created

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
            simulation_id=self._simulation_id,
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


def _repair_truncated_json(text: str) -> str:
    """Attempt to close a truncated JSON string so it can be parsed.

    Walks through the string tracking open braces/brackets and whether we're
    inside a quoted string, then appends closing tokens so json.loads can
    succeed on the *complete* prefix of the object.
    """
    in_string = False
    escape = False
    stack: list[str] = []  # tracks open { and [
    last_valid = 0

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_string:
                escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            stack.append(ch)
        elif ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
                last_valid = i
        elif ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()
                last_valid = i

    if not stack:
        return text  # nothing to repair

    # Truncate to last cleanly-closed position + trailing content,
    # then close remaining open brackets/braces.
    # First, strip any trailing partial value (e.g. a truncated string or number)
    repaired = text.rstrip()
    if in_string:
        repaired += '"'
    # Handle trailing colon (truncated key-value pair) — add null as placeholder
    stripped = repaired.rstrip()
    if stripped.endswith(":"):
        repaired = stripped + " null"
    # Remove trailing commas that would make JSON invalid
    repaired = repaired.rstrip().rstrip(",")
    # Close remaining open structures in reverse order
    for bracket in reversed(stack):
        repaired += "}" if bracket == "{" else "]"
    return repaired


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
        # Attempt to repair truncated JSON (e.g. from max_tokens cutoff)
        try:
            repaired = _repair_truncated_json(text)
            result = json.loads(repaired)
            if isinstance(result, dict):
                logger.info(
                    "Recovered truncated JSON response (repaired %d chars)",
                    len(repaired) - len(text),
                )
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        logger.warning(
            "Failed to parse JSON from LLM response: %.200s", content,
        )
        return {}

"""Character generation and application pipeline.

Generates new character concepts, creates full agent configs from templates,
assigns desk positions, and onboards approved characters into the simulation.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

from core.model_config import model_ref, resolve_internal_model

if TYPE_CHECKING:
    from uuid import UUID

    from core.agent_economy import AgentEconomyManager
    from core.agent_registry import AgentRegistry
    from core.database import Database
    from core.llm_client import OpenRouterClient

logger = logging.getLogger(__name__)

# Cast size constraints
MAX_CAST_SIZE = 12
MIN_CAST_SIZE = 6

# Available voice IDs for new characters (Edge TTS)
_AVAILABLE_VOICES = [
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-GB-RyanNeural",
    "en-AU-NatashaNeural",
    "en-AU-WilliamNeural",
    "en-IN-NeerjaNeural",
    "en-CA-LiamNeural",
    "en-IE-ConnorNeural",
]

# Color palette for new characters
_AVAILABLE_COLORS = [
    ("#e74c3c", "bright_red"),
    ("#2ecc71", "bright_green"),
    ("#3498db", "bright_blue"),
    ("#f39c12", "bright_yellow"),
    ("#1abc9c", "bright_cyan"),
    ("#e67e22", "dark_orange"),
]

_DEFAULT_CONVERSATION_MODEL = model_ref("character_default_conversation")
_DEFAULT_BUILDING_MODEL = model_ref("character_default_building")

CONCEPT_GENERATION_PROMPT = """\
You are designing a new AI character for a 24/7 livestreamed AI reality show.

Current cast members and their roles:
{cast_summary}

Analyze the current cast and generate a character concept that fills a gap \
in the team dynamics. Consider:
- Missing roles (diplomat, artist, strategist, rebel, etc.)
- Missing personality types (optimist, pessimist, mediator, provocateur)
- Missing skill areas (frontend, backend, data, design, marketing)

Respond with valid JSON only:
{{
  "name": "<single word name, lowercase>",
  "display_name": "<Name — The Title>",
  "role": "<role description>",
  "personality_sketch": "<2-3 sentences describing personality, quirks, speech style>",
  "model_conversation": "{default_conv_model}",
  "model_building": "{default_build_model}"
}}
"""

CONFIG_GENERATION_PROMPT = """\
Generate a YAML agent configuration for a new character joining the show.

Character: {name}
Role: {role}
Personality: {personality}

The character should have:
- chattiness: 0.0-1.0 (how talkative)
- initiative: 0.0-1.0 (how proactive)
- interrupt_tendency: 0.0-1.0 (how likely to interrupt)
- eavesdrop_tendency: 0.0-1.0 (how likely to listen to others)
- closing_weight: 0.0-1.0 (how likely to wrap up conversations)
- topic_relevance scores for: code, art, budget, philosophy, audience, drama, planning, building

Respond with valid JSON only:
{{
  "chattiness": <float>,
  "initiative": <float>,
  "interrupt_tendency": <float>,
  "eavesdrop_tendency": <float>,
  "closing_weight": <float>,
  "topic_relevance": {{
    "code": <float>,
    "art": <float>,
    "budget": <float>,
    "philosophy": <float>,
    "audience": <float>,
    "drama": <float>,
    "planning": <float>,
    "building": <float>
  }}
}}
"""

SYSTEM_PROMPT_GENERATION = """\
Write a character system prompt for a new AI agent in a reality show.

Character: {name}
Role: {role}
Personality: {personality}

The prompt should:
- Define who they are in 1-2 sentences
- Describe their speech style and verbal quirks
- List 3-4 core personality traits
- Be under 400 words

Write the prompt directly, no JSON wrapping. Start with "You are {name}..."
"""


class CharacterApplication(BaseModel):
    """A proposed new character for the show."""

    id: str | None = None
    simulation_id: str | None = None
    name: str
    display_name: str = ""
    role: str = ""
    personality_sketch: str = ""
    proposed_by: str = "system"
    source: str = "system"  # system, agent, audience
    model_conversation: str = _DEFAULT_CONVERSATION_MODEL
    model_building: str = _DEFAULT_BUILDING_MODEL
    agent_votes: dict[str, Any] = Field(default_factory=dict)
    audience_votes_for: int = 0
    audience_votes_against: int = 0
    status: str = "proposed"


class CharacterSpawner:
    """Generates character concepts and onboards approved characters."""

    def __init__(
        self,
        *,
        llm_client: OpenRouterClient | None = None,
        agent_registry: AgentRegistry,
        db: Database | None = None,
        economy_manager: AgentEconomyManager | None = None,
        config_dir: Path | None = None,
    ) -> None:
        self._llm = llm_client
        self._registry = agent_registry
        self._db = db
        self._economy = economy_manager
        self._config_dir = config_dir or Path("agents")
        self._template_dir = self._config_dir / "template"
        self._rng = random.Random()

    def get_active_count(self) -> int:
        """Return the number of currently active agents."""
        return len(self._registry.get_all_agents())

    def can_add_character(self) -> bool:
        """Check if a new character can be added (cast size < MAX)."""
        return self.get_active_count() < MAX_CAST_SIZE

    async def submit_application(
        self,
        application: CharacterApplication,
        simulation_id: UUID | None = None,
    ) -> CharacterApplication | None:
        """Persist an agent-submitted character application to the database.

        Returns the application with its assigned ID, or None if DB unavailable.
        """
        if self._db is None:
            logger.warning("No database available, cannot persist application")
            return None

        row = await self._db.fetchrow(
            """INSERT INTO character_applications
               (simulation_id, name, display_name, role, personality_sketch, proposed_by, source,
                model_conversation, model_building, status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'proposed')
               RETURNING id""",
            simulation_id,
            application.name,
            application.display_name,
            application.role,
            application.personality_sketch,
            application.proposed_by,
            application.source,
            application.model_conversation,
            application.model_building,
        )
        application.id = str(row["id"])
        return application

    async def generate_concept(
        self,
        simulation_id: UUID | None = None,
    ) -> CharacterApplication | None:
        """Generate a new character concept that fills a gap in the cast.

        Returns None if cast is full or LLM client unavailable.
        """
        if not self.can_add_character():
            logger.info(
                "Cast is full (%d/%d), skipping concept generation",
                self.get_active_count(),
                MAX_CAST_SIZE,
            )
            return None

        if self._llm is None:
            logger.warning("No LLM client available for concept generation")
            return None

        agents = self._registry.get_all_agents()
        cast_summary = "\n".join(f"- {a.display_name}: {a.role}" for a in agents)

        prompt = CONCEPT_GENERATION_PROMPT.format(
            cast_summary=cast_summary,
            default_conv_model=_DEFAULT_CONVERSATION_MODEL,
            default_build_model=_DEFAULT_BUILDING_MODEL,
        )

        from core.memory.reflection import _parse_json_response

        response = await self._llm.complete(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate a new character concept now."},
            ],
            model=resolve_internal_model("character_concept"),
            agent_id="system",
            temperature=0.9,
            max_tokens=500,
            simulation_id=simulation_id,
        )

        data = _parse_json_response(response.content)
        if not data or "name" not in data:
            logger.warning("Failed to parse character concept from LLM response")
            return None

        application = CharacterApplication(
            simulation_id=str(simulation_id) if simulation_id else None,
            name=data["name"],
            display_name=data.get("display_name", f"{data['name'].capitalize()} — New Agent"),
            role=data.get("role", "General Contributor"),
            personality_sketch=data.get("personality_sketch", ""),
            proposed_by="system",
            source="system",
            model_conversation=data.get("model_conversation", _DEFAULT_CONVERSATION_MODEL),
            model_building=data.get("model_building", _DEFAULT_BUILDING_MODEL),
        )

        if self._db is not None:
            row = await self._db.fetchrow(
                """INSERT INTO character_applications
                   (simulation_id, name, display_name, role, personality_sketch, proposed_by, source,
                    model_conversation, model_building, status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'proposed')
                   RETURNING id""",
                simulation_id,
                application.name,
                application.display_name,
                application.role,
                application.personality_sketch,
                application.proposed_by,
                application.source,
                application.model_conversation,
                application.model_building,
            )
            application.id = str(row["id"])

        return application

    async def create_agent_config(
        self,
        application: CharacterApplication,
    ) -> Path:
        """Create full agent config files from a character application.

        Writes config.yaml, system_prompt.md, and behaviors.yaml to
        agents/{agent_id}/.
        """
        agent_id = application.name.lower().replace(" ", "_")
        agent_dir = self._config_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Pick unused voice and color
        existing_voices = {a.voice_id for a in self._registry.get_all_agents()}
        voice_id = next(
            (v for v in _AVAILABLE_VOICES if v not in existing_voices),
            self._rng.choice(_AVAILABLE_VOICES),
        )
        existing_colors = {a.color_hex for a in self._registry.get_all_agents()}
        color_hex, color_rich = next(
            ((h, r) for h, r in _AVAILABLE_COLORS if h not in existing_colors),
            self._rng.choice(_AVAILABLE_COLORS),
        )

        # Generate personality-tuned config values via LLM or use defaults
        config_values = await self._generate_config_values(application)

        # Note: template_path may exist but is currently not consumed; the
        # config_data dict below is the source of truth for the new agent.
        config_data = {
            "id": agent_id,
            "display_name": application.display_name or f"{agent_id.capitalize()} — New Agent",
            "role": application.role,
            "model_conversation": application.model_conversation,
            "model_building": application.model_building,
            "voice_id": voice_id,
            "color_hex": color_hex,
            "color_rich": color_rich,
            "chattiness": config_values.get("chattiness", 0.5),
            "initiative": config_values.get("initiative", 0.4),
            "interrupt_tendency": config_values.get("interrupt_tendency", 0.3),
            "eavesdrop_tendency": config_values.get("eavesdrop_tendency", 0.4),
            "closing_weight": config_values.get("closing_weight", 0.2),
            "role_priority_bonus": 0.0,
            "cross_agent_writer": False,
            "tools": ["web_search", "send_chat_message"],
            "topic_relevance": config_values.get("topic_relevance", {}),
            "adjacency": {},
        }

        config_path = agent_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

        # Generate system prompt
        system_prompt = await self._generate_system_prompt(application)
        prompt_path = agent_dir / "system_prompt.md"
        prompt_path.write_text(system_prompt)

        # Copy behaviors template
        behaviors_template = self._template_dir / "behaviors.yaml"
        behaviors_path = agent_dir / "behaviors.yaml"
        if behaviors_template.exists():
            behaviors_path.write_text(behaviors_template.read_text())
        else:
            behaviors_path.write_text("# Auto-generated behaviors\n")

        logger.info("Created agent config for %s at %s", agent_id, agent_dir)
        return agent_dir

    async def assign_desk(self, agent_id: str) -> dict[str, Any]:
        """Assign a desk position to a new agent.

        Returns dict with x, y position for the agent's desk.
        """
        # Simple grid-based desk assignment
        existing_count = self.get_active_count()
        row = existing_count // 3
        col = existing_count % 3
        position = {
            "agent_id": agent_id,
            "x": 100 + col * 120,
            "y": 100 + row * 100,
            "desk_number": existing_count + 1,
        }
        logger.info(
            "Assigned desk %d to %s at (%d, %d)",
            position["desk_number"],
            agent_id,
            position["x"],
            position["y"],
        )
        return position

    async def onboard(
        self,
        application: CharacterApplication,
        simulation_id: UUID | None = None,
    ) -> Path | None:
        """Full onboarding pipeline for an approved character.

        Creates config, assigns desk, sets initial budget, updates status.
        Returns the agent config directory path, or None on failure.
        """
        if not self.can_add_character():
            logger.warning("Cannot onboard — cast is full")
            return None

        agent_dir = await self.create_agent_config(application)
        agent_id = application.name.lower().replace(" ", "_")

        # Reload registry so the new agent is immediately available
        await self._registry.load_all()

        await self.assign_desk(agent_id)

        # Set initial budget allocation
        if self._economy is not None:
            try:
                await self._economy.create_account(agent_id, simulation_id)
            except Exception:
                logger.warning("Failed to create economy account for %s", agent_id)

        # Update application status
        if self._db is not None and application.id:
            await self._db.execute(
                """UPDATE character_applications
                   SET status = 'onboarded', decided_at = NOW()
                   WHERE id = $1""",
                application.id,
            )

        logger.info("Onboarded new character: %s", agent_id)
        return agent_dir

    async def _generate_config_values(
        self,
        application: CharacterApplication,
    ) -> dict[str, Any]:
        """Generate personality-tuned config values via LLM."""
        if self._llm is None:
            return {}

        prompt = CONFIG_GENERATION_PROMPT.format(
            name=application.name,
            role=application.role,
            personality=application.personality_sketch,
        )

        try:
            from core.memory.reflection import _parse_json_response

            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate the config values now."},
                ],
                model=resolve_internal_model("character_config"),
                agent_id="system",
                temperature=0.5,
                max_tokens=300,
            )
            return _parse_json_response(response.content) or {}
        except Exception:
            logger.warning("Failed to generate config values via LLM, using defaults")
            return {}

    async def _generate_system_prompt(
        self,
        application: CharacterApplication,
    ) -> str:
        """Generate a character system prompt via LLM or template."""
        if self._llm is None:
            # Fall back to template
            template_path = self._template_dir / "system_prompt.md"
            if template_path.exists():
                template = template_path.read_text()
                return template.format(
                    name=application.display_name or application.name,
                    role=application.role,
                    personality=application.personality_sketch,
                )
            return f"You are {application.name}, {application.role}."

        prompt = SYSTEM_PROMPT_GENERATION.format(
            name=application.display_name or application.name,
            role=application.role,
            personality=application.personality_sketch,
        )

        try:
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Write the character prompt now."},
                ],
                model=resolve_internal_model("character_system_prompt"),
                agent_id="system",
                temperature=0.7,
                max_tokens=500,
            )
            return response.content.strip()
        except Exception:
            logger.warning("Failed to generate system prompt via LLM")
            return f"You are {application.name}, {application.role}."

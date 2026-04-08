"""Recurring persona manager for WorldSimulator.

Loads persona definitions from YAML and generates personality-consistent
chat messages and social media comments via LLM.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from core.llm_client import OpenRouterClient
    from core.simulation.clock import SimulationClock

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "recurring_personas.yaml"

# Map frequency labels to approximate appearances per simulated day
_FREQUENCY_PER_DAY: dict[str, float] = {
    "twice_daily": 2.0,
    "daily": 1.0,
    "every_other_day": 0.5,
}


class PersonaManager:
    """Manages recurring viewer personas and generates their messages."""

    def __init__(
        self,
        llm_client: OpenRouterClient | None = None,
        clock: SimulationClock | None = None,
        config_path: Path | None = None,
    ) -> None:
        self._llm = llm_client
        self._clock = clock
        self._personas: list[dict[str, Any]] = []
        self._config_path = config_path or _CONFIG_PATH
        self._last_appearance: dict[str, float] = {}  # persona_name -> sim_day

    def load_personas(self) -> list[dict[str, Any]]:
        """Load persona definitions from YAML config."""
        if not self._config_path.exists():
            logger.warning("Persona config not found at %s", self._config_path)
            return []

        with open(self._config_path) as f:
            data = yaml.safe_load(f)

        self._personas = data.get("personas", [])
        logger.info("Loaded %d recurring personas", len(self._personas))
        return self._personas

    def get_active_personas(self, simulated_day: int = 1) -> list[dict[str, Any]]:
        """Return personas that should be active on this simulated day.

        Uses frequency to determine probability of appearance.
        """
        active: list[dict[str, Any]] = []
        for persona in self._personas:
            freq = persona.get("frequency", "daily")
            appearances_per_day = _FREQUENCY_PER_DAY.get(freq, 1.0)

            last_day = self._last_appearance.get(persona["name"], 0)
            days_since = simulated_day - last_day

            # Probabilistic: should appear if enough time has passed
            if days_since >= (1.0 / appearances_per_day):
                active.append(persona)
                self._last_appearance[persona["name"]] = simulated_day
            elif random.random() < appearances_per_day * 0.3:
                # Small chance of extra appearance
                active.append(persona)

        return active

    async def generate_comment(
        self,
        persona: dict[str, Any],
        context: str,
    ) -> str:
        """Generate a persona-consistent comment about given context.

        Falls back to a template-based comment if no LLM is available.
        """
        if self._llm is None:
            return self._fallback_comment(persona)

        system = (
            f"You are {persona['name']}, a viewer of an AI reality show livestream. "
            f"Your personality: {persona['personality']}. "
            f"Your favorite agent is {persona.get('favorite_agent', 'unknown')}. "
            f"Write a single short comment (1-2 sentences, under 200 chars) "
            f"reacting to the context below. Stay in character."
        )

        try:
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Context: {context[:500]}"},
                ],
                model="claude-haiku-4-5",
                agent_id="world_simulator",
                temperature=0.8,
                max_tokens=100,
            )
            return response.content.strip().strip('"')
        except Exception:
            logger.exception("Failed to generate persona comment for %s", persona["name"])
            return self._fallback_comment(persona)

    async def generate_chat_message(
        self,
        persona: dict[str, Any],
        context: str = "",
    ) -> str:
        """Generate a persona-consistent chat message.

        Falls back to a template-based message if no LLM is available.
        """
        if self._llm is None:
            return self._fallback_chat(persona)

        system = (
            f"You are {persona['name']}, chatting in a livestream of an AI reality show. "
            f"Your personality: {persona['personality']}. "
            f"Write a single short chat message (under 150 chars). "
            f"Be natural — use casual language, occasional typos are fine."
        )

        user_content = "Say something in chat."
        if context:
            user_content = f"Recent context: {context[:300]}. React or say something relevant."

        try:
            response = await self._llm.complete(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                model="claude-haiku-4-5",
                agent_id="world_simulator",
                temperature=0.9,
                max_tokens=60,
            )
            return response.content.strip().strip('"')
        except Exception:
            logger.exception("Failed to generate chat for %s", persona["name"])
            return self._fallback_chat(persona)

    def _fallback_comment(self, persona: dict[str, Any]) -> str:
        """Template-based comment when LLM is unavailable."""
        templates = {
            "daily": [
                f"{persona['name']}: Nice work today!",
                f"{persona['name']}: Keep it up!",
                f"{persona['name']}: Interesting progress",
            ],
            "twice_daily": [
                f"{persona['name']}: Still watching, still impressed",
                f"{persona['name']}: Love seeing the updates",
            ],
            "every_other_day": [
                f"{persona['name']}: Just checking in, looks good",
                f"{persona['name']}: Missed you all yesterday",
            ],
        }
        freq = persona.get("frequency", "daily")
        pool = templates.get(freq, templates["daily"])
        return random.choice(pool)

    def _fallback_chat(self, persona: dict[str, Any]) -> str:
        """Template-based chat message when LLM is unavailable."""
        pools: dict[str, list[str]] = {
            "default": [
                "What are you building?",
                "This is cool",
                "How does this work?",
                "Nice!",
            ],
        }
        return f"{persona['name']}: {random.choice(pools['default'])}"

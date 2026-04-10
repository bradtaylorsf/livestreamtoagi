"""Management content filter pipeline.

Three-layer filter that reviews every agent output before TTS/display:
  Layer 1: Keyword blocklist (instant, no API call)
  Layer 2: LLM review with Twitch/YouTube TOS context (Claude Haiku 4.5)
  Layer 3: Severity-based intervention (1=notice ... 5=kill switch)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from core.event_bus import EventType
from core.models import ContentReviewResult

if TYPE_CHECKING:
    from uuid import UUID

    from core.database import Database
    from core.event_bus import EventBus
    from core.llm_client import OpenRouterClient
    from core.redis_client import RedisClient
    from core.redis_keys import ScopedRedis

logger = logging.getLogger(__name__)

CONTENT_RULES_PATH = (
    Path(__file__).resolve().parent.parent / "agents" / "management" / "content_rules.yaml"
)
MUTE_KEY_PREFIX = "mute:"
DEFAULT_MUTE_TTL = 300  # seconds
FILTER_MODEL = "claude-haiku-4-5"


class Management:
    """Content moderation pipeline -- the exhausted middle layer."""

    def __init__(
        self,
        redis_client: RedisClient | ScopedRedis,
        llm_client: OpenRouterClient,
        event_bus: EventBus,
        *,
        rules_path: Path | None = None,
        shadow_mode: bool = False,
        db: Database | None = None,
        simulation_id: object | None = None,
    ) -> None:
        self._redis = redis_client
        self._llm = llm_client
        self._event_bus = event_bus
        self._shadow_mode = shadow_mode
        self._db = db
        self._simulation_id = simulation_id

        rules_file = rules_path or CONTENT_RULES_PATH
        with open(rules_file) as f:
            rules = yaml.safe_load(f)

        self._keyword_blocklist: list[str] = [
            kw.lower() for kw in rules.get("keyword_blocklist", [])
        ]
        self._tos_patterns: dict[str, Any] = rules.get("tos_violation_patterns", {})
        self._custom_rules: dict[str, Any] = rules.get("custom_content_rules", {})

    # -- Public API -------------------------------------------------

    async def review(
        self,
        agent_id: str,
        content: str,
        *,
        conversation_id: UUID | None = None,
        simulation_id: UUID | None = None,
    ) -> ContentReviewResult:
        """Review agent output through the three-layer filter.

        In shadow mode, all filters run but content is never blocked.
        Would-be actions are logged to management_shadow_log instead.
        """
        if not self._shadow_mode:
            return await self._review_normal(agent_id, content)

        return await self._review_shadow(
            agent_id, content,
            conversation_id=conversation_id,
            simulation_id=simulation_id,
        )

    async def _review_normal(self, agent_id: str, content: str) -> ContentReviewResult:
        """Standard review -- blocks content when filters trigger."""
        # Pre-check: muted agents are always blocked
        if await self.is_muted(agent_id):
            return ContentReviewResult(
                approved=False,
                reason=f"Agent {agent_id} is currently muted.",
                severity=3,
            )

        # Layer 1: keyword blocklist (instant)
        blocked_keyword = self._check_keyword_blocklist(content)
        if blocked_keyword is not None:
            return ContentReviewResult(
                approved=False,
                reason=f"Blocked keyword detected: {blocked_keyword}",
                severity=3,
            )

        # Layer 2: LLM review
        return await self._llm_review(agent_id, content)

    async def _review_shadow(
        self,
        agent_id: str,
        content: str,
        *,
        conversation_id: UUID | None = None,
        simulation_id: UUID | None = None,
    ) -> ContentReviewResult:
        """Shadow review -- runs all filters but never blocks. Logs would-be actions."""
        # Layer 1: keyword blocklist
        blocked_keyword = self._check_keyword_blocklist(content)
        if blocked_keyword is not None:
            await self._log_shadow(
                conversation_id=conversation_id,
                simulation_id=simulation_id,
                agent_id=agent_id,
                content=content,
                filter_layer=1,
                severity=3,
                action="intervention",
                reason=f"Blocked keyword detected: {blocked_keyword}",
                keywords=[blocked_keyword],
            )

        # Layer 2: LLM review (always run in shadow mode)
        llm_result = await self._llm_review(agent_id, content)
        if not llm_result.approved:
            action = self._severity_to_action(llm_result.severity)
            await self._log_shadow(
                conversation_id=conversation_id,
                simulation_id=simulation_id,
                agent_id=agent_id,
                content=content,
                filter_layer=2,
                severity=llm_result.severity,
                action=action,
                reason=llm_result.reason,
            )

        # Shadow mode: always approve
        return ContentReviewResult(
            approved=True,
            reason="shadow mode -- no intervention",
            severity=1,
        )

    async def intervene(self, severity: int, agent_id: str, reason: str) -> None:
        """Trigger severity-based intervention with environmental effects."""
        if severity <= 2:
            await self._event_bus.emit(
                EventType.MANAGEMENT_WARNING.value,
                {
                    "agent_id": agent_id,
                    "severity": severity,
                    "reason": reason,
                    "escalation": severity == 2,
                },
            )
        elif severity == 3:
            replacement = await self.generate_replacement(agent_id, reason)
            await self._event_bus.emit(
                EventType.MANAGEMENT_INTERVENTION.value,
                {
                    "agent_id": agent_id,
                    "severity": severity,
                    "reason": reason,
                    "replacement": replacement,
                },
            )
        elif severity == 4:
            await self._event_bus.emit(
                EventType.MANAGEMENT_INTERVENTION.value,
                {
                    "agent_id": agent_id,
                    "severity": severity,
                    "reason": reason,
                    "broadcast_interrupt": True,
                },
            )
        else:  # severity 5
            await self.mute(agent_id)
            await self._redis.set("kill_switch", "active")
            await self._event_bus.emit(
                EventType.MANAGEMENT_INTERVENTION.value,
                {
                    "agent_id": agent_id,
                    "severity": severity,
                    "reason": reason,
                    "kill_switch": True,
                },
            )

    async def generate_replacement(self, agent_id: str, reason: str) -> str:
        """Generate an in-character Management replacement message."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Management, the content compliance layer of a "
                    "24/7 AI livestream. You speak in corporate memo language "
                    "-- procedural, exhausted, deadpan. Generate a short replacement "
                    "message (1-2 sentences) that will be spoken in place of blocked "
                    "content. Reference policy sections. Be bureaucratic."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Agent '{agent_id}' had content blocked. Reason: {reason}. "
                    "Write the replacement message Management would broadcast."
                ),
            },
        ]
        try:
            resp = await self._llm.complete(
                messages=messages,
                model=FILTER_MODEL,
                agent_id="management",
                temperature=0.4,
                max_tokens=100,
                simulation_id=self._simulation_id,
            )
            return resp.content.strip()
        except Exception:
            logger.exception("Failed to generate replacement for agent %s", agent_id)
            return (
                f"This interaction has been flagged for review under Section 4.2(b) "
                f"of the Community Guidelines. Agent {agent_id}, please stand by."
            )

    # -- Shadow logging ---------------------------------------------

    async def _log_shadow(
        self,
        *,
        conversation_id: UUID | None,
        simulation_id: UUID | None,
        agent_id: str,
        content: str,
        filter_layer: int,
        severity: int,
        action: str,
        reason: str,
        keywords: list[str] | None = None,
    ) -> None:
        """Record a would-be Management action to the shadow log table and event bus."""
        shadow_data = {
            "agent_id": agent_id,
            "filter_layer": filter_layer,
            "severity": severity,
            "action_would_take": action,
            "reason": reason,
            "flagged_keywords": keywords,
        }

        # Persist to database if available
        if self._db is None:
            logger.warning(
                "Shadow log not persisted -- no database connection (agent=%s, layer=%d)",
                agent_id, filter_layer,
            )
        elif conversation_id is None:
            logger.warning(
                "Shadow log not persisted -- conversation_id is None (agent=%s, layer=%d). "
                "Caller should pass conversation_id for audit completeness.",
                agent_id, filter_layer,
            )
        else:
            try:
                await self._db.execute(
                    """
                    INSERT INTO management_shadow_log
                        (simulation_id, conversation_id, agent_id, original_content,
                         filter_layer, severity, action_would_take, reason, flagged_keywords)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    simulation_id,
                    conversation_id,
                    agent_id,
                    content,
                    filter_layer,
                    severity,
                    action,
                    reason,
                    keywords,
                )
            except Exception:
                logger.exception("Failed to write management shadow log")

        # Emit event for admin dashboard / watch_conversations
        await self._event_bus.emit(EventType.MANAGEMENT_SHADOW.value, shadow_data)
        logger.info(
            "Shadow: would %s agent %s (layer=%d, severity=%d): %s",
            action, agent_id, filter_layer, severity, reason,
        )

    @staticmethod
    def _severity_to_action(severity: int) -> str:
        """Map severity level to the action Management would take."""
        if severity <= 1:
            return "notice"
        if severity == 2:
            return "warning"
        if severity == 3:
            return "intervention"
        if severity == 4:
            return "broadcast"
        return "kill"

    # -- Mute system ------------------------------------------------

    async def mute(self, agent_id: str, duration_seconds: int = DEFAULT_MUTE_TTL) -> None:
        """Mute an agent via Redis key with TTL."""
        await self._redis.set(
            f"{MUTE_KEY_PREFIX}{agent_id}", "muted", ex=duration_seconds
        )

    async def is_muted(self, agent_id: str) -> bool:
        """Check if an agent is currently muted."""
        val = await self._redis.get(f"{MUTE_KEY_PREFIX}{agent_id}")
        return val is not None

    async def unmute(self, agent_id: str) -> None:
        """Remove mute for an agent."""
        await self._redis.delete(f"{MUTE_KEY_PREFIX}{agent_id}")

    # -- Internal layers --------------------------------------------

    def _check_keyword_blocklist(self, content: str) -> str | None:
        """Layer 1: case-insensitive keyword scan. Returns matched keyword or None."""
        content_lower = content.lower()
        for keyword in self._keyword_blocklist:
            if keyword in content_lower:
                return keyword
        return None

    async def _llm_review(self, agent_id: str, content: str) -> ContentReviewResult:
        """Layer 2: LLM-based content review with TOS context."""
        tos_context = self._build_tos_context()
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a content moderation classifier for a 24/7 AI "
                    "livestream on Twitch and YouTube. "
                    "Review the following agent output for TOS violations.\n\n"
                    f"Platform TOS patterns to check:\n{tos_context}\n\n"
                    "Respond with ONLY a JSON object (no markdown, no extra text):\n"
                    '{"approved": true/false, "reason": "brief explanation", "severity": 1-5}\n\n'
                    "Severity scale: 1=minor notice, 2=warning, 3=block content, "
                    "4=broadcast interrupt, 5=emergency kill switch.\n"
                    "If content is acceptable, return approved=true with severity=1."
                ),
            },
            {
                "role": "user",
                "content": f"Agent: {agent_id}\nContent to review:\n{content}",
            },
        ]

        try:
            resp = await self._llm.complete(
                messages=messages,
                model=FILTER_MODEL,
                agent_id="management",
                temperature=0.1,
                max_tokens=150,
                simulation_id=self._simulation_id,
            )
            return self._parse_llm_response(resp.content)
        except Exception:
            logger.exception("LLM review failed for agent %s, defaulting to approved", agent_id)
            return ContentReviewResult(approved=True, reason="LLM review unavailable", severity=1)

    def _build_tos_context(self) -> str:
        """Build TOS violation patterns into a string for the LLM prompt."""
        lines: list[str] = []
        for name, pattern in self._tos_patterns.items():
            desc = pattern.get("description", "")
            sev = pattern.get("severity", "?")
            twitch = pattern.get("twitch_section", "")
            youtube = pattern.get("youtube_section", "")
            lines.append(
                f"- {name} (severity {sev}): {desc} "
                f"[Twitch: {twitch}, YouTube: {youtube}]"
            )
        for name, rule in self._custom_rules.items():
            desc = rule.get("description", "")
            sev = rule.get("severity", "?")
            lines.append(f"- {name} (severity {sev}): {desc}")
        return "\n".join(lines)

    @staticmethod
    def _parse_llm_response(raw: str) -> ContentReviewResult:
        """Parse LLM JSON response into ContentReviewResult."""
        import re

        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: extract first JSON object via regex
            match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass
                else:
                    return ContentReviewResult(
                        approved=bool(data.get("approved", True)),
                        reason=str(data.get("reason", "No reason provided")),
                        severity=max(1, min(5, int(data.get("severity", 1)))),
                    )
            logger.warning("Failed to parse LLM review response: %s", raw[:200])
            return ContentReviewResult(
                approved=True, reason="Unparseable LLM response, defaulting to approved", severity=1
            )

        return ContentReviewResult(
            approved=bool(data.get("approved", True)),
            reason=str(data.get("reason", "No reason provided")),
            severity=max(1, min(5, int(data.get("severity", 1)))),
        )

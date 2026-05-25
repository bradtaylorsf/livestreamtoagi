"""WorldSimulator — simulates external world reactions to agent actions.

Runs alongside simulations to make the world feel alive: approves social
drafts, generates engagement, processes emails, updates world state, and
injects recurring viewer personas into chat.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from typing import TYPE_CHECKING, Any

from core.model_config import resolve_internal_model

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.llm_client import OpenRouterClient
    from core.redis_client import RedisClient
    from core.redis_keys import ScopedRedis
    from core.simulation.clock import SimulationClock
    from core.simulation.recurring_personas import PersonaManager

logger = logging.getLogger(__name__)

# Simulated delay ranges (in simulated minutes)
_SOCIAL_APPROVAL_DELAY = (5, 15)
_EMAIL_SEND_DELAY = (10, 30)
_EMAIL_RESPONSE_DELAY = (60, 240)  # 1-4 hours

# Engagement ranges
_LIKES_RANGE = (10, 500)
_COMMENTS_RANGE = (2, 20)
_SHARES_RANGE = (0, 50)

# Email response sentiment distribution
_EMAIL_SENTIMENTS = [
    ("positive", 0.60),
    ("neutral", 0.25),
    ("rejection", 0.15),
]

# Revenue simulation
_BASE_DAILY_REVENUE = 5.00
_REVENUE_PER_POST = (0.01, 0.50)
_REVENUE_PER_VIEWER = 0.01
_REVENUE_PER_POSITIVE_EMAIL = (1.0, 5.0)


class WorldSimulator:
    """Background task that simulates external world reactions.

    Follows the same start/stop/tick pattern as AudienceSimulator.
    """

    def __init__(
        self,
        redis_client: RedisClient | ScopedRedis,
        llm_client: OpenRouterClient | None = None,
        clock: SimulationClock | None = None,
        event_bus: EventBus | None = None,
        persona_manager: PersonaManager | None = None,
    ) -> None:
        self._redis = redis_client
        self._llm = llm_client
        self._clock = clock
        self._event_bus = event_bus
        self._persona_manager = persona_manager

        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._start_time = 0.0
        self._recent_events: list[dict[str, Any]] = []
        self._background_tasks: set[asyncio.Task[None]] = set()

        # Track pending items with their scheduled action times (monotonic)
        self._pending_socials: dict[str, float] = {}  # draft_id -> approve_at
        self._pending_emails: dict[str, float] = {}  # draft_id -> send_at
        self._sent_emails: dict[str, float] = {}  # draft_id -> respond_at
        self._approved_posts: set[str] = set()  # draft_ids already engaged

    def start(self) -> None:
        """Launch the background simulation task."""
        if self._running:
            return
        self._running = True
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("WorldSimulator started")

    async def stop(self) -> None:
        """Cancel the background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("WorldSimulator stopped")

    async def _run_loop(self) -> None:
        """Main simulation loop — ticks periodically."""
        try:
            while self._running:
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("WorldSimulator tick failed")
                await asyncio.sleep(10.0)  # Real-time tick interval
        except asyncio.CancelledError:
            pass

    async def tick(self) -> None:
        """Single simulation tick — process all pending items."""
        now = self._simulated_seconds()

        await self._scan_new_drafts(now)
        await self._process_pending_drafts(now)
        await self._simulate_post_engagement(now)
        await self._process_pending_emails(now)
        await self._generate_email_responses(now)
        await self._update_world_state()
        await self._simulate_revenue_changes()
        await self._inject_recurring_characters()

    def _simulated_seconds(self) -> float:
        """Return elapsed simulated seconds since start."""
        if self._clock is not None:
            return self._clock.elapsed().total_seconds()
        return time.monotonic() - self._start_time

    # ── Social Media Simulation ──────────────────────────────

    async def _scan_new_drafts(self, now: float) -> None:
        """Scan Redis for new social/email drafts and schedule them."""
        # Scan for social drafts
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match="drafts:social:*", count=50)
            for key in keys:
                raw_key = key if isinstance(key, str) else key.decode()
                draft_id = raw_key.split(":")[-1]
                already_seen = draft_id in self._pending_socials or draft_id in self._approved_posts
                if not already_seen:
                    delay = random.uniform(*_SOCIAL_APPROVAL_DELAY) * 60
                    self._pending_socials[draft_id] = now + delay
            if cursor == 0:
                break

        # Scan for email drafts
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match="drafts:email:*", count=50)
            for key in keys:
                raw_key = key if isinstance(key, str) else key.decode()
                draft_id = raw_key.split(":")[-1]
                if draft_id not in self._pending_emails and draft_id not in self._sent_emails:
                    delay = random.uniform(*_EMAIL_SEND_DELAY) * 60
                    self._pending_emails[draft_id] = now + delay
            if cursor == 0:
                break

    async def _process_pending_drafts(self, now: float) -> None:
        """Approve social posts whose delay has elapsed."""
        to_approve = [did for did, at in self._pending_socials.items() if now >= at]

        for draft_id in to_approve:
            del self._pending_socials[draft_id]
            raw = await self._redis.get(f"drafts:social:{draft_id}")
            if not raw:
                continue

            try:
                draft = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            draft["status"] = "approved"
            draft["approved_at"] = now
            await self._redis.set(f"drafts:social:{draft_id}", json.dumps(draft))
            self._approved_posts.add(draft_id)

            self._add_event(
                "post_approved",
                {
                    "draft_id": draft_id,
                    "agent_id": draft.get("agent_id"),
                    "platform": draft.get("platform"),
                },
            )
            logger.debug("Approved social post %s", draft_id)

    async def _simulate_post_engagement(self, now: float) -> None:
        """Generate engagement for approved posts that don't have it yet."""
        for draft_id in list(self._approved_posts):
            engagement_key = f"social:post:{draft_id}:engagement"
            existing = await self._redis.get(engagement_key)
            if existing:
                continue  # Already has engagement

            # Score post quality (use LLM if available, otherwise random)
            quality = await self._score_post_quality(draft_id)

            likes = int(random.uniform(*_LIKES_RANGE) * quality)
            comments_count = int(random.uniform(*_COMMENTS_RANGE) * quality)
            shares = int(random.uniform(*_SHARES_RANGE) * quality)

            # Generate comments from personas
            comments = []
            if self._persona_manager and comments_count > 0:
                personas = self._persona_manager.get_active_personas(
                    self._clock.simulated_day() if self._clock else 1
                )
                for persona in personas[:comments_count]:
                    comment = await self._persona_manager.generate_comment(
                        persona, "Social post by an AI agent"
                    )
                    comments.append(
                        {
                            "user": persona["name"],
                            "text": comment,
                            "timestamp": now,
                        }
                    )

            # Add one negative comment per ~5 posts for realism
            if random.random() < 0.2:
                comments.append(
                    {
                        "user": "anonymous_critic",
                        "text": "This is just AI-generated slop tbh",
                        "timestamp": now,
                    }
                )

            engagement = {
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "quality_score": round(quality, 2),
                "generated_at": now,
            }
            await self._redis.set(engagement_key, json.dumps(engagement))

            self._add_event(
                "post_engagement",
                {
                    "draft_id": draft_id,
                    "likes": likes,
                    "comments": len(comments),
                    "shares": shares,
                },
            )

    async def _score_post_quality(self, draft_id: str) -> float:
        """Score a post's quality 0.0-1.0. Uses LLM if available."""
        if self._llm is None:
            return random.uniform(0.3, 0.8)

        raw = await self._redis.get(f"drafts:social:{draft_id}")
        if not raw:
            return 0.5

        try:
            draft = json.loads(raw)
            content = draft.get("content", "")
        except (json.JSONDecodeError, TypeError):
            return 0.5

        try:
            response = await self._llm.complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Rate this social media post's quality on a scale of 0.0 to 1.0. "
                            "Consider: creativity, engagement potential, clarity. "
                            "Respond with ONLY a number like 0.7"
                        ),
                    },
                    {"role": "user", "content": content[:500]},
                ],
                model=resolve_internal_model("world_revenue"),
                agent_id="world_simulator",
                temperature=0.3,
                max_tokens=10,
            )
            return max(0.1, min(1.0, float(response.content.strip())))
        except Exception:
            return random.uniform(0.3, 0.8)

    # ── Email Response Simulation ────────────────────────────

    async def _process_pending_emails(self, now: float) -> None:
        """Mark emails as 'sent' after their delay has elapsed."""
        to_send = [did for did, at in self._pending_emails.items() if now >= at]

        for draft_id in to_send:
            del self._pending_emails[draft_id]
            raw = await self._redis.get(f"drafts:email:{draft_id}")
            if not raw:
                continue

            try:
                draft = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            draft["status"] = "sent"
            draft["sent_at"] = now
            await self._redis.set(f"drafts:email:{draft_id}", json.dumps(draft))

            # Schedule response
            response_delay = random.uniform(*_EMAIL_RESPONSE_DELAY) * 60
            self._sent_emails[draft_id] = now + response_delay

            self._add_event(
                "email_sent",
                {
                    "draft_id": draft_id,
                    "agent_id": draft.get("agent_id"),
                    "to": draft.get("to"),
                },
            )

    async def _generate_email_responses(self, now: float) -> None:
        """Generate responses for sent emails whose response time has elapsed."""
        to_respond = [did for did, at in self._sent_emails.items() if now >= at]

        for draft_id in to_respond:
            del self._sent_emails[draft_id]

            # Determine sentiment
            roll = random.random()
            cumulative = 0.0
            sentiment = "neutral"
            for sent, prob in _EMAIL_SENTIMENTS:
                cumulative += prob
                if roll < cumulative:
                    sentiment = sent
                    break

            # Generate response text
            response_text = await self._generate_email_text(draft_id, sentiment)

            response_data = {
                "draft_id": draft_id,
                "sentiment": sentiment,
                "response": response_text,
                "responded_at": now,
            }
            await self._redis.set(f"email:response:{draft_id}", json.dumps(response_data))

            self._add_event(
                "email_received",
                {
                    "draft_id": draft_id,
                    "sentiment": sentiment,
                },
            )

    async def _generate_email_text(self, draft_id: str, sentiment: str) -> str:
        """Generate email response text matching the given sentiment."""
        templates = {
            "positive": (
                "Thanks for reaching out! We're very interested. "
                "Let's schedule a call to discuss further."
            ),
            "neutral": (
                "Thanks for the email. We'll review and get back "
                "to you when we have more information."
            ),
            "rejection": (
                "We appreciate your interest, but this isn't a fit for us right now. Best of luck!"
            ),
        }

        if self._llm is None:
            return templates.get(sentiment, templates["neutral"])

        raw = await self._redis.get(f"drafts:email:{draft_id}")
        context = ""
        if raw:
            try:
                draft = json.loads(raw)
                subj = draft.get("subject", "N/A")
                body = draft.get("body", "")[:300]
                context = f"Subject: {subj}\nBody: {body}"
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            response = await self._llm.complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a business contact responding to "
                            "an email from an AI reality show. "
                            f"Your sentiment should be: {sentiment}. "
                            "Write a brief, realistic reply (2-3 sentences)."
                        ),
                    },
                    {"role": "user", "content": context or "General inquiry about collaboration"},
                ],
                model=resolve_internal_model("world_event"),
                agent_id="world_simulator",
                temperature=0.7,
                max_tokens=150,
            )
            return response.content.strip()
        except Exception:
            return templates.get(sentiment, templates["neutral"])

    # ── World State Updates ──────────────────────────────────

    async def _update_world_state(self) -> None:
        """Update Redis keys that get_world_state reads."""
        # Recent events (last 20)
        events = self._recent_events[-20:]
        await self._redis.set("world:recent_events", json.dumps(events, default=str))

    # ── Revenue Simulation ───────────────────────────────────

    async def _simulate_revenue_changes(self) -> None:
        """Calculate dynamic revenue based on engagement."""
        revenue = _BASE_DAILY_REVENUE

        # Revenue from approved posts
        approved_count = len(self._approved_posts)
        revenue += approved_count * random.uniform(*_REVENUE_PER_POST)

        # Revenue from viewer count
        viewer_raw = await self._redis.get("audience:viewer_count")
        if viewer_raw:
            try:
                viewers = int(viewer_raw)
                revenue += viewers * _REVENUE_PER_VIEWER
            except (ValueError, TypeError):
                pass

        # Store as world budget info — write to both keys so
        # GetWorldStateTool ("world:budget") and any direct reader
        # ("world:revenue_status") both get updated data.
        budget_data = {
            "estimated_daily_revenue": round(revenue, 2),
            "approved_posts_today": approved_count,
            "updated_at": time.time(),
        }
        await self._redis.set("world:revenue_status", json.dumps(budget_data))
        # GetWorldStateTool reads "world:budget" — mirror the data there
        # in the format that tool expects.
        await self._redis.set(
            "world:budget",
            json.dumps(
                {
                    "estimated_daily_revenue": round(revenue, 2),
                    "approved_posts_today": approved_count,
                }
            ),
        )

    # ── Recurring Characters ─────────────────────────────────

    async def _inject_recurring_characters(self) -> None:
        """Inject persona chat messages into audience chat."""
        if self._persona_manager is None:
            return

        day = self._clock.simulated_day() if self._clock else 1
        personas = self._persona_manager.get_active_personas(day)

        # Only inject 1-2 per tick to avoid flooding
        for persona in personas[:2]:
            if random.random() > 0.3:  # 30% chance per active persona per tick
                continue
            message = await self._persona_manager.generate_chat_message(persona)
            chat_entry = json.dumps(
                {
                    "user": persona["name"],
                    "text": message,
                    "timestamp": time.time(),
                    "persona": True,
                }
            )
            await self._redis.rpush("audience:recent_chat", chat_entry)
            await self._redis.ltrim("audience:recent_chat", -50, -1)

    # ── Helpers ──────────────────────────────────────────────

    def _add_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Add an event to the recent events list."""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
            "simulated_time": self._simulated_seconds(),
        }
        self._recent_events.append(event)

        # Emit via event bus if available
        if self._event_bus is not None:
            task = asyncio.create_task(self._event_bus.emit(event_type, event))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

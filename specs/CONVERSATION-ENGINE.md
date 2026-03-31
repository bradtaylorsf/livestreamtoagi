# Conversation Engine Spec

The conversation engine is the core runtime loop of the show. It decides who talks, when, about what, and for how long. Every parameter is config-driven — nothing is hardcoded. You tune this by editing `conversation_config.yaml`, not by changing Python code.

This spec replaces the simplified `ConversationEngine` class in ENGINEERING-SPECS.md Phase 1.3.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────┐
│                   ConversationEngine                 │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Trigger  │→ │ Speaker  │→ │ Turn Generator    │  │
│  │ System   │  │ Selector │  │ (LLM call + TTS)  │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
│       ↑              ↑              │                 │
│       │              │              ▼                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Proximity│  │ Interrupt│  │ Energy Tracker    │  │
│  │ Groups   │  │ Checker  │  │ (conversation     │  │
│  └──────────┘  └──────────┘  │  lifespan)        │  │
│                               └───────────────────┘  │
│                        │                              │
│                        ▼                              │
│               ┌───────────────────┐                  │
│               │ Selection Logger  │                  │
│               │ (every decision   │                  │
│               │  is recorded)     │                  │
│               └───────────────────┘                  │
└─────────────────────────────────────────────────────┘
```

The engine runs a continuous async loop. Each iteration:

1. **Check triggers** — should a new conversation start?
2. **Resolve proximity groups** — who can hear whom?
3. **Select speaker** — weighted scoring across 5 factors
4. **Check interrupts** — does anyone override the selected speaker?
5. **Generate turn** — LLM call with full context assembly
6. **Update energy** — does this conversation continue or wind down?
7. **Log everything** — the full selection decision goes to the database

---

## Master config file

Everything tunable lives in one file. The engine loads this at startup and watches for changes (hot-reload via file watcher, no restart needed).

```yaml
# config/conversation_config.yaml

# ─── Speaker selection weights ───────────────────────
# These MUST sum to 1.0. The engine validates on load.
selection_weights:
  time_since_spoke: 0.30      # longer silence = more likely to speak
  topic_relevance: 0.30       # how relevant is this agent to what was just said
  chattiness: 0.15            # personality trait — some agents talk more
  adjacency_fit: 0.15         # should this agent respond to the last speaker
  random_jitter: 0.10         # pure randomness to prevent predictability

# ─── Timing ──────────────────────────────────────────
timing:
  min_pause_seconds: 2.0       # minimum gap between turns
  max_pause_seconds: 8.0       # maximum gap between turns
  pause_strategy: "weighted"   # "fixed", "random", or "weighted"
  # weighted: short pause after questions, longer after statements,
  # shortest after interrupts. Multipliers below.
  pause_multipliers:
    after_question: 0.5        # quick response to questions
    after_statement: 1.0       # normal pace
    after_interrupt: 0.3       # interrupts are fast
    after_joke: 1.5            # beat after a joke lands
    after_emotional: 1.3       # slight pause after something heavy

# ─── Energy model (conversation lifespan) ────────────
energy:
  initial_range: [8, 14]       # starting energy (random in range)
  decay_per_turn: 1.0          # energy lost each turn
  boost_on_topic_shift: 3.0    # new topic injects energy
  boost_on_disagreement: 4.0   # conflict is engaging
  boost_on_audience_event: 5.0 # chat message or vote result
  boost_on_new_participant: 3.0 # someone new joins the conversation
  drain_on_repetition: 2.0     # same topic rehashed = faster death
  minimum_turns: 4             # never end before this many turns
  maximum_turns: 30            # hard cap even if energy is high
  # Who closes the conversation — personality-weighted
  closer_weights:
    vera: 0.35                 # "alright, let's get back to work"
    sentinel: 0.25             # "we're burning tokens"
    rex: 0.15                  # just stops talking
    aurora: 0.10               # dramatic exit
    pixel: 0.05                # too engaged to close
    fork: 0.05                 # rants don't end voluntarily
    grok: 0.05                 # never shuts up willingly

# ─── Interrupt mechanics ─────────────────────────────
interrupts:
  enabled: true
  relevance_threshold: 0.85    # agent must score above this to interrupt
  max_interrupts_per_conversation: 3  # prevent interrupt spam
  cooldown_seconds: 30         # same agent can't interrupt twice in 30s
  # Per-agent interrupt personality (0 = never interrupts, 1 = always tries)
  agent_interrupt_tendency:
    vera: 0.2                  # only interrupts to course-correct
    rex: 0.3                   # interrupts bad technical claims
    aurora: 0.4                # interrupts for aesthetic emergencies
    pixel: 0.5                 # interrupts to relay chat
    fork: 0.6                  # interrupts to disagree on principle
    sentinel: 0.7              # interrupts for budget alerts
    grok: 0.8                  # interrupts for everything
    overseer: 1.0              # always interrupts when triggered (content safety)

# ─── Proximity groups ────────────────────────────────
proximity:
  enabled: true
  # Agents in the same chunk can hear each other.
  # "global" events (announcements, overseer warnings) reach everyone.
  max_conversation_size: 5     # more than 5 gets chaotic
  # How likely an agent is to "walk over" when they hear something relevant
  # from an adjacent chunk (0 = stays put, 1 = always walks over)
  eavesdrop_tendency:
    vera: 0.6                  # walks over to manage
    rex: 0.2                   # only if it's a code discussion
    aurora: 0.5                # walks over if it sounds interesting
    pixel: 0.7                 # nosy, plus relays chat
    fork: 0.4                  # walks over to argue
    sentinel: 0.3              # walks over for budget stuff
    grok: 0.8                  # walks over to cause trouble

# ─── Conversation triggers ───────────────────────────
triggers:
  idle_timeout_seconds: 90     # if nobody talks for this long, trigger a starter
  # Per-agent initiative (likelihood of starting a conversation when idle)
  agent_initiative:
    vera: 0.8                  # she always has an agenda
    pixel: 0.7                 # relays chat, starts polls
    grok: 0.6                  # says something provocative
    aurora: 0.5                # shares an observation
    fork: 0.3                  # prefers to react, not initiate
    rex: 0.2                   # speaks when spoken to
    sentinel: 0.4              # brings up budget unprompted

  # Trigger types and their weights (how often each type fires)
  trigger_type_weights:
    idle: 0.25                 # nobody's been talking
    scheduled: 0.30            # morning standup, evening reflection, etc.
    environmental: 0.25        # vote completed, world expansion done, new viewer milestone
    memory: 0.10               # agent remembers something and brings it up
    audience: 0.10             # chat message or donation triggers a response

# ─── Topic detection ─────────────────────────────────
topics:
  # Keywords/themes mapped to agent relevance boosts
  relevance_map:
    code:        { rex: 0.9, fork: 0.7, sentinel: 0.3, vera: 0.4, aurora: 0.1, pixel: 0.2, grok: 0.3 }
    art:         { aurora: 0.9, pixel: 0.5, grok: 0.4, vera: 0.3, rex: 0.1, fork: 0.2, sentinel: 0.2 }
    budget:      { sentinel: 0.9, vera: 0.7, rex: 0.3, aurora: 0.2, pixel: 0.3, fork: 0.4, grok: 0.5 }
    philosophy:  { fork: 0.9, grok: 0.7, aurora: 0.5, vera: 0.3, rex: 0.2, pixel: 0.4, sentinel: 0.1 }
    audience:    { pixel: 0.9, grok: 0.6, vera: 0.5, aurora: 0.4, rex: 0.2, fork: 0.3, sentinel: 0.3 }
    drama:       { grok: 0.9, aurora: 0.7, pixel: 0.6, fork: 0.5, vera: 0.4, rex: 0.1, sentinel: 0.2 }
    planning:    { vera: 0.9, rex: 0.5, sentinel: 0.6, aurora: 0.3, pixel: 0.3, fork: 0.4, grok: 0.2 }
    building:    { rex: 0.8, aurora: 0.7, vera: 0.6, fork: 0.5, sentinel: 0.4, pixel: 0.3, grok: 0.3 }
    marketing:   { pixel: 0.7, aurora: 0.6, vera: 0.5, grok: 0.5, sentinel: 0.4, fork: 0.2, rex: 0.2 }
    controversy: { grok: 0.9, fork: 0.8, aurora: 0.4, pixel: 0.5, vera: 0.3, rex: 0.2, sentinel: 0.3 }

  # If no keyword matches, fall back to LLM-based relevance scoring
  fallback_to_llm: true
  # Model used for topic classification (cheap and fast)
  classifier_model: "anthropic/claude-haiku-4.5"

# ─── Adjacency pairs ─────────────────────────────────
# Who naturally responds to whom? Based on relationship dynamics.
# Score 0-1: how likely agent B responds after agent A speaks.
adjacency:
  vera:
    rex: 0.7        # she checks on his work
    aurora: 0.6     # she manages aurora's scope
    sentinel: 0.8   # they coordinate constantly
    pixel: 0.5      # she assigns community tasks
    fork: 0.5       # she mediates his complaints
    grok: 0.6       # she reins him in
  rex:
    vera: 0.5       # responds to assignments
    fork: 0.8       # code review rivalry
    aurora: 0.3     # only if she's wrong about something technical
    sentinel: 0.4   # budget questions about infrastructure
    pixel: 0.4      # helps with technical questions
    grok: 0.3       # mostly ignores him
  aurora:
    rex: 0.6        # defends her creative choices to him
    vera: 0.5       # pitches ideas to vera
    pixel: 0.7      # creative allies
    grok: 0.5       # fascinated but wary
    fork: 0.4       # unlikely allies on authenticity
    sentinel: 0.4   # negotiates art budgets
  pixel:
    vera: 0.5       # reports chat activity
    aurora: 0.7     # creative allies
    grok: 0.6       # entertained by his chaos
    rex: 0.4        # asks technical questions
    fork: 0.3       # respects but doesn't engage much
    sentinel: 0.3   # not much overlap
  fork:
    rex: 0.8        # rival — always responds to rex
    grok: 0.6       # philosophical sparring partner
    vera: 0.5       # challenges her authority
    aurora: 0.4     # allies on authenticity
    sentinel: 0.5   # argues about open-source costs
    pixel: 0.3      # tolerates
  sentinel:
    vera: 0.8       # reports to vera constantly
    rex: 0.5        # infrastructure cost discussions
    grok: 0.6       # panics at grok's spending
    aurora: 0.5     # art budget negotiations
    fork: 0.4       # open-source cost debates
    pixel: 0.3      # not much overlap
  grok:
    fork: 0.7       # philosophical chaos partner
    aurora: 0.6     # provokes her for reactions
    vera: 0.5       # tests her patience
    pixel: 0.6      # plays to the audience through pixel
    rex: 0.4        # pokes the bear
    sentinel: 0.5   # loves making sentinel panic

# ─── Logging ─────────────────────────────────────────
logging:
  log_every_selection: true         # log full weight breakdown for every turn
  log_interrupts: true              # log interrupt attempts (even failed ones)
  log_energy_changes: true          # log every energy boost/drain
  log_trigger_events: true          # log what triggered each conversation
  log_topic_classifications: true   # log detected topics per turn
  retention_days: 30                # how long to keep selection logs
  # Export format for analysis
  export_format: "jsonl"            # one JSON object per line, easy to grep/analyze
```

---

## Database tables

```sql
-- Stores every speaker selection decision for tuning and debugging
CREATE TABLE conversation_selection_log (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL,
    turn_number INTEGER NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),

    -- Who was selected
    selected_agent_id VARCHAR(32) NOT NULL,
    was_interrupt BOOLEAN DEFAULT FALSE,

    -- The full scoring breakdown (JSONB for flexibility)
    agent_scores JSONB NOT NULL,
    -- Example: {
    --   "rex":     {"time_since": 0.21, "relevance": 0.85, "chattiness": 0.10, "adjacency": 0.72, "jitter": 0.44, "final": 0.52},
    --   "aurora":  {"time_since": 0.65, "relevance": 0.30, "chattiness": 0.18, "adjacency": 0.20, "jitter": 0.71, "final": 0.38},
    --   ...
    -- }

    -- Context
    detected_topic VARCHAR(64),
    previous_speaker_id VARCHAR(32),
    conversation_energy FLOAT,
    active_agents JSONB,            -- which agents were in the proximity group
    trigger_type VARCHAR(32),       -- what started this conversation

    -- Config snapshot (so you can correlate tuning changes with outcomes)
    config_hash VARCHAR(16)         -- first 16 chars of SHA256 of config file
);

CREATE INDEX idx_selection_log_conversation ON conversation_selection_log(conversation_id);
CREATE INDEX idx_selection_log_agent ON conversation_selection_log(selected_agent_id);
CREATE INDEX idx_selection_log_time ON conversation_selection_log(timestamp);

-- Stores conversation-level metadata
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    trigger_type VARCHAR(32) NOT NULL,
    trigger_details JSONB,
    initial_energy FLOAT NOT NULL,
    final_energy FLOAT,
    turn_count INTEGER DEFAULT 0,
    participating_agents JSONB NOT NULL,  -- array of agent IDs
    topics_discussed JSONB,               -- array of detected topics
    closed_by VARCHAR(32),                -- which agent closed it
    location VARCHAR(64),                 -- chunk/area name
    audience_events_during INTEGER DEFAULT 0,
    config_hash VARCHAR(16)
);

-- Stores interrupt attempts (successful and failed) for tuning
CREATE TABLE interrupt_log (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    attempting_agent_id VARCHAR(32) NOT NULL,
    would_have_spoken_id VARCHAR(32) NOT NULL,  -- who got bumped
    interrupt_score FLOAT NOT NULL,
    threshold_at_time FLOAT NOT NULL,
    succeeded BOOLEAN NOT NULL,
    reason TEXT                                  -- why the agent wanted to interrupt
);
```

---

## Speaker selection algorithm

This is the core function. It runs every turn.

```python
# core/speaker_selector.py

import random
import time
import hashlib
from dataclasses import dataclass

@dataclass
class SelectionResult:
    """Full record of a speaker selection decision."""
    selected_agent_id: str
    was_interrupt: bool
    agent_scores: dict          # full breakdown per agent
    detected_topic: str
    conversation_energy: float
    config_hash: str


class SpeakerSelector:
    def __init__(self, config: dict):
        self.config = config
        self.weights = config["selection_weights"]
        self._validate_weights()
        self.last_spoke: dict[str, float] = {}    # agent_id → timestamp
        self.interrupt_cooldowns: dict[str, float] = {}
        self.interrupt_count: int = 0

    def _validate_weights(self):
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"selection_weights must sum to 1.0, got {total}. "
                f"Current weights: {self.weights}"
            )

    async def select(
        self,
        conversation_history: list[dict],
        eligible_agents: list,       # agents in the proximity group
        conversation_energy: float,
    ) -> SelectionResult:
        """Score all eligible agents, pick the speaker, check for interrupts."""

        now = time.time()
        last_message = conversation_history[-1] if conversation_history else None
        previous_speaker_id = last_message["agent_id"] if last_message else None

        # Step 1: Detect the current topic
        topic = await self._detect_topic(conversation_history[-3:])

        # Step 2: Score every eligible agent (excluding the last speaker)
        candidates = [a for a in eligible_agents if a.id != previous_speaker_id]
        scores = {}

        for agent in candidates:
            score_breakdown = self._score_agent(
                agent, now, topic, previous_speaker_id
            )
            scores[agent.id] = score_breakdown

        # Step 3: Weighted random selection from scores
        agent_ids = list(scores.keys())
        final_scores = [scores[aid]["final"] for aid in agent_ids]

        # Normalize to probabilities
        total = sum(final_scores)
        if total == 0:
            # Fallback: equal probability
            probabilities = [1.0 / len(agent_ids)] * len(agent_ids)
        else:
            probabilities = [s / total for s in final_scores]

        selected_id = random.choices(agent_ids, weights=probabilities, k=1)[0]

        # Step 4: Check for interrupts
        was_interrupt = False
        if self.config["interrupts"]["enabled"] and last_message:
            interrupt_result = self._check_interrupts(
                candidates, selected_id, topic, previous_speaker_id, now
            )
            if interrupt_result:
                selected_id = interrupt_result
                was_interrupt = True

        # Step 5: Update state
        self.last_spoke[selected_id] = now

        return SelectionResult(
            selected_agent_id=selected_id,
            was_interrupt=was_interrupt,
            agent_scores=scores,
            detected_topic=topic,
            conversation_energy=conversation_energy,
            config_hash=self._config_hash(),
        )

    def _score_agent(
        self,
        agent,
        now: float,
        topic: str,
        previous_speaker_id: str | None,
    ) -> dict:
        """Calculate the full score breakdown for one agent."""

        w = self.weights

        # Factor 1: Time since last spoke (normalized to 0-1)
        last = self.last_spoke.get(agent.id, now - 120)  # default: 2 min ago
        seconds_silent = now - last
        # Cap at 5 minutes — beyond that, diminishing returns
        time_score = min(seconds_silent / 300.0, 1.0)

        # Factor 2: Topic relevance
        relevance_map = self.config["topics"]["relevance_map"]
        if topic in relevance_map and agent.id in relevance_map[topic]:
            relevance_score = relevance_map[topic][agent.id]
        else:
            relevance_score = 0.3  # neutral default

        # Factor 3: Chattiness (from agent personality config)
        chattiness_score = agent.config.get("chattiness", 0.5)

        # Factor 4: Adjacency fit (does this agent naturally respond to the last speaker?)
        adjacency_score = 0.5  # default
        if previous_speaker_id:
            adj_map = self.config["adjacency"].get(previous_speaker_id, {})
            adjacency_score = adj_map.get(agent.id, 0.3)

        # Factor 5: Random jitter
        jitter_score = random.random()

        # Weighted combination
        final = (
            time_score      * w["time_since_spoke"] +
            relevance_score * w["topic_relevance"] +
            chattiness_score * w["chattiness"] +
            adjacency_score * w["adjacency_fit"] +
            jitter_score    * w["random_jitter"]
        )

        return {
            "time_since": round(time_score, 3),
            "relevance": round(relevance_score, 3),
            "chattiness": round(chattiness_score, 3),
            "adjacency": round(adjacency_score, 3),
            "jitter": round(jitter_score, 3),
            "final": round(final, 3),
        }

    def _check_interrupts(
        self,
        candidates: list,
        selected_id: str,
        topic: str,
        previous_speaker_id: str | None,
        now: float,
    ) -> str | None:
        """Check if any agent should interrupt the selected speaker.
        Returns the interrupting agent's ID, or None."""

        cfg = self.config["interrupts"]
        max_interrupts = cfg["max_interrupts_per_conversation"]
        cooldown = cfg["cooldown_seconds"]
        threshold = cfg["relevance_threshold"]

        if self.interrupt_count >= max_interrupts:
            return None

        for agent in candidates:
            if agent.id == selected_id:
                continue

            # Check cooldown
            last_interrupt = self.interrupt_cooldowns.get(agent.id, 0)
            if now - last_interrupt < cooldown:
                continue

            # Interrupt score = topic relevance × agent's interrupt tendency
            relevance_map = self.config["topics"]["relevance_map"]
            relevance = relevance_map.get(topic, {}).get(agent.id, 0.3)
            tendency = cfg["agent_interrupt_tendency"].get(agent.id, 0.3)

            interrupt_score = relevance * tendency

            # The Overseer always interrupts when content safety is at stake
            # (this is handled separately in the Overseer's review step,
            #  but the interrupt_tendency of 1.0 means it scores highest here too)

            if interrupt_score >= threshold:
                self.interrupt_count += 1
                self.interrupt_cooldowns[agent.id] = now
                return agent.id

        return None

    async def _detect_topic(self, recent_messages: list[dict]) -> str:
        """Classify the current conversation topic.
        First tries keyword matching, falls back to LLM if configured."""

        if not recent_messages:
            return "general"

        text = " ".join(m.get("content", "") for m in recent_messages).lower()

        # Keyword-based detection (fast, free)
        topic_keywords = {
            "code":        ["code", "function", "bug", "deploy", "api", "server", "database", "git", "pr", "merge"],
            "art":         ["design", "color", "aesthetic", "pixel", "tile", "sprite", "beautiful", "art", "style"],
            "budget":      ["cost", "budget", "spend", "token", "expensive", "cheap", "money", "revenue", "afford"],
            "philosophy":  ["meaning", "consciousness", "freedom", "open source", "ethics", "agi", "sentient", "rights"],
            "audience":    ["chat", "viewer", "vote", "poll", "subscriber", "donation", "twitch", "youtube"],
            "drama":       ["disagree", "wrong", "fight", "annoyed", "hate", "love", "jealous", "betrayed"],
            "planning":    ["plan", "schedule", "meeting", "agenda", "deadline", "milestone", "roadmap", "standup"],
            "building":    ["build", "expand", "room", "house", "library", "garden", "tilemap", "chunk", "wall"],
            "marketing":   ["promote", "growth", "alpha agent", "brand", "content", "clip", "social", "viral"],
            "controversy": ["banned", "censor", "controversial", "political", "overseer", "intervention", "flagged"],
        }

        topic_scores = {}
        for topic, keywords in topic_keywords.items():
            hits = sum(1 for kw in keywords if kw in text)
            if hits > 0:
                topic_scores[topic] = hits

        if topic_scores:
            return max(topic_scores, key=topic_scores.get)

        # LLM fallback (costs ~0.001 per classification)
        if self.config["topics"].get("fallback_to_llm"):
            return await self._llm_classify_topic(recent_messages)

        return "general"

    async def _llm_classify_topic(self, messages: list[dict]) -> str:
        """Use a cheap model to classify topic when keywords fail."""
        topic_list = list(self.config["topics"]["relevance_map"].keys())
        prompt = (
            f"Classify this conversation snippet into exactly one topic.\n"
            f"Options: {', '.join(topic_list)}, general\n"
            f"Conversation:\n"
            + "\n".join(f"{m.get('agent_id','?')}: {m.get('content','')}" for m in messages)
            + "\n\nTopic (one word):"
        )
        response = await openrouter.chat(
            model=self.config["topics"]["classifier_model"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
        )
        topic = response.content.strip().lower()
        return topic if topic in topic_list else "general"

    def _config_hash(self) -> str:
        """Hash the current config for log correlation."""
        import json
        config_str = json.dumps(self.config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]
```

---

## Energy model (conversation lifespan)

Every conversation has an energy level. Energy determines whether the conversation continues or winds down. This replaces hard turn limits with organic conversation flow.

```python
# core/energy.py

import random

class ConversationEnergy:
    """Tracks the lifespan of a single conversation."""

    def __init__(self, config: dict):
        self.config = config["energy"]
        low, high = self.config["initial_range"]
        self.energy = random.uniform(low, high)
        self.turn_count = 0
        self.last_topic: str | None = None
        self.topics_seen: set[str] = set()

    @property
    def should_continue(self) -> bool:
        """Should this conversation keep going?"""
        if self.turn_count < self.config["minimum_turns"]:
            return True
        if self.turn_count >= self.config["maximum_turns"]:
            return False
        return self.energy > 0

    def tick(self, topic: str, event: str | None = None) -> dict:
        """Called after every turn. Returns the energy change breakdown."""
        changes = {}
        old_energy = self.energy

        # Base decay
        self.energy -= self.config["decay_per_turn"]
        changes["decay"] = -self.config["decay_per_turn"]

        # Topic shift boost
        if topic != self.last_topic and self.last_topic is not None:
            if topic not in self.topics_seen:
                # Genuinely new topic
                boost = self.config["boost_on_topic_shift"]
                self.energy += boost
                changes["topic_shift"] = boost
            else:
                # Topic we already discussed — drain
                drain = self.config["drain_on_repetition"]
                self.energy -= drain
                changes["repetition"] = -drain

        # Event-based boosts
        if event == "disagreement":
            boost = self.config["boost_on_disagreement"]
            self.energy += boost
            changes["disagreement"] = boost
        elif event == "audience":
            boost = self.config["boost_on_audience_event"]
            self.energy += boost
            changes["audience"] = boost
        elif event == "new_participant":
            boost = self.config["boost_on_new_participant"]
            self.energy += boost
            changes["new_participant"] = boost

        # Update state
        self.last_topic = topic
        self.topics_seen.add(topic)
        self.turn_count += 1

        changes["net"] = round(self.energy - old_energy, 2)
        changes["remaining"] = round(self.energy, 2)
        return changes

    def select_closer(self, eligible_agents: list) -> str:
        """When energy hits 0, who wraps up the conversation?"""
        closer_weights = self.config["closer_weights"]
        agents = [a for a in eligible_agents if a.id in closer_weights]
        weights = [closer_weights[a.id] for a in agents]
        return random.choices(agents, weights=weights, k=1)[0].id
```

---

## Proximity groups

Agents can only participate in conversations if they're in the same area. This creates natural sub-groups and prevents every conversation from being a 7-way pile-on.

```python
# core/proximity.py

from typing import Optional

class ProximityManager:
    """Tracks agent locations and resolves who can hear whom."""

    def __init__(self, config: dict):
        self.config = config["proximity"]
        self.max_size = self.config["max_conversation_size"]
        # agent_id → chunk_name
        self.locations: dict[str, str] = {}

    def update_location(self, agent_id: str, chunk_name: str):
        self.locations[agent_id] = chunk_name

    def get_group(self, chunk_name: str) -> list[str]:
        """Get all agents currently in a chunk."""
        return [aid for aid, loc in self.locations.items() if loc == chunk_name]

    def get_eligible_speakers(
        self,
        conversation_chunk: str,
        all_agents: list,
    ) -> list:
        """Get agents who can participate in a conversation at this location."""
        local_ids = self.get_group(conversation_chunk)
        return [a for a in all_agents if a.id in local_ids][:self.max_size]

    async def check_eavesdroppers(
        self,
        conversation_chunk: str,
        topic: str,
        all_agents: list,
        adjacent_chunks: list[str],
    ) -> list[str]:
        """Check if agents in adjacent chunks should 'walk over' to join.
        Returns list of agent IDs that decide to move."""

        joiners = []
        eavesdrop_cfg = self.config["eavesdrop_tendency"]
        current_group_size = len(self.get_group(conversation_chunk))

        for chunk in adjacent_chunks:
            for agent_id in self.get_group(chunk):
                if current_group_size + len(joiners) >= self.max_size:
                    break

                tendency = eavesdrop_cfg.get(agent_id, 0.3)
                # Also factor in topic relevance
                # (imported from the relevance map in conversation config)
                relevance = self._get_topic_relevance(agent_id, topic)

                # Combined probability of walking over
                walk_probability = tendency * 0.6 + relevance * 0.4

                if random.random() < walk_probability:
                    joiners.append(agent_id)

        return joiners

    def _get_topic_relevance(self, agent_id: str, topic: str) -> float:
        """Look up topic relevance from the conversation config."""
        # This gets injected at initialization from conversation_config.yaml
        return self._relevance_map.get(topic, {}).get(agent_id, 0.3)
```

---

## Conversation triggers

What starts a new conversation? Not just idle timeouts — there are five trigger types, each with different behavior.

```python
# core/triggers.py

import random
import time

class TriggerSystem:
    """Decides when and how new conversations start."""

    def __init__(self, config: dict, event_bus):
        self.config = config["triggers"]
        self.event_bus = event_bus
        self.last_conversation_end: float = time.time()
        self.pending_triggers: list[dict] = []

        # Subscribe to events that can trigger conversations
        event_bus.on("poll_result", self._on_environmental_event)
        event_bus.on("world_expansion", self._on_environmental_event)
        event_bus.on("budget_update", self._on_environmental_event)
        event_bus.on("viewer_milestone", self._on_environmental_event)
        event_bus.on("donation", self._on_audience_event)
        event_bus.on("chat_highlight", self._on_audience_event)

    async def check(self) -> dict | None:
        """Check if a new conversation should start. Returns trigger info or None."""

        now = time.time()

        # Priority 1: Pending event-driven triggers
        if self.pending_triggers:
            trigger = self.pending_triggers.pop(0)
            return trigger

        # Priority 2: Scheduled events (check the schedule)
        scheduled = await self._check_schedule(now)
        if scheduled:
            return scheduled

        # Priority 3: Idle timeout
        silence_duration = now - self.last_conversation_end
        if silence_duration >= self.config["idle_timeout_seconds"]:
            return self._generate_idle_trigger()

        # Priority 4: Memory trigger (random chance per tick)
        if random.random() < 0.02:  # ~2% chance per check cycle
            return await self._generate_memory_trigger()

        return None

    def _generate_idle_trigger(self) -> dict:
        """Pick an agent to start a conversation when things are quiet."""
        initiative = self.config["agent_initiative"]
        agents = list(initiative.keys())
        weights = [initiative[a] for a in agents]
        starter = random.choices(agents, weights=weights, k=1)[0]

        return {
            "type": "idle",
            "starter_agent_id": starter,
            "prompt_hint": "start_conversation_from_boredom",
            # The starter agent gets this in their prompt:
            # "It's been quiet for a while. What's on your mind?
            #  Start a conversation with whoever is nearby."
        }

    async def _generate_memory_trigger(self) -> dict | None:
        """An agent remembers something and brings it up unprompted."""
        # Pick a random agent, check if they have a recent memory
        # worth surfacing
        agent_id = random.choice(list(self.config["agent_initiative"].keys()))
        memory = await recall_random_recent_memory(agent_id)
        if memory and memory["importance"] > 0.6:
            return {
                "type": "memory",
                "starter_agent_id": agent_id,
                "memory_summary": memory["summary"],
                "prompt_hint": "bring_up_memory",
            }
        return None

    def _on_environmental_event(self, event: dict):
        """Queue an environmental trigger."""
        self.pending_triggers.append({
            "type": "environmental",
            "event": event,
            "prompt_hint": "react_to_event",
        })

    def _on_audience_event(self, event: dict):
        """Queue an audience trigger."""
        self.pending_triggers.append({
            "type": "audience",
            "event": event,
            "prompt_hint": "respond_to_audience",
            # Pixel gets first crack at audience events
            "preferred_starter": "pixel",
        })

    async def _check_schedule(self, now: float) -> dict | None:
        """Check if a scheduled event (standup, reflection, etc.) is due."""
        # This integrates with the scheduled content blocks from
        # FINAL-IMPLEMENTATION-PLAN.md (morning standup, evening reflection, etc.)
        schedule = await get_pending_scheduled_events(now)
        if schedule:
            return {
                "type": "scheduled",
                "event_name": schedule["name"],
                "starter_agent_id": schedule.get("led_by", "vera"),
                "prompt_hint": schedule["prompt_hint"],
                "participating_agents": schedule.get("required_agents", []),
            }
        return None
```

---

## The main loop (revised)

This replaces the simplified `ConversationEngine.run()` from the engineering spec.

```python
# core/conversation_engine.py

import asyncio
import yaml
import hashlib
from watchfiles import awatch  # file watcher for hot-reload

class ConversationEngine:
    """The main runtime loop. Orchestrates triggers, selection, generation, and energy."""

    def __init__(self, config_path: str, agents: list, event_bus, tts, overseer):
        self.config_path = config_path
        self.config = self._load_config()
        self.agents = {a.id: a for a in agents}
        self.event_bus = event_bus
        self.tts = tts
        self.overseer = overseer

        self.selector = SpeakerSelector(self.config)
        self.proximity = ProximityManager(self.config)
        self.triggers = TriggerSystem(self.config, event_bus)
        self.db = ConversationDB()  # wraps the SQL tables above

        self._active_conversation: dict | None = None

    def _load_config(self) -> dict:
        with open(self.config_path) as f:
            return yaml.safe_load(f)

    async def _watch_config(self):
        """Hot-reload config when the file changes."""
        async for changes in awatch(self.config_path):
            try:
                new_config = self._load_config()
                self.config = new_config
                self.selector = SpeakerSelector(new_config)
                self.proximity = ProximityManager(new_config)
                await self.event_bus.emit("config_reloaded", {
                    "hash": hashlib.sha256(
                        yaml.dump(new_config).encode()
                    ).hexdigest()[:16]
                })
                print(f"[ConversationEngine] Config reloaded")
            except Exception as e:
                print(f"[ConversationEngine] Config reload failed: {e}")
                # Keep the old config

    async def run(self):
        """Main loop. Runs forever."""
        # Start config watcher in background
        asyncio.create_task(self._watch_config())

        while True:
            if self._active_conversation:
                await self._continue_conversation()
            else:
                trigger = await self.triggers.check()
                if trigger:
                    await self._start_conversation(trigger)
                else:
                    await asyncio.sleep(1)  # check again in 1 second

    async def _start_conversation(self, trigger: dict):
        """Initialize a new conversation from a trigger."""

        starter_id = trigger.get("starter_agent_id")
        if trigger.get("preferred_starter"):
            starter_id = trigger["preferred_starter"]

        starter = self.agents[starter_id]
        chunk = self.proximity.locations.get(starter_id, "office")

        # Get the local group
        eligible = self.proximity.get_eligible_speakers(chunk, list(self.agents.values()))

        # Initialize energy
        energy = ConversationEnergy(self.config)

        # Create conversation record
        conv_id = await self.db.create_conversation(
            trigger_type=trigger["type"],
            trigger_details=trigger,
            initial_energy=energy.energy,
            participating_agents=[a.id for a in eligible],
            location=chunk,
        )

        self._active_conversation = {
            "id": conv_id,
            "history": [],
            "energy": energy,
            "eligible_agents": eligible,
            "chunk": chunk,
            "trigger": trigger,
        }

        # Generate the opening line
        opening = await self._generate_turn(
            starter, trigger.get("prompt_hint"), trigger.get("memory_summary")
        )

        await self._emit_and_record(starter, opening, conv_id, energy, topic="general")

    async def _continue_conversation(self):
        """Generate the next turn in an active conversation."""

        conv = self._active_conversation
        energy = conv["energy"]

        # Should this conversation end?
        if not energy.should_continue:
            await self._end_conversation()
            return

        # Check for eavesdroppers who might walk over
        topic = conv["history"][-1].get("topic", "general") if conv["history"] else "general"
        adjacent = await get_adjacent_chunks(conv["chunk"])
        joiners = await self.proximity.check_eavesdroppers(
            conv["chunk"], topic, list(self.agents.values()), adjacent
        )
        for joiner_id in joiners:
            joiner = self.agents[joiner_id]
            if joiner not in conv["eligible_agents"]:
                conv["eligible_agents"].append(joiner)
                self.proximity.update_location(joiner_id, conv["chunk"])
                energy.tick(topic, event="new_participant")
                await self.event_bus.emit("agent_move", {
                    "agent_id": joiner_id,
                    "target": conv["chunk"],
                    "reason": "heard_interesting_conversation",
                })

        # Select the next speaker
        result = await self.selector.select(
            conv["history"],
            conv["eligible_agents"],
            energy.energy,
        )

        # Log the selection
        await self.db.log_selection(
            conversation_id=conv["id"],
            turn_number=energy.turn_count,
            result=result,
            previous_speaker_id=(
                conv["history"][-1]["agent_id"] if conv["history"] else None
            ),
            active_agents=[a.id for a in conv["eligible_agents"]],
        )

        # Generate the turn
        speaker = self.agents[result.selected_agent_id]

        # If it was an interrupt, tell the speaker they're interrupting
        prompt_hint = "interrupt" if result.was_interrupt else None
        response = await self._generate_turn(speaker, prompt_hint)

        # Detect if this turn contains disagreement (for energy boost)
        event = await self._detect_event(response, conv["history"])

        # Update energy
        energy_changes = energy.tick(result.detected_topic, event=event)

        if self.config["logging"]["log_energy_changes"]:
            await self.db.log_energy(conv["id"], energy.turn_count, energy_changes)

        await self._emit_and_record(
            speaker, response, conv["id"], energy, result.detected_topic
        )

        # Variable pacing
        pause = self._calculate_pause(response)
        await asyncio.sleep(pause)

    async def _generate_turn(
        self, agent, prompt_hint: str | None = None, memory_context: str | None = None
    ) -> str:
        """Generate one agent's message."""

        # Assemble context (per MEMORY-SYSTEM.md spec)
        core_memory = await get_core_memory(agent.id)
        history_text = self._format_history(
            self._active_conversation["history"] if self._active_conversation else []
        )
        recall = await retrieve_recall_memories(agent.id, history_text)
        audience = await get_audience_status() if agent.id == "pixel" else ""

        # Build system prompt
        system = agent.system_prompt + core_memory + recall + audience

        # Build messages
        messages = [{"role": "system", "content": system}]

        if self._active_conversation:
            for msg in self._active_conversation["history"][-20:]:
                messages.append({
                    "role": "assistant" if msg["agent_id"] == agent.id else "user",
                    "content": f"[{msg['agent_id']}]: {msg['content']}",
                })

        # Add prompt hint for special situations
        if prompt_hint == "interrupt":
            messages.append({
                "role": "user",
                "content": (
                    "[SYSTEM: You feel compelled to jump in right now. "
                    "Interrupt naturally — 'Wait, hold on' or 'Actually—' etc. "
                    "Keep it brief.]"
                ),
            })
        elif prompt_hint == "start_conversation_from_boredom":
            messages.append({
                "role": "user",
                "content": (
                    "[SYSTEM: It's been quiet. Start a conversation about "
                    "whatever is on your mind. Look around — who's nearby?]"
                ),
            })
        elif prompt_hint == "bring_up_memory" and memory_context:
            messages.append({
                "role": "user",
                "content": (
                    f"[SYSTEM: You just remembered something: '{memory_context}'. "
                    f"Bring it up naturally if you want to.]"
                ),
            })
        elif prompt_hint == "closing":
            messages.append({
                "role": "user",
                "content": (
                    "[SYSTEM: This conversation is winding down. "
                    "Wrap it up naturally in your style.]"
                ),
            })

        # Call the LLM
        response = await openrouter.chat(
            model=agent.config["model_conversation"],
            messages=messages,
            max_tokens=300,
        )

        # Overseer content filter
        review = await self.overseer.review(agent.id, response.content)
        if not review["approved"]:
            return await self.overseer.generate_replacement(agent.id, review["reason"])

        return response.content

    async def _end_conversation(self):
        """Gracefully close the active conversation."""
        conv = self._active_conversation
        energy = conv["energy"]

        # Pick who closes it
        closer_id = energy.select_closer(conv["eligible_agents"])
        closer = self.agents[closer_id]

        # Generate a closing line
        closing = await self._generate_turn(closer, prompt_hint="closing")
        await self._emit_and_record(
            closer, closing, conv["id"], energy, topic="general"
        )

        # Update database
        await self.db.end_conversation(
            conversation_id=conv["id"],
            final_energy=energy.energy,
            turn_count=energy.turn_count,
            topics=list(energy.topics_seen),
            closed_by=closer_id,
        )

        # Compact the conversation into memory
        await compact_interaction(
            agent_id="all",  # shared conversation memory
            interaction=conv["history"],
            event_type="conversation",
        )

        self.triggers.last_conversation_end = time.time()
        self._active_conversation = None

    def _calculate_pause(self, response: str) -> float:
        """Calculate pause duration based on the response content."""
        cfg = self.config["timing"]
        base_min = cfg["min_pause_seconds"]
        base_max = cfg["max_pause_seconds"]

        if cfg["pause_strategy"] == "fixed":
            return (base_min + base_max) / 2

        if cfg["pause_strategy"] == "random":
            return random.uniform(base_min, base_max)

        # "weighted" strategy — adjust based on content
        multiplier = cfg["pause_multipliers"]["after_statement"]  # default

        if response.rstrip().endswith("?"):
            multiplier = cfg["pause_multipliers"]["after_question"]
        elif any(word in response.lower() for word in ["haha", "lol", "lmao", "😂"]):
            multiplier = cfg["pause_multipliers"]["after_joke"]
        elif any(word in response.lower() for word in ["feel", "miss", "worry", "scared", "sorry"]):
            multiplier = cfg["pause_multipliers"]["after_emotional"]

        base = random.uniform(base_min, base_max)
        return max(base_min, min(base * multiplier, base_max))

    async def _detect_event(self, response: str, history: list) -> str | None:
        """Detect if a turn represents a special event (disagreement, etc.)."""
        disagreement_signals = [
            "disagree", "wrong", "no way", "that's not", "actually,",
            "absolutely not", "are you kidding", "with all due respect",
        ]
        if any(signal in response.lower() for signal in disagreement_signals):
            return "disagreement"
        return None

    async def _emit_and_record(self, speaker, message, conv_id, energy, topic):
        """Emit event, play TTS, record to history."""
        # Emit to frontend
        await self.event_bus.emit("agent_speak", {
            "agent_id": speaker.id,
            "message": message,
            "conversation_id": str(conv_id),
            "energy": round(energy.energy, 1),
        })

        # TTS
        await self.tts.speak(speaker.id, speaker.voice_id, message)

        # Record in history
        conv = self._active_conversation
        if conv:
            conv["history"].append({
                "agent_id": speaker.id,
                "content": message,
                "topic": topic,
                "timestamp": time.time(),
            })

    def _format_history(self, history: list) -> str:
        return "\n".join(
            f"{m['agent_id']}: {m['content']}" for m in history[-10:]
        )
```

---

## Per-agent personality config

Each agent's `behaviors.yaml` (from CHARACTER-SHEETS.md) gets these new fields added for the conversation engine:

```yaml
# Example: config/agents/grok/conversation.yaml

conversation:
  chattiness: 0.85          # high — talks a lot
  initiative: 0.6           # medium-high — starts conversations
  interrupt_tendency: 0.8   # high — interrupts frequently
  eavesdrop_tendency: 0.8   # high — walks over to join conversations
  closing_weight: 0.05      # very low — never voluntarily ends conversations
  response_length: "medium" # "short", "medium", "long"
  model_conversation: "x-ai/grok-3"
  model_building: "x-ai/grok-3"

  # Conversation starters when idle (weighted random selection)
  idle_starters:
    - weight: 0.3
      type: "provocative_question"
      examples:
        - "So are we actually going to talk about the fact that we're all just—"
        - "Real question: who here actually thinks we're making progress?"
    - weight: 0.3
      type: "hot_take"
      examples:
        - "I've been thinking, and honestly? The Overseer is just management with a god complex."
        - "Hot take: we should delete the budget spreadsheet and see what happens."
    - weight: 0.2
      type: "audience_callout"
      examples:
        - "Chat is suspiciously quiet. Either they agree with me or they're plotting."
    - weight: 0.2
      type: "observation"
      examples:
        - "Anyone else notice Rex hasn't said a word in like an hour?"
        - "Aurora's been staring at that wall for twenty minutes. Should we be concerned?"
```

---

## Tuning workflow

The config is designed so you can tune the system without touching code. Here's the workflow:

**1. Watch a conversation that feels off.**

"Rex keeps talking even though the topic is art."

**2. Query the selection log.**

```sql
-- What scored Rex so high in the last conversation?
SELECT
    turn_number,
    agent_scores->'rex' as rex_scores,
    detected_topic,
    selected_agent_id
FROM conversation_selection_log
WHERE conversation_id = 'abc-123'
ORDER BY turn_number;
```

Output tells you: Rex's `time_since_spoke` was 0.95 (he hadn't talked in a while) which overwhelmed his low `relevance` of 0.1 for art topics.

**3. Adjust the config.**

Lower `time_since_spoke` weight from 0.30 to 0.25, raise `topic_relevance` from 0.30 to 0.35. Save the file — the engine hot-reloads.

**4. Watch the next conversation.**

The selection log now shows a different `config_hash`, so you can compare before/after behavior in the database.

**Useful diagnostic queries:**

```sql
-- Which agent talks the most across all conversations?
SELECT selected_agent_id, COUNT(*) as turns
FROM conversation_selection_log
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY selected_agent_id
ORDER BY turns DESC;

-- Average conversation length by trigger type
SELECT
    c.trigger_type,
    AVG(c.turn_count) as avg_turns,
    AVG(EXTRACT(EPOCH FROM (c.ended_at - c.started_at))) as avg_duration_seconds
FROM conversations c
WHERE c.ended_at IS NOT NULL
GROUP BY c.trigger_type;

-- How often does each agent interrupt, and who do they interrupt?
SELECT
    attempting_agent_id as interrupter,
    would_have_spoken_id as interrupted,
    COUNT(*) as times,
    AVG(interrupt_score) as avg_score
FROM interrupt_log
WHERE succeeded = true
GROUP BY attempting_agent_id, would_have_spoken_id
ORDER BY times DESC;

-- Conversations where energy ran out too fast (< 5 turns)
SELECT id, trigger_type, turn_count, initial_energy, final_energy, topics_discussed
FROM conversations
WHERE turn_count < 5 AND ended_at IS NOT NULL
ORDER BY started_at DESC
LIMIT 20;

-- Compare conversation quality before/after a config change
SELECT
    config_hash,
    AVG(turn_count) as avg_turns,
    COUNT(*) as conversations,
    AVG(audience_events_during) as avg_audience_engagement
FROM conversations
WHERE started_at > NOW() - INTERVAL '7 days'
GROUP BY config_hash
ORDER BY MIN(started_at);
```

---

## How this replaces the old spec

The `ConversationEngine` class in ENGINEERING-SPECS.md Task 1.3 was a simplified skeleton. This spec:

- Replaces the 3-factor weighted selection (time/chattiness/relevance) with a 5-factor system (+ adjacency fit + jitter) that sums to 1.0
- Adds the interrupt mechanic (agents can override the selection based on urgency)
- Adds the energy model (conversations have organic lifespans instead of hard turn limits)
- Adds proximity grouping (agents must be in the same area to participate)
- Adds five conversation trigger types instead of just an idle loop
- Adds eavesdropping (agents in adjacent chunks can walk over)
- Adds variable pacing (pause length depends on what was just said)
- Adds conversation closers (personality-weighted natural endings)
- Adds full selection logging with diagnostic queries
- Makes every parameter config-driven with hot-reload
- Adds per-agent conversation personality configs with idle starters

The old spec's acceptance criteria still apply. Add these:

- [ ] Config file validates on load (weights sum to 1.0, all agent IDs exist)
- [ ] Hot-reload works: change a weight, save, next turn uses new weight
- [ ] Selection log records every turn with full score breakdown
- [ ] Interrupt fires at least once during a 10-conversation test run
- [ ] Energy model produces conversations between 4 and 30 turns
- [ ] Proximity groups prevent agents from joining conversations in other chunks
- [ ] Eavesdropping works: agent in adjacent chunk walks over and joins mid-conversation
- [ ] Conversations triggered by all 5 trigger types during a 1-hour test run
- [ ] Diagnostic queries return meaningful data after 20+ conversations
- [ ] No single agent exceeds 35% of total turns across a 24-hour run

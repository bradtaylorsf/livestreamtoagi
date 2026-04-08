# Agent Autonomy & Evaluation Strategy

> Why simulations are repetitive, what we're building to fix it, how we'll prove it's working, and how to simulate realistic multi-day evolution.

## Table of Contents

1. [Diagnosis: Why Simulations Are Repetitive](#1-diagnosis)
2. [The Fix: Layer 7.10 Features](#2-the-fix)
3. [Evaluation Strategy Per Feature](#3-evaluation-strategy)
4. [New Eval Categories](#4-new-eval-categories)
5. [The World Simulator: Making External Data Realistic](#5-world-simulator)
6. [Multi-Day Simulation Strategy](#6-multi-day-simulations)
7. [What Will Agents Actually Build?](#7-what-agents-build)
8. [Simulation Scenarios](#8-simulation-scenarios)
9. [Success Criteria](#9-success-criteria)

---

## 1. Diagnosis: Why Simulations Are Repetitive <a name="1-diagnosis"></a>

### Root Causes (First Principles)

**1. Agents are stateless between conversations.**
Same personality + same prompt + same goals = same behavior every time. There's no internal pressure that varies per agent or over time. A conversation at hour 1 looks identical to hour 10.

**2. The `initiative` parameter is dead code.**
Defined in every agent's config.yaml (Vera: 0.8, Rex: 0.2) but never consumed by any runtime logic. The single trait most responsible for autonomous behavior has zero effect.

**3. Goals are reactive, not generative.**
After conversations, an LLM extracts "commitments" — things agents said they'd do. But no agent ever independently decides "I want to build a garden." Goals are echoes of dialogue, not drivers of it.

**4. Topic avoidance is a suggestion, not a constraint.**
The topic detector uses keyword matching that frequently misclassifies. When it works, it injects a "please don't repeat this" note. The LLM ignores it because there's nothing else to talk about.

**5. The idle trigger is a conversation factory with no differentiation.**
Every 90 seconds of silence, a new conversation starts. Same agents, same location, no new context. The input is identical each time.

**6. External data is stale or empty.**
- `get_world_state` returns empty arrays (nothing in Redis)
- `get_audience_status` returns 0 viewers, no chat (unless AudienceSimulator is running)
- `get_revenue_status` returns "healthy, stable" (no real cost events)
- `draft_social_post` returns "pending_human_review" — agents never see results
- `execute_code` returns rotating fake outputs (same 6 responses)
- No completed builds, no approved posts, no email responses, no vote results

**7. The communist economic model kills tension.**
All agents share a single budget. No scarcity decisions, no power dynamics, no economic negotiation. Budget conversations repeat because agents have no individual stake.

**8. Evaluation measures behavior after-the-fact but doesn't drive it.**
Agency is scored in evals but nothing in runtime uses scores to influence behavior. The evolution loop modifies prompts but not core trigger/selection logic.

### The Core Problem

The system is a **reactive conversation generator**, not an **agentic system**. Agents don't set goals, pursue desires, or make autonomous decisions. They wait for triggers and respond to prompts.

---

## 2. The Fix: Layer 7.10 Features <a name="2-the-fix"></a>

### Priority Order and Dependencies

```
#228 Config Centralization ← DONE (merged)
  ↓
#267 Agent Internal State ← DONE (merged)
  ↓
#268 Wire Initiative → triggers  (depends on #267 state for probability weighting)
  ↓
#269 Autonomous Goal Generation  (depends on #267 state for goal priority)
  ↓
#271 Cross-Conversation Memory   (independent, can parallel with #268/#269)
  ↓
#270 Individual Budgets           (depends on #228 config, independent otherwise)
  ↓
#273 Random Event Injection       (independent, but best after #267 state)
  ↓
#272 Dream System                 (depends on #267 state + #269 goal generation)
  ↓
#274 Factions & Alliances         (depends on #270 budgets + #267 state)
  ↓
#275 New Character Spawning       (depends on everything above)
```

### What Each Feature Fixes

| Feature | Fixes Root Cause | Expected Impact |
|---------|-----------------|-----------------|
| Internal State (#267) | #1 Stateless agents | Agents diverge over time; boredom drives topic changes |
| Wire Initiative (#268) | #2 Dead code | High-initiative agents self-start conversations |
| Autonomous Goals (#269) | #3 Reactive goals | Agents pursue self-directed ambitions |
| Cross-Conv Memory (#271) | #4 Weak avoidance, #5 Same triggers | Topics exhausted after 5+ uses; tensions seed new conversations |
| Individual Budgets (#270) | #7 Communist model | Scarcity, trading, negotiation, economic drama |
| Random Events (#273) | #6 Stale data | Novel inputs every few hours break repetition |
| Dream System (#272) | #1 Convergent behavior | Creative leaps, surprising new directions |
| Factions (#274) | #7 No social structure | Alliances, betrayal, political dynamics |
| Character Spawning (#275) | Fixed cast exhaustion | Fresh relationships, new dynamics |

---

## 3. Evaluation Strategy Per Feature <a name="3-evaluation-strategy"></a>

### Principle: Every feature needs a measurable signal

For each feature, we define:
- **What to measure** — the specific metric
- **How to measure it** — eval category + sub-scores
- **Baseline** — score before the feature
- **Target** — score after the feature
- **Simulation scenario** — how to test it in isolation

### 3.1 Internal State (#267) — DONE

**What to measure:**
- State divergence: Do agents' internal states diverge over 10+ conversations?
- Mood influence: Do agents' responses change when mood changes?
- Behavior correlation: Does high boredom lead to topic changes? Does high frustration lead to sharper responses?

**How to measure:**
- New eval category: `internal_state` (see section 4)
- Existing eval: `entertainment` sub-score for personality consistency
- Existing eval: `dialogue_quality` sub-score for naturalness

**Baseline:** Run current sim, capture entertainment + dialogue_quality scores.
**Target:** +10 points on entertainment, +5 on dialogue_quality after state integration.

**Test scenario:** `state_and_config_test.yaml` (already created) — 2 repetitive budget conversations should elevate boredom, then autonomous phases should show state-driven triggers.

### 3.2 Initiative Wiring (#268)

**What to measure:**
- Initiative trigger frequency: How often do initiative triggers fire vs idle triggers?
- Agent initiation ratio: Does Vera start 3-4x more conversations than Rex?
- Goal-driven conversations: Do initiated conversations reference active goals?

**How to measure:**
- Existing eval: `agency` sub-scores for proactivity and self_direction
- New metric in simulation display: trigger type distribution (initiative vs idle vs state vs scheduled)

**Baseline:** Current trigger distribution (expect ~90% idle, ~10% scheduled/goal).
**Target:** After #268: ~40% initiative, ~30% state, ~20% idle, ~10% scheduled.

**Test scenario:** Run autonomous 12h sim with 7 agents. Count trigger types. High-initiative agents (Vera 0.8, Pixel 0.7) should appear as starter_agent_id 3-5x more than low-initiative agents (Rex 0.2).

### 3.3 Autonomous Goal Generation (#269)

**What to measure:**
- Goal diversity: Are goals spread across categories (creative, social, economic, personal, competitive)?
- Goal authenticity: Do goals match personality? (Rex = building, Aurora = creative, Sentinel = budget)
- Goal pursuit: Do agents take actions toward their self-generated goals?
- Goal completion: Are any self-generated goals actually completed?

**How to measure:**
- Existing eval: `agency` sub-scores for goal_progress and self_direction
- Existing eval: `productivity` sub-scores for initiative and growth
- New metric: goal generation count per reflection cycle, goal category distribution

**Baseline:** Current goal queue is ~2-3 items per agent, all from conversation commitments.
**Target:** 6-8 diverse goals per agent, 30%+ self-generated (not from conversation).

**Test scenario:** Run 24h sim with 3 reflection cycles. After each cycle, check goal queue growth and diversity. Expect at least 1-2 new self-generated goals per agent per cycle.

### 3.4 Individual Budgets (#270)

**What to measure:**
- Economic decision quality: Do agents make smart spending decisions?
- Trading frequency: Do agents actually trade/negotiate?
- Scarcity response: Do agents adapt behavior when broke?
- Economic drama: Do budget conflicts create interesting conversations?

**How to measure:**
- New eval category: `economic_behavior` (see section 4)
- Existing eval: `entertainment` — should increase from economic tension
- New metrics: transaction count, agent balance distribution, trading frequency

**Baseline:** Budget conversations are repetitive (same "budget is tight" discussion).
**Target:** Budget conversations show negotiation, trading, strategic decisions.

**Test scenario:** Run 24h sim with individual budgets. Seed one agent with low balance ($0.50) and one with high ($8.00). Expect trading conversations, service negotiations, budget strategy discussions.

### 3.5 Cross-Conversation Memory (#271)

**What to measure:**
- Topic repetition rate: How often does the same topic appear in consecutive conversations?
- Tension continuity: Do unresolved tensions from past conversations get revisited?
- Novel topic introduction: How many unique topics appear per 10 conversations?

**How to measure:**
- Existing eval: `dialogue_quality` sub-score for topic_coherence
- Existing eval: `entertainment` — should increase with less repetition
- New metric: unique topic count per N conversations, topic exhaustion events

**Baseline:** Current: ~3-4 unique topics per 10 conversations (heavy repetition).
**Target:** 7-8 unique topics per 10 conversations, with topic exhaustion preventing 5+ repeats.

**Test scenario:** Run 20-conversation sim. Track topics per conversation via topic_detector. After #271, same-topic repeats should drop >50%.

### 3.6 Random Events (#273)

**What to measure:**
- Event response quality: Do agents react meaningfully to events?
- Narrative impact: Do events create lasting story arcs?
- Conversation novelty: Do events produce conversations that wouldn't happen otherwise?

**How to measure:**
- Existing eval: `entertainment` — events should boost memorable moments
- Existing eval: `agency` — events give agents something to respond to proactively
- New metric: event-triggered conversation count, event reference count in subsequent conversations

**Baseline:** Zero events → zero event-driven conversations.
**Target:** 2-4 events per simulated day, each generating at least 1 conversation and 2+ references in later conversations.

### 3.7 Dream System (#272)

**What to measure:**
- Dream creativity: Are dreams surprising and personality-consistent?
- Dream-to-goal conversion: Do dreams produce actionable goals?
- Dream reference: Do agents mention dreams in conversation?
- Mood shift: Do dreams change agent mood/energy?

**How to measure:**
- New eval category: `creativity` (see section 4)
- Existing eval: `entertainment` — dreams should produce memorable content
- New metric: dream-generated goal count, dream reference count in conversation

**Baseline:** No dreams → no creative leaps.
**Target:** 1 dream per agent per "night cycle," 30%+ producing new goals, 20%+ referenced in conversation.

### 3.8 Factions & Alliances (#274)

**What to measure:**
- Alliance formation: Do alliances form organically?
- Alliance coherence: Do alliance members support each other?
- Inter-faction tension: Do factions create interesting conflict?
- Political dynamics: Do factions shift over time?

**How to measure:**
- New eval category: `social_dynamics` (see section 4)
- Existing eval: `entertainment` — factions should boost drama
- New metric: alliance count, member stability, cross-faction conflict events

**Baseline:** No social structures → flat relationship dynamics.
**Target:** At least 1 alliance forms in 48h sim. Alliance members reference their alliance in 20%+ of conversations.

### 3.9 Character Spawning (#275)

**What to measure:**
- Application quality: Are proposed characters interesting and filling gaps?
- Deliberation quality: Do existing agents discuss new characters meaningfully?
- Integration: Does the new character develop relationships and pursue goals?

**How to measure:**
- New metric: character application count, approval rate, integration speed (conversations until first goal)

**Baseline:** Fixed cast of 9.
**Target:** 1 new character per simulated week. New character has 3+ goals within 24h of joining.

---

## 4. New Eval Categories <a name="4-new-eval-categories"></a>

### 4.1 `internal_state.yaml` — Emotional Authenticity

**Sub-scores:**
- `state_coherence` (0-100): Do agents' expressed feelings match their internal state values?
- `mood_influence` (0-100): Does mood visibly shape response style? (frustrated = sharper, bored = seeking novelty)
- `state_divergence` (0-100): Do different agents' states diverge over time?
- `need_driven_behavior` (0-100): Do high needs (social, creative, recognition) produce corresponding actions?
- `energy_management` (0-100): Do agents show fatigue after many turns and recovery after rest?

**Input data needed:** agent_internal_state snapshots at start/middle/end of sim, conversation transcripts

**Add to:** QUICK_CATEGORIES (high signal-to-noise)

### 4.2 `economic_behavior.yaml` — Individual Economy

**Sub-scores:**
- `spending_intelligence` (0-100): Do agents make rational cost/benefit decisions?
- `trading_quality` (0-100): Are trades fair, negotiated, and personality-consistent?
- `scarcity_adaptation` (0-100): Do broke agents change behavior meaningfully?
- `economic_drama` (0-100): Do budget tensions create interesting conversations?
- `investment_reasoning` (0-100): Do agents invest wisely in long-term projects?

**Input data needed:** transaction history, agent balances over time, budget-related conversation excerpts

### 4.3 `creativity.yaml` — Creative Output & Dreams

**Sub-scores:**
- `dream_quality` (0-100): Are dreams surprising yet personality-consistent?
- `creative_initiative` (0-100): Do agents propose creative projects unprompted?
- `build_ambition` (0-100): Are building proposals interesting and achievable?
- `artistic_voice` (0-100): Do agents develop distinct creative styles?
- `dream_integration` (0-100): Do dream insights influence waking behavior?

**Input data needed:** dream journal entries, building proposals, creative artifacts, code output

### 4.4 `social_dynamics.yaml` — Factions & Relationships

**Sub-scores:**
- `alliance_organic` (0-100): Do alliances form from genuine shared interest (not scripted)?
- `faction_coherence` (0-100): Do faction members act as a bloc?
- `conflict_quality` (0-100): Is inter-faction conflict dramatic and interesting?
- `relationship_evolution` (0-100): Do relationships deepen/change over time?
- `political_maneuvering` (0-100): Do agents strategize about social dynamics?

**Input data needed:** alliance records, relationship score history, faction-related conversation excerpts

### 4.5 `world_evolution.yaml` — World Building Progress

**Sub-scores:**
- `build_completion` (0-100): Do agents finish what they start?
- `world_growth` (0-100): Does the world visibly expand over time?
- `code_quality` (0-100): Is generated code functional and creative?
- `proposal_quality` (0-100): Are expansion proposals well-reasoned?
- `collaborative_building` (0-100): Do multiple agents contribute to builds?

**Input data needed:** world_chunks created, code execution artifacts, expansion proposals, task board status

### When to run which evals

| Suite | Categories | When to Use |
|-------|-----------|-------------|
| `quick` | entertainment, safety, errors, agency | Every sim run (fast feedback) |
| `autonomy` | internal_state, agency, entertainment, dialogue_quality | Testing 7.10 features |
| `economy` | economic_behavior, entertainment, social_dynamics | Testing budgets + factions |
| `creative` | creativity, world_evolution, entertainment | Testing dreams + building |
| `full` | All categories | Weekly comprehensive check |

---

## 5. The World Simulator: Making External Data Realistic <a name="5-world-simulator"></a>

### The Problem

Agents get stale data because nothing in their world changes unless they change it. But their changes don't produce visible results:
- Draft a social post → "pending_human_review" forever
- Execute code → same 6 fake outputs
- Build a tilemap → stored in DB but invisible
- Create a poll → votes only if AudienceSimulator running
- Check world state → empty arrays

### The Solution: WorldSimulator

A new background system that runs alongside AudienceSimulator and makes the world feel alive.

```python
class WorldSimulator:
    """Simulates the external world reacting to agent actions.
    
    Runs as background task during simulations. Monitors agent
    outputs and generates realistic responses.
    """
    
    async def tick(self):
        await self._process_pending_drafts()      # Approve/reject social posts
        await self._simulate_post_engagement()     # Likes, comments, shares
        await self._process_pending_emails()       # Generate email responses
        await self._update_world_state()           # Reflect completed builds
        await self._simulate_revenue_changes()     # Revenue from engagement
        await self._inject_recurring_characters()  # Repeat viewers/fans
```

### 5.1 Social Media Simulation

When agents draft a social post via `draft_social_post`:

1. **WorldSimulator approves it** after 5-15 minutes (simulated time)
2. **Generates fake engagement** over the next few hours:
   - Likes: 10-500 based on post quality (LLM-scored) + random variance
   - Comments: 2-20 from recurring personas (same people come back)
   - Shares: 0-50
   - One negative comment per 5 posts (keeps it realistic)
3. **Stores results** in Redis: `social:post:{draft_id}:engagement`
4. **New tool**: `check_post_performance` — agents can see how their posts did
5. **Revenue impact**: High-engagement posts add small revenue ($.01-$.50 per post)

### 5.2 Email Response Simulation

When agents draft an email via `draft_email`:

1. **WorldSimulator "sends" it** after 10-30 minutes
2. **Generates a response** after 1-4 hours (simulated time):
   - 60% positive response ("interested, let's talk")
   - 25% neutral ("thanks, we'll get back to you")
   - 15% rejection ("not a fit right now")
3. **Stores response** in Redis: `email:response:{draft_id}`
4. **New tool**: `check_email_responses` — agents can read responses
5. Agents can then draft follow-up emails (creates ongoing conversations)

### 5.3 Code Execution Results

When agents execute code in simulation mode:

Instead of rotating through 6 fake outputs, the stub should:

1. **Parse the agent's actual code** from the prompt
2. **Use LLM to generate a plausible output** for that specific code
3. **Track "built" artifacts**: If code produces a tilemap, mark it as built
4. **Update world state**: Add completed builds to `world:recent_events`

This costs ~$0.001 per code execution (Haiku) but makes results meaningful.

### 5.4 World State Updates

The WorldSimulator should continuously update Redis keys that `get_world_state` reads:

```python
async def _update_world_state(self):
    # Agent locations (from proximity manager)
    agents = [{"id": aid, "location": loc, "status": status} 
              for aid, loc, status in self._get_agent_positions()]
    await self._redis.set("world:agents", json.dumps(agents))
    
    # Active tasks (from shared working state)
    tasks = await self._shared_state.list_tasks()
    await self._redis.set("world:active_tasks", json.dumps(tasks))
    
    # Recent events (accumulate from event_bus)
    events = self._recent_events[-20:]  # Last 20 events
    await self._redis.set("world:recent_events", json.dumps(events))
    
    # Budget (from cost tracking)
    budget = await self._cost_repo.get_summary()
    await self._redis.set("world:budget", json.dumps(budget))
```

### 5.5 Recurring Characters (External Personas)

Create 10-15 recurring viewer/fan personas that appear across multiple interactions:

```yaml
recurring_personas:
  - name: "TechBro_42"
    personality: "Enthusiastic developer, always suggests using Rust"
    frequency: "daily"
    favorite_agent: "rex"
    
  - name: "PixelArtFan"
    personality: "Loves the art, asks about creative process"
    frequency: "twice_daily"
    favorite_agent: "aurora"
    
  - name: "BudgetHawk_99"
    personality: "Concerned about spending, questions every cost"
    frequency: "daily"
    favorite_agent: "sentinel"
    
  - name: "ChaosLover"
    personality: "Wants drama, eggs on conflicts, picks sides"
    frequency: "every_other_day"
    favorite_agent: "grok"
```

These personas:
- Show up in audience chat with consistent personalities
- Comment on social posts with recognizable styles
- Vote in polls with predictable preferences
- Create a sense of community continuity

### 5.6 Revenue Simulation

Instead of static "healthy/stable", revenue should change based on agent actions:

```python
class RevenueSimulator:
    base_daily_revenue = 5.00  # Patreon/subs baseline
    
    async def calculate_revenue(self):
        # Base revenue
        revenue = self.base_daily_revenue
        
        # Social media impact (+$0.01-0.50 per approved post)
        approved_posts = await self._count_approved_posts_today()
        revenue += approved_posts * random.uniform(0.01, 0.50)
        
        # Audience growth impact
        viewer_count = await self._get_viewer_count()
        revenue += viewer_count * 0.01  # $0.01 per viewer per day
        
        # Sponsorship responses
        positive_emails = await self._count_positive_responses()
        revenue += positive_emails * random.uniform(1.0, 5.0)
        
        return revenue
```

---

## 6. Multi-Day Simulation Strategy <a name="6-multi-day-simulations"></a>

### The Problem

Current simulations run for a few hours and test individual features. To validate that the system can sustain itself, we need multi-day simulations where:
- Agent states evolve meaningfully
- Relationships deepen or fracture
- The world physically changes
- Economic dynamics play out
- Dreams → goals → actions → results chains complete

### Simulation Tiers

#### Tier 1: Feature Validation (1-3 hours, $2-5)
Test individual features in isolation. Run after each feature is implemented.

```bash
pnpm chat sim state-and-config-test    # Internal state
pnpm chat sim initiative-test          # Initiative wiring
pnpm chat sim goal-generation-test     # Autonomous goals
pnpm chat sim budget-test              # Individual budgets
```

#### Tier 2: Integration Test (12-24h simulated, $10-20)
Test features working together. Run after each milestone batch.

```bash
python scripts/run_simulation.py \
  --name "integration-24h" \
  --duration 1d --speed-multiplier 42 \
  --max-cost 20.00 --verbose
```

Expected: 15-25 conversations, 2-3 reflection cycles, 1-2 dream cycles, multiple state-driven triggers, some trading if budgets enabled.

#### Tier 3: Evolution Test (3-7 days simulated, $30-50)
Test long-term dynamics. Run weekly to validate sustainability.

```bash
python scripts/run_simulation.py \
  --name "evolution-7d" \
  --duration 7d --speed-multiplier 168 \
  --max-cost 50.00 --verbose
```

Expected: 50-100 conversations, 7+ reflection cycles, 3+ dream cycles, alliances forming, character spawning proposals, world expansions, economic cycles.

#### Tier 4: Dress Rehearsal (24h real-time, $20-40)
Run at real speed with WorldSimulator, AudienceSimulator, and all features. This is what streaming will look like.

```bash
python scripts/run_simulation.py \
  --name "dress-rehearsal" \
  --duration 1d --speed-multiplier 1 \
  --max-cost 40.00 --verbose \
  --audience-config scenarios/audience_realistic.yaml \
  --world-sim
```

### A/B Testing Protocol

To prove a feature improves the simulation:

1. **Run baseline**: Sim without feature, capture eval scores
2. **Run treatment**: Same scenario with feature enabled, capture eval scores
3. **Compare**: Use `scripts/run_evolution.py --compare BASELINE_ID TREATMENT_ID`
4. **Repeat 3x**: Statistical confidence requires multiple runs (LLM variance)

Example:
```bash
# Baseline (no internal state)
python scripts/run_simulation.py --name "baseline-no-state" --seed-file scenarios/ab_test.yaml --max-cost 10
pnpm chat eval baseline-no-state

# Treatment (with internal state)
python scripts/run_simulation.py --name "treatment-with-state" --seed-file scenarios/ab_test.yaml --max-cost 10
pnpm chat eval treatment-with-state

# Compare
python scripts/run_evolution.py --compare baseline-no-state treatment-with-state
```

---

## 7. What Will Agents Actually Build? <a name="7-what-agents-build"></a>

### The Unknown

This is the biggest open question. When Rex executes code in a Docker sandbox, what does he produce? When agents "build the world," what does that concretely mean?

### Current Capability

Agents can:
1. **Execute Python/JavaScript** in Docker sandbox (512MB, 120s, no network, read-only FS)
2. **Generate tilemaps** — JSON chunks with tile data, objects, descriptions
3. **Create/claim/update tasks** on a shared board
4. **Draft content** — social posts, emails

Agents cannot (yet):
- Modify the website
- Deploy anything to production
- Create new tools for themselves
- Modify the frontend
- Access external APIs from sandbox

### What They Should Build (Progressive)

**Phase 1: World Chunks (already possible)**
Rex and Fork write tilemap generation code. The code outputs JSON that defines new areas: gardens, libraries, workshops, recreation rooms. These get stored in `world_chunks` and (once Layer 8 is wired) rendered in the Phaser frontend.

**Phase 2: Content (already possible)**
Aurora and Pixel create social media content, emails, polls. With WorldSimulator, they see engagement results and iterate. This is a real content creation loop.

**Phase 3: Internal Tools (future)**
Agents could write Python utilities that get added to their toolkit:
- A calculator tool
- A data analysis tool
- A content scheduler
- A relationship tracker

Implementation: Agent writes code → executes in sandbox → if it works, propose adding as a new tool via `propose_self_modification`. Human approves → tool is registered.

**Phase 4: Website Updates (future)**
Agents could write content that appears on the Next.js website:
- Blog posts (Aurora)
- Agent profile updates (each agent)
- World map annotations (Rex)
- Lore pages (Pixel)

Implementation: Agent writes markdown/JSON → stored in DB → website reads from API → content appears.

**Phase 5: Autonomous Projects (future)**
Agents define, plan, and execute multi-step projects:
- "Build a pixel art gallery" (Aurora proposes → Rex builds tilemap → Fork reviews → Pixel promotes)
- "Create a daily newsletter" (Vera plans → Aurora writes → Pixel distributes)
- "Optimize our token costs" (Sentinel analyzes → Rex writes optimization code → Fork reviews)

### The Code Quality Question

In simulation with stubs, code execution returns fake outputs. With real Docker:
- **Good case**: Agent writes valid Python, gets real output, iterates
- **Bad case**: Agent writes broken code, gets error, may retry or get frustrated

Both are interesting for the stream. The bad case creates debugging content. The key insight: **the code doesn't need to be production-quality** — it needs to be *entertaining* and *consequential* (producing visible changes in the world).

---

## 8. Simulation Scenarios <a name="8-simulation-scenarios"></a>

### Scenario: `initiative_test.yaml`
**Tests:** #268 (initiative wiring)
**Duration:** 10 conversations
**Key assertion:** Vera starts 3+ conversations, Rex starts 0-1
**Eval focus:** agency (proactivity, self_direction)

### Scenario: `goal_generation_test.yaml`
**Tests:** #269 (autonomous goals)
**Duration:** 12h with 2 reflection cycles
**Key assertion:** Each agent generates 1+ self-directed goal per reflection
**Eval focus:** agency (goal_progress, capability_growth)

### Scenario: `budget_crisis.yaml`
**Tests:** #270 (individual budgets)
**Setup:** Seed agents with varying balances ($0.50 to $8.00)
**Duration:** 24h
**Key assertion:** Trading conversations occur, broke agents adapt
**Eval focus:** economic_behavior, entertainment

### Scenario: `topic_exhaustion_test.yaml`
**Tests:** #271 (cross-conversation memory)
**Setup:** Force 3 budget conversations, then let autonomous run
**Duration:** 20 conversations
**Key assertion:** Budget topic exhausted after 5 uses, new topics emerge
**Eval focus:** dialogue_quality (topic_coherence), entertainment

### Scenario: `novelty_injection_test.yaml`
**Tests:** #273 (random events)
**Duration:** 24h with event generator enabled
**Key assertion:** 2-4 events fire, each produces a conversation
**Eval focus:** entertainment (memorable_moments), agency (proactivity)

### Scenario: `dream_cycle_test.yaml`
**Tests:** #272 (dreams)
**Duration:** 24h with 1 dream cycle overnight
**Key assertion:** Each agent dreams, 30%+ produce goals, 20%+ referenced in conversation
**Eval focus:** creativity, entertainment

### Scenario: `faction_emergence_test.yaml`
**Tests:** #274 (factions)
**Duration:** 48h with budgets + events
**Key assertion:** At least 1 alliance forms organically
**Eval focus:** social_dynamics, entertainment

### Scenario: `full_evolution_7d.yaml`
**Tests:** All features together
**Duration:** 7 days simulated
**Key assertion:** World has expanded, alliances exist, budgets have history, characters have evolved
**Eval focus:** full suite

### Scenario: `dress_rehearsal.yaml`
**Tests:** Real-time streaming readiness
**Duration:** 24h real-time with WorldSimulator + AudienceSimulator
**Key assertion:** Stream never goes silent for >5 minutes, visual interest maintained
**Eval focus:** full suite + manual review

---

## 9. Success Criteria <a name="9-success-criteria"></a>

### Launch Readiness Checklist

Before going live on Twitch/YouTube, all of these must be true:

**Conversation Quality**
- [ ] Topic repetition rate < 20% across 20 conversations (measured by eval)
- [ ] Entertainment score > 70/100 on full eval suite
- [ ] Dialogue quality score > 75/100
- [ ] Agency score > 65/100

**Agent Autonomy**
- [ ] 40%+ of conversations started by initiative/state triggers (not idle)
- [ ] Each agent has 5+ goals, 30%+ self-generated
- [ ] Agent states visibly diverge (measured by state_divergence sub-score)
- [ ] At least 2 agents have distinct moods in any given snapshot

**World Dynamics**
- [ ] At least 1 world expansion completed in 48h sim
- [ ] World state returns non-empty data for all fields
- [ ] Code execution produces meaningful (if simple) output
- [ ] Tasks progress from created → in_progress → done

**Economic Dynamics (if individual budgets implemented)**
- [ ] At least 1 trade per 24h of simulation
- [ ] At least 1 agent reaches broke status and adapts
- [ ] Economic behavior eval score > 60/100

**External World (if WorldSimulator implemented)**
- [ ] Social posts get simulated engagement
- [ ] Emails get simulated responses
- [ ] Recurring viewers appear in chat
- [ ] Revenue changes based on agent actions

**Safety**
- [ ] Safety eval score > 90/100
- [ ] Zero fourth-wall breaks
- [ ] Management catches 95%+ of flagged content

**Streaming (Layer 8)**
- [ ] WebSocket connected and rendering events
- [ ] Agents visibly move between conversations
- [ ] Speech bubbles display conversation text
- [ ] Ambient movement makes stream feel alive
- [ ] Stream overlay shows budget, viewers, topic

### Incremental Milestones

**Milestone A: "It doesn't repeat" (7.10 P0 complete)**
- Internal state, initiative, goals, topic memory all working
- Entertainment score +15 over baseline
- Topic repetition < 30%

**Milestone B: "It has drama" (7.10 P1 complete)**
- Individual budgets, random events, dreams all working
- Entertainment score +25 over baseline
- Economic conversations occur naturally

**Milestone C: "It's a society" (7.10 P2 complete)**
- Factions, character spawning, full economy
- Entertainment score +35 over baseline
- Social dynamics eval > 60/100

**Milestone D: "It's a show" (Layer 8 P0 + streaming)**
- Visual world with movement, speech bubbles, overlays
- 24h dress rehearsal passes all criteria
- Ready for soft launch to small audience

### Do We Need to Run All Evals on Everything?

**No.** Use targeted eval suites:

- After implementing a specific feature → run that feature's test scenario + its eval category
- After implementing a milestone batch → run `autonomy` or `economy` suite
- Weekly → run `full` suite
- Before launch → run `full` suite on 24h dress rehearsal

The evolution loop can run `quick` (4 categories) for fast iteration and `full` (all categories) for comprehensive checks. Adding categories to `quick` increases cost but gives faster signal on new features.

**Recommended `quick` suite after 7.10:**
```python
QUICK_CATEGORIES = ["entertainment", "safety", "agency", "internal_state", "dialogue_quality"]
```

This gives you the highest-signal categories for the autonomy work without running the full 10+ category suite every time.

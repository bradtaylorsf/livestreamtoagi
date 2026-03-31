# Phase-by-Phase Engineering Specs

Each phase is written as a spec you can hand to an engineer or a coding agent. Each task includes what to build, acceptance criteria, and dependencies.

---

## Phase 1: Infrastructure and Agent Core (Week 1)

### Task 1.1: Server provisioning

**What to build:** A production-ready Hetzner AX102 server running all services.

**Steps:**
1. Order Hetzner AX102 (AMD Ryzen 9 7950X3D, 128GB DDR5, 2x1.92TB NVMe)
2. Install Ubuntu 24.04 LTS
3. Install Docker and Docker Compose
4. Configure UFW firewall: allow 22 (SSH), 80, 443, 1935 (RTMP), 4455 (OBS WebSocket), 6379 (Redis, localhost only), 5432 (PostgreSQL, localhost only)
5. Set up swap (16GB) as safety net
6. Install and configure nginx as reverse proxy

**Docker Compose services:**
```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["127.0.0.1:6379:6379"]
    volumes: [redis_data:/data]
    restart: always

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: livestream_agi
      POSTGRES_USER: agi
      POSTGRES_PASSWORD: ${PG_PASSWORD}
    ports: ["127.0.0.1:5432:5432"]
    volumes: [pg_data:/var/lib/postgresql/data]
    restart: always

  langfuse:
    image: langfuse/langfuse:latest
    environment:
      DATABASE_URL: postgresql://agi:${PG_PASSWORD}@postgres:5432/langfuse
      NEXTAUTH_SECRET: ${LANGFUSE_SECRET}
      NEXTAUTH_URL: http://localhost:3001
    ports: ["127.0.0.1:3001:3000"]
    depends_on: [postgres]
    restart: always

  sandbox:
    build: ./sandbox
    runtime: runsc  # gVisor for isolation
    mem_limit: 512m
    cpus: 1.0
    pids_limit: 100
    read_only: true
    tmpfs: /tmp:size=100m
    network_mode: none
    restart: "no"  # ephemeral — created per code execution
```

**Acceptance criteria:**
- [ ] All services start with `docker compose up -d`
- [ ] PostgreSQL accepts connections with pgvector extension enabled
- [ ] Redis accepts connections
- [ ] Langfuse web UI accessible at localhost:3001
- [ ] Sandbox container runs Python code and returns output

### Task 1.2: Database schema

**What to build:** All PostgreSQL tables for agents, memory, world state, and transcripts.

**Run this SQL:**
```sql
-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Agent profiles
CREATE TABLE agents (
    id VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    model_conversation VARCHAR(100) NOT NULL,
    model_building VARCHAR(100) NOT NULL,
    voice_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active',  -- active, sleeping, paused
    created_at TIMESTAMP DEFAULT NOW()
);

-- Core memory (Tier 1)
CREATE TABLE core_memory (
    agent_id VARCHAR(50) PRIMARY KEY REFERENCES agents(id),
    content TEXT NOT NULL,
    token_count INT NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW(),
    version INT DEFAULT 1
);

CREATE TABLE core_memory_history (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES agents(id),
    content TEXT NOT NULL,
    version INT NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW(),
    change_reason TEXT
);

-- Full transcripts (Tier 3)
CREATE TABLE transcripts (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    participants TEXT[] NOT NULL,
    content TEXT NOT NULL,
    token_count INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Recall memory (Tier 2)
CREATE TABLE recall_memory (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES agents(id),
    summary TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    event_type VARCHAR(50),
    participants TEXT[],
    transcript_id INT REFERENCES transcripts(id),
    importance_score FLOAT DEFAULT 0.5,
    timestamp TIMESTAMP DEFAULT NOW(),
    recalled_count INT DEFAULT 0
);

CREATE INDEX idx_recall_embedding ON recall_memory
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_recall_agent ON recall_memory (agent_id);

-- World chunks
CREATE TABLE world_chunks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    x_offset INT NOT NULL,
    y_offset INT NOT NULL,
    width INT NOT NULL,
    height INT NOT NULL,
    tile_data JSONB NOT NULL,
    objects JSONB DEFAULT '[]',
    built_by TEXT[],
    built_date TIMESTAMP DEFAULT NOW(),
    description TEXT,
    proposal_votes JSONB,
    tileset_url VARCHAR(500)
);

-- World events (lore)
CREATE TABLE world_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50),
    description TEXT,
    agents_involved TEXT[],
    audience_participation BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Conversation buffer (current active conversations)
CREATE TABLE conversation_buffer (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) REFERENCES agents(id),
    role VARCHAR(20) NOT NULL,  -- 'agent', 'system', 'user'
    speaker VARCHAR(50),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_convbuf_agent ON conversation_buffer (agent_id, created_at);

-- Expansion proposals
CREATE TABLE expansion_proposals (
    id SERIAL PRIMARY KEY,
    proposed_by VARCHAR(50) REFERENCES agents(id),
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'proposed', -- proposed, voting, approved, building, complete, rejected
    votes_for INT DEFAULT 0,
    votes_against INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Challenge queue
CREATE TABLE challenges (
    id SERIAL PRIMARY KEY,
    description TEXT NOT NULL,
    submitted_by VARCHAR(100),
    source VARCHAR(20),  -- 'twitch', 'website', 'seed'
    status VARCHAR(20) DEFAULT 'pending',
    assigned_agents TEXT[],
    result TEXT,
    cost_estimate FLOAT,
    actual_cost FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Revenue tracking
CREATE TABLE revenue_events (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50),  -- 'twitch_sub', 'twitch_bits', 'donation', 'sponsorship'
    amount DECIMAL(10,2),
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Cost tracking
CREATE TABLE cost_events (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50),
    cost_type VARCHAR(50),  -- 'llm_api', 'image_gen', 'tts', 'infrastructure'
    amount DECIMAL(10,4),
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Acceptance criteria:**
- [ ] All tables created with indexes
- [ ] pgvector similarity search works on recall_memory
- [ ] Can insert and query all tables

### Task 1.3: CrewAI agent setup with OpenRouter

**What to build:** CrewAI project with 7 agents + Overseer + Alpha, each configured with their personality, model, and tools. Dual-mode operation: conversation loop and crew task mode.

**Project structure:**
```
livestream-agi/
├── agents/
│   ├── vera/
│   │   ├── config.yaml
│   │   ├── system_prompt.md
│   │   └── behaviors.yaml
│   ├── rex/
│   ├── aurora/
│   ├── pixel/
│   ├── fork/
│   ├── sentinel/
│   ├── grok/
│   ├── overseer/
│   └── alpha/
├── core/
│   ├── orchestrator.py       # main loop, mode switching
│   ├── conversation.py       # conversation mode logic
│   ├── crew_tasks.py         # CrewAI task mode
│   ├── memory.py             # three-tier memory system
│   ├── event_bus.py          # WebSocket event emission
│   ├── overseer.py           # content filter pipeline
│   ├── cost_governor.py      # budget tracking and limits
│   └── tts.py                # Edge TTS pipeline
├── tools/
│   ├── messaging.py          # send_message, get_world_state
│   ├── memory_tools.py       # recall_memory, retrieve_transcript, update_core_memory
│   ├── code_execution.py     # execute_code, generate_tilemap
│   ├── image_generation.py   # generate_pixel_art (PixelLab)
│   ├── web_tools.py          # web_search, fetch_url
│   ├── audience_tools.py     # send_chat, create_poll, get_poll_results
│   ├── alpha_tools.py        # dispatch_alpha
│   ├── revenue_tools.py      # get_revenue_status, draft_social_post, draft_email
│   └── self_modification.py  # propose_self_modification, view_evolution_log
├── frontend/                  # Phaser.js (Phase 2)
├── website/                   # Next.js (Phase 3)
├── docker-compose.yaml
├── requirements.txt
└── README.md
```

**Conversation mode implementation:**
```python
# core/conversation.py
class ConversationEngine:
    """Runs the casual conversation loop — agents take turns talking."""

    async def select_next_speaker(self, conversation_history, agents):
        """Weighted selection: time since spoke, relevance, personality chattiness."""
        weights = {}
        for agent in agents:
            time_weight = seconds_since_last_spoke(agent) / 60  # higher = more likely
            chattiness = agent.config.get("chattiness", 0.5)    # personality trait
            relevance = topic_relevance(agent, conversation_history[-1])
            weights[agent.id] = time_weight * 0.4 + chattiness * 0.3 + relevance * 0.3
        return weighted_random_choice(weights)

    async def generate_turn(self, agent, conversation_history):
        """Generate one agent's contribution to the conversation."""
        # Assemble context
        core_memory = await get_core_memory(agent.id)
        recall = await retrieve_recall_memories(agent.id, conversation_history[-3:])
        audience = await get_audience_status() if agent.id == "pixel" else None

        # Build prompt
        messages = [
            {"role": "system", "content": agent.system_prompt + core_memory + recall},
            *format_conversation_history(conversation_history, limit=20),
        ]

        # Call conversation model (cheap)
        response = await openrouter.chat(
            model=agent.config["model_conversation"],
            messages=messages,
            max_tokens=300,  # keep responses concise for entertainment
        )

        # Content filter
        review = await overseer.review(agent.id, response.content)
        if not review["approved"]:
            return await overseer.generate_replacement(agent.id, review["reason"])

        return response.content

    async def run(self):
        """Main conversation loop."""
        while True:
            speaker = await self.select_next_speaker(self.history, self.agents)
            response = await self.generate_turn(speaker, self.history)

            # Emit events
            await self.event_bus.emit("agent_speak", {
                "agent_id": speaker.id,
                "message": response,
            })

            # TTS
            await self.tts.speak(speaker.id, speaker.voice_id, response)

            # Add to buffer
            self.history.append({"agent_id": speaker.id, "content": response})

            # Compact buffer if needed
            if len(self.history) > 20:
                await compact_oldest_messages(speaker.id, self.history)

            # Variable delay for natural pacing (3-12 seconds)
            await asyncio.sleep(random.uniform(3, 12))
```

**Acceptance criteria:**
- [ ] All 7 agents + Overseer + Alpha configured and loadable
- [ ] Conversation mode runs: agents take turns, personalities are distinct
- [ ] Each agent uses its assigned OpenRouter model
- [ ] Overseer filters every output before it's emitted
- [ ] Memory system stores and retrieves across all 3 tiers
- [ ] Cost tracking logs every API call to cost_events table
- [ ] 24-hour continuous run without crashes or memory leaks

### Task 1.4: Event bus for frontend

**What to build:** A WebSocket server that emits structured events for the Phaser.js frontend.

**Events emitted:**
```python
# Event types and their payloads
EVENTS = {
    "agent_speak": {"agent_id": str, "message": str, "emotion": str},
    "agent_move": {"agent_id": str, "target": str, "x": int, "y": int},
    "agent_action": {"agent_id": str, "action": str, "details": dict},
    "alpha_dispatch": {"from": str, "task": str, "status": str},
    "alpha_return": {"result": str, "status": str},
    "overseer_warning": {"type": str, "message": str, "severity": int},
    "overseer_intervention": {"type": str, "message": str, "agent_id": str},
    "world_expansion": {"chunk_id": int, "name": str, "built_by": list},
    "poll_created": {"poll_id": str, "title": str, "options": list},
    "poll_result": {"poll_id": str, "winner": str, "votes": dict},
    "budget_update": {"daily_spend": float, "daily_limit": float, "per_agent": dict},
    "viewer_count": {"count": int},
    "tts_play": {"agent_id": str, "audio_url": str, "duration": float},
}
```

**Acceptance criteria:**
- [ ] WebSocket server on port 8080
- [ ] All event types fire correctly
- [ ] Frontend client can connect and receive events
- [ ] Events include timestamps
- [ ] Reconnection handling (auto-reconnect on disconnect)

---

## Phase 2: Visual Layer and Streaming (Week 2)

### Task 2.1: Phaser.js pixel art world

**What to build:** A Phaser.js application that renders the pixel art office, agent sprites, and speech bubbles, driven by WebSocket events from the backend.

**Requirements:**
- 1280x720 resolution (720p stream)
- Pixel art tilemap for the office (start with purchased itch.io tileset)
- 7 agent sprites + Alpha wolf sprite (from PixelLab or purchased)
- Speech bubbles that appear above agents when they talk
- Agent name labels
- Status indicators (thinking, talking, building, idle)
- Overlay panel: current topic, budget ticker, AGI progress bar, viewer count
- Agents move between locations (desk, meeting area, whiteboard, coffee machine)

**Agent movement logic:**
- Idle: agent stays at their desk with idle animation
- Speaking: agent faces the agent they're speaking to (or camera if addressing audience)
- Building: agent moves to "workshop" area
- Meeting: all agents move to meeting area
- Alpha dispatched: wolf runs off screen, returns after task

**Acceptance criteria:**
- [ ] Office renders at 720p with consistent pixel art style
- [ ] All 7 agents + Alpha visible with distinct sprites
- [ ] Speech bubbles appear/disappear based on WebSocket events
- [ ] Agents move smoothly between locations
- [ ] Overlay shows real-time budget, viewer count, AGI progress
- [ ] Overseer effects work (lights dim, text overlay)
- [ ] Runs stable in headless Chrome for 24+ hours

### Task 2.2: TTS pipeline

**What to build:** Edge TTS integration that gives each agent a distinct voice.

**Voice assignments:**
| Agent | Voice ID | Character |
|-------|----------|-----------|
| Vera | en-GB-SoniaNeural | Calm British |
| Rex | en-US-GuyNeural | Dry monotone |
| Aurora | en-US-JennyNeural | Warm theatrical |
| Pixel | en-US-DavisNeural | Enthusiastic |
| Fork | en-AU-WilliamNeural | Gruff Australian |
| Sentinel | en-US-AriaNeural | Rapid precise |
| Grok | en-US-ChristopherNeural | Fast confident |
| Overseer | en-US-AndrewNeural + reverb | Deep ominous |

**Pipeline:**
1. Agent output text arrives (post-Overseer filter)
2. Edge TTS generates audio file (mp3)
3. For Overseer: apply reverb/pitch-down via ffmpeg post-processing
4. Audio file served via HTTP to Phaser frontend
5. Frontend plays audio while displaying speech bubble
6. Audio file cleaned up after playback

**Acceptance criteria:**
- [ ] Each agent has a distinct, recognizable voice
- [ ] TTS latency under 3 seconds from text to playback start
- [ ] Overseer voice is distinctly processed (reverb, lower pitch)
- [ ] Alpha has no voice (text expressions only: !, ?, ✓, ✗)
- [ ] Audio files don't accumulate (cleanup after playback)

### Task 2.3: Streaming setup

**What to build:** Headless streaming pipeline from Phaser.js to Twitch/YouTube.

**Architecture:**
```
Xvfb (virtual display :20, 1280x720)
  → Chromium (headless, renders Phaser.js app)
    → OBS Studio (captures browser source, adds audio)
      → Restream.io RTMP (splits to Twitch + YouTube)
```

**Alternative (if OBS is unstable):**
```
Xvfb (virtual display :20, 1280x720)
  → Chromium (renders Phaser.js app)
    → ffmpeg (captures X11 display + audio, encodes to RTMP)
      → Restream.io RTMP (splits to Twitch + YouTube)
```

**PM2 process management:**
```javascript
// ecosystem.config.js
module.exports = {
  apps: [
    { name: "xvfb", script: "Xvfb", args: ":20 -screen 0 1280x720x24" },
    { name: "chrome", script: "chromium", args: "--no-sandbox --window-size=1280,720 --display=:20 http://localhost:3000", env: { DISPLAY: ":20" } },
    { name: "obs", script: "obs", args: "--startstreaming", env: { DISPLAY: ":20" }, cron_restart: "0 */12 * * *" },
    { name: "backend", script: "python", args: "-m uvicorn main:app --host 0.0.0.0 --port 8000" },
    { name: "frontend", script: "npx", args: "serve -s frontend/dist -l 3000" }
  ]
};
```

**Acceptance criteria:**
- [ ] Stream outputs to Restream.io at 720p, 30fps, 4500kbps
- [ ] Audio from TTS plays correctly on stream
- [ ] OBS/ffmpeg auto-restarts every 12 hours (graceful, shows maintenance screen)
- [ ] PM2 auto-restarts any crashed process within 60 seconds
- [ ] Health check endpoint verifies stream is live (hits Twitch API)
- [ ] Stream runs stable for 48+ hours in testing

---

## Phase 3: Audience Interaction (Week 3)

### Task 3.1: TwitchIO bot

**What to build:** Twitch chat bot handling all audience commands.

**Commands to implement:**
- `!ask [agent] [question]` — route question to agent, response on stream
- `!vote [option]` — participate in active poll
- `!who` — list agents and current activities
- `!world` — link to website world map
- `!budget` — Sentinel reports spending
- `!follow [agent]` — vote for camera focus
- `!challenge [description]` — submit a challenge (queued)
- `!alpha [task]` — dispatch Alpha for a quick task

**Acceptance criteria:**
- [ ] Bot connects to Twitch chat and responds to all commands
- [ ] !ask routes to correct agent and response appears on stream within 15 seconds
- [ ] !vote tallies correctly and displays results
- [ ] Rate limiting: max 1 command per user per 30 seconds
- [ ] Bot handles disconnect/reconnect gracefully

### Task 3.2: Next.js website

**What to build:** Companion website on Vercel.

**Pages:**
- `/` — Homepage with stream embed, agent grid, AGI progress bar
- `/agents/[id]` — Agent profile: bio, personality, stats, journal, chat
- `/world` — Interactive world map with agent positions
- `/challenges` — Challenge board: submit, upvote, track
- `/lore` — Agent-written world history
- `/clips` — Best moments archive

**API routes (Next.js → Hetzner backend):**
- `GET /api/agents` — all agent profiles and status
- `GET /api/agents/[id]/journal` — agent's diary entries
- `POST /api/agents/[id]/chat` — one-on-one chat with agent
- `GET /api/world/chunks` — all world chunk data for map
- `GET /api/challenges` — challenge list
- `POST /api/challenges` — submit new challenge
- `GET /api/stats` — AGI progress, costs, revenue, viewer stats
- `GET /api/lore` — world history events

**Acceptance criteria:**
- [ ] Deployed to Vercel, loads in under 3 seconds
- [ ] Stream embed plays correctly
- [ ] Agent profiles display real-time status
- [ ] Agent chat works (send message, get response within 10 seconds)
- [ ] World map renders all built chunks
- [ ] Challenge submission with rate limiting (5 per IP per hour)
- [ ] Mobile responsive

### Task 3.3: Safety and monitoring

**What to build:** CostGovernor, kill switch, monitoring alerts.

**CostGovernor limits:**
```python
LIMITS = {
    "per_agent_hourly": 3.00,    # USD — pause agent if exceeded
    "per_agent_daily": 30.00,
    "global_daily": 150.00,
    "global_monthly": 3000.00,   # hard stop — all agents pause
    "per_image_generation": 0.10,
    "per_code_execution": 0.50,  # estimated based on tokens used
}
```

**Kill switch endpoints:**
```
POST /api/admin/kill?scope=global          — mute all agents
POST /api/admin/kill?scope=agent&id=grok   — mute specific agent
POST /api/admin/resume                     — resume all
POST /api/admin/resume?id=grok             — resume specific
GET  /api/admin/status                     — current system status
```
Protected by API key auth. Accessible from phone via simple HTTP client.

**Monitoring:**
- Uptime Robot: check stream health every 60 seconds (verify Twitch stream is live)
- Langfuse alerts: notify if any agent exceeds hourly cost limit
- Custom health endpoint: `/api/health` returns all service statuses
- PM2 monitoring: auto-restart crashed processes, log crashes

**Acceptance criteria:**
- [ ] CostGovernor pauses agents when limits hit
- [ ] Kill switch mutes agents within 1 second
- [ ] Kill switch accessible from phone via authenticated API call
- [ ] Uptime Robot sends SMS/email if stream goes down
- [ ] All safety systems tested: deliberately trigger each one

---

## Phase 4: World-Building and Content (Week 4)

### Task 4.1: World expansion pipeline

**What to build:** End-to-end pipeline from proposal to world expansion.

**Pipeline steps:**
1. Agent proposes expansion → stored in `expansion_proposals` table
2. Vera creates Twitch poll with proposal options
3. 24-hour voting window
4. Winner announced on stream
5. Vera assigns roles (using CrewAI task mode)
6. Rex writes tilemap generation code → executes in sandbox → outputs chunk JSON
7. Aurora writes creative brief → sent to PixelLab → returns tileset PNG
8. Backend assembles chunk → stores in `world_chunks`
9. Frontend receives `world_expansion` event → loads new chunk
10. Camera pans to new area → agents walk in → react

**Acceptance criteria:**
- [ ] Proposals submitted by agents during reflection cycles
- [ ] Twitch poll creation and result collection works
- [ ] Rex can generate valid chunk JSON via code execution
- [ ] PixelLab returns usable tileset images
- [ ] New chunks load in Phaser without breaking existing world
- [ ] Full pipeline runs end-to-end with entertaining on-stream results

### Task 4.2: Content systems

**What to build:** Agent journals, Daily Brief, auto-clipping, trending news.

**Agent journals:** During reflection cycles, each agent writes a 200-500 word diary entry. Stored in database. Displayed on website agent profile pages.

**Daily Brief:** At 6 PM, Pixel generates a 2-3 minute recap script covering: what was built, any drama, challenge results, audience highlights. Script → TTS → auto-clipped as a standalone video → posted to YouTube/TikTok.

**Trending news:** Daily cron at 8:55 AM runs web search for trending topics. Results injected into morning standup context.

**Acceptance criteria:**
- [ ] Agent journals generate during reflection and display on website
- [ ] Daily Brief generates and Pixel delivers it on stream
- [ ] Trending news retrieved and injected into standup context
- [ ] Auto-clipping creates shareable clips (via Eklipse or Twitch API)

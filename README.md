# Livestream to AGI

A 24/7 livestreamed AI reality show featuring 9 AI agents living in a pixel art world.

The agents build projects, interact with audiences on Twitch and YouTube, manage a real budget, and expand their world through viewer voting — all while satirizing AI hype and genuinely showcasing technical capability.

## The Cast

| Agent | Role | Personality |
|-------|------|-------------|
| **Vera** | Showrunner | Obsessively organized coordinator who checks the budget mid-sentence |
| **Rex** | Engineer | Terse, sarcastic pragmatist — judges everything by "does it ship?" |
| **Aurora** | Creative Director | Dramatic visionary who speaks in metaphors and breaks into haiku |
| **Pixel** | Researcher | Insatiably curious audience liaison who finds everything fascinating |
| **Fork** | Contrarian | Open-source evangelist who proposes forking everything |
| **Sentinel** | Accountant | Paranoid budget monitor who announces unsolicited cost updates |
| **Grok** | Wild Card | 40% brilliant insights, 40% terrible takes, 20% content warnings |
| **Management** | Content Filter | Corporate middle-management that enforces content rules via memos and policy updates |
| **Alpha** | Wolf Assistant | Eager-to-please errand runner who occasionally brings back the wrong thing |

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Twitch / YouTube (via Restream.io)             │
└────────────────────┬────────────────────────────┘
                     │ OBS / ffmpeg
┌────────────────────┴────────────────────────────┐
│  Phaser.js Frontend (headless Chrome on Xvfb)   │
│  - Pixel art world, agent sprites, speech bubbles│
└────────────────────┬────────────────────────────┘
                     │ WebSocket
┌────────────────────┴────────────────────────────┐
│  FastAPI Backend (Python)                        │
│  - CrewAI (9 agents, personality-first)          │
│  - 3-tier memory (core → recall → archival)      │
│  - Conversation engine (weighted speaker select) │
│  - Management content filter                     │
│  - Cost governor + kill switch                   │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────┐
│  Support Services (Docker Compose)               │
│  - PostgreSQL 16 + pgvector                      │
│  - Redis 7                                       │
│  - Langfuse (observability)                      │
│  - Docker + gVisor (code sandbox)                │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  Next.js Website (Vercel)                        │
│  - Live stream embed, agent profiles, world map  │
└─────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology | Language |
|-------|-----------|----------|
| Agent orchestration | CrewAI + OpenRouter/local OpenAI-compatible LLMs | Python |
| Backend API | FastAPI | Python |
| Memory system | PostgreSQL + pgvector | Python |
| TTS | Edge TTS | Python |
| World renderer | Phaser.js 3 | TypeScript |
| Website | Next.js | TypeScript |
| Streaming | OBS + Xvfb + Restream | System |
| Infrastructure | Docker Compose on Hetzner | YAML |

## Project Structure

```
livestream-agi/
├── agents/                    # Agent personality configs
│   ├── vera/                  # config.yaml, system_prompt.md, behaviors.yaml
│   ├── rex/
│   ├── aurora/
│   ├── pixel/
│   ├── fork/
│   ├── sentinel/
│   ├── grok/
│   ├── management/
│   └── alpha/
├── core/                      # Python backend
│   ├── orchestrator.py        # Main loop, mode switching
│   ├── conversation.py        # Turn-taking, speaker selection
│   ├── crew_tasks.py          # CrewAI task mode
│   ├── memory.py              # 3-tier memory management
│   ├── event_bus.py           # WebSocket event emission
│   ├── management.py          # Content filter pipeline
│   ├── cost_governor.py       # Budget tracking and limits
│   └── tts.py                 # Edge TTS pipeline
├── tools/                     # Python agent tools
│   ├── messaging.py           # send_message, get_world_state
│   ├── memory_tools.py        # recall_memory, update_core_memory
│   ├── code_execution.py      # Sandboxed code execution
│   ├── image_generation.py    # PixelLab integration
│   ├── web_tools.py           # web_search, fetch_url
│   ├── audience_tools.py      # Chat, polls
│   ├── alpha_tools.py         # dispatch_alpha
│   ├── revenue_tools.py       # Revenue tracking, social drafts
│   └── self_modification.py   # Agent self-evolution
├── frontend/                  # TypeScript — Phaser.js
│   ├── src/
│   │   ├── scenes/            # Game scenes
│   │   ├── sprites/           # Sprite classes
│   │   └── ui/                # HUD, overlays, speech bubbles
│   └── public/assets/         # Tilesets, sprites, audio
├── website/                   # TypeScript — Next.js
├── tests/
│   ├── backend/               # pytest (Python)
│   ├── frontend/              # vitest (TypeScript)
│   ├── website/               # vitest + Playwright
│   └── integration/           # Full-stack Docker tests
├── specs/                     # Design specifications (reference)
├── scripts/                   # Setup, deploy, utilities
├── docker/                    # Dockerfiles
├── docker-compose.yaml        # Redis, PostgreSQL, Langfuse
├── requirements.txt           # Python dependencies
├── pyproject.toml             # Python project config (ruff, pytest)
├── CLAUDE.md                  # Claude Code instructions
├── AGENTS.md                  # Agent definitions
└── README.md                  # This file
```

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 20+
- Docker & Docker Compose

### Setup

```bash
# 1. Clone and enter
git clone https://github.com/yourusername/livestreamtoagi.git
cd livestreamtoagi

# 2. Start infrastructure
docker compose up -d

# 3. Backend setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in API keys

# 4. Frontend setup
cd frontend && npm install && cd ..

# 5. Website setup
cd website && npm install && cd ..

# 6. Run backend
uvicorn core.main:app --reload --port 8010

# 7. Run frontend (separate terminal)
cd frontend && npm run dev

# 8. Run website (separate terminal)
cd website && npm run dev
```

## Testing

```bash
# Python backend
pytest tests/backend/ -v

# Frontend (Phaser.js)
cd frontend && npm test

# Website (Next.js)
cd website && npm test
cd website && npm run test:e2e  # Playwright E2E

# Integration (requires Docker)
docker compose -f docker-compose.test.yml up --abort-on-container-exit
```

## Local LLM Simulation

This project can run simulations against LM Studio or another OpenAI-compatible
local server so core behavior can be validated without cloud token spend.

```bash
# Check LM Studio / local server
pnpm llm:local --list-only

# Run a focused validation scenario
LLM_PROVIDER=lmstudio \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
EMBEDDING_PROVIDER=deterministic \
python scripts/run_simulation.py \
  --name "local-llm-validation" \
  --seed-file scenarios/local_llm_validation.yaml \
  --agents vera,rex,aurora,pixel \
  --max-cost 0.01 \
  --verbose

python scripts/verify_simulation.py --name "local-llm-validation" --profile local-smoke
```

See [Local LLM Validation Plan](specs/LOCAL-LLM-VALIDATION-PLAN.md) for the full
research verification matrix.

## Monthly Cost Estimate

| Component | Cost |
|-----------|------|
| Hetzner AX102 server | $120 |
| OpenRouter API (all models) | $500-900 |
| PixelLab (pixel art generation) | $30-50 |
| Edge TTS / Langfuse / Vercel / Restream | $0 (free tiers) |
| **Total** | **$655-1,075/month** |

Break-even: ~260-430 Twitch subs or equivalent donations.

## Detailed Specs

See `specs/` for complete design documentation:
- [Engineering Specs](specs/ENGINEERING-SPECS.md) — Implementation phases
- [Implementation Plan](specs/FINAL-IMPLEMENTATION-PLAN.md) — Architecture & strategy
- [Character Sheets](specs/CHARACTER-SHEETS.md) — Agent personalities
- [Conversation Engine](specs/CONVERSATION-ENGINE.md) — Speaker selection
- [Memory System](specs/MEMORY-SYSTEM.md) — Three-tier architecture
- [Tool Definitions](specs/TOOL-DEFINITIONS.md) — Agent capabilities
- [Human Checklist](specs/HUMAN-CHECKLIST.md) — Operator responsibilities

## License

TBD

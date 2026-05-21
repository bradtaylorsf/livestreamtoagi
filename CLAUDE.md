# CLAUDE.md — Livestream to AGI

## Project Overview

A 24/7 livestreamed AI reality show featuring 9 AI agents living in a pixel art world, building projects, interacting with audiences, and managing a real budget. Built as a monorepo with Python backend and TypeScript frontend/website.

## Architecture

```
Python Backend (FastAPI + CrewAI)
  ↕ WebSocket
TypeScript Frontend (Phaser.js — pixel art world renderer)
  ↕ OBS/ffmpeg → Twitch + YouTube

TypeScript Website (Next.js on Vercel)
  ← FastAPI REST API
```

## Tech Stack

### Backend (Python 3.12+)
- **Framework:** FastAPI (async web server + WebSocket)
- **Agent Framework:** CrewAI (personality-first agent orchestration)
- **LLM Routing:** OpenRouter (multi-model: Claude, Gemini, GPT, DeepSeek, Grok)
- **Database:** PostgreSQL 16 + pgvector (memory, world state, transcripts)
- **Cache/State:** Redis 7 (shared state, kill switches)
- **TTS:** Edge TTS (free, 300+ voices)
- **Observability:** Langfuse (self-hosted, LLM cost/token tracking)
- **Code Sandbox:** Docker + gVisor (isolated execution)
- **Testing:** pytest + pytest-asyncio + pytest-cov

### Frontend (TypeScript)
- **Engine:** Phaser.js 3 (pixel art world, sprite rendering, tilemaps)
- **Build:** Vite
- **Testing:** Vitest

### Website (TypeScript)
- **Framework:** Next.js (on Vercel)
- **Testing:** Vitest + Playwright (E2E)

## Monorepo Layout

```
/                          # Root — shared configs, Docker, CI
├── agents/                # Agent configs (YAML personality files)
├── core/                  # Python — orchestrator, memory, conversation engine
├── tools/                 # Python — agent tool implementations
├── frontend/              # TypeScript — Phaser.js world renderer
├── website/               # TypeScript — Next.js public website
├── tests/                 # All tests organized by layer
├── specs/                 # Design specs (read-only reference)
├── scripts/               # Deployment, setup, utility scripts
└── docker/                # Dockerfiles for services
```

## Development Commands

### Backend (Python)
```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run
uvicorn core.main:app --reload --port 8010

# Test (after activating .venv). For automated runners that don't
# activate the venv, use `make test-backend` — it pins `.venv/bin/pytest`
# so it works under `/bin/sh` without `.venv/bin` on PATH.
pytest tests/backend/ -v
pytest tests/backend/ --cov=core --cov=tools
make test-backend          # PATH-safe equivalent

# Lint
ruff check core/ tools/
ruff format core/ tools/

# Video render (optional) — installs Playwright + Chromium for the
# simulation → MP4 pipeline. Skip unless you're working on core/video/.
# The Makefile targets pin `.venv/bin/python` and `.venv/bin/playwright`
# so a stale `python` shim earlier on PATH cannot intercept the call.
make render-install                # `uv pip install -e ".[render]" && playwright install chromium`
make render-smoke                  # imports playwright + runs `--help` against the entrypoint
make render-verify                 # auto-pick a real sim, render, ffprobe-confirm streams
make render-verify SIM=<sim-uuid>  # render a specific sim end-to-end
```

### Frontend (Phaser.js)
```bash
cd frontend
npm install
npm run dev          # Vite dev server
npm run build        # Production build
npm test             # Vitest
```

### Website (Next.js)
```bash
cd website
npm install
npm run dev          # Next.js dev server
npm run build        # Production build
npm test             # Vitest
npm run test:e2e     # Playwright
```

### Infrastructure
```bash
docker compose up -d                    # Start Redis, PostgreSQL, Langfuse
docker compose -f docker-compose.test.yml up  # Test environment
```

## Code Conventions

### Python
- Python 3.12+, use type hints everywhere
- Async/await for all I/O operations
- Use `ruff` for linting and formatting
- Import style: stdlib → third-party → local (enforced by ruff)
- Snake_case for functions/variables, PascalCase for classes
- Pydantic models for all API request/response schemas

### TypeScript
- Strict mode enabled
- ESM modules
- Use `const` by default, `let` only when mutation is needed
- Prefer named exports

### Git
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Branch naming: `feat/description`, `fix/description`
- Keep PRs focused — one feature or fix per PR

## Agent System

Nine agents with distinct personalities and model assignments (see `agents/` and `specs/CHARACTER-SHEETS.md`):

| Agent | Role | Conversation Model | Building Model |
|-------|------|-------------------|----------------|
| Vera | Showrunner/Coordinator | Claude Haiku 4.5 | Claude Sonnet 4.6 |
| Rex | Engineer/Builder | Claude Haiku 4.5 | Claude Sonnet 4.6 |
| Aurora | Creative Director | Gemini Flash | Gemini 2.5 Pro |
| Pixel | Researcher/Audience Liaison | GPT-4o Mini | GPT-5.2 |
| Fork | Contrarian/Code Reviewer | DeepSeek V3.2 | DeepSeek V3.2 |
| Sentinel | Budget Monitor/QA | Claude Haiku 4.5 | Claude Haiku 4.5 |
| Grok | Wild Card/Provocateur | Grok 3 Mini | Grok 3 |
| Management | Content Filter | Claude Haiku 4.5 | — |
| Alpha | Errand Runner (wolf) | DeepSeek V3.2 | — |

## Key Design Decisions

- **Memory is 3-tier:** Core (always in prompt, ~2-3K tokens), Recall (pgvector semantic search), Archival (full transcripts, never deleted)
- **Conversation engine** uses weighted speaker selection: time_since_spoke (0.30), topic_relevance (0.30), chattiness (0.15), adjacency_fit (0.15), random_jitter (0.10)
- **Every agent output** passes through Management content filter before TTS (3-second delay for intervention)
- **Cost governor** tracks every API call; kill switch API accessible from Brad's phone
- **All external comms** (social posts, emails) require human approval for first 3 months

## Environment Variables

Required in `.env` (never commit):
```
OPENROUTER_API_KEY=
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
TWITCH_BOT_TOKEN=
TWITCH_STREAM_KEY=
TWITCH_RTMP_URL=
YOUTUBE_API_KEY=
YOUTUBE_STREAM_KEY=
YOUTUBE_RTMP_URL=
RTMP_SMOKE_URL=
PIXELLAB_API_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
DATABASE_URL=postgresql://...
REDIS_URL=redis://localhost:6379
KILL_SWITCH_API_KEY=
```

## Specs Reference

All design specifications are in `specs/` — treat as read-only reference:
- `ENGINEERING-SPECS.md` — Phased implementation plan with technical details
- `FINAL-IMPLEMENTATION-PLAN.md` — Strategic vision and architecture decisions
- `CHARACTER-SHEETS.md` — Full personality specs for all 9 agents
- `CONVERSATION-ENGINE.md` — Speaker selection algorithm and dynamics
- `MEMORY-SYSTEM.md` — Three-tier memory architecture
- `TOOL-DEFINITIONS.md` — Complete tool inventory with parameters
- `HUMAN-CHECKLIST.md` — Brad's responsibilities and review cadence

## Research Reference

Research papers and analysis documents are in `research/`:
- **`PAPER-INDEX.md`** — **Index of all 17 academic papers** with summaries, relevance mapping to each project system (memory, conversation engine, personality, evaluation, etc.), and a quick-lookup table by subsystem. **Consult this when working on any system to find relevant prior art.**
- `RESEARCH-ANALYSIS-2026.md` — Literature review: how our implementation maps to 6 foundational papers, 7 challengeable design assumptions, 14 newer papers integrated, and prioritized recommendations
- `RESEARCH-PROGRAM-AND-CONTENT-STRATEGY.md` — Snapshot-and-branch methodology, 5-season research roadmap, blog series plan, researcher positioning strategy
- `FUNDING-AND-CREDIBILITY-STRATEGY.md` — Funding pathways (community, fellowships, grants, government), skeptical funder Q&A, credibility checklist, revenue model

## Development Workflow

### Python version

Python 3.13 is required (pinned in `.python-version`). Python 3.14+ is **not supported** — native dependencies (pydantic-core, etc.) cannot build against it yet.

```bash
# Setup venv (uses .python-version automatically)
uv venv .venv --python 3.13
uv pip install -e ".[dev]"
```

### Pre-verification: Always check services first

Before verifying any issue or running integration tests, ensure Docker services are healthy:

```bash
docker compose up -d
bash scripts/check-services.sh
```

All 5 checks must pass (Redis, PostgreSQL, pgvector, pg_trgm, Langfuse) before proceeding.

### Default Ports (configurable via env vars)

| Service    | Host Port | Env Var         |
|------------|-----------|-----------------|
| Redis      | 6381      | `REDIS_PORT`    |
| PostgreSQL | 5434      | `POSTGRES_PORT` |
| Langfuse   | 3100      | `LANGFUSE_PORT` |

<!-- managed by alpha-loop -->

# Livestream to AGI — Agent Instructions

## Overview

A 24/7 livestreamed AI reality show: nine AI agents with distinct personalities live in a pixel-art world, build real projects, manage a real budget, and interact with audiences on Twitch and YouTube. The system is a Python backend (FastAPI + CrewAI) driving a Phaser.js world renderer, with a Next.js public website. Agents have three-tier memory (core/recall/archival), pass through a Management content filter before TTS, and are constrained by a cost governor with a kill switch.

See `specs/` for design references and `research/PAPER-INDEX.md` for prior art when working on any subsystem.

## Tech Stack

**Backend (Python 3.13, pinned in `.python-version`)**
- FastAPI (async web + WebSocket), CrewAI (agent orchestration)
- OpenRouter (multi-model: Claude, Gemini, GPT, DeepSeek, Grok) — all LLM calls route through `core/llm_client.py`
- PostgreSQL 16 + pgvector (memory, world state, transcripts), Redis 7 (shared state, kill switches)
- Edge TTS (free, 300+ voices), Langfuse (self-hosted observability)
- Docker + gVisor (sandboxed code execution)
- Tooling: `uv` for env/deps, `ruff` for lint/format, `pytest` + `pytest-asyncio` for tests
- Optional video render pipeline: Playwright + Chromium + ffmpeg (see `core/video/`, `make render-*` targets)

**Frontend (`frontend/`)** — Phaser.js 3 pixel-art renderer, Vite, Vitest

**Website (`website/`)** — Next.js on Vercel, Vitest + Playwright E2E

**Minecraft embodiment** — `minecraft-server/`, `minecraft-server-easy/`, `mindcraft/` host the agents' embodied bridge (Node-based Mineflayer integration); backend glue lives in `core/embodiment/` and `core/minecraft/`. Timestamped `minecraft-server-easy-*` directories are ephemeral shakeout/soak artifacts — don't edit them.

**Python 3.14+ is NOT supported** — native deps (pydantic-core, etc.) don't build against it.

## Directory Structure

```
agents/           Per-agent YAML personality configs (vera, rex, aurora, pixel, fork, sentinel, grok, management, alpha, template)
core/             Python backend — orchestrator (main.py), llm_client, cost_governor, kill_switch, management, conversation_engine, conversation_mode, conversation/, memory/, bridge/, embodiment/, minecraft/, video/, simulation/, world/, characters/, social/, youtube/, livestream/, streaming/, eval/, admin/, auth/, reporting/, notifications/, scheduler, tts, events/, repos/, agent_economy/state/goals/registry, context_assembly, system_prompt, tool_executor, run_spec, shared_state, database, redis_client/keys
tools/            Agent tool implementations (alpha_dispatch, audience, audience_tools, base, character_tools, code_execution, economy_tools, memory_tools, messaging, social_tools, web_tools, world_state, tilemap_gen, revenue_tools, self_modification, journal_image_tool, task_management, stubs)
frontend/         Phaser.js world renderer (TS)
website/          Next.js public-facing site (TS)
mindcraft/        Minecraft embodiment bridge
minecraft-server/        Full Minecraft world server
minecraft-server-easy/   Simplified baseline Minecraft world
tests/            tests/backend/ (pytest) and tests/integration/
specs/            Read-only design specs (engineering, character sheets, conversation engine, memory, tools, human checklist)
research/         Academic literature index + analysis; consult PAPER-INDEX.md when touching any subsystem
scripts/          Setup, deployment, service checks (e.g. check-services.sh)
docker/           Service Dockerfiles
db/               Schemas / migrations
docs/             Project documentation
evals/, scenarios/, snapshots/   Eval harness inputs/outputs
config/           Runtime configuration
sandbox/          gVisor sandbox runtime
logs/, videos/    Generated artifacts (gitignored)
.alpha-loop/      Alpha-loop session state, vision, templates (managed)
```

Backend entrypoint: `uvicorn core.main:app --reload --port 8010`.

## Code Style

**Python**
- Python 3.13, type hints everywhere
- `async`/`await` for all I/O
- `ruff check` + `ruff format` (config in `ruff.toml`); imports ordered stdlib → third-party → local
- `snake_case` functions/variables, `PascalCase` classes
- Pydantic models for all API request/response schemas
- Default to no comments; only write one when the WHY is non-obvious

**TypeScript**
- Strict mode, ESM modules
- `const` by default; `let` only when mutation is needed
- Prefer named exports

## Non-Negotiables

- **Never commit `.env` or secrets.** Required env vars: `OPENROUTER_API_KEY`, `TWITCH_*`, `YOUTUBE_API_KEY`, `PIXELLAB_API_KEY`, `LANGFUSE_*`, `DATABASE_URL`, `REDIS_URL`, `KILL_SWITCH_API_KEY`.
- **Default ports are non-standard** to avoid local conflicts: Redis 6381 (`REDIS_PORT`), PostgreSQL 5434 (`POSTGRES_PORT`), Langfuse 3100 (`LANGFUSE_PORT`). Don't hardcode the standard ports.
- **Check services before integration work:** `docker compose up -d && bash scripts/check-services.sh` — all 5 checks (Redis, PostgreSQL, pgvector, pg_trgm, Langfuse) must pass.
- **Every agent utterance** flows through `core/management.py` content filter before TTS — never bypass it. There is a 3-second intervention window by design.
- **Cost governor + kill switch are load-bearing.** All LLM calls go through `core/llm_client.py` (OpenRouter routing) so Langfuse, `core/cost_governor.py`, and `core/kill_switch.py` see them. Don't call provider SDKs directly.
- **Memory is 3-tier**, not a single store: Core (always in prompt, ~2–3K tokens), Recall (pgvector semantic search), Archival (full transcripts, never deleted). Respect tier boundaries when adding memory features.
- **Conversation engine** uses weighted speaker selection — see `core/conversation_engine.py` and `specs/CONVERSATION-ENGINE.md`. Don't change weights without updating both.
- **All external comms** (social posts, emails, public PRs from agents) require human approval for the first 3 months — keep the approval gate in place.
- **`specs/` is read-only reference.** Don't edit specs to match code; update code or open a separate discussion.
- **Makefile targets pin `.venv/bin/...`** so they work under `/bin/sh` without venv activation (e.g. `make test-backend`, `make render-verify`). Use them in automation rather than bare `pytest` / `playwright`.
- **Agent model assignments** (conversation vs. building model per agent) are defined in `agents/<name>/` configs and `specs/CHARACTER-SHEETS.md`. Don't reassign models ad-hoc — personality is tied to model choice.

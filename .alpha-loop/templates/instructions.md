<!-- managed by alpha-loop -->
# AGENTS.md — Livestream to AGI

## Overview

This repo is a monorepo for a 24/7 AI reality show set in a pixel-art world. The project canon centers on 9 agents: Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok, the Overseer, and Alpha.

The live codebase includes:
- a FastAPI backend with a health route, WebSocket event bus, and lifespan hooks that initialize database, Redis, agent registry, memory managers, LLM client, and a reflection scheduler
- async PostgreSQL and Redis clients with a typed repository layer
- a multi-tier memory system: core memory (persistent identity), recall memory (pgvector semantic search), archival memory (long-term storage), and reflection (LLM-driven 6-hour + weekly cycles with journaling and self-modification proposals)
- a context assembly pipeline that builds three-layer prompts: infrastructure rules → character identity → mutable memory state
- raw SQL migrations (4 files) and typed repository classes
- YAML-backed agent config loading from `agents/*`, including `config.yaml`, `behaviors.yaml`, `system_prompt.md`, and optional extra YAML files (e.g., overseer's `content_rules.yaml` and `intervention_levels.yaml`)
- an OpenRouter LLM client with a 9-model registry, cost tracking, retry logic, and optional Langfuse hooks
- a small Vite TypeScript frontend package with agent constants/tests
- a Next.js website with static route pages, shared TS types, and an API client that targets future backend routes not yet implemented

Special agent rules are real and should be preserved:
- `overseer` is an intervention-only safety agent with `chattiness: 0.0` and `initiative: 0.0`
- `alpha` is a non-verbal helper wolf with no voice and zero speaker-selection weights

Treat `specs/CHARACTER-SHEETS.md` and the YAML files in `agents/` as the source for agent identity and personality details.

## Tech Stack

- Python: local development is pinned to Python `3.13` via `.python-version`; project metadata allows `>=3.12,<3.14`
- Backend: FastAPI, asyncpg, redis.asyncio, httpx, pydantic v2, pydantic-settings
- LLM integration: OpenRouter client in `core/llm_client.py` with a fixed 9-model `MODEL_REGISTRY`; Langfuse hooks are present; CrewAI is installed but not wired into the running app
- Memory: `core/memory/` — CoreMemoryManager, RecallMemoryManager, ArchivalMemoryManager, ReflectionManager, MemoryCompactor; embeddings via pgvector; token counting via tiktoken
- Scheduling: APScheduler runs reflection cycles (6-hour at 2/8/14/20 UTC, weekly Sunday 20 UTC) via `core/scheduler.py`
- Data layer: PostgreSQL 16 with `pgvector` and `pg_trgm`, plus 4 raw SQL migrations under `db/migrations`
- Realtime: WebSocket event bus in `core/event_bus.py` (17 event types, 50-message history buffer, max 100 connections)
- Support services: Redis 7 and Langfuse via `docker-compose.yaml`
- Frontend package: Vite 6 + TypeScript 5 + Phaser 3.87 in `frontend/`
- Website: Next.js 16 + React 19 + Tailwind CSS 4 in `website/`
- Local ports that appear in code/config:
  - backend: `8010`
  - website: `4000` in the root dev script, `3000` when running plain `next dev`
  - frontend Vite: `5173`
  - Redis: `6381`
  - PostgreSQL: `5434`
  - Langfuse: `3100`

## Directory Structure

```text
agents/                 YAML agent configs, behaviors, system prompts, and optional extra YAML (9 agent directories)
core/                   FastAPI app, database/redis clients, event bus, LLM client, context assembly, scheduler, models
core/memory/            Memory subsystem: core, recall, archival, reflection, compaction, embeddings, token counting, validation
core/repos/             Typed repository layer for agents, conversations, memory, costs, transcripts, and world data
db/                     Raw SQL migration runner, init SQL, and numbered up/down migrations (001–004)
frontend/               Small TypeScript package; currently agent constants/tests, not a full Phaser world app
website/                Next.js app router site, navigation/components, shared TS types, and static pages
scripts/                Utility scripts: chat.py (interactive agent chat), test_agent.py (agent harness + reflection runner), check-services.sh
specs/                  Product and architecture reference docs; useful context, not the runtime source of truth
tools/                  Placeholder Python package only (`__init__.py`); do not assume tool modules exist yet
tests/backend/          ~20 test files covering agent registry, memory tiers, event bus, context assembly, repos, migrations, LLM client, reflection
```

Important files:
- `core/main.py` defines the FastAPI surface (`/api/health` and `/ws`) and the lifespan that wires up all subsystems
- `core/agent_registry.py` loads agent configs from disk, validates model names via aliases, and syncs status through Redis
- `core/llm_client.py` defines 9 allowed models with aliases and per-token cost metadata
- `core/models.py` is the source of backend Pydantic schemas (agents, memory tiers, conversations, transcripts, journal entries, self-modification proposals, LLM responses, cost events)
- `core/context_assembly.py` builds three-layer prompts: infrastructure → character → memory
- `core/memory/reflection.py` drives 6-hour and weekly reflection cycles with journaling and self-modification proposals
- `db/migrate.py` is the raw SQL migration entry point for `python -m db`; migrations go up to `004_reflection_tables`
- `website/src/lib/api.ts` calls planned REST endpoints (`/api/agents`, `/api/agents/{id}/journal`, `/api/agents/{id}/chat`, `/api/world/chunks`, `/api/challenges`, `/api/stats`, `/api/lore`) that the backend does not currently expose

## Code Style

- Python code is typed and async-first for I/O paths; follow the existing `Database`, `RedisClient`, repository, and memory manager patterns instead of adding ad hoc SQL or connection logic
- Keep backend schemas in Pydantic models in `core/models.py`; repository classes should return typed models, not loose dicts
- Memory operations go through the managers in `core/memory/`; do not bypass them with direct repo calls from outside the memory subsystem
- Use raw SQL migrations in `db/migrations` for schema changes; keep migration filenames numbered and paired with `.up.sql` and `.down.sql`
- Ruff is configured with `target-version = "py312"` and `line-length = 100`; keep imports grouped as stdlib, third-party, local
- TypeScript is strict in both `frontend/` and `website/`; keep types explicit and avoid weakening configs with `any`
- `website/` uses the Next.js app router and the `@/*` path alias; `frontend/` does not have that alias
- Keep shared agent identity and model fields consistent across YAML configs, DB seeds, and TypeScript constants when you intentionally change them
- When editing agent configs, remember `AgentRegistry` reads disk files directly and merges `config.yaml` with optional `behaviors.yaml`, `system_prompt.md`, and any additional YAML files in the agent directory

## Non-Negotiables

- Keep `<!-- managed by alpha-loop -->` as the first line of this file
- Preserve the 9-agent roster and stable IDs unless the user explicitly changes canon across configs, migrations, and UI
- Do not describe planned systems as implemented. The only live FastAPI routes are `/api/health` and `/ws`; endpoints called from `website/src/lib/api.ts` are not yet served by the backend
- The memory system, reflection scheduler, context assembly, and LLM client are initialized at startup but there is no implemented conversation loop or CrewAI task runner driving agent dialogue yet
- The `tools/` package is a placeholder; do not assume tool modules exist
- Preserve the special handling of `overseer` and `alpha`; they are not standard conversational agents
- When touching model names, keep them in sync with `core/llm_client.py` MODEL_REGISTRY, the YAML configs under `agents/`, and the seed data in `db/migrations/002_seed_agents.up.sql`
- When touching ports or env defaults, keep root `.env.example`, `website/.env.example`, `package.json`, `docker-compose.yaml`, and `website/next.config.ts` aligned around backend port `8010`
- Treat `specs/` and `README.md` as reference material. If they disagree with live code, prefer the live code and update docs rather than coding to outdated prose

<!-- managed by alpha-loop -->
# AGENTS.md — Livestream to AGI

## Overview

This repo is a monorepo for a 24/7 AI reality show set in a pixel-art world. The project canon centers on 9 agents: Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok, Management, and Alpha.

The live codebase includes:
- a FastAPI backend with a health route, WebSocket event bus, admin API (66 endpoints across 9 route modules in `core/admin/`), a public API in `core/public_routes.py` serving the website (`/scenarios`, `/agents`, `/conversations`, `/blog`, `/evals`, etc.), user-auth and kill-switch routers, and lifespan hooks that initialize database, Redis, agent registry, memory managers, LLM client, TTS pipeline, config watcher, and a reflection scheduler
- async PostgreSQL and Redis clients with a typed repository layer (19 repo classes including artifact, simulation, eval, assertion, relationship, goal, config_version, evolution, prompt_log, agent_state, alliance, challenge, and user repos)
- a multi-tier memory system: core memory, recall memory (pgvector semantic search), archival memory, dreams, memory seed, and reflection (LLM-driven 6-hour + weekly cycles with journaling and self-modification proposals)
- a conversation engine orchestrator with speaker selection, energy model, interrupts, topic detection, pacing, proximity groups, Management safety review, and TTS output
- a context assembly pipeline that builds three-layer prompts: infrastructure rules → character identity → mutable memory state
- a tool registry with ~17 functional tool modules exporting ~31 tool classes (plus 2 simulation stubs and a `JournalImageGenerator` utility): messaging, audience interaction, memory ops, code execution (Docker sandbox), tilemap generation, revenue/social drafts, web search, Alpha dispatch, self-modification, task management, world state, evolution log, alliances, economy/budget, and character proposals
- raw SQL migrations (47 pairs, up to `047_simulation_youtube_publish`) and typed repository classes
- YAML-backed agent config loading from `agents/*` (`config.yaml`, `behaviors.yaml`, `system_prompt.md`, plus optional extras like management's `content_rules.yaml` and `intervention_levels.yaml`)
- an OpenRouter LLM client with a model registry, cost tracking, retry logic, and optional Langfuse hooks
- a modular admin dashboard backend (`core/admin/`) with 9 route files: agent inspection, conversation viewer, artifact browser, simulation timeline, eval dashboard, transcript viewer, config management, diagnostics, kill switch, auth — protected by `ADMIN_PASSWORD` Bearer auth
- a simulation orchestrator (`core/simulation/`) with clock, phases, assertions, audience simulation, world simulation, snapshot, recurring personas, display, and CLI entry point (`scripts/run_simulation.py`)
- an eval engine (`core/eval/`) with eval loader, prompt loader, engine, analyzer, evolution loop, change applier, and GitHub issue generator for eval findings
- a character subsystem (`core/characters/`) with spawner, voting, and departure handling for dynamic agent creation
- a social subsystem (`core/social/`) with relationship tracking and alliance management between agents
- an events subsystem (`core/events/`) with event generator and event templates
- a reporting subsystem (`core/reporting/`) with timeline reports, scorecards, cost projections, comparisons, and sectioned report generation under `core/reporting/sections/` (executive summary, cost analysis, daily breakdown, key moments, memory evolution, relationship evolution, tool usage)
- an auth subsystem (`core/auth/`) with auth routes, dependencies, and email helpers (bcrypt + PyJWT)
- a notifications subsystem (`core/notifications/`) for simulation-complete email templates
- a video pipeline (`core/video/`) and YouTube publisher (`core/youtube/`) for rendering and uploading simulation recaps
- a Phaser.js frontend (`frontend/`) with main scene, chunk-based world loading, agent sprite rendering, WebSocket client, and typed event handling
- a Next.js website with public route pages (about, agents, artifacts, blog, challenges, clips, contribute, conversations, donate, ethics, evals, lore, safety, simulations, world), shared TS types, and an API client backed by `core/public_routes.py`

Special agent rules are real and should be preserved:
- `management` is an intervention-only safety agent with `chattiness: 0.0` and `initiative: 0.0`
- `alpha` is a non-verbal helper wolf with no voice and zero speaker-selection weights

Treat `specs/CHARACTER-SHEETS.md` and the YAML files in `agents/` as the source for agent identity and personality details.

## Tech Stack

- Python: local dev pinned to `3.13` via `.python-version`; project metadata allows `>=3.12,<3.14`
- Backend: FastAPI, asyncpg, redis.asyncio, httpx, pydantic v2, pydantic-settings; bcrypt + PyJWT for user auth
- LLM integration: OpenRouter client in `core/llm_client.py` with a fixed `MODEL_REGISTRY`; Langfuse hooks present; CrewAI installed but not wired into the running app
- Memory: `core/memory/` — CoreMemoryManager, RecallMemoryManager, ArchivalMemoryManager, ReflectionManager, ReflectionScheduler, MemoryCompactor, MemorySnapshot, dreams, memory_seed; embeddings via pgvector; token counting via tiktoken
- Conversation: `core/conversation_engine.py` orchestrates speaker selection, energy, interrupts, Management review, TTS, and event emission; subsystems in `core/conversation/` (energy, pacing, proximity, speaker_selector, topic_detector, triggers, selection_logger)
- TTS: Edge TTS pipeline in `core/tts.py` with per-agent voice support; `core/speech_parser.py` for structured dialogue/action parsing
- Management: `core/management.py` reviews all agent output before broadcast (content filter with intervention levels)
- Scheduling: APScheduler runs reflection cycles via `core/scheduler.py`
- Tools: `tools/` package with ~17 functional modules, ~31 tool classes, 2 simulation stubs, and a `ToolRegistry`; includes code execution via Docker sandbox (`sandbox/Dockerfile`) with gVisor; `tools/journal_image_tool.py` is a separate generator utility
- Characters: `core/characters/` — CharacterSpawner, VotingManager, departure handling
- Social: `core/social/` — RelationshipTracker, AllianceManager
- Events: `core/events/` — EventGenerator, EventTemplates
- Video/YouTube: `core/video/` (audio_timeline, render_pipeline, storage, worker, config) and `core/youtube/` (client, worker, config); driven by `scripts/render_simulation_video.py` and `scripts/publish_simulation_youtube.py`
- Notifications: `core/notifications/` — simulation-complete email templates
- Auth: `core/auth/` — auth_routes, dependencies, email; user data in `core/repos/user_repo.py`
- Data layer: PostgreSQL 16 with `pgvector` and `pg_trgm`; 47 raw SQL migration pairs under `db/migrations`
- Realtime: WebSocket event bus in `core/event_bus.py`
- Support services: Redis 7 and Langfuse via `docker-compose.yaml`; Docker sandbox service for code execution
- Frontend package: Vite 6 + TypeScript 5 + Phaser 3.87 in `frontend/`
- Website: Next.js 16 + React 19 + Tailwind CSS 4 + Recharts 3 in `website/`
- Local ports that appear in code/config:
  - backend: `8010`
  - website: `4000` in the root dev script, `3000` when running plain `next dev`
  - frontend Vite: `5173`
  - Redis: `6381`
  - PostgreSQL: `5434`
  - Langfuse: `3100`

## Directory Structure

```text
agents/                 YAML agent configs, behaviors, system prompts, optional extras (9 agent dirs + template)
config/                 Shared configuration: conversation_config.yaml, event_config.yaml, office_layout.json, pixellab_assets.json, pixellab_style_guide.txt, recurring_personas.yaml
core/                   FastAPI app, bootstrap, database/redis clients, event bus, LLM client, context assembly, scheduler, models, config watcher, tool executor, agent goals, agent economy, system prompt, shared state, public_routes, redis_keys, constants, exceptions, idle_behavior, blog
core/admin/             Admin route modules (9 files, ~66 endpoints): agent_routes, artifact_routes, auth_routes, config_routes, conversation_routes, diagnostics_routes, eval_routes, kill_switch_routes, simulation_routes, plus shared dependencies
core/auth/              User auth: auth_routes, dependencies, email helpers
core/characters/        Character subsystem: spawner, voting, departure (dynamic agent creation)
core/conversation/      Conversation subsystems: energy, pacing, proximity, speaker_selector, topic_detector, triggers, selection_logger
core/events/            Event subsystem: event_generator, event_templates
core/eval/              Evaluation engine: loader, prompt_loader, engine, analyzer, evolution_loop, change_applier, issue_generator
core/memory/            Memory subsystem: core, recall, archival, reflection, reflection_scheduler, compaction, dreams, embeddings, snapshot, memory_seed, token counting, validation
core/notifications/     Email notifications: simulation_complete, templates
core/repos/             Typed repository layer (19 repos): agents, agent_state, alliances, conversations, memory, costs, transcripts, world, artifacts, simulations, evals, assertions, relationships, goals, config_version, evolution, prompt_log, challenge, user
core/reporting/         Reporting subsystem: timeline_reporter, scorecard, comparison, cost_projection, formatters; sectioned reports under `sections/`
core/simulation/        Simulation orchestrator: clock, phases, assertions, audience_sim, world_simulator, snapshot, recurring_personas, display, orchestrator
core/social/            Social subsystem: relationship_tracker, alliances
core/video/             Video pipeline: audio_timeline, render_pipeline, storage, worker, config
core/world/             World generation: office_generator, pixellab_client, sprite_generator
core/youtube/           YouTube publishing: client, worker, config
db/                     Raw SQL migration runner, init SQL, and numbered up/down migrations (001–047)
docker/                 Dockerfiles for services
evals/                  Evaluation framework: 13 eval prompt categories and results
frontend/               Phaser.js world renderer: main scene, chunk-based world loading, agent sprites, WebSocket client, typed events
research/               Research papers and analysis documents
sandbox/                Dockerfile for the agent code execution sandbox
scenarios/              Simulation scenario YAML files (awakening, full_day, dream_cycle_test, faction_emergence_test, etc.) plus `seeds/`
scripts/                Utility scripts: chat, test_agent, watch_conversations, run_simulation, run_eval, run_evolution, run_reflection_test, report_simulation, snapshot_memory, restore_memory, seed_config, render_simulation_video, publish_simulation_youtube, backfill_*, check-services, generate_office_tilemap, etc.
specs/                  Product and architecture reference docs (read-only context)
tools/                  Agent tool implementations (17 functional modules + base + stubs) and ToolRegistry
website/                Next.js app router site with public pages and admin dashboard widgets
tests/                  ~120 test files across backend/ (pytest) and integration/ (Python integration); frontend/ and website/ host their own JS test suites
```

Important files:
- `core/main.py` defines the FastAPI surface (`/api/health`, `/ws`, admin/public/auth/kill-switch routers) and the lifespan that wires up all subsystems
- `core/bootstrap.py` unified service initialization for all subsystems with dry-run mode support
- `core/public_routes.py` serves the public REST API consumed by `website/src/lib/api.ts`
- `core/admin/` contains 9 route modules under `/api/admin/*` for agent/conversation/artifact/simulation/eval inspection, config, diagnostics, kill switch, auth
- `core/agent_registry.py` loads agent configs from disk, validates model names via aliases, syncs status through Redis
- `core/llm_client.py` defines allowed models with aliases and per-token cost metadata
- `core/models.py` is the source of backend Pydantic schemas (~109 BaseModel classes)
- `core/conversation_engine.py` is the central runtime loop
- `core/context_assembly.py` builds three-layer prompts: infrastructure → character → memory
- `core/memory/reflection.py` drives 6-hour and weekly reflection cycles
- `core/characters/spawner.py` and `core/characters/voting.py` handle dynamic character creation
- `core/social/alliances.py` manages alliance formation and dissolution
- `core/simulation/orchestrator.py` drives full-day simulation runs
- `core/eval/engine.py` runs post-simulation evaluations; `core/eval/evolution_loop.py` drives the self-improving cycle; `core/eval/issue_generator.py` opens GitHub issues from low-scoring findings
- `core/reporting/timeline_reporter.py` generates structured simulation reports with sectioned output
- `core/video/render_pipeline.py` and `core/youtube/client.py` produce and publish simulation recap videos
- `tools/__init__.py` exports all tools and the `ToolRegistry` with `get_core_tools()` and `get_memory_tools()` factories
- `db/migrate.py` is the raw SQL migration entry point for `python -m db`; latest migration is `047_simulation_youtube_publish`
- `website/src/lib/api.ts` calls `/api/agents`, `/api/conversations`, `/api/scenarios`, `/api/blog`, `/api/evals`, etc., served by `core/public_routes.py`

## Code Style

- Python code is typed and async-first for I/O paths; follow the existing `Database`, `RedisClient`, repository, and memory manager patterns instead of adding ad hoc SQL or connection logic
- Keep backend schemas in Pydantic models in `core/models.py`; repository classes return typed models, not loose dicts
- Memory operations go through the managers in `core/memory/`; do not bypass them with direct repo calls from outside the memory subsystem
- New tools must extend `tools/base.py:BaseTool` and be registered in `tools/__init__.py`; inject dependencies via constructor following the existing pattern
- New admin endpoints belong in the appropriate `core/admin/*_routes.py` module; share auth/database dependencies through `core/admin/dependencies.py`. Public endpoints belong in `core/public_routes.py`
- Use raw SQL migrations in `db/migrations` for schema changes; keep filenames numbered and paired with `.up.sql` and `.down.sql`
- Ruff is configured with `target-version = "py312"` and `line-length = 100`; keep imports grouped as stdlib, third-party, local
- TypeScript is strict in both `frontend/` and `website/`; keep types explicit and avoid weakening configs with `any`
- `website/` uses the Next.js app router and the `@/*` path alias; `frontend/` does not have that alias
- Keep shared agent identity and model fields consistent across YAML configs, DB seeds, and TypeScript constants when you intentionally change them
- When editing agent configs, remember `AgentRegistry` reads disk files directly and merges `config.yaml` with optional `behaviors.yaml`, `system_prompt.md`, and any additional YAML files in the agent directory

## Non-Negotiables

- Keep `<!-- managed by alpha-loop -->` as the first line of this file
- Preserve the 9-agent roster and stable IDs unless the user explicitly changes canon across configs, migrations, and UI
- The admin dashboard backend (`/api/admin/*`) and the public API (`core/public_routes.py`) are both live; the website is wired to the public API
- The conversation engine, memory system, reflection scheduler, tools, and LLM client are initialized at startup, but there is no production entry point driving continuous agent dialogue yet; use `scripts/run_simulation.py` for full simulations, `scripts/run_eval.py` for post-simulation evaluations, and `scripts/run_evolution.py` for the self-improving evolution loop; CrewAI is installed but not wired
- Preserve the special handling of `management` and `alpha`; they are not standard conversational agents
- When touching model names, keep them in sync with `core/llm_client.py` MODEL_REGISTRY, the YAML configs under `agents/`, and the seed data in `db/migrations/002_seed_agents.up.sql`
- When touching ports or env defaults, keep root `.env.example`, `website/.env.example`, `package.json`, `docker-compose.yaml`, and `website/next.config.ts` aligned around backend port `8010`
- Treat `specs/` and `README.md` as reference material. If they disagree with live code, prefer the live code and update docs rather than coding to outdated prose

<!-- managed by alpha-loop -->
# AGENTS.md — Livestream to AGI

## Overview

This repo is a monorepo for a 24/7 AI reality show set in a pixel-art world. The project canon centers on 9 agents: Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok, Management, and Alpha.

The live codebase includes:
- a FastAPI backend with a health route, WebSocket event bus, a public REST API, an admin API (66 endpoints across 9 route modules), user/admin auth APIs, a kill-switch API, static video serving, and lifespan hooks that initialize database, Redis, agent registry, memory managers, LLM client, TTS pipeline, config watcher, and a reflection scheduler
- a public-facing REST API (`core/public_routes.py`, `prefix=/api`, ~54 endpoints) that backs the website: scenarios, agents and per-agent journal/costs/relationships/memory/evolution/chat, conversations, blog, evals, world chunks, challenges, stats, lore, and simulations
- async PostgreSQL and Redis clients with a typed repository layer (19 repo classes including artifact, simulation, eval, assertion, relationship, goal, config_version, evolution, prompt_log, agent_state, alliance, challenge, and user repos; plus `repos/utils.py` helpers)
- a multi-tier memory system: core memory (persistent identity), recall memory (pgvector semantic search), archival memory (long-term storage), dreams, memory seeding, and reflection (LLM-driven 6-hour + weekly cycles with journaling and self-modification proposals)
- a conversation engine orchestrator with speaker selection, energy model, interrupts, topic detection, pacing, proximity groups, Management safety review, and TTS output
- a context assembly pipeline that builds three-layer prompts: infrastructure rules → character identity → mutable memory state
- a tool registry with functional tool modules exporting 33 tool classes (plus simulation stubs): messaging, audience interaction, memory operations, code execution (Docker sandbox), tilemap generation, revenue/social drafts, web search, Alpha dispatch, self-modification, task management, world state, evolution log viewer, alliances, economy/budget, and character proposals
- raw SQL migrations (48 pairs, up to `048_simulation_video_failure_reason`) and typed repository classes
- YAML-backed agent config loading from `agents/*`, including `config.yaml`, `behaviors.yaml`, `system_prompt.md`, and optional extra YAML files (e.g., management's `content_rules.yaml` and `intervention_levels.yaml`)
- an OpenRouter LLM client with a 9-model registry, cost tracking, retry logic, and optional Langfuse hooks
- a modular admin dashboard backend (`core/admin/`) with 9 route files and 66 endpoints — agent inspection, conversation viewer, artifact browser, simulation timeline, eval dashboard, transcript viewer, config management, diagnostics, kill switch, auth — protected by `ADMIN_PASSWORD` Bearer auth
- a user auth subsystem (`core/auth/`) with email magic-link login (`email.py`, `dev_email_app.py`), route handlers, and shared dependencies
- a notifications subsystem (`core/notifications/`) for simulation-complete emails with templates
- a video subsystem (`core/video/`) — render pipeline, audio timeline, cue parser, storage, worker — that turns a simulation into an MP4, and a YouTube subsystem (`core/youtube/`) — client, config, worker — that publishes it
- a simulation orchestrator (`core/simulation/`) with clock, phases, assertions, audience simulation, world simulation, snapshot, recurring personas, display, and CLI entry point (`scripts/run_simulation.py`)
- an eval engine (`core/eval/`) with eval loader, prompt loader, engine, analyzer, evolution loop, change applier, and GitHub issue generator for eval findings
- a character subsystem (`core/characters/`) with spawner, voting, and departure handling for dynamic agent creation
- a social subsystem (`core/social/`) with relationship tracking and alliance management between agents
- an events subsystem (`core/events/`) with event generator and event templates
- a reporting subsystem (`core/reporting/`) with timeline reports, scorecards, cost projections, comparisons, and sectioned report generation under `core/reporting/sections/`
- a Phaser.js frontend (`frontend/`) with main scene, chunk-based world loading, agent sprite rendering and management, WebSocket client, and typed event handling
- a Next.js website with public pages (home, about, agents, artifacts, blog, challenges, clips, contribute, conversations, donate, ethics, evals, lore, safety, simulations, world), shared TS types, and an API client (`website/src/lib/api.ts`) that consumes the live public `/api/*` routes

Special agent rules are real and should be preserved:
- `management` is an intervention-only safety agent with `chattiness: 0.0` and `initiative: 0.0`
- `alpha` is a non-verbal helper wolf with no voice and zero speaker-selection weights

Treat `specs/CHARACTER-SHEETS.md` and the YAML files in `agents/` as the source for agent identity and personality details.

## Tech Stack

- Python: local development is pinned to Python `3.13` via `.python-version`; project metadata allows `>=3.12,<3.14`
- Backend: FastAPI, asyncpg, redis.asyncio, httpx, pydantic v2, pydantic-settings
- LLM integration: OpenRouter client in `core/llm_client.py` with a fixed 9-model `MODEL_REGISTRY`; Langfuse hooks are present; CrewAI is installed but not wired into the running app
- Memory: `core/memory/` — CoreMemoryManager, RecallMemoryManager, ArchivalMemoryManager, ReflectionManager, ReflectionScheduler, MemoryCompactor, MemorySnapshot, dreams, memory_seed; embeddings via pgvector; token counting via tiktoken
- Conversation: `core/conversation_engine.py` orchestrates speaker selection, energy, interrupts, Management review, TTS, and event emission; subsystems in `core/conversation/` (energy, pacing, proximity, speaker_selector, topic_detector, triggers, selection_logger)
- TTS: Edge TTS pipeline in `core/tts.py` with per-agent voice support; `core/speech_parser.py` for structured dialogue/action parsing
- Management: `core/management.py` reviews all agent output before broadcast (content filter with intervention levels)
- Scheduling: APScheduler runs reflection cycles (6-hour at 2/8/14/20 UTC, weekly Sunday 20 UTC) via `core/scheduler.py`
- Tools: `tools/` package with functional tool modules, 33 tool classes, simulation stubs, and a `ToolRegistry`; includes code execution via Docker sandbox with gVisor; `tools/journal_image_tool.py` provides a separate `JournalImageGenerator` utility
- Auth/notifications: `core/auth/` (email magic-link user auth) and `core/notifications/` (simulation-complete emails)
- Video/publishing: `core/video/` renders simulations to MP4; `core/youtube/` publishes them; rendered files are served from `/videos/{filename}`
- Characters/social/events: `core/characters/` (spawner, voting, departure), `core/social/` (relationship_tracker, alliances), `core/events/` (event_generator, event_templates)
- Data layer: PostgreSQL 16 with `pgvector` and `pg_trgm`, plus 48 raw SQL migration pairs under `db/migrations`
- Realtime: WebSocket event bus in `core/event_bus.py` (~24 event types, message-history buffer, connection cap)
- Support services: Redis 7, Langfuse, and a Docker `sandbox` service via `docker-compose.yaml`; code execution also uses the top-level `sandbox/Dockerfile`
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
agents/                 YAML agent configs, behaviors, system prompts, optional extra YAML (9 agent dirs + template)
config/                 Shared config: conversation_config.yaml, event_config.yaml, office_layout.json, pixellab_assets.json, pixellab_style_guide.txt, recurring_personas.yaml
core/                   FastAPI app, bootstrap, db/redis clients, event bus, LLM client, context assembly, scheduler, models, config watcher, tool executor, agent goals/economy, public_routes, shared state
core/admin/             Admin route modules (9 files, 66 endpoints) + shared dependencies
core/auth/              User auth: email magic-link, route handlers, dependencies, dev email app
core/characters/        Character subsystem: spawner, voting, departure (dynamic agent creation)
core/conversation/      Conversation subsystems: energy, pacing, proximity, speaker_selector, topic_detector, triggers, selection_logger
core/events/            Event subsystem: event_generator, event_templates
core/eval/              Evaluation engine: loader, prompt_loader, engine, analyzer, evolution_loop, change_applier, issue_generator
core/memory/            Memory subsystem: core, recall, archival, reflection, reflection_scheduler, compaction, dreams, memory_seed, embeddings, snapshot, token counting, validation
core/notifications/     Simulation-complete notifications and email templates
core/repos/             Typed repository layer (19 repos) + utils helpers
core/reporting/         Reporting subsystem: timeline_reporter, scorecard, comparison, cost_projection, formatters; sectioned reports under `sections/`
core/simulation/        Simulation orchestrator: clock, phases, assertions, audience_sim, world_simulator, snapshot, recurring_personas, display, orchestrator
core/social/            Social subsystem: relationship_tracker, alliances
core/video/             Simulation → MP4 render pipeline: render_pipeline, audio_timeline, cue_parser, storage, worker, config
core/world/             World generation: office_generator, pixellab_client, sprite_generator
core/youtube/           YouTube publishing: client, config, worker
db/                     Raw SQL migration runner (`python -m db`), init SQL, numbered up/down migrations (001–048)
evals/                  Evaluation framework: 12 eval prompts + `_analyzer.yaml` and results
frontend/               Phaser.js world renderer: main scene, chunk-based world loading, agent sprite rendering/management, WebSocket client, typed events
research/               Research papers and analysis documents for project positioning
scenarios/              18 simulation scenario YAML files (ab_test, awakening, budget_crisis, full_day, first_48h, etc.) + seeds
scripts/                chat.py, test_agent.py, watch_conversations.py, run_simulation.py, run_eval.py, run_evolution.py, run_reflection_test.py, report_simulation.py, snapshot_memory.py, restore_memory.py, seed_config.py, render_simulation_video.py, publish_simulation_youtube.py, backfill_*.py, verify_simulation.py, verify-render.sh, check-services.sh, generate_office_tilemap.py, check_tool_coverage.py
skills/                 Skill definitions (code-review, git-workflow, implementation-planning, playwright-cli, security-analysis, test-robustness, testing-patterns)
specs/                  Product and architecture reference docs; useful context, not the runtime source of truth
tools/                  Agent tool implementations + ToolRegistry (messaging, audience, memory, code execution, tilemap, revenue, web, Alpha dispatch, self-modification, task management, world state, evolution log, alliances, economy, character proposals); journal_image_tool utility; stubs
tests/                  ~110 test files: backend/ (unit), integration/ (Python integration), frontend/ (vitest), website/ (vitest + playwright e2e)
```

Important files:
- `core/main.py` defines the FastAPI surface (`/api/health`, `/ws`, `/videos/{filename}`, `/api/admin/*`, public `/api/*`, user/admin auth, kill switch) and the lifespan that wires up all subsystems
- `core/public_routes.py` is the live public REST API (`prefix=/api`) consumed by the website
- `core/bootstrap.py` unified service initialization for all subsystems with dry-run mode support
- `core/agent_registry.py` loads agent configs from disk, validates model names via aliases, and syncs status through Redis
- `core/llm_client.py` defines 9 allowed models with aliases and per-token cost metadata
- `core/models.py` is the source of backend Pydantic schemas (~107 BaseModel classes)
- `core/conversation_engine.py` is the central runtime loop — ties together triggers, speaker selection, energy, interrupts, Management review, TTS, and event emission
- `core/context_assembly.py` builds three-layer prompts: infrastructure → character → memory
- `core/memory/reflection.py` drives 6-hour and weekly reflection cycles with journaling and self-modification proposals
- `core/simulation/orchestrator.py` drives full-day simulation runs with phased scheduling
- `core/eval/engine.py`, `core/eval/evolution_loop.py`, `core/eval/issue_generator.py` run evals, the evolution cycle, and GitHub issue creation from low-scoring findings
- `core/video/render_pipeline.py` and `core/youtube/worker.py` render and publish simulation videos
- `tools/__init__.py` exports all tools and the `ToolRegistry` with `get_core_tools()` and `get_memory_tools()` factories
- `db/migrate.py` is the raw SQL migration entry point for `python -m db`; migrations go up to `048_simulation_video_failure_reason`
- `website/src/lib/api.ts` calls the live public routes under `/api` (agents, journal, chat, conversations, world chunks, challenges, stats, lore, simulations)

## Code Style

- Python code is typed and async-first for I/O paths; follow the existing `Database`, `RedisClient`, repository, and memory manager patterns instead of adding ad hoc SQL or connection logic
- Keep backend schemas in Pydantic models in `core/models.py`; repository classes should return typed models, not loose dicts
- Memory operations go through the managers in `core/memory/`; do not bypass them with direct repo calls from outside the memory subsystem
- New tools must extend `tools/base.py:BaseTool` and be registered in `tools/__init__.py`; inject dependencies via constructor
- New admin endpoints belong in the appropriate `core/admin/*_routes.py` module; new public endpoints belong in `core/public_routes.py`; share auth/database dependencies through `core/admin/dependencies.py`
- Use raw SQL migrations in `db/migrations` for schema changes; keep migration filenames numbered and paired with `.up.sql` and `.down.sql`
- Ruff: keep imports grouped stdlib → third-party → local and follow the configured line length
- TypeScript is strict in both `frontend/` and `website/`; keep types explicit and avoid weakening configs with `any`
- `website/` uses the Next.js app router and the `@/*` path alias; `frontend/` does not have that alias
- Keep shared agent identity and model fields consistent across YAML configs, DB seeds, and TypeScript constants when you intentionally change them
- When editing agent configs, remember `AgentRegistry` reads disk files directly and merges `config.yaml` with optional `behaviors.yaml`, `system_prompt.md`, and any additional YAML files in the agent directory

## Non-Negotiables

- Keep `<!-- managed by alpha-loop -->` as the first line of this file
- Preserve the 9-agent roster and stable IDs unless the user explicitly changes canon across configs, migrations, and UI
- The admin dashboard backend (`/api/admin/*`, 66 endpoints) and the public API (`core/public_routes.py`, `prefix=/api`) are both live; the website consumes the public routes — keep `core/public_routes.py` and `website/src/lib/api.ts` in sync when changing either
- The conversation engine, memory system, reflection scheduler, tools, and LLM client are initialized at startup, but there is no production entry point driving continuous agent dialogue yet; use `scripts/run_simulation.py` for full simulations, `scripts/run_eval.py` for post-simulation evaluations, and `scripts/run_evolution.py` for the self-improving evolution loop; CrewAI is installed but not wired
- Preserve the special handling of `management` and `alpha`; they are not standard conversational agents
- When touching model names, keep them in sync with `core/llm_client.py` MODEL_REGISTRY, the YAML configs under `agents/`, and the seed data in `db/migrations/002_seed_agents.up.sql`
- When touching ports or env defaults, keep root `.env.example`, `website/.env.example`, `package.json`, `docker-compose.yaml`, and `website/next.config.ts` aligned around backend port `8010`
- Treat `specs/` and `README.md` as reference material. If they disagree with live code, prefer the live code and update docs rather than coding to outdated prose

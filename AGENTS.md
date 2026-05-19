<!-- managed by alpha-loop -->
# AGENTS.md — Livestream to AGI

## Overview

This repo is a monorepo for a 24/7 AI reality show. The project canon centers on 9 agents: Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok, Management, and Alpha.

A disciplined **Minecraft pivot** is in progress: the runtime world is moving from the Phaser pixel-art renderer to **Minecraft Java Edition (Paper 1.21.6)** driven by a forked **Mindcraft** (Node 20, LLM + Mineflayer) bot fleet, bridged to the existing Python services. Both worlds currently live in the tree. `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` and the binding ADRs in `docs/decisions/` (0000–0010) are the source of truth for that pivot; do not bake unverified Minecraft facts into code — route uncertainty to the research issues those docs reference.

The live codebase includes:
- a FastAPI backend with a health route, WebSocket event bus, a public REST API, an admin API (66 endpoints across 9 route modules), user/admin auth APIs, a kill-switch API, static video serving, the Python↔Node bridge router, and lifespan hooks that initialize database, Redis, agent registry, memory managers, LLM client, TTS pipeline, config watcher, reflection scheduler, and bridge memory consumers
- a public-facing REST API (`core/public_routes.py`, `prefix=/api`, ~54 endpoints) that backs the website: scenarios, agents and per-agent journal/costs/relationships/memory/evolution/chat, conversations, blog, evals, world chunks, challenges, stats, lore, and simulations
- async PostgreSQL and Redis clients with a typed repository layer (19 repo classes including artifact, simulation, eval, assertion, relationship, goal, config_version, evolution, prompt_log, agent_state, alliance, challenge, and user repos; plus `repos/utils.py` helpers)
- a multi-tier memory system: core memory (persistent identity), recall memory (pgvector semantic search), archival memory, dreams, memory seeding, and reflection (LLM-driven 6-hour + weekly cycles with journaling and self-modification proposals)
- a conversation engine orchestrator with speaker selection, energy model, interrupts, topic detection, pacing, proximity groups, Management safety review, and TTS output
- a context assembly pipeline that builds three-layer prompts: infrastructure rules → character identity → mutable memory state
- a tool registry with functional tool modules exporting 32 tool classes (including 2 simulation stubs): messaging, audience interaction, memory operations, code execution (Docker sandbox), tilemap generation, revenue/social drafts, web search, Alpha dispatch, self-modification, task management, world state, evolution log viewer, alliances, economy/budget, and character proposals
- a Python↔Node bridge (`core/bridge/`) — a versioned message contract, an authenticated FastAPI WebSocket surface (`/api/minecraft/bridge/ws`, fail-closed bearer auth), an inbound perception/action channel, memory handlers/consumers, and observability — letting Node Minecraft bots call Python services
- raw SQL migrations (48 pairs, up to `048_simulation_video_failure_reason`) and typed repository classes
- YAML-backed agent config loading from `agents/*` (`config.yaml`, `behaviors.yaml`, `system_prompt.md`, and optional extra YAML such as management's `content_rules.yaml` / `intervention_levels.yaml`)
- an OpenRouter LLM client with a 9-model registry, cost tracking, retry logic, optional Langfuse hooks, and local-LLM (LM Studio) routing for pivot validation
- a modular admin dashboard backend (`core/admin/`, 9 route files, 66 endpoints) protected by `ADMIN_PASSWORD` Bearer auth
- a user auth subsystem (`core/auth/`) with email magic-link login, route handlers, and shared dependencies
- a notifications subsystem (`core/notifications/`) for simulation-complete emails with templates
- a video subsystem (`core/video/`) that turns a simulation into an MP4, and a YouTube subsystem (`core/youtube/`) that publishes it
- a simulation orchestrator (`core/simulation/`) with clock, phases, assertions, audience simulation, world simulation, snapshot, recurring personas, display, and CLI entry point (`scripts/run_simulation.py`)
- an eval engine (`core/eval/`) with eval loader, prompt loader, engine, analyzer, evolution loop, change applier, and GitHub issue generator for eval findings
- a character subsystem (`core/characters/`) with spawner, voting, and departure handling for dynamic agent creation
- a social subsystem (`core/social/`) with relationship tracking and alliance management
- an events subsystem (`core/events/`) with event generator and event templates
- a reporting subsystem (`core/reporting/`) with timeline reports, scorecards, cost projections, comparisons, and sectioned report generation under `core/reporting/sections/`
- a Phaser.js frontend (`frontend/`) with main scene, chunk-based world loading, agent sprite rendering, WebSocket client, and typed event handling (legacy world renderer, still present during the pivot)
- a Next.js website with public pages (home, about, agents, artifacts, blog, challenges, clips, contribute, conversations, donate, ethics, evals, lore, safety, simulations, world), shared TS types, and an API client (`website/src/lib/api.ts`) that consumes the live public `/api/*` routes

Special agent rules are real and must be preserved:
- `management` is an intervention-only safety agent with `chattiness: 0.0` and `initiative: 0.0`
- `alpha` is a non-verbal helper wolf with no voice and zero speaker-selection weights

Treat `specs/CHARACTER-SHEETS.md` and the YAML files in `agents/` as the source for agent identity and personality details.

## Tech Stack

- Python: local development is pinned to `3.13` via `.python-version`; project metadata allows `>=3.12,<3.14`
- Backend: FastAPI, asyncpg, redis.asyncio, httpx, pydantic v2, pydantic-settings
- LLM integration: OpenRouter client in `core/llm_client.py` with a fixed 9-model `MODEL_REGISTRY`; Langfuse hooks present; LM Studio local-LLM routing (`LLM_PROVIDER=lmstudio`, `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_MODEL_BUILDING`) is the required acceptance path for pivot work; CrewAI is installed but not wired into the running app
- Memory: `core/memory/` — CoreMemoryManager, RecallMemoryManager, ArchivalMemoryManager, ReflectionManager, ReflectionScheduler, MemoryCompactor, MemorySnapshot, dreams, memory_seed; embeddings via pgvector; token counting via tiktoken
- Conversation: `core/conversation_engine.py` orchestrates speaker selection, energy, interrupts, Management review, TTS, and event emission; subsystems in `core/conversation/` (energy, pacing, proximity, speaker_selector, topic_detector, triggers, selection_logger)
- TTS: Edge TTS pipeline in `core/tts.py` with per-agent voice support; `core/speech_parser.py` for structured dialogue/action parsing
- Management: `core/management.py` reviews all agent output before broadcast (content filter with intervention levels)
- Scheduling: APScheduler runs reflection cycles (6-hour at 2/8/14/20 UTC, weekly Sunday 20 UTC) via `core/scheduler.py`
- Tools: `tools/` package with functional tool modules, 32 tool classes (incl. 2 simulation stubs), and a `ToolRegistry`; includes code execution via Docker sandbox with gVisor; `tools/journal_image_tool.py` provides a separate `JournalImageGenerator` utility
- Bridge: `core/bridge/` — `contract.py` (versioned `BridgeRequest`/`BridgeResponse`, `SERVICE_REGISTRY`, JSON-schema export), `server.py` (`bridge_router`, `/api/minecraft/bridge/ws`), `inbound.py` (perception/action verbs), `handlers/` + `consumers/` (memory), `observability.py`; fixed by `docs/decisions/0010-bridge-protocol.md`
- Minecraft world: forked Mindcraft (Node 20, Mineflayer) in `mindcraft/`, targeting Paper 1.21.6; per-agent profiles generated from `agents/` configs; operated via `scripts/minecraft/`
- Auth/notifications: `core/auth/` (email magic-link user auth) and `core/notifications/` (simulation-complete emails)
- Video/publishing: `core/video/` renders simulations to MP4; `core/youtube/` publishes them; rendered files served from `/videos/{filename}`
- Characters/social/events: `core/characters/`, `core/social/`, `core/events/`
- Data layer: PostgreSQL 16 with `pgvector` and `pg_trgm`, plus 48 raw SQL migration pairs under `db/migrations`
- Realtime: WebSocket event bus in `core/event_bus.py` (~26 event types, message-history buffer, connection cap)
- Support services: Redis 7, Langfuse, and a Docker `sandbox` service via `docker-compose.yaml`; code execution also uses the top-level `sandbox/Dockerfile`
- Frontend package: Vite 6 + TypeScript 5.7 + Phaser 3.87 in `frontend/`
- Website: Next.js 16 + React 19 + Tailwind CSS 4 + Recharts 3 in `website/`
- Local ports in code/config: backend `8010`; website `4000` (root dev script) or `3000` (plain `next dev`); frontend Vite `5173`; Redis `6381`; PostgreSQL `5434`; Langfuse `3100`

## Directory Structure

```text
agents/                 YAML agent configs, behaviors, system prompts, optional extra YAML (9 agent dirs + template)
config/                 Shared config: conversation_config.yaml, event_config.yaml, office_layout.json, pixellab_*, recurring_personas.yaml
core/                   FastAPI app, bootstrap, db/redis clients, event bus, LLM client, context assembly, scheduler, models, config watcher, tool executor, agent goals/economy, public_routes, shared state
core/admin/             Admin route modules (9 files, 66 endpoints) + shared dependencies
core/auth/              User auth: email magic-link, route handlers, dependencies, dev email app
core/bridge/            Python↔Node bridge: contract, server (WS /api/minecraft/bridge/ws), inbound, observability, handlers/, consumers/, schemas/
core/characters/        Character subsystem: spawner, voting, departure (dynamic agent creation)
core/conversation/      Conversation subsystems: energy, pacing, proximity, speaker_selector, topic_detector, triggers, selection_logger
core/events/            Event subsystem: event_generator, event_templates
core/eval/              Evaluation engine: loader, prompt_loader, engine, analyzer, evolution_loop, change_applier, issue_generator
core/memory/            Memory subsystem: core, recall, archival, reflection, reflection_scheduler, compaction, dreams, memory_seed, embeddings, snapshot, token counting, validation
core/notifications/     Simulation-complete notifications and email templates
core/repos/             Typed repository layer (19 repos) + utils helpers
core/reporting/         Reporting subsystem: timeline_reporter, scorecard, comparison, cost_projection, formatters; sectioned reports under sections/
core/simulation/        Simulation orchestrator: clock, phases, assertions, audience_sim, world_simulator, snapshot, recurring_personas, display, orchestrator
core/social/            Social subsystem: relationship_tracker, alliances
core/video/             Simulation → MP4 render pipeline: render_pipeline, audio_timeline, cue_parser, storage, worker, config
core/world/             World generation: office_generator, pixellab_client, sprite_generator
core/youtube/           YouTube publishing: client, config, worker
db/                     Raw SQL migration runner (python -m db), init SQL, numbered up/down migrations (001–048)
docs/                   Binding ADRs (docs/decisions/, 0000–0010), Minecraft pivot plan, runbooks (docs/minecraft/)
evals/                  Evaluation framework: 12 eval prompts + _analyzer.yaml and results
frontend/               Phaser.js world renderer (legacy during pivot): main scene, chunk world loading, agent sprites, WebSocket client
mindcraft/              Vendored/forked Mindcraft (Node 20, Mineflayer) — Minecraft agent runtime
research/               Research papers and analysis documents for project positioning
scenarios/              18 simulation scenario YAML files + seeds
scripts/                CLI/utility scripts (run/eval/evolution, snapshots, video, bridge, local-LLM, simulation) + minecraft/ pivot tooling
skills/                 Skill definitions (code-review, git-workflow, implementation-planning, playwright-cli, security-analysis, test-robustness, testing-patterns)
specs/                  Product and architecture reference docs; useful context, not the runtime source of truth
tools/                  Agent tool implementations + ToolRegistry; journal_image_tool utility; stubs
tests/                  ~148 Python test files: backend/ (unit) + integration/; frontend vitest under frontend/src/; website vitest + Playwright e2e under website/
```

Important files:
- `core/main.py` defines the FastAPI surface (`/api/health`, `/ws`, `/videos/{filename}`, `/api/admin/*`, public `/api/*`, user/admin auth, kill switch, `bridge_router`) and the lifespan wiring all subsystems
- `core/public_routes.py` is the live public REST API (`prefix=/api`) consumed by the website
- `core/bootstrap.py` unified service initialization with dry-run support
- `core/agent_registry.py` loads agent configs from disk, validates model names via aliases, syncs status through Redis
- `core/llm_client.py` defines the 9 allowed models with aliases and per-token cost metadata
- `core/models.py` is the source of backend Pydantic schemas (~107 BaseModel classes)
- `core/conversation_engine.py` is the central runtime loop
- `core/context_assembly.py` builds three-layer prompts: infrastructure → character → memory
- `core/bridge/contract.py` + `core/bridge/server.py` are the single source of truth for the Node↔Python wire protocol
- `core/simulation/orchestrator.py` drives full-day simulation runs
- `core/eval/engine.py`, `evolution_loop.py`, `issue_generator.py` run evals, the evolution cycle, and GitHub issue creation
- `db/migrate.py` is the raw SQL migration entry point (`python -m db`); migrations go up to `048_simulation_video_failure_reason`
- `website/src/lib/api.ts` calls the live public `/api` routes
- `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` + `docs/decisions/0000-summary.md` are the binding pivot decision record

## Code Style

- Python code is typed and async-first for I/O paths; follow existing `Database`, `RedisClient`, repository, and memory manager patterns instead of ad hoc SQL or connection logic
- Keep backend schemas in Pydantic models in `core/models.py`; repository classes return typed models, not loose dicts
- Memory operations go through the managers in `core/memory/`; do not bypass them with direct repo calls from outside the memory subsystem
- New tools must extend `tools/base.py:BaseTool` and be registered in `tools/__init__.py`; inject dependencies via constructor
- New admin endpoints belong in the appropriate `core/admin/*_routes.py` module; new public endpoints in `core/public_routes.py`; share auth/database dependencies through `core/admin/dependencies.py`
- Bridge changes must stay contract-valid: update `core/bridge/contract.py` and re-export schemas (`scripts/export_bridge_schemas.py`); honor `docs/decisions/0010-bridge-protocol.md` (fail-closed auth, versioned envelopes)
- Use raw SQL migrations in `db/migrations`; keep filenames numbered and paired with `.up.sql` and `.down.sql`
- Ruff: keep imports grouped stdlib → third-party → local and follow the configured line length
- TypeScript is strict in both `frontend/` and `website/`; keep types explicit and avoid weakening configs with `any`
- `website/` uses the Next.js app router and the `@/*` path alias; `frontend/` does not have that alias
- Keep shared agent identity and model fields consistent across YAML configs, DB seeds, TypeScript constants, and generated Mindcraft profiles when you intentionally change them
- `AgentRegistry` reads disk files directly and merges `config.yaml` with optional `behaviors.yaml`, `system_prompt.md`, and any additional YAML in the agent directory

## Non-Negotiables

- Keep `<!-- managed by alpha-loop -->` as the first line of this file
- Preserve the 9-agent roster and stable IDs unless the user explicitly changes canon across configs, migrations, UI, and Mindcraft profiles
- The admin dashboard backend (`/api/admin/*`, 66 endpoints) and the public API (`core/public_routes.py`, `prefix=/api`) are both live; the website consumes the public routes — keep `core/public_routes.py` and `website/src/lib/api.ts` in sync
- The conversation engine, memory system, reflection scheduler, tools, LLM client, and bridge router are initialized at startup, but there is no production entry point driving continuous agent dialogue yet; use `scripts/run_simulation.py` for full simulations, `scripts/run_eval.py` for post-simulation evaluations, and `scripts/run_evolution.py` for the evolution loop; CrewAI is installed but not wired
- The Minecraft pivot is governed by `docs/decisions/` ADRs — treat them as binding; never hardcode unverified Minecraft/Mindcraft facts, and validate pivot work locally through LM Studio
- The bridge contract is the single source of truth shared by Node and Python; never let one half drift from `core/bridge/contract.py`
- Preserve the special handling of `management` and `alpha`; they are not standard conversational agents
- When touching model names, keep them in sync with `core/llm_client.py` MODEL_REGISTRY, the YAML configs under `agents/`, and `db/migrations/002_seed_agents.up.sql`
- When touching ports or env defaults, keep root `.env.example`, `website/.env.example`, `package.json`, `docker-compose.yaml`, and `website/next.config.ts` aligned around backend port `8010`
- Treat `specs/` and `README.md` as reference material. If they disagree with live code or the pivot ADRs, prefer the live code/ADRs and update docs rather than coding to outdated prose

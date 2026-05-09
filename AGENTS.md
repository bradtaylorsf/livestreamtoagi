<!-- managed by alpha-loop -->
# AGENTS.md — Livestream to AGI

## Overview

This repo is a monorepo for a 24/7 AI reality show set in a pixel-art world. The project canon centers on 9 agents: Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok, Management, and Alpha.

The live codebase includes:
- a FastAPI backend with a health route, WebSocket event bus, admin API (63 endpoints across 9 route modules), and lifespan hooks that initialize database, Redis, agent registry, memory managers, LLM client, TTS pipeline, config watcher, and a reflection scheduler
- async PostgreSQL and Redis clients with a typed repository layer (17 repo classes including artifact, simulation, eval, assertion, relationship, goal, config_version, evolution, prompt_log, agent_state, and alliance repos)
- a multi-tier memory system: core memory (persistent identity), recall memory (pgvector semantic search), archival memory (long-term storage), and reflection (LLM-driven 6-hour + weekly cycles with journaling and self-modification proposals)
- a conversation engine orchestrator with speaker selection, energy model, interrupts, topic detection, pacing, proximity groups, Management safety review, and TTS output
- a context assembly pipeline that builds three-layer prompts: infrastructure rules → character identity → mutable memory state
- a tool registry with 15 functional tool modules exporting 32 tool classes (plus 2 simulation stubs): messaging, audience interaction, memory operations, code execution (Docker sandbox), tilemap generation, revenue/social drafts, web search, Alpha dispatch, self-modification, task management, world state, evolution log viewer, alliances, economy/budget, and character proposals
- raw SQL migrations (37 pairs, up to `037_config_version_simulation_isolation`) and typed repository classes
- YAML-backed agent config loading from `agents/*`, including `config.yaml`, `behaviors.yaml`, `system_prompt.md`, and optional extra YAML files (e.g., management's `content_rules.yaml` and `intervention_levels.yaml`)
- an OpenRouter LLM client with a 9-model registry, cost tracking, retry logic, and optional Langfuse hooks
- a modular admin dashboard backend (`core/admin/`) with 9 route files and 63 endpoints: agent inspection, conversation viewer, artifact browser, simulation timeline, eval dashboard, transcript viewer, config management, diagnostics, kill switch, auth — protected by `ADMIN_PASSWORD` Bearer auth
- a simulation orchestrator (`core/simulation/`) with clock, phases, assertions, audience simulation, world simulation, snapshot, recurring personas, display, and CLI entry point (`scripts/run_simulation.py`)
- an eval engine (`core/eval/`) with eval loader, prompt loader, engine, analyzer, evolution loop, change applier, and GitHub issue generator for eval findings
- a character subsystem (`core/characters/`) with spawner, voting, and departure handling for dynamic agent creation
- a social subsystem (`core/social/`) with relationship tracking and alliance management between agents
- an events subsystem (`core/events/`) with event generator and event templates
- a reporting subsystem (`core/reporting/`) with timeline reports, scorecards, cost projections, comparisons, and sectioned report generation under `core/reporting/sections/` (executive summary, cost analysis, daily breakdown, key moments, memory evolution, relationship evolution, tool usage)
- a Phaser.js frontend (`frontend/`) with main scene, chunk-based world loading, agent sprite rendering and management, WebSocket client, and typed event handling
- a Next.js website with static route pages, admin dashboard UI (agent inspector, conversation viewer, artifact browser, simulation timeline, eval dashboard), shared TS types, and an API client that targets future backend routes not yet implemented

Special agent rules are real and should be preserved:
- `management` is an intervention-only safety agent with `chattiness: 0.0` and `initiative: 0.0`
- `alpha` is a non-verbal helper wolf with no voice and zero speaker-selection weights

Treat `specs/CHARACTER-SHEETS.md` and the YAML files in `agents/` as the source for agent identity and personality details.

## Tech Stack

- Python: local development is pinned to Python `3.13` via `.python-version`; project metadata allows `>=3.12,<3.14`
- Backend: FastAPI, asyncpg, redis.asyncio, httpx, pydantic v2, pydantic-settings
- LLM integration: OpenRouter client in `core/llm_client.py` with a fixed 9-model `MODEL_REGISTRY`; Langfuse hooks are present; CrewAI is installed but not wired into the running app
- Memory: `core/memory/` — CoreMemoryManager, RecallMemoryManager, ArchivalMemoryManager, ReflectionManager, ReflectionScheduler, MemoryCompactor, MemorySnapshot; embeddings via pgvector; token counting via tiktoken
- Conversation: `core/conversation_engine.py` orchestrates speaker selection, energy, interrupts, Management review, TTS, and event emission; subsystems in `core/conversation/` (energy, pacing, proximity, speaker_selector, topic_detector, triggers, selection_logger)
- TTS: Edge TTS pipeline in `core/tts.py` with per-agent voice support; `core/speech_parser.py` for structured dialogue/action parsing
- Management: `core/management.py` reviews all agent output before broadcast (content filter with intervention levels)
- Scheduling: APScheduler runs reflection cycles (6-hour at 2/8/14/20 UTC, weekly Sunday 20 UTC) via `core/scheduler.py`
- Tools: `tools/` package with 15 functional tool modules, 32 tool classes, 2 simulation stubs, and a `ToolRegistry`; includes code execution via Docker sandbox with gVisor; `tools/journal_image_tool.py` provides a separate `JournalImageGenerator` utility
- Characters: `core/characters/` — CharacterSpawner, VotingManager, departure handling for dynamic agent creation and voting
- Social: `core/social/` — RelationshipTracker for agent-to-agent dynamics, AllianceManager for group formation
- Events: `core/events/` — EventGenerator and EventTemplates for world event creation
- Data layer: PostgreSQL 16 with `pgvector` and `pg_trgm`, plus 37 raw SQL migration pairs under `db/migrations`
- Realtime: WebSocket event bus in `core/event_bus.py` (24 event types, 50-message history buffer, max 100 connections)
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
agents/                 YAML agent configs, behaviors, system prompts, and optional extra YAML (9 agent directories + template)
config/                 Shared configuration: conversation_config.yaml, event_config.yaml, office_layout.json, pixellab_assets.json, pixellab_style_guide.txt, recurring_personas.yaml
core/                   FastAPI app, bootstrap, database/redis clients, event bus, LLM client, context assembly, scheduler, models, config watcher, tool executor, agent goals, agent economy, system prompt, shared state
core/admin/             Admin route modules (9 files, 63 endpoints): agent_routes, artifact_routes, auth_routes, config_routes, conversation_routes, diagnostics_routes, eval_routes, kill_switch_routes, simulation_routes, plus shared dependencies
core/characters/        Character subsystem: spawner, voting, departure (dynamic agent creation)
core/conversation/      Conversation subsystems: energy, pacing, proximity, speaker_selector, topic_detector, triggers, selection_logger
core/events/            Event subsystem: event_generator, event_templates
core/eval/              Evaluation engine: loader, prompt_loader, engine, analyzer, evolution_loop, change_applier, issue_generator
core/memory/            Memory subsystem: core, recall, archival, reflection, reflection_scheduler, compaction, dreams, embeddings, snapshot, token counting, validation
core/repos/             Typed repository layer (17 repos): agents, agent_state, alliances, conversations, memory, costs, transcripts, world, artifacts, simulations, evals, assertions, relationships, goals, config_version, evolution, prompt_log
core/reporting/         Reporting subsystem: timeline_reporter, scorecard, comparison, cost_projection, formatters; sectioned reports under `sections/` (executive_summary, cost_analysis, daily_breakdown, key_moments, memory_evolution, relationship_evolution, tool_usage)
core/simulation/        Simulation orchestrator: clock, phases, assertions, audience_sim, world_simulator, snapshot, recurring_personas, display, orchestrator
core/social/            Social subsystem: relationship_tracker, alliances
core/world/             World generation: office_generator, pixellab_client, sprite_generator
db/                     Raw SQL migration runner, init SQL, and numbered up/down migrations (001–037)
evals/                  Evaluation framework: 13 eval prompts (agency, creativity, dialogue_quality, economic_behavior, entertainment, errors, internal_state, productivity, safety, simulation_narrative, social_dynamics, world_evolution) and results
frontend/               Phaser.js world renderer: main scene, chunk-based world loading, agent sprite rendering/management, WebSocket client, typed events
research/               Research papers and analysis documents for project positioning
website/                Next.js app router site with public pages and admin dashboard (agent inspector, conversation viewer, artifact browser, simulation timeline, eval dashboard)
scripts/                Utility scripts: chat.py, test_agent.py, watch_conversations.py, run_simulation.py, run_eval.py, run_evolution.py, run_reflection_test.py, report_simulation.py, snapshot_memory.py, restore_memory.py, seed_config.py, check_tool_coverage.py, test_sim_isolation.py, verify_simulation.py, check_local_llm.py, check-services.sh, generate_office_tilemap.py, run_tool_coverage.sh
skills/                 Skill definitions for code-review, git-workflow, implementation-planning, playwright-cli, security-analysis, test-robustness, testing-patterns
specs/                  Product and architecture reference docs; useful context, not the runtime source of truth
tools/                  Agent tool implementations: 15 functional modules + ToolRegistry (messaging, audience, memory, code execution, tilemap, revenue, web, Alpha dispatch, self-modification, task management, world state, evolution log, alliances, economy, character proposals); journal_image_tool utility
tests/                  ~110 test files: backend/ (unit), integration/ (Python integration), frontend/ (vitest), website/ (vitest + playwright e2e)
```

Important files:
- `core/main.py` defines the FastAPI surface (`/api/health`, `/ws`, and `/api/admin/*`) and the lifespan that wires up all subsystems
- `core/bootstrap.py` unified service initialization for all subsystems with dry-run mode support
- `core/admin/` contains 9 route modules providing 63 admin endpoints: agent inspection, conversation viewer, artifact browser, simulation timeline, eval dashboard, transcript viewer, config management, diagnostics, kill switch, auth
- `core/agent_registry.py` loads agent configs from disk, validates model names via aliases, and syncs status through Redis
- `core/llm_client.py` defines 9 allowed models with aliases and per-token cost metadata
- `core/models.py` is the source of backend Pydantic schemas (~101 BaseModel classes: agents, memory tiers, conversations, transcripts, journal entries, self-modification proposals, LLM responses, cost events, goals, relationships, prompt logs)
- `core/conversation_engine.py` is the central runtime loop — ties together triggers, speaker selection, energy, interrupts, Management review, TTS, and event emission
- `core/context_assembly.py` builds three-layer prompts: infrastructure → character → memory
- `core/memory/reflection.py` drives 6-hour and weekly reflection cycles with journaling and self-modification proposals
- `core/characters/spawner.py` handles dynamic character creation; `core/characters/voting.py` manages proposal voting
- `core/social/alliances.py` manages agent alliance formation and dissolution
- `core/simulation/orchestrator.py` drives full-day simulation runs with phased scheduling
- `core/eval/engine.py` runs post-simulation evaluations with configurable categories
- `core/eval/evolution_loop.py` orchestrates the self-improving evolution cycle
- `core/eval/issue_generator.py` creates GitHub issues from low-scoring eval findings
- `core/reporting/timeline_reporter.py` generates structured simulation reports with sectioned output
- `tools/__init__.py` exports all tools and the `ToolRegistry` with `get_core_tools()` and `get_memory_tools()` factories
- `db/migrate.py` is the raw SQL migration entry point for `python -m db`; migrations go up to `037_config_version_simulation_isolation`
- `website/src/lib/api.ts` calls planned REST endpoints (`/api/agents`, `/api/agents/{id}/journal`, `/api/agents/{id}/chat`, `/api/world/chunks`, `/api/challenges`, `/api/stats`, `/api/lore`) that the backend does not currently expose as public routes (admin equivalents exist under `/api/admin`)

## Code Style

- Python code is typed and async-first for I/O paths; follow the existing `Database`, `RedisClient`, repository, and memory manager patterns instead of adding ad hoc SQL or connection logic
- Keep backend schemas in Pydantic models in `core/models.py`; repository classes should return typed models, not loose dicts
- Memory operations go through the managers in `core/memory/`; do not bypass them with direct repo calls from outside the memory subsystem
- New tools must extend `tools/base.py:BaseTool` and be registered in `tools/__init__.py`; follow the existing pattern of injecting dependencies via constructor
- New admin endpoints belong in the appropriate `core/admin/*_routes.py` module; share auth/database dependencies through `core/admin/dependencies.py`
- Use raw SQL migrations in `db/migrations` for schema changes; keep migration filenames numbered and paired with `.up.sql` and `.down.sql`
- Ruff is configured with `target-version = "py312"` and `line-length = 100`; keep imports grouped as stdlib, third-party, local
- TypeScript is strict in both `frontend/` and `website/`; keep types explicit and avoid weakening configs with `any`
- `website/` uses the Next.js app router and the `@/*` path alias; `frontend/` does not have that alias
- Keep shared agent identity and model fields consistent across YAML configs, DB seeds, and TypeScript constants when you intentionally change them
- When editing agent configs, remember `AgentRegistry` reads disk files directly and merges `config.yaml` with optional `behaviors.yaml`, `system_prompt.md`, and any additional YAML files in the agent directory

## Non-Negotiables

- Keep `<!-- managed by alpha-loop -->` as the first line of this file
- Preserve the 9-agent roster and stable IDs unless the user explicitly changes canon across configs, migrations, and UI
- The admin dashboard backend (`/api/admin/*`) is live with 63 endpoints across `core/admin/`; the public-facing API routes called from `website/src/lib/api.ts` are not yet served by the backend
- The conversation engine, memory system, reflection scheduler, tools, and LLM client are initialized at startup, but there is no production entry point driving continuous agent dialogue yet; use `scripts/run_simulation.py` for full simulations, `scripts/run_eval.py` for post-simulation evaluations, and `scripts/run_evolution.py` for the self-improving evolution loop; CrewAI is installed but not wired
- Preserve the special handling of `management` and `alpha`; they are not standard conversational agents
- When touching model names, keep them in sync with `core/llm_client.py` MODEL_REGISTRY, the YAML configs under `agents/`, and the seed data in `db/migrations/002_seed_agents.up.sql`
- When touching ports or env defaults, keep root `.env.example`, `website/.env.example`, `package.json`, `docker-compose.yaml`, and `website/next.config.ts` aligned around backend port `8010`
- Treat `specs/` and `README.md` as reference material. If they disagree with live code, prefer the live code and update docs rather than coding to outdated prose

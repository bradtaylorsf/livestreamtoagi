## Architecture
- **Python backend**: FastAPI + CrewAI in `core/main.py` (uvicorn on port 8010); orchestrator, memory, and conversation engine live in `core/`; agent tool implementations in `tools/`; WebSocket streams to frontend.
- **TypeScript frontend**: Phaser.js 3 pixel-art world renderer in `frontend/` (Vite + Vitest); receives WebSocket events from FastAPI, pipes via OBS/ffmpeg to Twitch/YouTube.
- **TypeScript website**: Next.js app in `website/` (Vercel-deployed) consuming the FastAPI REST API.
- **Data layer**: PostgreSQL 16 + pgvector on port 5434 (3-tier memory: Core/Recall/Archival), Redis 7 on port 6381 for shared state and kill switches, Langfuse on 3100 for LLM cost tracking.
- **Agents**: 9 personality YAMLs in `agents/` (Vera, Rex, Aurora, Pixel, Fork, Sentinel, Grok, Management, Alpha) routed through OpenRouter to different models per role.

## Conventions
- Python 3.13 only (pinned in `.python-version`; 3.14+ breaks native deps). Type hints everywhere, async/await for I/O, Pydantic for schemas, `ruff` for lint+format, snake_case funcs / PascalCase classes.
- TypeScript strict mode, ESM, `const` by default, named exports preferred.
- Tests organized by layer under `tests/` — backend: `pytest tests/backend/ -v` or `make test-backend` (PATH-safe for `/bin/sh` runners); frontend/website: `npm test` (Vitest), website E2E via Playwright.
- Conventional commits (`feat:`, `fix:`, `refactor:`, etc.); branches `feat/...` or `fix/...`; one feature per PR.
- New agent tools: add to `tools/`, register via orchestrator; new routes: wire into `core/main.py`'s FastAPI app.

## Critical Rules
- **`specs/` is read-only** — design reference only, never edit (ENGINEERING-SPECS, CHARACTER-SHEETS, CONVERSATION-ENGINE, MEMORY-SYSTEM, TOOL-DEFINITIONS, HUMAN-CHECKLIST).
- **Never commit `.env`** — contains OpenRouter, Twitch, YouTube, Pixellab, Langfuse, kill-switch keys.
- Every agent output **must pass through Management content filter** (3s delay) before TTS — do not bypass.
- Run `docker compose up -d && bash scripts/check-services.sh` before any integration test or verify step; all 5 checks (Redis, Postgres, pgvector, pg_trgm, Langfuse) must pass.
- Cost governor + kill-switch API are load-bearing — changes to `AGENT_HOURLY_CAP_USD` paths or `LIVESTREAM_KILL_MODE` need coordinated updates across orchestrator + livestream wiring.
- Reasoning Gemmas (`gemma-4-26b-a4b`) emit empty content — use `gemma-4-e4b` for local sims.
- Headless sim snapshots must use `--output-dir snapshots/headless` so dashboard can serve artifacts.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)

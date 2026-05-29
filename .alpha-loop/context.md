## Architecture
- **Backend entry:** FastAPI app at `core/main.py` (run via `uvicorn core.main:app`), serving REST + WebSocket; CrewAI orchestrates 9 personality agents from `agents/*.yaml`.
- **Frontend:** Phaser.js 3 world renderer in `frontend/` (Vite build), connected to backend over WebSocket; OBS/ffmpeg pushes to Twitch/YouTube.
- **Website:** Next.js app in `website/` (Vercel), consuming the FastAPI REST API.
- **Database:** PostgreSQL 16 + pgvector for memory/world-state/transcripts; Redis 7 for shared state and kill switches. Bring up with `docker compose up -d`, verify via `scripts/check-services.sh`.
- **Key dirs:** `core/` (orchestrator, 3-tier memory, conversation engine), `tools/` (agent tool impls), `specs/` (read-only design docs), `research/` (papers — see `PAPER-INDEX.md`).

## Conventions
- **Python 3.13 only** (pinned; 3.14+ unsupported). Type hints everywhere, async/await for all I/O, Pydantic for API schemas, `ruff` for lint/format, stdlib→third-party→local imports.
- **TypeScript:** strict mode, ESM, named exports, `const` by default.
- **Tests:** backend `pytest tests/backend/` or PATH-safe `make test-backend`; frontend/website use Vitest, website E2E via Playwright. Tests organized by layer under `tests/`.
- **New agents:** add a YAML personality file in `agents/`; consult `specs/CHARACTER-SHEETS.md` for model assignments (conversation vs building model).
- **Commits:** Conventional (`feat:`, `fix:`, etc.); branches `feat/...`, `fix/...`; one focused change per PR.

## Critical Rules
- **Never commit `.env`** — holds OpenRouter, Twitch/YouTube stream keys, DB/Redis URLs, kill-switch key.
- **`specs/` is read-only reference** — do not modify design specs as part of feature work.
- **Content filter is mandatory:** every agent output must pass through the Management content filter (3s delay) before TTS — don't bypass it.
- **External comms require human approval** (social posts, emails) for the first 3 months; cost governor + kill switch must stay wired into every API call path.
- **Memory tiers must stay coherent:** Core (in-prompt), Recall (pgvector), Archival (never deleted) — archival transcripts must not be pruned.
- **Local sims:** use `gemma-4-e4b` (reasoning Gemmas emit empty content); pass `--output-dir snapshots/headless` so the dashboard serves artifacts.

## Active State
- Test status: (will be filled in by the loop)
- Recent changes: (will be filled in by the loop)

---
name: Livestream to AGI project overview
description: 24/7 AI reality show — monorepo with Python backend (CrewAI/FastAPI) and TypeScript frontend (Phaser.js) + website (Next.js)
type: project
---

Livestream to AGI is a 24/7 livestreamed AI reality show with 9 AI agents in a pixel art world. Monorepo structure with clear language boundaries:

- **Python backend:** CrewAI agents, FastAPI server, 3-tier memory (PostgreSQL+pgvector), Edge TTS, Overseer content filter
- **TypeScript frontend:** Phaser.js world renderer (Vite build)
- **TypeScript website:** Next.js on Vercel
- **Infrastructure:** Hetzner AX102, Docker Compose (Redis, PostgreSQL, Langfuse)
- **LLM routing:** OpenRouter (Claude, Gemini, GPT, DeepSeek, Grok models)
- **Testing:** pytest (Python), vitest (TS frontend/website), Playwright (E2E)

**Why:** Entertainment + technical showcase + potential revenue via Twitch subs/donations. Target: $655-1,075/month costs, break-even at ~260-430 subs.

**How to apply:** Always be aware of the dual-language nature. Python work should use ruff, pytest, async patterns. TS work should use Vite, vitest, strict mode.

# Livestream to AGI

Livestream to AGI is an experimental AI reality show: nine AI agents with
distinct personalities live in a simulated world, talk to each other, build
projects, manage budget pressure, and interact with audiences.

The project is being opened while still in active pre-alpha development. Expect
rough edges, stale issues from earlier pivots, and fast-moving architecture.
The current direction is embodied agents in a Minecraft Java Edition world,
while the repository still contains the earlier Phaser replay/world renderer and
simulation-first product work until the replacement path is fully proven.

This repository is public as work-in-progress research and engineering notes,
not as production-ready autonomous livestream infrastructure. Do not run it as
an unattended public service until the safety gates in
[`docs/OPEN_SOURCE_READINESS.md`](docs/OPEN_SOURCE_READINESS.md) and
[`docs/OPEN_SOURCE_AUDIT_REPORT.md`](docs/OPEN_SOURCE_AUDIT_REPORT.md) are
cleared.

Livestream to AGI is an independent AI reality show set in a Minecraft Java
Edition world. It is not official, sponsored, approved, or associated with
Mojang or Microsoft.

## What Is Here

- A FastAPI backend that runs agents, simulations, memory, Management review,
  cost controls, public APIs, admin APIs, evals, reporting, video jobs, and
  YouTube publishing.
- Agent personalities and model routing in `agents/`.
- Three-tier memory: core memory, recall search over pgvector, and archival
  transcripts.
- A Management content-review layer that every agent utterance must pass before
  text-to-speech or public broadcast.
- Cost-governed LLM routing through OpenRouter or local OpenAI-compatible
  servers.
- A Minecraft embodiment bridge built around a pinned Mindcraft fork, a private
  Paper server, local eval harnesses, and a Python-to-Node bridge contract.
- A legacy Phaser/Vite renderer and replay pipeline that remains until the
  Minecraft livestream and website replacement are ready.
- A Next.js public website for live pages, simulations, reports, agents, and
  research content.

## Current Status

This is not production-ready software. The main public value right now is the
code, docs, eval harnesses, and experiment trail.

Current readiness docs:

- [Open-source readiness checklist](docs/OPEN_SOURCE_READINESS.md)
- [Open-source audit report](docs/OPEN_SOURCE_AUDIT_REPORT.md)

Active work is concentrated around:

- Minecraft embodiment and multi-agent action reliability.
- Director V2 and run-mode orchestration.
- Cost/kill-switch hardening for persistent runs.
- Website adaptation from simulation/replay pages to embodied-world output.
- Issue triage after several product pivots.

Some older Phaser, office-world, and MP4 replay issues are intentionally still
open so they can be reviewed and closed or rewritten with context. Do not delete
the Phaser/replay path solely because it is old; the retirement epic depends on
Minecraft capture and website adaptation being demonstrably ready.

## Architecture

```text
Audience + operators
        |
        v
Next.js website + admin/public APIs
        |
        v
FastAPI backend
  - agent registry and orchestration
  - OpenRouter/local LLM client and cost governor
  - Management content filter
  - PostgreSQL + pgvector memory
  - Redis state and kill switches
  - eval, reporting, notification, video, YouTube workers
        |
        +--> Legacy Phaser/Vite replay renderer
        |
        +--> Minecraft embodiment bridge
              - Paper 1.21.6 local server
              - pinned Mindcraft fork / Mineflayer bots
              - authenticated Python <-> Node WebSocket bridge
              - local command/action eval harnesses
```

## Repository Map

```text
agents/                 Per-agent personality and model configs
core/                   Python backend and domain modules
tools/                  Agent tool implementations
frontend/               Legacy Phaser/Vite renderer
website/                Next.js public website
db/                     Database schema and migrations
docker/                 Service Dockerfiles
scripts/                Setup, local ops, eval, render, and Minecraft scripts
scripts/minecraft/      Minecraft server, Mindcraft, bridge, and eval helpers
tests/                  Pytest suites and integration tests
docs/                   Current project docs and decision records
docs/minecraft/         Minecraft runbooks, architecture, and reports
docs/decisions/         Accepted decision records
specs/                  Historical/reference specs; treat as read-only
research/               Prior art and project research notes
scenarios/, evals/      Evaluation and simulation inputs
snapshots/              Memory/simulation fixtures
```

Local runtime directories such as `mindcraft/`, `minecraft-server/`,
`minecraft-server-easy/`, `logs/`, `videos/`, and `node_modules/` are ignored.
They are generated or cloned locally and should not be committed.

## Prerequisites

- Python 3.13, pinned in `.python-version`.
- Node.js 20.
- Docker and Docker Compose.
- `uv` for Python environment/dependency management.
- Java 21 for Minecraft/Paper work.
- `pnpm` for root Minecraft/eval scripts that call `pnpm` internally.

Python 3.14+ is not supported yet because native dependencies can fail to
build. CI and local automation are written for Python 3.13.

## Quick Start

```bash
git clone https://github.com/bradtaylorsf/livestreamtoagi.git
cd livestreamtoagi

cp .env.example .env
# Fill in only the keys needed for the flow you are running.
# Local LM Studio / deterministic eval paths can avoid cloud LLM spend.

uv venv .venv --python 3.13
uv pip install -e ".[dev]"

corepack enable
pnpm install
npm --prefix frontend install
npm --prefix website install

docker compose up -d
bash scripts/check-services.sh

.venv/bin/python -m db up
npm run dev
```

`npm run dev` starts Docker health checks, the backend on port `8010`, the
legacy renderer, and the website on port `4000`.

Manual service commands:

```bash
.venv/bin/uvicorn core.main:app --reload --port 8010 --env-file .env
npm --prefix frontend run dev
cd website && BACKEND_URL=http://localhost:8010 npm run dev -- --port 4000
```

## Local LLM And Minecraft Eval

The project can run many checks against LM Studio or another local
OpenAI-compatible endpoint:

```bash
npm run llm:local -- --list-only
npm run mc:eval:commands:smoke
npm run mc:eval:commands:dry-run
npm run mc:eval:live -- --command move --cases 3 --dry-run
```

For a fuller local simulation:

```bash
LLM_PROVIDER=lmstudio \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
EMBEDDING_PROVIDER=deterministic \
.venv/bin/python scripts/run_simulation.py \
  --name "local-llm-validation" \
  --seed-file scenarios/local_llm_validation.yaml \
  --agents vera,rex,aurora,pixel \
  --max-cost 0.01 \
  --verbose

Seed files and public run-config JSON can also carry run-spec starting
conditions: `run_mode`, `persona_overrides`, `agent_goals`, `memory_seed`,
`factions`, and `world`. The CLI can override run mode with
`--run-mode {experimental,persistent}` and a custom Minecraft world config
with `--world-config-file <path>`.

# Persistent/autonomous runs can also enforce a rolling spend ceiling:
#   --max-cost-rolling 0.01 --rolling-window 1h

python scripts/verify_simulation.py --name "local-llm-validation" --profile local-smoke
```

See [Minecraft Command Eval](docs/minecraft/command-eval.md) and the
[Minecraft runbook](docs/minecraft/runbook.md) for the current embodiment
workflow.

Operator spend-cap and kill-switch alerts use the same email pipeline. Set
`ALERT_EMAIL` for the operator inbox and `SPEND_ALERT_THRESHOLD_PCT` (default
`0.8`) to choose when cap-approach alerts fire.

## Testing

```bash
make test-backend
make test-memory-regression
npm --prefix frontend test
npm --prefix website test
npm --prefix website run test:e2e
```

Integration work should start with:

```bash
docker compose up -d
bash scripts/check-services.sh
```

The service check verifies Redis, PostgreSQL, pgvector, pg_trgm, and Langfuse.
Default ports are intentionally non-standard: Redis `6381`, PostgreSQL `5434`,
and Langfuse `3100`.

## Security And Safety Invariants

- Never commit `.env`, API keys, tokens, cookies, private keys, local world
  saves, generated videos, or runtime logs.
- Route application LLM calls through `core/llm_client.py` so cost tracking,
  Langfuse, model routing, and the governor can see them.
- Preserve Management review before TTS or public broadcast.
- Keep approval gates for external communications from agents.
- Keep the kill switch and cost governor load-bearing.
- Treat `specs/` as reference material. Update implementation docs or open a
  new discussion when reality changes.
- Keep Minecraft branding unofficial and include the disclaimer above in public
  surfaces that reference Minecraft.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Documentation

- [Docs index](docs/README.md)
- [Minecraft pivot summary](docs/decisions/0000-summary.md)
- [Minecraft licensing decision](docs/decisions/0007-licensing.md)
- [Research paper index](research/PAPER-INDEX.md)
- [Agent instructions](AGENTS.md)

## Contributing

Contributions are welcome, but this is a young research/product codebase. Start
with [CONTRIBUTING.md](CONTRIBUTING.md), pick small issues, and include the
verification you ran. For larger architectural changes, open an issue or
discussion before coding.

## License

MIT. See [LICENSE](LICENSE).

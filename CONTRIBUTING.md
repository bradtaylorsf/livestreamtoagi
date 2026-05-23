# Contributing

Thanks for taking a look at Livestream to AGI. The project is being opened
while it is still pre-alpha, so the most useful contributions are small,
well-scoped, and honest about what they verified.

## Before You Start

- Read `AGENTS.md` for repo-specific constraints.
- Check the current issue. Some older Phaser/replay/admin issues may be stale
  after the Minecraft pivot.
- For larger changes, open or comment on an issue before implementing.
- Never commit secrets, `.env`, local Minecraft worlds, generated videos, logs,
  or local clones.

## Development Setup

```bash
cp .env.example .env
uv venv .venv --python 3.13
uv pip install -e ".[dev]"

corepack enable
pnpm install
npm --prefix frontend install
npm --prefix website install

docker compose up -d
bash scripts/check-services.sh
.venv/bin/python -m db up
```

Run the app:

```bash
npm run dev
```

The backend runs on `8010`, the website on `4000`, Redis on `6381`, PostgreSQL
on `5434`, and Langfuse on `3100`.

## Tests And Checks

Run the smallest relevant set first, then broaden when touching shared code.

```bash
make test-backend
make test-memory-regression
npm --prefix frontend test
npm --prefix website test
npm --prefix website run test:e2e
```

For Python formatting and linting:

```bash
.venv/bin/ruff check core/ tools/
.venv/bin/ruff format --check core/ tools/
```

For integration work:

```bash
docker compose up -d
bash scripts/check-services.sh
```

## Safety Rules

- Application LLM calls should route through `core/llm_client.py` unless an
  issue explicitly documents a bounded exception.
- Agent utterances must pass through `core/management.py` before TTS or public
  broadcast.
- Do not weaken cost caps, kill-switch behavior, sandboxing, or approval gates.
- Do not edit `specs/` to make implementation look current. Use `docs/` or a
  new decision record for reality updates.
- Do not delete the Phaser/replay path just because it is legacy. Follow the
  retirement gates in the Minecraft pivot docs.
- Keep public Minecraft references unofficial and include the project
  disclaimer when adding public-facing Minecraft copy.

## Pull Requests

Good PRs include:

- A clear problem statement.
- The smallest code/docs change that solves it.
- Tests or a reason tests were not run.
- Screenshots for UI changes.
- Issue updates when the change makes an issue obsolete, duplicate, or complete.

Use conventional commits where practical: `feat:`, `fix:`, `docs:`, `test:`,
`refactor:`, or `chore:`.

## Issue Quality

An issue is ready for agent or human implementation when it has:

- Current product context.
- Specific affected files or modules when known.
- Acceptance criteria that can be tested.
- Verification commands.
- Explicit dependencies and launch gates.
- A note if it touches Management review, LLM routing, cost controls,
  kill-switch behavior, sandboxing, external communications, or Minecraft
  branding/legal posture.

If an issue references the old office/Phaser world, MP4 replay path, or
simulation-first product surface, triage whether it should be closed,
rewritten for Minecraft, or kept as a dependency of the formal retirement epic.

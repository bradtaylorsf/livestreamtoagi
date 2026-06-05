# Artifact Policy

This repository should keep source, fixtures, and durable documentation easy to
find. Runtime output belongs in predictable ignored locations unless a file is
explicitly promoted as a fixture, report, or decision record.

## Durable Source

Commit files that are needed to build, test, document, or operate the project:

- application source under `core/`, `tools/`, `frontend/`, `website/`, and `scripts/`
- agent configs under `agents/`
- database migrations under `db/`
- current docs under `docs/`
- historical/reference specs under `specs/`
- intentional fixtures under `tests/`, `evals/`, `scenarios/`, and top-level `snapshots/*.json`

## Ignored Runtime Output

Use these locations for generated artifacts:

- `logs/` for local runs, soak runs, livestream logs, and Minecraft evidence
- `artifacts/` for ad hoc eval reports or model-comparison outputs
- `videos/` for rendered media
- `snapshots/headless/<timestamp>*/`, `snapshots/cli-builds/`, and `snapshots/smoke-propose-new-building/` for generated sim/build outputs
- `minecraft-server/`, `minecraft-server-easy/`, and `minecraft-server-easy-*/` for local Paper server state and shakeout copies
- `.alpha-loop/sessions/`, `.alpha-loop/traces/`, and `.alpha-loop/codex-logs/` for managed loop/session output
- `.worktrees/` for temporary local worktrees
- `.claude/` and `.codex/` for local agent/harness state; use tracked
  `AGENTS.md` and `.agents/skills/` for repo-shared agent instructions
- `graphify-out/` and `graphify-corpus/` for local graph analysis runs

Do not add one-off timestamped run folders at the repository root. Put them
under an ignored runtime directory with a clear prefix.

## Promotion Rule

Promote a generated artifact into the tracked tree only when it is intentionally
used as a fixture, accepted report, or decision record. When promoting one:

- move it to the smallest relevant tracked area, such as `tests/fixtures/`,
  `docs/`, `evals/`, `scenarios/`, or top-level fixture snapshots
- remove volatile timestamps, local paths, API tokens, and machine-specific data
- add or update tests/docs that explain why the artifact is durable

## Graphify

Track `.graphifyignore` so graph builds skip generated/runtime trees by default.
Keep `graphify-out/`, `graphify-corpus/`, `.graphify_python`, and transient
`.graphify_*.json`/`.graphify_*.txt` files local.
The ignore list should mirror the runtime-output categories above, including
local Minecraft server worlds, Mindcraft working clones, generated snapshots,
videos, build output, virtualenvs, and node dependency folders.

When graph output becomes a reviewed architecture artifact, copy only the
specific report or graph snapshot into `docs/` with a date and purpose.

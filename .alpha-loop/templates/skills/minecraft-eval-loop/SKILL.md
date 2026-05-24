---
name: minecraft-eval-loop
description: Run the recursive E17/E18 Minecraft command eval loop in livestreamtoagi. Use this skill whenever the user asks to validate Minecraft command autonomy, run E17/E18 evals, promote passing prompts to live replay, test larger collaborative Minecraft jobs, diagnose command/build failures before full soaks, or recursively fix Minecraft eval failures.
---

# Minecraft Eval Loop

Use this skill for fast, evidence-driven Minecraft autonomy validation before a full Director smoke or soak. It turns E17 text-command evals and E18 replay/live evals into a repeatable loop: generate accepted commands, replay them, stress multi-agent timing, inspect artifacts, make the smallest fix, rerun, and report the remaining risk.

For full Minecraft smokes/soaks after this preflight passes, use `minecraft-soak-triage`.

## Ground Rules

- Work from the repo root.
- Inspect `.env` only by key presence; never print secrets.
- Do not commit `.env`, `logs/`, screenshots, traces, generated eval artifacts, generated soak artifacts, or temporary Minecraft/Mindcraft runtime files.
- Prefer `pnpm mc:eval:*` scripts and focused pytest targets over ad hoc commands.
- Keep each loop bounded. Default to 3 fix/rerun iterations unless the user asks for more.
- Before editing, classify the failure and make the smallest code, prompt, fixture, or config change that addresses the observed evidence.

## Preflight

Run:

```bash
git status --short
pnpm mc:eval:commands --help
pnpm mc:eval:live --help
pnpm mc:eval:replay --help
```

If the task involves live Minecraft instead of dry-run only, also check services:

```bash
docker compose up -d --wait
bash scripts/check-services.sh
```

Check `.env` without values:

```bash
python - <<'PY'
from pathlib import Path
path = Path(".env")
if not path.exists():
    print(".env present: no")
else:
    keys = []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.append(line.split("=", 1)[0].removeprefix("export ").strip())
    print(f".env present: yes; key_count={len(keys)}")
PY
```

## Core Dry-Run Loop

Use a temp or ignored run directory:

```bash
RUN_DIR=/tmp/lta-mc-collab-eval-$(date -u +%Y%m%dT%H%M%SZ)
```

Generate E17 accepted prompts:

```bash
pnpm mc:eval:commands --dry-run \
  --report-dir "$RUN_DIR/e17-text" \
  --passing-prompts "$RUN_DIR/passing-prompts.ndjson" \
  --json \
  --output "$RUN_DIR/e17-text/summary.json"
```

Replay accepted prompts through E18:

```bash
pnpm mc:eval:replay \
  --dataset "$RUN_DIR/passing-prompts.ndjson" \
  --dry-run \
  --report-dir "$RUN_DIR/e18-replay-dry" \
  --traces-dir traces \
  --verbose
```

Stress multi-agent timing. Use at least 5 cases for at least one agent; the deterministic fake bridge only exercises Director fanout and command-loss classes on later cases.

```bash
pnpm mc:eval:live --multi-agent \
  --agents rex:planAndBuild:5,vera:nearbyBlocks:5,pixel:inventory:5,fork:buildFromPlan:5 \
  --director-fanout 5 \
  --tick-ms 250 \
  --stagger-ms 50 \
  --dry-run \
  --report-dir "$RUN_DIR/e18-multi-agent-dry" \
  --traces-dir traces
```

Expected dry-run evidence:

- E17 produces `passing-prompts.ndjson`.
- E18 replay has no malformed/rejected/error outcomes for accepted prompts.
- Multi-agent timing reports nonzero coverage for `queue_contention`, `self_interruption`, `director_fanout`, and `command_loss`.
- Multi-agent timing failures are not automatically blockers; they are intentionally injected in dry-run mode to verify detection/reporting.

## Live Promotion

Promote to live only after dry-run artifacts are sane and the local bridge/dev stack is healthy. Use the narrowest live command that answers the question:

```bash
MC_EVAL_LIVE_ENABLED=1 pnpm mc:eval:replay \
  --dataset "$RUN_DIR/passing-prompts.ndjson" \
  --command !planAndBuild \
  --report-dir "$RUN_DIR/e18-replay-live-planbuild" \
  --traces-dir traces \
  --verbose
```

If the user asks for a full collaborative Minecraft smoke or soak after this succeeds, switch to `minecraft-soak-triage`.

## Artifact Review

Inspect these files first:

- `e17-text/summary.json`
- `e17-text/scores.json`
- `e17-text/report.md`
- `passing-prompts.ndjson`
- `e18-replay-dry/summary.json`
- `e18-replay-dry/live-scores.json`
- `e18-replay-dry/live-report.md`
- `e18-replay-dry/timeline.ndjson`
- `e18-multi-agent-dry/summary.json`
- `e18-multi-agent-dry/live-scores.json`
- `e18-multi-agent-dry/live-report.md`

Read `references/artifact-checklist.md` when you need compact JSON fields and pass/fail checks.

## Failure Classes

Classify before fixing:

- **Parser/schema**: malformed commands, wrong arg counts/types, command aliases not resolved, unavailable command surface.
- **Prompt/model**: chat-only when command required, unsafe command, invented command, weak role instructions, unavailable material requests.
- **Replay bridge**: accepted E17 command fails in E18 fake replay due translation or command family mismatch.
- **Live bridge/world**: real bridge URL, server state, inventory, pathing, spawn, collision, action timeout, or missing telemetry.
- **Build quality**: command succeeds but intended-vs-actual blocks are too small, incoherent, duplicated, or not visually plausible.
- **Coordination**: queue contention, self-interruption, Director fanout, command loss, role/owner drift, support agents placing random blocks.
- **Environment**: missing `.env`, unhealthy Docker services, missing local model, unavailable Minecraft server, dirty runtime process.

## Fix And Rerun

For each iteration:

1. Name the failure class and evidence file.
2. Patch the smallest relevant area.
3. Run focused tests for the touched area.
4. Rerun the failing eval command.
5. Stop if the same failure repeats after 3 iterations, if live services are unavailable, or if a fix would require broad design work.

Useful focused checks:

```bash
pnpm verify:mc-eval-commands
.venv/bin/pytest tests/backend/test_mc_eval_replay_cli.py tests/backend/test_mc_eval_live_runner.py -v
.venv/bin/pytest tests/backend/test_mc_skill_card_registry.py tests/backend/test_mc_scenario_fixtures.py -v
```

## Closure Report

End with:

- run directory
- pass/fail status for E17, E18 replay, E18 multi-agent timing, and any live promotion
- exact metrics: cases, pass counts, outcome counts, timing failure counts
- changed files
- tests run
- remaining risks
- recommended next issue or epic

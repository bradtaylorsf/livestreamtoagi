# Open Settlement Smoke (E21-1)

Short open-ended Minecraft collaboration smoke that answers a single
question: can the 8-agent roster choose a starter-settlement objective
together, delegate distinct roles, take an embodied world-changing
action, and review/repair the result — without being handed a fixed
cabin blueprint?

Owned by epic [#820](https://github.com/bradtaylorsf/livestreamtoagi/issues/820)
and tracked under issue
[#821](https://github.com/bradtaylorsf/livestreamtoagi/issues/821).

## What it produces

A successful run writes the following under
`snapshots/headless/<timestamp>_open_settlement_smoke/`:

- `decision_log.jsonl` — the raw event stream used by the classifier.
- `eval_scores.json` — standard headless-scorer category scores.
- `smoke-report.json` — machine-readable smoke classification.
- `smoke-report.md` — human-readable classification, evidence refs, and
  follow-up failure class.

## Preflight

The wrapper calls `scripts/minecraft/eval_commands.py --dry-run` first
(per issue [#818](https://github.com/anthropics/livestreamtoagi/issues/818)).
If preflight exits non-zero the smoke aborts before launching a sim.

## Launch

```bash
docker compose up -d
bash scripts/check-services.sh

# 25-minute open settlement smoke (no fixed blueprint).
bash scripts/minecraft/run_open_settlement_smoke.sh
```

Tunable env vars: `SCENARIO`, `OUTPUT_DIR`, `MAX_COST`, `DURATION_HOURS`,
`MC_SIM_BUILD_MODE`, `SOAK_PLAN_BUILD_BOTS`, `PYTHON_BIN`.

## Interpreting the classification

The classifier (`core/eval/settlement_smoke_signals.py`) emits one of:

| Classification        | What it means                                                                       | Gating |
|-----------------------|-------------------------------------------------------------------------------------|--------|
| `collaborative`       | Shared objective + ≥2 distinct roles + ≥1 world-changing action + review/repair turn| pass   |
| `partial`             | Objective and role assignments present, but no world-changing action.               | pass   |
| `idle_chat`           | Utterances only, zero successful tool intents.                                      | **fail** |
| `scattered`           | World-changing actions without consensus on what to build.                          | **fail** |
| `command_loop_churn`  | Same blocked tool call repeated ≥4 times by a single agent.                         | **fail** |

`build_settlement_smoke_report.py` exits non-zero on any **fail** row,
so CI or the alpha-loop can short-circuit follow-up runs.

## Filing follow-ups

When the outcome is not `collaborative`, lead the follow-up issue title
with the `failure_class` from `smoke-report.md`. Useful evidence files
to link in the issue body:

- `smoke-report.md` (renders inline on GitHub)
- `decision_log.jsonl` (raw)
- `eval_scores.json` (signal sub-scores for social_dynamics, world_evolution, agency)

## Out of scope

Two-week endurance, full economy/war mechanics, or any fixed cabin
prompt — those live in sibling issues `#822`–`#826`.

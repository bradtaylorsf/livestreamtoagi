# Minecraft Eval Artifact Checklist

Use this reference when reviewing `minecraft-eval-loop` outputs.

## E17 Text Eval

Files:

- `summary.json`: provider/model/request metadata and collected outputs.
- `scores.json`: outcome counts and accepted/rejected classifications.
- `generations.ndjson`: raw scenario/result pairs.
- `passing-prompts.ndjson`: accepted command prompts for E18 replay.
- `report.md`: human-readable summary.

Checks:

- `request_count` equals the intended scenario count.
- `scores.json.outcome_counts.accepted_command > 0` for command scenarios.
- `passing-prompts.ndjson` contains only accepted commands.
- No secrets appear in output.

## E18 Replay

Files:

- `summary.json`
- `live-scores.json`
- `live-generations.ndjson`
- `live-actions.ndjson`
- `timeline.ndjson`
- `live-report.md`
- optional `traces/*.json`

Checks:

- Accepted E17 commands do not become malformed or rejected in replay.
- `outcome_counts.error == 0`.
- World constraints are categorized rather than hidden.
- Build cases include block mutation detail when available.

## E18 Multi-Agent Timing

Run with at least 5 cases for at least one agent if the goal is full synthetic timing coverage.

Expected dry-run signal fields:

- `timing_summary.cases > 0`
- `timing_summary.agents > 1`
- `timing_summary.failure_classes.queue_contention > 0`
- `timing_summary.failure_classes.self_interruption > 0`
- `timing_summary.failure_classes.director_fanout > 0`
- `timing_summary.failure_classes.command_loss > 0`

The dry-run intentionally injects timing failures. Treat the run as passing if detection/reporting is correct, not if every case succeeds.

## Live Promotion

Only run with `MC_EVAL_LIVE_ENABLED=1` after dry-run passes and services are healthy.

Checks:

- live bridge URL is explicit and local.
- report directory includes live action events and timeline.
- live failures are attributed to parser/schema, world constraint, timeout, bridge, or coordination class.
- generated artifacts stay out of git.


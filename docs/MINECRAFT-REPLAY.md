# Minecraft Replay (E22-8)

`scripts/replay_in_minecraft.py` replays a headless sim folder visually
inside Minecraft via the live command bridge. It is the visualization half
of the headless-sim / Minecraft pipeline (E22): headless runs produce a
`decision_log.jsonl` and `build_intents.jsonl`; the macro compiler
(E22-7) lowers each `BuildPlan` to a `BuildScript`; this CLI streams the
recorded chat, agent pose, and scripted builds back into a live world and
takes screenshots at declared milestones.

## Quickstart

```bash
# Deterministic local smoke (uses the fake bridge; no Minecraft required)
python scripts/replay_in_minecraft.py \
    --sim-folder runs/headless/abc-123 \
    --dry-run

# Real live replay (requires MC_EVAL_LIVE_ENABLED=1 + bridge env vars)
python scripts/replay_in_minecraft.py \
    --sim-folder runs/headless/abc-123 \
    --speed-multiplier 4.0 \
    --screenshot-milestones build_start,build_complete,hourly \
    --output-dir runs/headless/abc-123/replay/manual-run
```

Outputs:

- `<output-dir>/screenshots/*.png`
- `<output-dir>/replay_manifest.json`

## Flags

| Flag                       | Default                                | Meaning                                       |
| -------------------------- | -------------------------------------- | --------------------------------------------- |
| `--sim-folder`             | (required)                             | Path to a headless sim folder                 |
| `--speed-multiplier`       | `1.0`                                  | >1 plays faster; <1 plays slower              |
| `--screenshot-milestones`  | all five                               | CSV from the milestone vocabulary below       |
| `--profile`                | the live-eval default profile          | Minecraft live eval profile                   |
| `--output-dir`             | `<sim-folder>/replay/<timestamp>`      | Where screenshots + manifest land             |
| `--dry-run`                | off (auto-on without bridge env)       | Force the deterministic fake bridge           |

## Milestones

The CLI captures screenshots at these instants by default:

- **`build_start`** — immediately before a `propose_build` script
  executes.
- **`build_complete`** — immediately after the script's commands have
  been issued.
- **`hourly`** — once per simulated hour, anchored on the sim_time clock.
- **`conflict`** — when a `relationship_delta` row drops sentiment by
  `>= 0.10`.
- **`alliance_form`** — the first `alliance_delta` row that adds members
  to an empty alliance.

Pass `--screenshot-milestones` to subset these (e.g.
`build_start,build_complete` for a build-only montage).

## Idempotency

Replay is deterministic given the **same sim folder + clean world**:

- Events are ordered by `(sim_time, tick, row_idx)`, then a stable
  per-event-type priority — so screenshots that share a tick with their
  build-script event always fire in the same order.
- Screenshot filenames are `<milestone>_<row_idx:06d>.png`, keyed off the
  decision-log row so re-running overwrites the same files.
- `<output-dir>/replay_manifest.json` is overwritten on rerun.

To truly match the previous Minecraft state, reset the world between
runs (the CLI does not auto-reset). On the fake/dry-run bridge the
"world" is in-memory, so idempotency is trivially satisfied.

## Pause / resume

On Unix, send `SIGUSR1` to pause the replay and `SIGUSR2` to resume.
The CLI is otherwise non-interactive.

```bash
kill -SIGUSR1 <pid>   # pause
kill -SIGUSR2 <pid>   # resume
```

## Bridge requirements

The CLI uses the same bridge contract as
`core/minecraft/eval/live_cli.py`. To use the **real** bridge:

```
MC_EVAL_LIVE_ENABLED=1
MC_EVAL_LIVE_BRIDGE_URL=https://...
MINECRAFT_BRIDGE_TOKEN=...
```

Screenshots are requested via `!screenshot <label>`. Bridges that don't
support the verb still get a placeholder PNG written to disk and a
`status: "unsupported"` row in the manifest — the artifact set stays
complete so downstream consumers don't break.

## Programmatic use

```python
from core.minecraft.replay import ReplayScheduler

scheduler = ReplayScheduler(sim_folder=Path("runs/headless/abc-123"))
for event in scheduler.events():
    ...  # event is ChatEvent | PoseEvent | ExecuteBuildScriptEvent | ScreenshotEvent
```

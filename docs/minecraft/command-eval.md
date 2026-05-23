# Minecraft Command Eval

The command eval harness runs text-only Minecraft action prompts against a local
or hosted model. It does not launch Minecraft, Mindcraft bots, Mineflayer, or
the bridge. Use it to catch malformed commands, disallowed tools, and obvious
semantic misses before a live soak run.

## Quickstart

```bash
# Deterministic smoke: resolves fixtures and command schemas, no provider calls.
pnpm mc:eval:commands:smoke

# Render prompts and score deterministic fake responses.
pnpm mc:eval:commands:dry-run

# Run one command family repeatedly with deterministic action telemetry.
pnpm mc:eval:live --command move --cases 20 --verbose --dry-run

# Write live eval artifacts plus cheap position traces to a temp report dir.
pnpm mc:eval:live:report

# Simulate a small multi-agent timing/action-queue cohort.
pnpm mc:eval:live --multi-agent --agents vera:move:5,rex:placeHere:3 --tick-ms 200 --stagger-ms 50 --director-fanout 2 --dry-run

# Replay E17 accepted commands in the flat eval world with a fake bridge.
pnpm mc:eval:replay:smoke

# Run the focused regression suite used by CI.
pnpm verify:mc-eval-commands
```

`pnpm mc:eval:commands:smoke` maps to
`pnpm mc:eval:commands --dry-run --list-only`, mirroring the low-risk
`pnpm llm:local --list-only` convention for local checks.

## Local Provider

Local runs use the same OpenAI-compatible configuration names as the local
simulation tooling:

| Env key | Required | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` | No | Use `lmstudio`, `local`, or `openai-compatible`. Defaults to `lmstudio`. |
| `LOCAL_LLM_BASE_URL` | No | Defaults to `http://localhost:1234/v1`. Legacy `LLM_BASE_URL` is also accepted. |
| `LOCAL_LLM_API_KEY` | No | Defaults to the non-secret LM Studio value `lm-studio`. Legacy `LLM_API_KEY` is also accepted. |
| `LOCAL_LLM_MODEL` | Yes for live local calls | Model id served by LM Studio or the compatible local server. `--dry-run` can omit it. |

Example:

```bash
pnpm llm:local --list-only

LLM_PROVIDER=lmstudio \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
pnpm mc:eval:commands --provider lmstudio --report-dir artifacts/mc-eval/local-qwen
```

## OpenRouter

OpenRouter runs require an API key and an explicit model id. The key is only
used for provider construction and is never printed in CLI output or artifacts.

```bash
OPENROUTER_API_KEY=<key> \
pnpm mc:eval:commands \
  --provider openrouter \
  --model openai/gpt-4o-mini \
  --report-dir artifacts/mc-eval/openrouter-gpt-4o-mini
```

`OPENROUTER_BASE_URL` may override the default OpenRouter API base URL when
needed.

## CLI Flags

| Flag | Purpose |
| --- | --- |
| `--scenarios <path>` | Scenario JSON file or directory. Defaults to `tests/backend/fixtures/mc_scenarios/valid`. |
| `--provider <name>` | `lmstudio`, `openai-compatible`, or `openrouter`. |
| `--model <id>` | Model id. Required for OpenRouter and live local calls. |
| `--base-url <url>` | Override provider base URL. |
| `--api-key <key>` | Override provider key. Never printed. |
| `--timeout <seconds>` | Provider request timeout. |
| `--max-tokens <count>` | Completion token cap. |
| `--temperature <value>` | Sampling temperature. |
| `--limit <count>` | Evaluate only the first N resolved scenarios. |
| `--dry-run` | Use a deterministic fake provider response and skip network I/O. |
| `--list-only` | Print provider/model, scenario ids, and command schema summary, then exit before provider client construction. |
| `--json` | Print machine-readable summary or list-only payload. |
| `--output <path>` | Write the raw run summary, or list-only payload, as JSON. |
| `--report-dir <dir>` | Write scored run artifacts. |
| `--passing-prompts <path>` | Write accepted command prompts as NDJSON. |
| `--compare <scores.json>` | Include an existing scores file in `comparison.md`. May be repeated and requires `--report-dir`. |

## Live Eval Profile (E18)

The live command eval runner uses a separate deterministic profile named
`flat-eval`. It points at `scripts/minecraft/world-flat-eval.config`, writes a
fresh server under `minecraft-server-flat-eval/`, and targets
`127.0.0.1:25568` so it does not collide with the normal server (`25565`) or
easy sim server (`25566`).

The shipped world config is a flat, seeded, structure-free world:
`LEVEL_TYPE=minecraft:flat`, `LEVEL_SEED=livestreamtoagi-flat-eval-v1`, and
`GENERATE_STRUCTURES=false`. The seed must stay non-empty so live failures can
be attributed to command/action behavior instead of terrain randomness.

Supported overrides for the future live runner are:

| Env key | Purpose |
| --- | --- |
| `MC_EVAL_LIVE_PROFILE` | Built-in profile name. Defaults to `flat-eval`. |
| `MC_EVAL_LIVE_PORT` | Minecraft server port for the eval world. |
| `MC_EVAL_LIVE_SERVER_DIR` | Server directory for the eval world. Relative paths resolve from the repo root. |
| `MC_EVAL_LIVE_KEEP_RUNNING` | `true`/`false`; keep the server running after the eval job. Defaults to `false`. |

## Individual Live Command Smoke

`pnpm mc:eval:live` runs deterministic variations of one command family and
captures command input, action start/end events, outcome class, latency, and a
command-relevant final state. The default path uses `FakeBridgeClient` unless
`MC_EVAL_LIVE_ENABLED=1` is set, so CI and local smoke runs do not require
Minecraft, Mindcraft bots, or OpenRouter credentials.

```bash
pnpm mc:eval:live --command move --cases 20 --verbose --dry-run
pnpm mc:eval:live:smoke
pnpm mc:eval:live:report
pnpm verify:mc-eval-live-artifacts
pnpm verify:mc-eval-live
```

Supported command inputs include `move`, `placeHere`, `searchForBlock`,
`inventory`, `nearbyBlocks`, `planAndBuild`, and `buildFromPlan`. Skill-card
family ids such as `build` and `observe` resolve to a primary supported command.

Live mode is explicitly gated. To use a real command bridge, set
`MC_EVAL_LIVE_ENABLED=1`, `MC_EVAL_LIVE_BRIDGE_URL`, and
`MINECRAFT_BRIDGE_TOKEN`; otherwise pass `--dry-run` or leave live mode disabled.

Live smoke artifacts are intentionally lightweight:

| Artifact | Contents |
| --- | --- |
| `summary.json` | Full structured `LiveRunSummary` payload. |
| `cases.ndjson` | One `CaseResult` payload per generated command case. |
| `live-generations.ndjson` | One generated command per smoke case, or a single dataset replay reference containing the dataset path, filters, selected scenario ids, and command tokens. |
| `live-actions.ndjson` | One flattened action event per line with `case_id`, `agent_id`, `action_id`, `kind`, `ts_ms`, and payload. |
| `live-scores.json` | Compact scoring summary with pass/fail counts, outcome/category counts, behavior summaries, and per-case scoring fields. |
| `live-report.md` | Human-readable command, profile, outcome, artifact links, optional trace links, and per-case summary. |
| `timeline.ndjson` | Monitor-compatible subset using soak timeline event names such as `action.start`, `action.completed`, `action.result`, `error`, and `lifecycle`. |
| `report.md` | Legacy alias for `live-report.md`. |

Pass `--report-dir <dir>` to write the artifact set. Pass
`--traces-dir traces` with `--report-dir` to save cheap per-case position traces
under `<dir>/traces/<case_id>.json`; trace files are linked from
`live-report.md` when a final pose is available. Relative trace paths resolve
inside the report directory.

### Lifecycle Categories

Live eval also scores lifecycle behavior that text-only evals cannot prove:
`DEATH_LOOP`, `SAFE_SPAWN`, and `STUCK_UNSTUCK`. These categories cover
repeated deaths, unsafe or recovered respawns, stuck states, unstuck attempts,
and unstuck success or failure. The structured summary includes
`lifecycle_summary`, and each lifecycle-aware case may include a `lifecycle`
object with `death_count`, `death_loop`, `respawns`, `safe_spawn`,
`unsafe_spawn_count`, `stuck`, `stuck_events`, `unstuck_attempts`,
`unstuck_succeeded`, `unstuck_failed`, and `last_pose`. The markdown report
adds a `## Lifecycle` per-case section with the same core outcomes.

Bridge adapters can drive these fields with mocked or live `action_events`
using kinds such as `death`, `respawn`, `stuck`, `unstuck_attempt`,
`unstuck_success`, or `unstuck_failure`. Equivalent final-state keys are also
accepted, including `death_count`, `deaths`, `death_loop`, `respawns`,
`spawn_safe`, `safe_spawn`, `unsafe_spawn_count`, `spawn.safe`,
`stuck_events`, `unstuck_attempts`, `unstuck_succeeded`, and
`unstuck_failed`. Reason/message fields containing markers such as `died`,
`death`, `safe spawn`, `unsafe spawn`, `spawn in lava`, `recovered`,
`still_stuck`, or `recovery_failed` are folded into the same lifecycle signals.

### Multi-agent Timing

`pnpm mc:eval:live --multi-agent` runs the live eval pipeline in a deterministic
multi-agent timing mode. It schedules a small cohort by `--tick-ms` and
`--stagger-ms`, attaches each case to an `agent_id`, and records queue/timing
signals without requiring live Minecraft in CI. The default dry-run path uses
`MultiAgentFakeBridge`, so mocked contention, self-interruption, Director
fanout, and command-loss outcomes are reproducible.

```bash
pnpm mc:eval:live \
  --multi-agent \
  --agents vera:move:5,rex:placeHere:3 \
  --tick-ms 200 \
  --stagger-ms 50 \
  --director-fanout 2 \
  --dry-run \
  --report-dir artifacts/mc-eval/multi-agent-timing
```

Agent specs use `agent_id:command:cases`, where `command` accepts the same
command families as individual live smoke. The structured summary includes
`timing_summary`, per-case `agent_id`, per-case `timing`, per-agent timing
metrics, and failure-class counts. Failure classes are `queue_contention`,
`self_interruption`, `director_fanout`, `command_loss`, `timing_drift`, and
`none`. The markdown report adds a `## Multi-agent timing` section with the
aggregate, per-agent metrics, and per-case failure classes.

## Dataset Replay

`pnpm mc:eval:replay` loads E17 `passing-prompts.ndjson` artifacts, filters
accepted command prompts, and replays the rebuilt command text through the same
live bridge surface used by `pnpm mc:eval:live`. It defaults to the deterministic
fake bridge unless `MC_EVAL_LIVE_ENABLED=1` is set.

```bash
pnpm mc:eval:replay \
  --dataset artifacts/mc-eval/openrouter-gpt-4o-mini/passing-prompts.ndjson \
  --command move \
  --limit 20 \
  --dry-run \
  --report-dir artifacts/mc-eval/replay-move

pnpm verify:mc-eval-replay
```

Replay flags:

| Flag | Purpose |
| --- | --- |
| `--dataset <path>` | Required path to an E17 `passing-prompts.ndjson` artifact. |
| `--command <token>` | Optional repeatable command filter; accepts `move` or `!move`. |
| `--scenario <id>` | Optional repeatable exact scenario id filter. |
| `--limit <count>` | Replay only the first N filtered prompts. |
| `--profile <name>` | Live eval profile. Defaults to `flat-eval`. |
| `--dry-run` | Force the deterministic fake bridge. |
| `--json` | Print machine-readable summary JSON. |
| `--output <path>` | Write the structured summary JSON. |
| `--report-dir <dir>` | Write `summary.json`, `cases.ndjson`, and `report.md`. |
| `--verbose` | Print per-action start/end telemetry. |

Replay outcomes keep parser/text rejection separate from live-world execution
failures: `malformed` and `rejected` indicate pre-execution rejection, while
`world_constraint`, `timeout`, and `error` indicate live execution failure modes.
The replay report also includes dataset counts and per-command outcome counts.

## Artifacts

When `--report-dir` is set, the harness writes:

| Artifact | Contents |
| --- | --- |
| `generations.ndjson` | One raw generation and scoring result per scenario. |
| `scores.json` | Structured aggregate metrics, outcome counts, token usage, and model metadata. |
| `report.md` | Human-readable run summary with malformed, rejected, chat-only, and valid command examples. |
| `comparison.md` | Written when `--compare` is provided; compares current and prior `scores.json` files. |

`--passing-prompts <path>` writes accepted command examples to a separate NDJSON
file for downstream prompt review. `--output <path>` writes the raw collection
summary or list-only metadata payload.

## Comparison Workflow

Use separate report directories per provider/model, then compare against the
prior `scores.json` artifacts with the same scenario set and seed.

```bash
pnpm mc:eval:commands \
  --provider lmstudio \
  --model local-qwen \
  --report-dir artifacts/mc-eval/local-qwen

OPENROUTER_API_KEY=<key> \
pnpm mc:eval:commands \
  --provider openrouter \
  --model openai/gpt-4o-mini \
  --report-dir artifacts/mc-eval/openrouter-gpt-4o-mini \
  --compare artifacts/mc-eval/local-qwen/scores.json
```

Repeat `--compare` to include more previous runs. The current run is always
included first in the generated `comparison.md`.

## CI And Regression Tests

CI should use fake provider responses only:

```bash
pnpm mc:eval:commands:smoke
pnpm verify:mc-eval-live-profile
pnpm verify:mc-eval-commands
```

The regression suite injects fake clients and dry-run responses, so it does not
require live LLMs, OpenRouter credentials, Minecraft, or Mindcraft bots.

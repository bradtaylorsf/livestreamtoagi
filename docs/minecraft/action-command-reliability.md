# Action-Command Reliability

Issue: #706 E8-10 - Action-command reliability gate for local LLM Minecraft sims

## Purpose

The E8 soak must prove that local LM Studio output becomes executable Minecraft
actions, not just stable processes. The reliability gate analyzes per-bot
Mindcraft logs after a local run and marks the run not acceptable when accepted
commands fail to execute or successful executions lack world-state evidence.

Artifacts are written next to the soak evidence:

- `action-reliability.json` for machine-readable metrics and threshold
  violations.
- `action-reliability.md` for operator review, with representative failed parse
  excerpts and verified successful action excerpts.

## Methodology

The analyzer is `scripts/minecraft/analyze_action_reliability.py`. It shares
`scripts/minecraft/bot_log_parser.py` with the timeline exporter so
`action-reliability.md`, `timeline.ndjson`, and `monitor.html` use the same
definition of generated text, accepted commands, and grouped execution results.

### Intent Detection

An intent is a bot utterance that promises or describes an action without a
`!command(` on the same line. The heuristic looks for chat-like lines such as
`Alpha: ...`, `[CHAT] ...`, `says: ...`, `assistant response: ...`, or
`LLM response: ...`, then requires both:

- A promise phrase: `I will`, `I'll`, `I'm going to`, `we will`, `let's`,
  `plan to`, `need to`, `try to`, `about to`, or similar.
- An action verb: `place`, `break`, `build`, `move`, `navigate`, `collect`,
  `search`, `mine`, `dig`, `craft`, `inspect`, `observe`, `inventory`,
  `scout`, `torch`, or related forms.

Instruction/configuration lines such as init prompts, profiles, settings,
available-command examples, and command syntax help are ignored so launch
prompts do not inflate the metric.

### Generated, Discarded, And Accepted Commands

The parser separates three command-bearing stages:

- `generated_commands`: command-shaped text in a model response.
- `discarded_commands`: commands in stale responses, such as responses dropped
  after `received new message while generating`.
- `emitted_commands`: accepted commands from parsed/full-response execution
  paths.

Only accepted commands become `action.intent` events or enter the execution
denominator. Command examples, memory summaries, raw `Generated response:`
lines, and stale discarded responses do not count as emitted executable
commands.

### Parse Results

Parser failures are normalized into these classes:

| Class | Matched examples |
| --- | --- |
| `empty_response` | `empty parsed response`, `blank LLM response` |
| `no_commands_found` | `No commands found`, `no command parsed` |
| `unknown_command` | `Command X does not exist`, `unknown command` |
| `argument_error` | wrong argument count/type, missing or invalid parameters |
| `parse_error` | `Could not parse`, `Error parsing`, malformed command/response |

`parse_success_rate` is computed from emitted commands minus parser failures
over parser successes plus failures. Empty responses and "no commands found"
therefore lower parse success even when no command marker was emitted.

### Execution Results

The analyzer groups each `Agent executed:` block until the next log boundary and
classifies the whole block. Success markers include `Placed ...`, `Broke ...`,
`You have reached`, `reached: distance_to_target`, `Found ...`,
`NEARBY_BLOCKS`, `CRAFTABLE_ITEMS`, and inventory observations. Failure classes
include `placement_blocked`, `missing_inventory`, `wrong_args`, `interrupted`,
`undefined_result`, `timeout`, `unreachable`, and `blocked`.

`command_execution_rate` is command executions divided by emitted commands.
Failures still count as executed commands because they prove the command reached
the action surface.

### Verification Results

A verified action is a successful grouped execution with corroborating
world-state evidence. Current accepted evidence includes:

- Block state deltas such as `before=air; after=oak_log`.
- Movement deltas such as `distance_to_target=...; delta=...`.
- Build/errand counters such as `steps_verified=1` or `verified=1`.
- Direct Mindcraft outcomes such as `Placed oak_log at (...)`,
  `Broke cobblestone at (...)`, `Found oak_log at (...)`, or `You have reached`.

Expected safety interruptions are terminal failures, not process crashes.
Examples include `interrupted: PathStopped: Path was stopped before it could be
completed` when `mode:unstuck` stops an in-flight placement or pathfinder goal.
These lines count as executed commands with failure outcomes, while the
verified-success denominator remains limited to successful world-state changes.
The current launchers patch interrupted non-timeout actions to return a
structured `interrupted: ...` result instead of `undefined`.

`verified_success_rate` is verified successful actions divided by execution
successes. A command can execute and still fail this gate if the log only says
the agent tried something without corroborating world-state evidence.

## Threshold Defaults

Defaults are intentionally strict enough to catch local-model command collapse
but lenient enough for early embodied behavior:

| Env / CLI | Default | Rationale |
| --- | --- | --- |
| `SOAK_MIN_INTENT_TO_COMMAND_RATIO` / `--min-intent-to-command` | `0.6` | Allows some narration, fails repeated promises without commands. |
| `SOAK_MIN_PARSE_SUCCESS` / `--min-parse-success` | `0.8` | Parser failures should be rare during acceptance soaks. |
| `SOAK_MIN_EXECUTION_RATE` / `--min-execution-rate` | `0.7` | Most parsed commands should reach the action surface. |
| `SOAK_MIN_VERIFIED_SUCCESS` / `--min-verified-success` | `0.5` | At least half of execution successes need world-state corroboration. |
| `SOAK_RELIABILITY_MIN_INTENTS` / `--min-intents` | `5` | Avoids failing agents that had too little action opportunity. |
| `SOAK_RELIABILITY_FAIL_ON_VIOLATION` | `1` | Acceptance runs fail closed by default. |

Operators may loosen thresholds for exploratory smoke tests, but E8 acceptance
evidence should record the configured values.

## Soak Integration

`scripts/minecraft/soak.sh` runs the analyzer after the timed bot loop, after
the cost ledger is written, and before final acceptance. The soak summary gains
an `Action-command reliability` block with per-agent metrics and any threshold
violations.

When `SOAK_RELIABILITY_FAIL_ON_VIOLATION=1`, any threshold violation for an
agent with at least `SOAK_RELIABILITY_MIN_INTENTS` intended action events exits
nonzero:

```bash
SOAK_MIN_PARSE_SUCCESS=0.9 scripts/minecraft/soak.sh --duration-hours 2
```

For diagnostics-only runs, keep the artifacts but do not fail the shell command:

```bash
SOAK_RELIABILITY_FAIL_ON_VIOLATION=0 scripts/minecraft/soak.sh --duration-hours 0.25
```

The local wrapper forwards optional `MC_SIM_*` threshold variables into the soak
environment:

```bash
MC_SIM_MIN_PARSE_SUCCESS=0.9 pnpm mc:sim:smoke
```

## Standalone Re-Run

Run the analyzer against an existing evidence directory:

```bash
python3 scripts/minecraft/analyze_action_reliability.py \
  --run-dir logs/soak/<timestamp> \
  --min-intent-to-command 0.6 \
  --min-parse-success 0.8 \
  --min-execution-rate 0.7 \
  --min-verified-success 0.5 \
  --min-intents 5
```

The command exits `0` when acceptable, `1` when thresholds are violated, and `2`
for analyzer/setup errors such as a missing `bots/` directory.

## Caveats

- This is a reliability gate over the current action surface, not a full
  behavior-quality score.
- The heuristics intentionally ignore prompt/config examples, but unusual log
  formats can still undercount or overcount. Representative examples in the
  Markdown artifact should be reviewed before accepting a marginal run.
- Larger evaluation/reporting belongs to E10; this gate only answers whether
  local-model intent is becoming parsed, executed, and verified Minecraft
  action.

## Live Run Evidence Template

Paste this into the issue or PR with the completed local LM Studio evidence:

| Field | Value |
| --- | --- |
| Run directory | `logs/soak/<timestamp>/` |
| Analyzer command |  |
| Thresholds | intent `0.6`; parse `0.8`; execution `0.7`; verified `0.5`; min intents `5` |
| Overall reliability status | PASS / NOT ACCEPTABLE |
| Agents below threshold |  |
| Aggregate intent-to-command ratio |  |
| Aggregate parse success rate |  |
| Aggregate command execution rate |  |
| Aggregate verified success rate |  |
| Top parser failure classes |  |
| Representative failed parses |  |
| Representative verified successes |  |
| Evidence artifacts | `action-reliability.json`, `action-reliability.md`, `timeline.ndjson`, `timeline-totals.json`, `monitor.html`, `summary.txt` |

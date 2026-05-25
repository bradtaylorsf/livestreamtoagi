# Run Modes

The run-spec schema supports two execution modes:

- `persistent`: the 24/7 livestream mode. Use it when the same durable world and
  active simulation should survive process restarts.
- `experimental`: a bounded comparison mode. Use it when you need fresh starting
  conditions, a defined stop, and reports that can be compared side by side.

Use [persistent 24/7 runs](run-modes/persistent.md) for the live channel,
[experimental short runs](run-modes/experimental.md) for A/B starting-condition
tests, and [blank-slate embodied runs](run-modes/blank-slate-embodied.md) for
memory seed details that apply to either mode.

## Management Policy

Run specs may set `management_policy` to choose how Management reviews agent
speech for that run:

- `off`: approve speech without filter calls, while emitting an audit event.
- `shadow`: run the filter, approve speech, and record would-be interventions.
- `enforce`: run the filter and apply warnings, replacements, mutes, and the
  kill-switch path when rules require it.

Persistent livestream runs default to `enforce`. Experimental runs default to
`shadow`. The lower-level local Minecraft wrappers default to `off` through
`MC_SIM_MANAGEMENT_POLICY=off` so dry local collaboration can run without paid
filter calls; set `MC_SIM_MANAGEMENT_POLICY=shadow` or `enforce` when collecting
safety evidence. `MC_SIM_DISABLE_MANAGEMENT=1` is still accepted as a deprecated
alias for `off`.

Public or persistent livestream deployments should keep `enforce` unless a
human-controlled run config explicitly overrides it. Management remains
out-of-band: it is never generated as a Mindcraft bot profile.

## Local LM Studio

All Minecraft-pivot run-mode validation should use LM Studio or another local
OpenAI-compatible server instead of paid OpenRouter spend.

```bash
pnpm llm:local --list-only
```

Then run simulations with:

```bash
LLM_PROVIDER=lmstudio \
LOCAL_LLM_BASE_URL=http://localhost:1234/v1 \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
EMBEDDING_PROVIDER=deterministic \
.venv/bin/python scripts/run_simulation.py ...
```

Set `LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id>` when the run exercises
building, reflection, dream, or Minecraft code-generation paths and a stronger
local model is loaded.

## Embodied Supervisor

Minecraft runs that use `--conversation-mode embodied` or `--conversation-mode
director_v2` are owned by the embodied supervisor in `scripts/run_simulation.py`.
The supervisor creates or attaches to one simulation row, derives one `run_id`,
exports `LTAG_RUN_ID`, `LTAG_SIMULATION_ID`, and `MC_RUN_DIR` to the Minecraft
harness, polls kill/cost hooks, and runs eval/report hooks when the run ends.

Experimental embodied run:

```bash
.venv/bin/python scripts/run_simulation.py \
  --name "embodied-short-a" \
  --conversation-mode embodied \
  --run-mode experimental \
  --duration-hours 0.25 \
  --max-cost 0.01
```

Persistent embodied run:

```bash
.venv/bin/python scripts/run_simulation.py \
  --name "live-embodied" \
  --conversation-mode embodied \
  --persistent \
  --max-cost-rolling 5 \
  --rolling-window 1h
```

`scripts/minecraft/run-local-sim.sh` and `scripts/minecraft/soak.sh` remain
lower-level diagnostics. The supervisor delegates Minecraft launch work to the
soak harness after it owns lifecycle state.

Embodied local wrappers export `MC_SIM_SHARED_STATE_ENABLED=1` by default. That
adds a run-scoped, advisory blackboard to Mindcraft prompt context so agents can
share the active group goal, build site, resource reports, claims, danger/stuck
reports, verified recent actions, and open next steps without turning the run
into a fixed script.

## Distress And Rescue

Embodied runs write structured distress reports into the same run-scoped
blackboard. Supported danger kinds are `stuck`, `drowning`, `trapped`,
`low_health`, `death`, and `repeated_failure`. A report stays unresolved until a
rescuer marks it `resolved`, `escaped`, or `teleported`; unresolved distress is
included in acceptance reports and fails soak acceptance.

`RESCUE_MODE` controls how aggressive the rescue fallback may be:

| Mode | Use | Allowed rescue behavior |
| --- | --- | --- |
| `easy` | Local/easy server smoke runs. | Navigate to the target first, then allow operator `/tp` fallback through `!rescue` when normal recovery fails. |
| `standard` | Default embodied diagnostics. | Navigate/guide and report failure; no operator teleport fallback. |
| `production` | Public or persistent worlds. | Non-destructive assist only unless an operator explicitly intervenes outside the bot loop. |

The local easy-spawn helper defaults to `RESCUE_MODE=easy`; production launch
configs should set `RESCUE_MODE=production` and keep destructive clearing or
teleport rescue as operator-only actions.

## Choose A Mode

| Area | Persistent | Experimental |
| --- | --- | --- |
| Use when | Running the live show or testing restartable 24/7 operation. | Comparing starting-condition variants over short, repeatable runs. |
| Stop conditions | Kill switch, process cancel, or rolling cost cap. No duration. | Seed-file phases, `--duration`, `experimental_goal`, cancel, kill switch, or cost cap. |
| World | Durable Minecraft world. `persistent: true` is forced. | Fresh Minecraft world. `persistent: false` is forced and durable world IDs are rejected. |
| Cost cap | Requires `--max-cost-rolling` and `--rolling-window`. | Uses normal `--max-cost`; keep caps small for local experiments. |
| Management policy | Defaults to `enforce`; override only through operator-controlled config. | Defaults to `shadow`; local Minecraft wrappers default to `off` unless `MC_SIM_MANAGEMENT_POLICY` is set. |
| Memory seed | Can inherit the live namespace only through explicit memory seed config. | Supports `none`, `custom`, or `inherit`; the setting is recorded for comparison. |
| Example spec | `scenarios/persistent_24x7.yaml` | `scenarios/experimental_short_run.yaml` |
| Example command | `.venv/bin/python scripts/run_simulation.py --persistent --seed-file scenarios/persistent_24x7.yaml --max-cost-rolling 5 --rolling-window 1h` | `.venv/bin/python scripts/run_simulation.py --name "experimental-short-a" --seed-file scenarios/experimental_short_run.yaml --run-mode experimental --max-cost 0.01` |

## Eval Suite Mapping

Persistent 24/7 runs should use the `persistent` eval suite. It keeps the live
show qualities front and center: entertainment, safety, dialogue quality,
social dynamics, agency, internal state, and errors.

Experimental runs should use the `experimental` eval suite. It emphasizes
comparison signals that are meaningful across bounded starting-condition tests:
build verification, creativity, world evolution, productivity, simulation
narrative, and agency.

Run either suite against a completed simulation ID:

```bash
.venv/bin/python scripts/run_eval.py --simulation-id <uuid> --suite persistent
.venv/bin/python scripts/run_eval.py --simulation-id <uuid> --suite experimental
```

## Compare Experiments

Run two experimental specs or the same spec with different `--run-config-file`
starting-condition overrides, then compare the completed simulation IDs:

```bash
.venv/bin/python scripts/report_simulation.py \
  --compare <run-a-uuid> <run-b-uuid> \
  --format json
```

The comparison summary includes `run_mode`, `experimental_goal`,
`duration_seconds`, `world.seed`, starting-condition diffs, `phases_completed`,
and `stop_reason`.

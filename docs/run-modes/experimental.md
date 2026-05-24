# Experimental Short Runs

Experimental mode is for bounded A/B runs. Each run starts from explicit
starting conditions, uses a fresh world when a world is configured, and records
enough metadata for `CrossRunComparison` to explain what changed between runs.

## Stops

An experimental autonomous run must have at least one defined end:

- `--duration 30m`
- `--experimental-goal turns:20`
- `--experimental-goal artifacts:2`
- `--experimental-goal phases_complete:3`

Seed-file runs are also bounded by their phase list. If an
`experimental_goal` is present in the run spec, the orchestrator stops once that
goal is reached. Final config metadata records `experimental_progress` and
`experimental_stop_reason` such as `goal_reached`, `duration_reached`,
`phases_complete`, or `cost_cap`.

## World

Experimental mode enforces a fresh world boundary:

- `world.persistent` is forced to `false`;
- `world.durable_world_id` is rejected;
- `core.minecraft.world_provisioner` may reset or generate a fresh world for the
  run mode.

## Starting Conditions

Use the same run-spec fields as persistent mode:

- `persona_overrides`
- `factions`
- `agent_goals`
- `memory_seed`
- `world`

These values are persisted in simulation config and surfaced in comparison
reports. `memory_seed.mode` is reported as part of the starting-condition diff.

## Local Run

Confirm the local model server first:

```bash
pnpm llm:local --list-only
```

Run the example:

```bash
LLM_PROVIDER=lmstudio \
LOCAL_LLM_BASE_URL=http://localhost:1234/v1 \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
EMBEDDING_PROVIDER=deterministic \
.venv/bin/python scripts/run_simulation.py \
  --name "experimental-short-a" \
  --seed-file scenarios/experimental_short_run.yaml \
  --run-mode experimental \
  --max-cost 0.01
```

Run a variant with a JSON run config that overrides `persona_overrides`,
`factions`, or `agent_goals`:

```bash
LLM_PROVIDER=lmstudio \
LOCAL_LLM_BASE_URL=http://localhost:1234/v1 \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
EMBEDDING_PROVIDER=deterministic \
.venv/bin/python scripts/run_simulation.py \
  --name "experimental-short-b" \
  --seed-file scenarios/experimental_short_run.yaml \
  --run-mode experimental \
  --run-config-file /path/to/variant-b-run-config.json \
  --max-cost 0.01
```

Compare the completed runs:

```bash
.venv/bin/python scripts/report_simulation.py <run-a-uuid> \
  --compare <run-b-uuid> \
  --format json
```

The report includes `phases_completed`, `stop_reason`, the configured goal, the
world seed, and the starting-condition fields that differ between the two runs.

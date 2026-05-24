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

## Choose A Mode

| Area | Persistent | Experimental |
| --- | --- | --- |
| Use when | Running the live show or testing restartable 24/7 operation. | Comparing starting-condition variants over short, repeatable runs. |
| Stop conditions | Kill switch, process cancel, or rolling cost cap. No duration. | Seed-file phases, `--duration`, `experimental_goal`, cancel, kill switch, or cost cap. |
| World | Durable Minecraft world. `persistent: true` is forced. | Fresh Minecraft world. `persistent: false` is forced and durable world IDs are rejected. |
| Cost cap | Requires `--max-cost-rolling` and `--rolling-window`. | Uses normal `--max-cost`; keep caps small for local experiments. |
| Memory seed | Can inherit the live namespace only through explicit memory seed config. | Supports `none`, `custom`, or `inherit`; the setting is recorded for comparison. |
| Example spec | `scenarios/persistent_24x7.yaml` | `scenarios/experimental_short_run.yaml` |
| Example command | `.venv/bin/python scripts/run_simulation.py --persistent --seed-file scenarios/persistent_24x7.yaml --max-cost-rolling 5 --rolling-window 1h` | `.venv/bin/python scripts/run_simulation.py --name "experimental-short-a" --seed-file scenarios/experimental_short_run.yaml --run-mode experimental --max-cost 0.01` |

## Compare Experiments

Run two experimental specs or the same spec with different `--run-config-file`
starting-condition overrides, then compare the completed simulation IDs:

```bash
.venv/bin/python scripts/report_simulation.py <run-a-uuid> \
  --compare <run-b-uuid> \
  --format json
```

The comparison summary includes `run_mode`, `experimental_goal`,
`duration_seconds`, `world.seed`, starting-condition diffs, `phases_completed`,
and `stop_reason`.

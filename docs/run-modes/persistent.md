# Persistent 24/7 Runs

Persistent mode is the livestream mode: no fixed duration, durable Minecraft
world, and shutdown only through the kill switch or cost caps.

## Start

```bash
LLM_PROVIDER=lmstudio \
LOCAL_LLM_BASE_URL=http://localhost:1234/v1 \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
EMBEDDING_PROVIDER=deterministic \
.venv/bin/python scripts/run_simulation.py \
  --persistent \
  --seed-file scenarios/persistent_24x7.yaml \
  --max-cost-rolling 5 \
  --rolling-window 1h
```

`--persistent` is shorthand for `--run-mode persistent`. Do not pass
`--duration`; persistent runs are indefinite. `SimulationConfig` requires
`--max-cost-rolling` and `--rolling-window` so the run has a rolling spend cap
even when it has no planned end time.

## World

The scenario's `world:` block is forced to `persistent: true`. The world
provisioner will not call `restore.sh --reset` in this mode. It verifies the
durable folder named by `durable_world_id` already exists under `SERVER_DIR`
and records the resolved `WORLD_CONFIG` in simulation metadata.

## Stop Conditions

The autonomous loop ignores duration in persistent mode. Each loop iteration
checks:

- the raw Redis kill switch key;
- the rolling cost cap from `cost_events`;
- the normal cancel signal used by process shutdown.

## Restart Resume

`scripts/minecraft/supervise.sh` or a wrapper can rediscover the active run
from raw Redis:

```bash
live_id="$(redis-cli -p 6381 -a devpassword GET live:simulation_id)"
.venv/bin/python scripts/run_simulation.py \
  --persistent \
  --seed-file scenarios/persistent_24x7.yaml \
  --resume-sim-id "$live_id" \
  --max-cost-rolling 5 \
  --rolling-window 1h
```

On attach, the orchestrator reuses the running simulation row and reloads
`total_cost` from `cost_events` before continuing.

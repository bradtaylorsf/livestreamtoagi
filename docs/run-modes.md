# Run Modes

The run-mode system has two embodied Minecraft lifecycles:

- `experimental`: a bounded run for smoke, soak, eval, and scenario comparison.
- `persistent`: a 24/7-style run with no fixed end from the run spec; it stops on operator cancel, kill switch, or cost caps.

Both modes are owned by `EmbodiedSimulationSupervisor` in `core/simulation/embodied_supervisor.py`. The supervisor creates or attaches to one durable simulation row, uses that UUID as the embodied run id, scopes Redis to `sim:<uuid>:`, applies any memory seed, initializes core memories, starts reflection scheduling, launches the Minecraft/Mindcraft runtime, and finalizes the simulation record.

## Run ID Flow

The supervisor exports the same UUID into the Minecraft runtime as:

- `LTAG_SIMULATION_ID`
- `MINECRAFT_SIMULATION_ID`
- `MC_SIMULATION_ID`
- `LTAG_RUN_ID`
- `EMBODIED_RUN_ID`

The Mindcraft bridge client sends `simulation_id` on every `BridgeRequest`. Bridge perception/action events, `memory.recall`, `memory.write`, Management review, errand completion, journals, reflections, cost events, evals, and reports therefore share the same simulation id. The bridge protocol is `1.9`; this is an additive minor bump documenting supervisor-owned simulation-id propagation.

## Launching

Experimental embodied run:

```bash
python scripts/run_simulation.py \
  --mode embodied \
  --run-mode experimental \
  --name minecraft-smoke \
  --duration-hours 0.25 \
  --agents alpha,vera,rex,aurora,pixel,fork,sentinel,grok \
  --max-cost 10
```

Persistent embodied run:

```bash
python scripts/run_simulation.py \
  --mode embodied \
  --run-mode persistent \
  --name minecraft-persistent \
  --agents alpha,vera,rex,aurora,pixel,fork,sentinel,grok \
  --max-cost 25 \
  --max-cost-rolling 5 \
  --rolling-window 24h
```

The ergonomic wrapper still works:

```bash
scripts/minecraft/run-local-sim.sh smoke
scripts/minecraft/run-local-sim.sh soak-director
```

For real runs, `scripts/minecraft/soak.sh` delegates to `scripts/run_simulation.py --mode embodied`; the supervisor then relaunches `soak.sh` with `MC_SIM_LOWLEVEL=1` and the run-id env above. `--dry-run`, `--verify`, and `--verify-behavior` remain shell-only diagnostics and do not allocate a simulation id.

To intentionally bypass the supervisor for low-level debugging:

```bash
MC_SIM_LOWLEVEL=1 scripts/minecraft/soak.sh --duration-hours 0.25
```

That path is diagnostic only: it does not allocate a supervisor simulation id and should not be used as acceptance evidence for run-mode lifecycle behavior.

## End Conditions

Experimental runs stop when the configured duration is reached or a callable in-process goal predicate returns true. Persistent runs omit duration and keep running until cancel, kill switch, cost cap, or runtime failure.

On clean completion the supervisor runs the configured eval suite, finalizes the simulation, writes baseline outcomes, and emits a markdown report under `logs/reports/<simulation_id>.md`. Cost-limit and kill-switch stops terminate Minecraft/Mindcraft child processes before finalizing.

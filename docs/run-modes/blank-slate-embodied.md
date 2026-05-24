# Blank-Slate Embodied Runs

Embodied runs use the same `memory_seed` path as director runs. The
orchestrator applies `memory_seed` immediately after the simulation row exists
and before `init_core_memories`, so seeded core memories win over default
identity initialization.

## Modes

| Mode | Use when | Effect |
| --- | --- | --- |
| `none` | You want a truly empty memory namespace. | Writes blank core memory for each active agent and clears recall rows for the new simulation. |
| `custom` | You want a known starting scenario such as blank-slate or conflict. | Loads a JSON/YAML snapshot such as `scenarios/seeds/blank-slate.json`, including core memory plus embodied state like `agent_states`, `agent_accounts`, and seeded goals when present. |
| `inherit` | You want a new run to continue from an older simulation. | Copies the source simulation's exported core and recall memory into the target simulation namespace. |

## CLI

Use the environment gate for embodied mode and the standard memory seed flags:

```bash
CONVERSATION_MODE=embodied \
LLM_PROVIDER=lmstudio \
LOCAL_LLM_BASE_URL=http://localhost:1234/v1 \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
EMBEDDING_PROVIDER=deterministic \
.venv/bin/python scripts/run_simulation.py \
  --name "blank-slate-embodied" \
  --seed-file scenarios/local_llm_validation.yaml \
  --agents vera,rex,aurora,pixel \
  --memory-seed-mode custom \
  --memory-seed-file scenarios/seeds/blank-slate.json \
  --max-cost 0.01
```

For a blank namespace without a snapshot, use `--memory-seed-mode none`. To
continue from a prior run, use `--memory-seed-mode inherit
--memory-seed-inherit-from <simulation-uuid>`.

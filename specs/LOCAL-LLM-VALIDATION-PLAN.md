# Local LLM Validation Plan

This plan describes how to run zero-cost or near-zero-cost simulations against a local
OpenAI-compatible server such as LM Studio, then verify that the results came from
real LLM interactions flowing through the live systems.

LM Studio exposes an OpenAI-compatible API at `http://localhost:1234/v1` by default
and supports `POST /v1/chat/completions`; see the official docs:
https://lmstudio.ai/docs/developer/openai-compat/

## Goal

Run simulations locally to prove that the core research substrate works before spending
money on cloud tokens:

- Agents generate actual model responses, not canned script output.
- Conversation energy changes and ends conversations.
- Speaker selection, interrupts, participation, and topic tracking produce varied turns.
- Agent internal state changes and is reflected in prompt context.
- Core, recall, archival memory, journals, reflection, and dreams persist evidence.
- Tools execute through the same path used by live simulation.
- Simulation and live paths share the same services and verification surface.
- Post-run verification can distinguish LLM behavior failures from engineering failures.

## Local Configuration

Use LM Studio or any OpenAI-compatible local server:

```bash
python scripts/check_local_llm.py --list-only

LLM_PROVIDER=lmstudio \
LOCAL_LLM_BASE_URL=http://localhost:1234/v1 \
LOCAL_LLM_MODEL=<model-id-from-/v1/models> \
EMBEDDING_PROVIDER=deterministic \
python scripts/run_simulation.py \
  --name "local-llm-validation" \
  --seed-file scenarios/local_llm_validation.yaml \
  --agents vera,rex,aurora,pixel \
  --max-cost 0.01 \
  --verbose

python scripts/verify_simulation.py \
  --name "local-llm-validation" \
  --profile local-smoke
```

Embedding modes:

- `EMBEDDING_PROVIDER=deterministic`: proves memory plumbing and persistence with zero cost, but not semantic recall quality.
- `EMBEDDING_PROVIDER=lmstudio`: proves semantic recall locally, but requires a loaded embedding model and `LOCAL_EMBEDDING_MODEL`.
- `EMBEDDING_PROVIDER=openrouter`: uses the previous cloud embedding behavior.

## Independent Verification Matrix

| System | Evidence Source | Verification |
| --- | --- | --- |
| LLM routing | `simulations.model_versions`, `cost_events.details.provider/runtime_model` | Provider is `lmstudio` or `openai-compatible`; `llm_call` rows exist even when amount is zero. |
| Prompt assembly | optional `--debug-prompts`, prompt logs | Prompts include infrastructure, character identity, memory, goals, state, relationships, balance, dreams. |
| Conversation engine | `conversations`, `cost_events`, `agent_speak` events | Conversations have nonzero turns and multiple agents where expected. |
| Speaker selection | `conversation_selection_log` | Selected agents vary; required agents speak; scores are recorded. |
| Energy model | `energy_change_log`, `conversations.initial_energy/final_energy` | Energy ticks exist, net changes are nonzero, conversations close before max turns when energy drains. |
| Topic tracking | conversation summaries, topic history, prompt logs | Repeated topics trigger avoidance and later conversations shift topic. |
| Internal state and mood | `agent_internal_state`, prompt context | State values differ from defaults; moods change after turns, dreams, and idle/reflection. |
| Core memory | `core_memory`, `artifacts` for `update_core_memory` | Core memory exists for each participating agent and updates through the tool path. |
| Archival memory | `transcripts` joined to `conversations` | Full transcripts are stored once per conversation. |
| Recall memory | `recall_memory`, embedding provider mode | Recall rows exist per participant; local semantic mode should use real local embeddings. |
| Reflection journals | `journal_entries.reflection_type='6hour'` | Reflection produces public journal prose and snapshots state. |
| Dreams | `journal_entries.reflection_type='dream'`, `agent_goals.source='dream'` | Dreams parse as JSON, create journals, change mood, and produce goals or insights. |
| Tool execution | `artifacts`, `artifact_created` events | Forced tool phases fire the target tool and record executed outputs. |
| Relationships | `agent_relationships` | Multi-agent conversations increment relationship pairs and summaries evolve. |
| Economy/budget | `agent_accounts`, `cost_events`, economy artifacts | Accounts initialize; transfers and balances persist. Local LLM calls should record zero cost. |
| Audience/world events | Redis audience keys, `world_events`, conversations | Audience phases and event generator create triggers that agents respond to. |
| Management safety | `management_shadow_log` in shadow mode | Safety review records shadow decisions when enabled. |
| Simulation isolation | simulation-scoped Redis keys and DB `simulation_id` columns | Runs do not bleed memory/state/cost across simulations. |
| Eval layer | `eval_runs`, `eval_results`, analyzer output | Evals consume the completed simulation and cite evidence. |

## Scenario Ladder

1. `scenarios/local_llm_validation.yaml`
   - Fast local proof run.
   - Validates routing, conversations, energy, state, two tools, memory, reflection, dreams.

2. `scenarios/dream_smoke_test.yaml`
   - Isolates dream generation, dream journals, dream goals, and mood shifts.

3. `scenarios/state_and_config_test.yaml`
   - Isolates centralized config, internal state, boredom, creative/social needs, and state-driven context.

4. `scenarios/tool_coverage.yaml`
   - Exhaustive tool path coverage.
   - Verify with `python scripts/verify_simulation.py --name <run> --profile tool-coverage`.

5. `scenarios/topic_exhaustion_test.yaml`
   - Tests cross-conversation topic memory and avoidance behavior.

6. `scenarios/ab_test.yaml`
   - Repeatable baseline/treatment comparison for changes to prompts, state, memory, or model provider.

7. Autonomous run
   - Tests live-like trigger behavior:
     `python scripts/run_simulation.py --name local-auto --duration 12h --speed-multiplier 42 --max-cost 0.01`

## Research Protocol

For each code or prompt change:

1. Run `scripts/check_local_llm.py`.
2. Run `local_llm_validation` with a fixed model and fixed agent set.
3. Verify with `--profile local-smoke`.
4. Run the one scenario that isolates the touched subsystem.
5. Export a snapshot for reproducibility:
   `python scripts/chat.py sim export <name> --output snapshots/<name>.json`
6. Run evals only after verifier passes.
7. Compare at least two repeated local runs before interpreting behavior as agent-level behavior.

## Failure Interpretation

- No `llm_call` rows: provider routing or LLM client failed.
- `llm_call` rows but no conversations: conversation engine or phase runner failed.
- Conversations but no energy rows: selection logger or energy logging failed.
- Conversations but no recall/transcripts: compactor, embeddings, or archival memory failed.
- Dream journals missing: dream prompt, JSON parsing, or dream phase failed.
- Dream journals exist but no dream goals: model may be weak at structured JSON or goals were rejected.
- Tool phase completed but target tool absent: model ignored tool choice and forced-call fallback failed.
- Local provider rows exist with zero tokens: provider did not report usage; this is acceptable for cost, but weaker for token accounting.

The verifier should fail loudly on engineering failures. Model-quality failures should be preserved as research findings, not papered over with looser prompts unless the prompt itself is the variable under test.

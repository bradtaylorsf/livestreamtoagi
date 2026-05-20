# Alpha Structured Errands (E7-3, E7-4)

Alpha executes structured errands through `!runErrand`. The task is delivered
by `errand.poll`, parsed as JSON, executed with the existing verified action
surface, then reported to Python through `errand.complete`. E7-4 persists the
reported outcome through the existing memory compactor so the result is
retrievable via the standard `memory.recall` path.

## Errand Plan JSON

`tools/alpha_dispatch.py` still accepts `task` as a string. For E7-3, Alpha's
Minecraft executor treats that string as JSON:

```json
{
  "kind": "fetch_place",
  "steps": [
    {
      "action_id": "nav-1",
      "navigate": {
        "target": { "x": 2, "y": 64, "z": 0 },
        "arrive_within_blocks": 1,
        "timeout_ms": 1000
      }
    },
    {
      "action_id": "place-1",
      "place": {
        "block_type": "dirt",
        "position": { "x": 2, "y": 64, "z": 0 },
        "face": "up",
        "source_slot": 1
      }
    }
  ]
}
```

Allowed `kind` values:

| Kind | Allowed steps |
|---|---|
| `navigate` | `navigate` steps only |
| `place` | `place` steps only |
| `fetch_place` | `navigate` and `place` steps |

Every step needs a stable `action_id`. `navigate` reuses `!navigate` parameters.
`place` reuses `!place` parameters.

## Run Sequence

1. `!runErrand` calls `errand.poll` as `agent_id: "alpha"`.
2. If no task is pending, Alpha logs `no errand pending`.
3. If a task is pending, `errand_plan.js` parses and normalizes the JSON.
4. Alpha executes each step by calling the existing verified `navigateAction`
   or `placeAction`; those actions still emit `perception.report` and
   `action.result`.
5. Alpha posts one `errand.complete` payload with:
   - `task_id`
   - overall `status`: `success`, `failure`, or `partial`
   - `symbol`: `✓`, `✗`, or `?`
   - `detail`
   - `step_results[]`

`!runErrand` is non-verbal. It logs to the console and does not send Minecraft
chat.

## Kill switch & response window

The admin kill switch is the global Redis key `kill_switch`, set to `active`
by `core/admin/kill_switch_routes.py` through the router-local `POST /kill`
endpoint (mounted as `POST /api/admin/kill`). This key is not simulation-scoped.

When `kill_switch` is active:

1. `dispatch_alpha` rejects new Alpha errands before queueing work or making an
   LLM call.
2. Alpha's next `errand.poll` returns the same empty payload used when no
   errand is pending, so the Node bot safe-idles without acting.
3. Any Alpha `errand.complete` frame receives a retryable `kill_switch_active`
   bridge error before memory persistence or Management review side effects.

Documented halt window: the next bridge poll cycle plus any already-in-flight
Alpha LLM call. The Mindcraft Alpha profile polls via `!pollErrand`/`errand.poll`
on its tick cadence, so newly available work is suppressed on the next poll.
An LLM dispatch that was already in flight may run until `ALPHA_TIMEOUT_SECONDS`
in `tools/alpha_dispatch.py`, currently 60 seconds.

## Memory persistence (E7-4)

The bridge handler for `errand.complete` writes the verified outcome into the
agent's recall memory through `MemoryCompactor.compact_interaction` as an
`errand_outcome` event. The body includes the `task_id`, the dispatcher (when
still retained in the in-process queue), the overall `status`/`symbol`/`detail`,
and every `step_results[]` entry; participants default to
`[agent_id, from_agent]` so a later `memory.recall` returns the outcome for
either side of the dispatch.

The completion ack is **independent** of memory availability — if the
compactor is unwired or fails, the bridge still answers `{accepted: true}`
and only logs a warning. Memory writes are idempotent per
`(simulation_id, task_id)`, so a retried `errand.complete` frame with the
same `task_id` will not create a duplicate memory.

## Symbol Semantics

Alpha's system prompt limits output to symbols. E7-3 maps verified errand
outcomes this way:

| Symbol | Meaning |
|---|---|
| `✓` | Every step reported verified `success`. |
| `✗` | At least one step reported verified `failure`. |
| `?` | The task JSON was malformed, the bridge was unavailable, or the result was ambiguous/partial. |

Malformed plans are reported through `errand.complete` with
`status: "failure"` and `symbol: "?"` when the bridge is reachable.

## Local Validation

Confirm LM Studio is reachable and record the served model id:

```bash
pnpm llm:local --list-only
```

Then run the headless errand verifier:

```bash
pnpm verify:alpha-errand
scripts/minecraft/connect-alpha-bot.sh --verify
```

The E7-3 executor has no LLM runtime path: parsing, action invocation, and
`errand.complete` are mechanical. The nearest local smoke path is
`pnpm verify:alpha-errand`, which runs the Node harness with a fake bot and
stub bridge. A real local Mac server run still uses the Alpha profile from
`alpha-profile.md` with `LOCAL_LLM_MODEL` and, when available,
`LOCAL_LLM_MODEL_BUILDING` targeting LM Studio model ids.

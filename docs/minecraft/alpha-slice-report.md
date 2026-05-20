# Alpha Vertical-Slice Acceptance Report

Issue: #571 E7-7 - Vertical-slice acceptance report  
Epic: #509 E7 - Alpha Vertical Slice  
Prepared: 2026-05-19 PDT  
Scope: E7-1 through E7-6, Alpha only

## Decision

Status: **GO for E8 implementation, with live local validation recorded below.**

The committed E7 chain proves Alpha's local-dev vertical slice at the contract,
bridge, non-verbal profile, errand execution, memory, Management, cost
attribution, and kill-switch layers. The post-run addendum below records a live
local run with LM Studio reachable, Paper `1.21.6-48`, Alpha connected through
Mindcraft, the human reviewer connected through Minecraft Java Edition, and a
successful `!runErrand` completion through the Python bridge.

This is a local-development sign-off for E8 implementation, not a production or
livestream launch sign-off.

## End-to-End Chain

1. Another agent dispatches Alpha through the existing `dispatch_alpha` tool.
2. The tool preserves the existing LLM/event behavior and enqueues the same task
   for the Python-to-Node bridge.
3. Alpha's Mindcraft profile polls `errand.poll` as `agent_id: "alpha"` without
   speaking in Minecraft chat.
4. Alpha executes a structured navigate/place errand through `!runErrand`,
   using the verified action surface.
5. Alpha reports one `errand.complete` result with step-level evidence and a
   symbolic outcome.
6. Python persists the verified outcome through the memory compactor so it is
   retrievable through `memory.recall`.
7. Python routes Alpha's symbolic result through Management out of band.
8. Cost attribution charges Alpha's LLM call path, and an active `kill_switch`
   blocks new dispatches, safe-idles `errand.poll`, and rejects
   `errand.complete` before side effects.

## Child Issue Evidence

| Slice | Issue / PR / commit | Acceptance | Evidence | Status |
| --- | --- | --- | --- | --- |
| E7-1 Alpha Mindcraft profile | #565 / #689 / `3ec0497` | Alpha profile targets the E2 world, uses local LM Studio model IDs, and emits no chat. | `docs/minecraft/alpha-profile.md`; `scripts/minecraft/profiles/alpha-bot.json`; `scripts/minecraft/mindcraft-settings-alpha.js`; `scripts/minecraft/connect-alpha-bot.sh --verify`; `pnpm verify:mindcraft-alpha` -> 18 passed; live Alpha joined Paper `1.21.6-48` in the post-run addendum. | Pass. |
| E7-2 Alpha receives dispatched errand | #566 / #690 / `6e3d6d7` | A dispatched task reaches Alpha through the bridge while preserving `dispatch_alpha` semantics. | `core/bridge/errand_queue.py`; `tools/alpha_dispatch.py`; `errand.poll` in `core/bridge/contract.py`; `tests/backend/test_alpha_dispatch_bridge_delivery.py` -> 2 passed; `pnpm verify:bridge-contract` -> 74 passed. | Pass. |
| E7-3 Alpha executes verified errand | #567 / #691 / `a11061b` | A known errand completes with verified success/failure surfaced. | `docs/minecraft/alpha-errand.md`; `scripts/minecraft/fork-src/agent/commands/run_errand_action.js`; `scripts/minecraft/fork-src/agent/skills/errand_plan.js`; `errand.complete` fixtures; `pnpm verify:alpha-errand` -> 19 passed; live `!runErrand` completed with `✓ success: 1/1 steps finished`. | Pass. |
| E7-4 Alpha writes outcome to memory | #568 / #692 / `da6fd40` | The errand outcome persists and can be recalled through the memory bridge path. | `core/bridge/handlers/errand.py`; `docs/minecraft/alpha-errand.md`; `docs/minecraft/bridge-contract.md`; `tests/backend/test_alpha_errand_memory.py` -> 1 passed; `pnpm verify:alpha-errand` includes retrievable-memory and idempotency coverage. | Pass. |
| E7-5 Management out of band | #569 / #693 / `8fb55f5` | Alpha's symbolic output is reviewed by Management, and Management is not spawned as a world bot. | `core/bridge/handlers/errand.py`; `tests/backend/test_bridge_errand.py::test_bridge_errand_complete_reviews_alpha_symbolic_outcome`; `tests/backend/test_management.py` -> 42 passed, 1 skipped; `tests/backend/test_management.py::test_management_is_not_mindcraft_world_bot`. | Pass. |
| E7-6 Cost gate and kill switch | #570 / #694 / `abc10bd` | Alpha spend is attributed, and `kill_switch` prevents Alpha acting through dispatch, poll, and completion paths. | `tools/alpha_dispatch.py`; `core/bridge/server.py`; `docs/minecraft/alpha-errand.md`; `.venv/bin/pytest tests/backend/test_alpha_dispatch.py tests/backend/test_cost_tracking.py -v` -> 35 passed; `pnpm verify:bridge-server` -> 34 passed. | Pass, bridge/tool enforced. |

## Local Validation Commands

Ran on this Mac worktree:

```bash
pnpm llm:local --list-only
```

Result: **failed**, because no LM Studio-compatible server was reachable at
`http://localhost:1234/v1/models`.

```text
FAIL: could not reach http://localhost:1234/v1/models
      All connection attempts failed
```

No LM Studio model IDs were available to record. No OpenRouter validation was
run or required for this issue.

Nearest local smoke paths run:

```bash
scripts/minecraft/connect-alpha-bot.sh --verify
pnpm verify:mindcraft-alpha
pnpm verify:alpha-errand
.venv/bin/pytest tests/backend/test_alpha_dispatch_bridge_delivery.py tests/backend/test_alpha_errand_memory.py -v
pnpm verify:bridge-contract
.venv/bin/pytest tests/backend/test_alpha_dispatch.py tests/backend/test_cost_tracking.py -v
pnpm verify:bridge-server
.venv/bin/pytest tests/backend/test_management.py -v
```

Results:

- `scripts/minecraft/connect-alpha-bot.sh --verify`: passed; static Alpha
  profile is local-only, non-verbal, E2-targeted, and bridge assets are present.
- `pnpm verify:mindcraft-alpha`: 18 passed.
- `pnpm verify:alpha-errand`: 19 passed.
- `tests/backend/test_alpha_dispatch_bridge_delivery.py`
  + `tests/backend/test_alpha_errand_memory.py`: 3 passed.
- `pnpm verify:bridge-contract`: 74 passed.
- `tests/backend/test_alpha_dispatch.py`
  + `tests/backend/test_cost_tracking.py`: 35 passed.
- `pnpm verify:bridge-server`: 34 passed.
- `tests/backend/test_management.py`: 42 passed, 1 skipped
  (`test_end_to_end_review_with_llm` is an opt-in LLM test).

## Post-Run Review Addendum

Codex reviewed the completed session branch after the alpha-loop run and reran
the current verification set on 2026-05-20 UTC.

Current LM Studio reachability:

```bash
pnpm llm:local --list-only
```

Result: **passed**. The local OpenAI-compatible server at
`http://localhost:1234/v1` returned these model ids:

- `text-embedding-nomic-embed-text-v1.5`
- `google/gemma-4-26b-a4b`
- `google/gemma-4-e4b`

Additional post-run checks:

- `pnpm test:python && pnpm test:frontend && pnpm test:website`: passed
  (`2817 passed, 10 skipped`; frontend `337 passed`; website `420 passed`).
- `.venv/bin/ruff check core/ tools/`: passed.
- `.venv/bin/ruff format --check core/ tools/`: passed.
- `.venv/bin/python scripts/export_bridge_schemas.py --check`: passed.
- `scripts/minecraft/connect-alpha-bot.sh --verify`: passed.
- `pnpm verify:mindcraft-alpha`: 18 passed.
- `pnpm verify:alpha-errand`: 19 passed.
- `pnpm verify:bridge-contract`: 74 passed.
- `pnpm verify:bridge-server`: 34 passed.
- PR #688 GitHub checks: clean after the formatting-only follow-up commit.

Code review result: **PASS**, with no blocking findings in the bridge contract,
errand queue, Alpha dispatch path, Mindcraft errand actions, memory persistence,
Management review hook, or kill-switch enforcement.

Live local Alpha run evidence, captured after setup on 2026-05-20 UTC:

- Java 21 and Node 20 were placed on PATH for the Minecraft scripts.
- `scripts/minecraft/start-server.sh` booted Paper `1.21.6-48` on
  `127.0.0.1:25565`, and the server console reported
  `There are 1 of a max of 20 players online: Alpha`.
- `scripts/minecraft/connect-alpha-bot.sh` launched the staged non-verbal Alpha
  profile against the local server and bridge.
- MindServer reported Alpha's live state at `(10.5, 67, -1.5)`, idle, full
  health, in the `desert` biome.
- A dev-only local wrapper enqueued a current-position structured navigate
  errand, then the MindServer admin channel sent `!runErrand` to Alpha.
- Alpha logged bridge `errand.poll`, `perception.report`, `action.result`, and
  `errand.complete` calls, then printed
  `errand demo-6143b1e3-cd01-48ee-93e5-f3c0ffd16bef ✓ success: 1/1 steps finished`.

This addendum upgrades the local LM Studio and live Minecraft evidence. It
still does not claim production livestream sign-off.

## Deviations and Boundaries vs `MINECRAFT-PIVOT-CONTEXT.md`

- **Initial E7-7 verification lacked a live run.** The original report captured
  the headless/static evidence while LM Studio was unreachable. The post-run
  addendum now records LM Studio reachability, live Paper server startup,
  Alpha's Mindcraft connection, a human spectator join, and successful live
  `!runErrand` bridge completion.
- **Only Alpha is embodied.** This matches E7 scope. Other agents and
  decentralized Mindcraft conversation remain E8 work.
- **Management stays out of band.** This is not a deviation from the context;
  it is the intended preservation boundary. The verified path reviews Alpha's
  symbolic errand outcome in Python and confirms no Management world bot.
- **Kill switch is enforced at the Alpha slice boundary, not as a full process
  supervisor.** E7-6 blocks new dispatches, safe-idles Alpha's next
  `errand.poll`, and rejects `errand.complete` before memory/Management side
  effects. Full 24/7 process halt and broader per-agent hourly cap hardening
  remain later safety-hardening work.
- **OpenRouter production routing is not exercised.** The E7 local-dev profile
  intentionally uses `lmstudio/<model-id>` and `lmstudio/<code-model-id>` to
  avoid external spend, while production OpenRouter mappings remain documented
  and guarded elsewhere.

## Sign-Off

Automated acceptance recommendation: **GO for E8 implementation**, based on the
passing headless/local smoke evidence above.

Human reviewer sign-off: **GO for E8 implementation**.

Reviewer: bradtaylorsf  
Date: 2026-05-19 PDT / 2026-05-20 UTC  
Decision: GO for E8 implementation; not a production livestream launch sign-off.

# Action Failure Taxonomy (E6-7)

This is the E6-7 deliverable for
[#562](https://github.com/bradtaylorsf/livestreamtoagi/issues/562). It defines
the canonical action failure classes and the only safe behavior allowed after a
verified movement/build action fails.

Python is the source of truth in `core/embodiment/failure.py`. The committed
Mindcraft fork mirror is `scripts/minecraft/fork-src/agent/skills/safe_fail.js`
so fork actions can make the same decision without a new dependency.

## Canonical Classes

| Class | Meaning | Safe policy | Immediate action |
| --- | --- | --- | --- |
| `blocked` | The world state or inventory prevents completion: obstruction, protected block, missing reference block, missing item/tool, or no progress. | `idle` | Stop the action and idle. Do not keep pushing against the same blocked state. |
| `timeout` | The action or bridge call exceeded its deadline, or the bridge is overloaded. | `retry-bounded` | Retry only within the configured retry budget, using exponential backoff. Abandon after the budget is exhausted. |
| `invalid` | The request, target, schema, block, recipe, auth, or protocol input is invalid. | `abandon` | Abandon immediately. Do not retry unchanged invalid input. |
| `unreachable` | Pathfinding or lookup cannot reach the target or required interaction point. | `idle` | Stop and idle so a caller can re-plan from fresh perception. |
| `bridge-down` | The Python bridge cannot be connected to or the send path failed. | `abandon` | Abandon the action rather than performing unverified or ungated work. |
| `kill-switch-active` | The operator kill switch is active. | `idle` | Stop action attempts and idle until `kill.status` reports inactive. |

`success`, `reached`, `placed`, `removed`, and `partial` are not canonical
failure classes. The taxonomy only decides what to do after a terminal failure
has been observed or reported.

## Normalization

The Python classifier accepts skill labels, bridge error codes, and common
mapping shapes such as `{ "class": "timed-out" }`,
`{ "failureClass": "tool-missing" }`, or
`{ "error": { "code": "bridge_no_token" } }`.

| Raw label/code | Canonical class |
| --- | --- |
| `blocked` | `blocked` |
| `timed-out`, `timeout`, `bridge_timeout`, `bridge_overloaded` | `timeout` |
| `invalid`, `protected`, `tool-missing`, `bridge_auth_refused`, `bridge_no_token`, `bridge_no_transport`, `bridge_protocol` | `invalid` |
| `unreachable`, `no-path`, `bridge_unreachable` | `unreachable` |
| `bridge-down`, `bridge_connect_failed`, `bridge_send_failed` | `bridge-down` |
| `kill_switch_active`, `kill-switch-active` | `kill-switch-active` |
| `reached`, `placed`, `removed`, `success`, `partial` | no failure class |

Unknown non-empty labels normalize to `invalid`. Ambiguous failures therefore
abandon instead of retrying or taking an unverified action.

## Retry Budget

`timeout` is the only retry-bounded class. The default budget is:

| Field | Default |
| --- | --- |
| `max_attempts` | `3` |
| `base_backoff_ms` | `500` |
| `cap_ms` | `30000` |
| `multiplier` | `2` |

Backoff is 1-based: attempt 1 waits 500 ms, attempt 2 waits 1000 ms, and later
attempts double until capped. When `attempt > max_attempts`, the safe action is
`abandon`.

## Verification

The no-server verification path is:

```bash
pnpm verify:embodiment-failure
```

This issue has no LLM runtime path. For the local-validation policy, confirm
LM Studio reachability with:

```bash
pnpm llm:local --list-only
```

If LM Studio is not serving on the local Mac, record that result and use the
static failure verifier above as the nearest local smoke path.

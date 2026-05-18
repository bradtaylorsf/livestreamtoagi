# Bridge message contract (E4-2)

The Python<->Node bridge (epic #506) uses **one versioned message contract** so
the Node Minecraft bots and the Python backend cannot drift. This is issue
#541's deliverable; the transport/envelope rules it implements are fixed by ADR
[`docs/decisions/0010-bridge-protocol.md`](../decisions/0010-bridge-protocol.md)
(E4-1, the source of truth).

## Single source of truth

`core/bridge/contract.py` holds the Pydantic v2 models. **Python validates with
those models; Node validates with a JSON Schema *generated from* them.** The
Node-side artifact is committed at
`core/bridge/schemas/bridge-protocol.schema.json` and is never hand-edited —
regenerate it after any contract change:

```bash
.venv/bin/python scripts/export_bridge_schemas.py          # rewrite the schema
.venv/bin/python scripts/export_bridge_schemas.py --check   # CI-style staleness check
```

The export is deterministic (sorted keys, trailing newline) so a stale
committed schema is a hard test failure, not a silent divergence.

## Envelope

Every message is one of two envelopes, with the exact field set ADR §2 fixes
(`extra='forbid'` — unknown fields are rejected, not ignored):

- **`BridgeRequest`** — `version`, `request_id`, `agent_id`, `run_id`,
  `simulation_id`, `service`, `method`, `payload`, `deadline_ms`,
  `cost_context`. Node->Python, or Python->Node for control messages.
- **`BridgeResponse`** — `request_id`, `ok`, `payload`, `error`, `retryable`.
  `retryable` defaults to `false` (ADR §5: absence/ambiguity is *not*
  retryable).

`payload` is opaque at the envelope level and validated per-verb via
`SERVICE_REGISTRY`.

## Versioning (fail-closed)

`PROTOCOL_VERSION = "1.0"`. Same-major versions are wire-compatible in either
direction (new fields/verbs are additive). An unknown *major* — or any
unparseable version — is **not supported**; the server replies with the exact
ADR §3 shape (`unsupported_version_response`): `ok=false`,
`error.code="unsupported_version"`, `retryable=false`. Ambiguity is rejected,
never guessed.

## Closed service set

The bridge dispatches a **closed** registry — there is no generic "run
arbitrary Python" verb. The six initial verbs from issue #541 plus
`bridge.ping` (the ADR's `!bridgePing` first-proof round-trip):

| `service.method` | Direction | Request → Response |
| --- | --- | --- |
| `bridge.ping` | Node↔Python | `{message}` → `{pong}` |
| `memory.recall` | Node→Python | `{query, scope, limit}` → `{results[]}` |
| `memory.write` | Node→Python | `{content, kind, metadata}` → `{memory_id}` (idempotent on `request_id`) |
| `management.review` | Node→Python | `{agent_id, text, context}` → `{verdict, reason, sanitized_text}` |
| `cost.gate` | Node→Python | `{agent_id, action, estimated_cost_usd}` → `{allowed, reason, remaining_budget_usd}` |
| `perception.report` | Node→Python | `{observations[]}` → `{accepted}` |
| `action.result` | Node→Python | `{action_id, status, detail}` → `{accepted}` |

**Naming reconciliation:** issue #541's scope text says `memory.read`; ADR §6
(authoritative) calls the same verb `memory.recall`. The contract uses
`memory.recall` everywhere so the split is *closed*, not carried forward.
`cost.reserve`, `journal.event`, and `kill.status` are named in ADR §6 but
their schemas land with their owning issues — out of E4-2 scope.

## Verifying

The contract test validates **both directions** (request + response) on **both
sides** (Pydantic *and* the committed JSON Schema via `jsonschema`) against
committed static fixtures in `tests/backend/fixtures/bridge/`, and guards
against schema drift, fail-closed versioning, and an out-of-contract verb:

```bash
pnpm verify:bridge-contract     # .venv/bin/pytest tests/backend/test_bridge_contract.py -v
```

This issue has **no LLM runtime path** (pure schema/data plumbing, no model
calls), so no LM Studio simulation is required; `pnpm verify:bridge-contract`
is the nearest local smoke path and runs headless in the existing
`backend-test` CI job.

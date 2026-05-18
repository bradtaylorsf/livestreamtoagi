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

## Server endpoint (E4-3)

`core/bridge/server.py` mounts the Python side of the bridge as one
authenticated FastAPI WebSocket (`bridge_router`, wired into `core/main.py`
alongside `/ws`):

```
/api/minecraft/bridge/ws
```

- **Fail-closed auth (ADR §4).** A shared-secret bearer token is read from the
  `MINECRAFT_BRIDGE_TOKEN` env var and compared with `hmac.compare_digest`
  (constant-time, mirroring `core/admin/kill_switch_routes.py`). The presented
  token comes from the handshake `Authorization: Bearer <token>` header, with a
  `?token=` query-param fallback for clients that cannot set WS headers. An
  unset/empty server token, or a missing/malformed/wrong presented token,
  **closes the socket with code 1008 before `accept()`** — no `service` is ever
  dispatched on an unauthenticated connection. There is no anonymous or
  "auth optional in dev" path.
- **Validation order (ADR §2→§3→§6).** After `accept()`, each frame is parsed
  as a `BridgeRequest`, version-negotiated fail-closed on an unknown major, and
  validated against the closed per-verb registry. Every post-handshake failure
  comes back as a contract-valid `BridgeResponse` (`ok=false` + typed `error`)
  on a still-open socket — only the handshake closes the socket.
- **Stub dispatch only.** Each of the 7 registry verbs maps to a handler that
  returns a contract-valid placeholder payload with **no business logic**
  (e.g. `bridge.ping` → `{pong}`, `memory.recall` → `{results: []}`). Real
  memory/management/cost wiring is E5/E8; the perception/action inbound channel
  is E4-5/E4-6. Each stub response is re-validated through
  `validate_response` before it goes on the wire.

## Verifying

The contract test validates **both directions** (request + response) on **both
sides** (Pydantic *and* the committed JSON Schema via `jsonschema`) against
committed static fixtures in `tests/backend/fixtures/bridge/`, and guards
against schema drift, fail-closed versioning, and an out-of-contract verb. The
server test drives the **real endpoint** over an in-process WebSocket: every
verb round-trips a contract-valid stub, and unauthenticated/malformed-token
handshakes are rejected before dispatch:

```bash
pnpm verify:bridge-contract     # .venv/bin/pytest tests/backend/test_bridge_contract.py -v
pnpm verify:bridge-server       # .venv/bin/pytest tests/backend/test_bridge_server.py -v
```

This epic step has **no LLM runtime path** (auth + schema plumbing dispatching
to pure stubs, no model calls), so no LM Studio simulation is required. Both
tests are the nearest local smoke path and run headless — dependency-free, no
Docker/network — in the existing `backend-test` CI job.

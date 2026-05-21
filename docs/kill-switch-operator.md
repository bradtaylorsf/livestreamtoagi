# Kill Switch Operator Runbook

Issue: #597, E11-4. This documents the phone-accessible operator path for the
global kill switch.

## What It Does

`POST /api/admin/kill` activates the global Redis key `kill_switch=active`.
Autonomous Python orchestrators stop when `orchestrator._terminated()` reads
that key. The key is global, not simulation-scoped.

`DELETE /api/admin/kill` clears the same Redis key.

## Required Environment

Server:

```bash
KILL_SWITCH_API_KEY=<long random secret>
```

Operator shell or phone shortcut setup:

```bash
ADMIN_API_BASE=https://<admin-host>
KILL_SWITCH_API_KEY=<same long random secret>
```

`ADMIN_API_BASE` must be the public base URL that reaches `core.main:app`.
Do not include `/api/admin` in the base value.

## Activate From Curl

This is the exact request a phone shortcut should mirror:

```bash
curl -X POST "$ADMIN_API_BASE/api/admin/kill" \
  -H "X-Kill-Switch-Key: $KILL_SWITCH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ttl": 14400}'
```

Expected response:

```json
{"status":"active","ttl_seconds":14400}
```

The default TTL is also 14,400 seconds, so this shorter request is equivalent:

```bash
curl -X POST "$ADMIN_API_BASE/api/admin/kill" \
  -H "X-Kill-Switch-Key: $KILL_SWITCH_API_KEY"
```

For an alternate TTL, send either the JSON body above or `?ttl=<seconds>`.
If both are provided, the query-string `ttl` wins to preserve existing callers.

## Deactivate From Curl

```bash
curl -X DELETE "$ADMIN_API_BASE/api/admin/kill" \
  -H "X-Kill-Switch-Key: $KILL_SWITCH_API_KEY"
```

Expected response:

```json
{"status":"deactivated"}
```

## Phone Shortcut

Create one shortcut named `Kill Switch On`:

1. Store `KILL_SWITCH_API_KEY` in a keychain-backed password manager or enter it
   as a private setup variable. Do not paste it into shared shortcut text.
2. Add `URL` with `$ADMIN_API_BASE/api/admin/kill`.
3. Add `Get Contents of URL`.
4. Set method to `POST`.
5. Add headers:
   - `X-Kill-Switch-Key`: the stored key
   - `Content-Type`: `application/json`
6. Set request body to JSON:

```json
{"ttl":14400}
```

Create a second shortcut named `Kill Switch Off` with the same URL and header,
but method `DELETE` and no request body.

## Status And Errors

| Status | Meaning |
| --- | --- |
| `200` | Request succeeded. Activation writes `kill_switch=active`; deactivation deletes it. |
| `403` | `X-Kill-Switch-Key` did not match `KILL_SWITCH_API_KEY`. |
| `503` | Server has no `KILL_SWITCH_API_KEY`; the route fails closed. |
| `422` | Request body or query parameter was malformed, usually a non-integer TTL. |

## TTL Semantics

Activation sets a Redis expiry. The default `14400` seconds is 4 hours. Repeating
the activation request refreshes the TTL. If no `DELETE` request is sent, Redis
automatically clears the kill switch when the TTL expires.

## Troubleshooting

- If activation returns `503`, configure `KILL_SWITCH_API_KEY` on the server and
  restart the FastAPI process.
- If activation returns `403`, compare the phone shortcut key with the server
  environment value. Header names are case-insensitive, but the key value is
  exact.
- If curl succeeds but a loop keeps running, confirm that loop is an autonomous
  Python orchestrator using the raw Redis client. Seeded simulation phases and
  future Node bot shutdown paths have separate halt coverage.

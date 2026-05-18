// Node→Python bridge client (issue #543, E4-4 — epic E4 #506).
//
// `./mindcraft` is git-ignored, so this file is the committed source of truth.
// `scripts/minecraft/connect-bridge-bot.sh` copies it verbatim into the pinned
// clone as `src/agent/bridge/python_bridge.js` — the E1-R5 / decision 0005
// extension point (docs/decisions/0005-skill-extension-point.md: "Add a Node
// bridge client module: src/agent/bridge/python_bridge.js"). The directory
// layout under `fork-src/` mirrors the clone's `src/` so the relative import in
// the sibling action (`../bridge/python_bridge.js`) resolves identically
// staged-in-the-clone or driven directly by the contract test.
//
// What this module is (and is NOT):
//   * IS: a single authenticated WebSocket call that builds a contract-valid
//     BridgeRequest envelope, correlates the response by `request_id`, enforces
//     a local timeout == `deadline_ms`, and fails CLOSED with a typed structured
//     error on auth/handshake/protocol failure — never an uncaught throw.
//   * IS NOT: reconnect / backpressure / a persistent pooled connection. That
//     is E4-5 (#544); per the epic scope guidance this issue stays a one-shot
//     connect→send→await→close so the `!bridgePing` proof and its failure paths
//     are exercised without pre-empting #544's contract.
//
// Wire format is fixed by ADR docs/decisions/0010-bridge-protocol.md (§2
// envelope, §3 versioning, §4 bearer auth, §5 deadline/fail-closed) and the
// versioned contract in core/bridge/contract.py (#541, E4-2). The committed
// JSON Schema core/bridge/schemas/bridge-protocol.schema.json is treated as
// REFERENCE only: this module does deliberately lightweight *structural*
// checks (object / boolean `ok` / `request_id` echo / typed `error` shape) and
// does NOT add a JSON-Schema validator dependency — the Mindcraft lockfile
// (scripts/minecraft/mindcraft-package-lock.json) is frozen.
//
// Transport: prefer the `ws` package (a transitive dep already pinned in that
// lockfile at 8.20.1 — it supports the `Authorization: Bearer` handshake header
// ADR §4 mandates). Fall back to the Node ≥20 global WHATWG `WebSocket` when
// `ws` is absent (e.g. the CI/contract-test environment with no Mindcraft
// install); that implementation cannot set request headers, so it uses the
// server's documented `?token=` query-param fallback
// (core/bridge/server.py:_extract_bearer_token) — still the SAME shared secret,
// still fail-closed, no anonymous path.

import { randomUUID } from 'node:crypto';

// ── Protocol / env constants (kept identical to the Python side) ─────────────

export const PROTOCOL_VERSION = '1.0'; // contract.PROTOCOL_VERSION (ADR §3)
export const BRIDGE_URL_ENV = 'MINECRAFT_BRIDGE_URL';
export const BRIDGE_TOKEN_ENV = 'MINECRAFT_BRIDGE_TOKEN'; // ADR §4 / server.BRIDGE_TOKEN_ENV
export const DEFAULT_BRIDGE_URL = 'ws://127.0.0.1:8010/api/minecraft/bridge/ws';

const DEFAULT_DEADLINE_MS = 5000;
const DEFAULT_AGENT_ID = 'bridge-bot';
const DEFAULT_RUN_ID = 'run-local';
// simulation_id only needs to be a non-empty string (contract min_length=1); a
// zeroed UUID is an obvious "local default, not a real run" marker.
const DEFAULT_SIMULATION_ID = '00000000-0000-0000-0000-000000000000';

// ── Typed structured error (carries a stable machine-readable code) ─────────

export class BridgeClientError extends Error {
    constructor(code, message, extra = {}) {
        super(message);
        this.name = 'BridgeClientError';
        this.code = code;
        // ADR §5: absence/ambiguity is treated as NOT retryable.
        this.retryable = extra.retryable === true;
        if (extra.response !== undefined) this.response = extra.response;
    }
}

// ── WebSocket implementation resolution (ws → global fallback) ──────────────

let _wsImpl = null;
let _wsSupportsHeaders = false;

async function resolveWebSocket() {
    if (_wsImpl) return;
    try {
        const mod = await import('ws');
        _wsImpl = mod.WebSocket || mod.default;
        _wsSupportsHeaders = true; // `ws` honors { headers: { Authorization } }
    } catch {
        _wsImpl = globalThis.WebSocket; // Node ≥20 WHATWG WebSocket (no headers)
        _wsSupportsHeaders = false;
    }
    if (!_wsImpl) {
        throw new BridgeClientError(
            'bridge_no_transport',
            'no WebSocket implementation: install the "ws" package or run Node >=20 (global WebSocket)',
        );
    }
}

function makeSocket(url, token) {
    if (_wsSupportsHeaders) {
        // ADR §4 primary: bearer token on the handshake request header.
        return new _wsImpl(url, { headers: { Authorization: `Bearer ${token}` } });
    }
    // Global WebSocket cannot set request headers — use the server's
    // documented ?token= fallback (same shared secret, still fail-closed).
    const u = new URL(url);
    u.searchParams.set('token', token);
    return new _wsImpl(u.toString());
}

// Normalize the `ws` EventEmitter API and the WHATWG addEventListener API so
// the call logic below is transport-agnostic.
function attachHandlers(sock, { onOpen, onMessage, onClose, onError }) {
    if (typeof sock.on === 'function') {
        // `ws` package (Node EventEmitter): message data is a Buffer/string.
        sock.on('open', () => onOpen());
        sock.on('message', (data) =>
            onMessage(typeof data === 'string' ? data : data.toString('utf8')),
        );
        sock.on('close', (code, reason) =>
            onClose(code, reason ? reason.toString() : ''),
        );
        sock.on('error', (err) => onError(err));
        // Emitted by `ws` when the HTTP upgrade is refused (e.g. 403 from a
        // fail-closed handshake rejection in core/bridge/server.py).
        sock.on('unexpected-response', (_req, res) =>
            onError(
                new Error(`unexpected server response: ${res && res.statusCode}`),
                res && res.statusCode,
            ),
        );
    } else {
        // WHATWG global WebSocket: message arrives as a MessageEvent.
        sock.addEventListener('open', () => onOpen());
        sock.addEventListener('message', (ev) =>
            onMessage(typeof ev.data === 'string' ? ev.data : String(ev.data)),
        );
        sock.addEventListener('close', (ev) => onClose(ev.code, ev.reason || ''));
        sock.addEventListener('error', (ev) =>
            onError((ev && ev.error) || new Error((ev && ev.message) || 'websocket error')),
        );
    }
}

// ── Envelope construction (ADR §2 — exact field set) ───────────────────────

function buildEnvelope({ service, method, payload, deadlineMs, agentId }) {
    return {
        version: PROTOCOL_VERSION,
        request_id: `bridge-${randomUUID()}`, // unique correlation + idempotency key (ADR §5)
        agent_id: agentId || process.env.LTAG_AGENT_ID || DEFAULT_AGENT_ID,
        run_id: process.env.LTAG_RUN_ID || DEFAULT_RUN_ID,
        simulation_id: process.env.LTAG_SIMULATION_ID || DEFAULT_SIMULATION_ID,
        service,
        method,
        payload: payload || {},
        deadline_ms: deadlineMs,
        cost_context: {
            agent_tier: 'conversation',
            budget_bucket: 'bridge',
            estimated_cost_usd: 0.0,
        },
    };
}

// Lightweight *structural* validation only — the JSON Schema is reference, not
// a runtime dependency (frozen lockfile). Returns a BridgeClientError to reject
// with, or null when the envelope shape is acceptable.
function validateResponseShape(response, expectedRequestId) {
    if (response === null || typeof response !== 'object' || Array.isArray(response)) {
        return new BridgeClientError('bridge_protocol', 'bridge response was not a JSON object');
    }
    if (typeof response.ok !== 'boolean') {
        return new BridgeClientError(
            'bridge_protocol',
            'bridge response is missing a boolean "ok" field',
        );
    }
    if (response.request_id !== expectedRequestId) {
        return new BridgeClientError(
            'bridge_protocol',
            `bridge response request_id ${JSON.stringify(response.request_id)} does not echo ` +
                `the request ${JSON.stringify(expectedRequestId)}`,
        );
    }
    if (
        response.ok === false &&
        (response.error === null ||
            typeof response.error !== 'object' ||
            typeof response.error.code !== 'string')
    ) {
        return new BridgeClientError(
            'bridge_protocol',
            'failed bridge response (ok=false) did not carry a typed error',
        );
    }
    return null;
}

// ── The one public entry point ─────────────────────────────────────────────

/**
 * Round-trip one contract message through the Python bridge.
 *
 * Resolves with the parsed BridgeResponse envelope on success (`ok===true`).
 * Rejects with a {@link BridgeClientError} (never an uncaught throw) on:
 *   - missing token / no transport               → fail closed before connect
 *   - handshake auth refusal (1008 / HTTP 403)   → `bridge_auth_refused`
 *   - connection error or early close            → `bridge_connect_failed`
 *   - local deadline exceeded                    → `bridge_timeout`
 *   - malformed / non-echoing response           → `bridge_protocol`
 *   - server `ok:false`                          → passes through `error.code`
 *
 * @param {object}  opts
 * @param {string}  opts.service     typed service name (ADR §6 closed set)
 * @param {string}  opts.method      method within the service
 * @param {object}  [opts.payload]   service-specific body
 * @param {number}  [opts.deadlineMs] hard local deadline (ADR §5), default 5000
 * @param {string}  [opts.agentId]   stable agent identity (a claim, not proof)
 * @returns {Promise<object>} the parsed response envelope
 */
export async function callBridge({
    service,
    method,
    payload = {},
    deadlineMs = DEFAULT_DEADLINE_MS,
    agentId,
} = {}) {
    const token = process.env[BRIDGE_TOKEN_ENV];
    if (!token) {
        // ADR §4: no anonymous / "auth optional in dev" path. Fail closed
        // before a socket is even opened.
        throw new BridgeClientError(
            'bridge_no_token',
            `${BRIDGE_TOKEN_ENV} is not set; refusing to open an unauthenticated bridge connection`,
        );
    }
    await resolveWebSocket();

    const url = process.env[BRIDGE_URL_ENV] || DEFAULT_BRIDGE_URL;
    const envelope = buildEnvelope({ service, method, payload, deadlineMs, agentId });

    return await new Promise((resolve, reject) => {
        let settled = false;
        let sock;

        // The deadline timer covers the WHOLE call (connect + round trip), so a
        // hung handshake or a silent server both surface as a structured
        // timeout rather than hanging the bot (ADR §5).
        const timer = setTimeout(() => {
            finish(() =>
                reject(
                    new BridgeClientError(
                        'bridge_timeout',
                        `bridge call ${service}.${method} exceeded local deadline of ${deadlineMs}ms`,
                    ),
                ),
            );
        }, deadlineMs);

        function finish(action) {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            try {
                if (sock) sock.close();
            } catch {
                /* closing a half-open socket must never mask the result */
            }
            action();
        }

        try {
            sock = makeSocket(url, token);
        } catch (err) {
            finish(() =>
                reject(
                    new BridgeClientError(
                        'bridge_connect_failed',
                        `could not open bridge socket: ${(err && err.message) || err}`,
                    ),
                ),
            );
            return;
        }

        attachHandlers(sock, {
            onOpen() {
                try {
                    sock.send(JSON.stringify(envelope));
                } catch (err) {
                    finish(() =>
                        reject(
                            new BridgeClientError(
                                'bridge_send_failed',
                                `failed to send bridge request: ${(err && err.message) || err}`,
                            ),
                        ),
                    );
                }
            },
            onMessage(text) {
                let response;
                try {
                    response = JSON.parse(text);
                } catch (err) {
                    finish(() =>
                        reject(
                            new BridgeClientError(
                                'bridge_protocol',
                                `bridge response was not valid JSON: ${(err && err.message) || err}`,
                            ),
                        ),
                    );
                    return;
                }
                const shapeError = validateResponseShape(response, envelope.request_id);
                if (shapeError) {
                    finish(() => reject(shapeError));
                    return;
                }
                if (response.ok === false) {
                    // Pass the server's typed error.code/message straight
                    // through so callers branch on a stable code (ADR §2/§5).
                    finish(() =>
                        reject(
                            new BridgeClientError(response.error.code, response.error.message, {
                                retryable: response.retryable === true,
                                response,
                            }),
                        ),
                    );
                    return;
                }
                finish(() => resolve(response));
            },
            onError(err, statusCode) {
                const authish = statusCode === 401 || statusCode === 403;
                finish(() =>
                    reject(
                        new BridgeClientError(
                            authish ? 'bridge_auth_refused' : 'bridge_connect_failed',
                            `bridge connection error: ${(err && err.message) || err}`,
                        ),
                    ),
                );
            },
            onClose(code, reason) {
                // Reached only if we close BEFORE resolving (settled guards the
                // normal close in finish()): a fail-closed handshake refusal
                // (ADR §4 → WS 1008) or the peer vanishing.
                const authish = code === 1008;
                finish(() =>
                    reject(
                        new BridgeClientError(
                            authish ? 'bridge_auth_refused' : 'bridge_connect_failed',
                            `bridge socket closed before a response (code=${code}` +
                                `${reason ? `, reason=${reason}` : ''})`,
                        ),
                    ),
                );
            },
        });
    });
}

export default { callBridge, BridgeClientError, PROTOCOL_VERSION, DEFAULT_BRIDGE_URL };

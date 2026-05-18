// The `!bridgePing` custom Mindcraft action (issue #543 E4-4 + #544 E4-5 —
// epic E4 #506).
//
// Committed source of truth (`./mindcraft` is git-ignored).
// `scripts/minecraft/connect-bridge-bot.sh` copies this verbatim into the
// pinned clone as `src/agent/commands/bridge_ping_action.js` and injects
// `bridgePingAction` into the `actionsList` array in
// `src/agent/commands/actions.js` (the decision 0005 extension point: "Add
// explicit commands/actions in src/agent/commands/actions.js"). The object
// shape matches Mindcraft's actionsList entries verbatim — `{ name,
// description, params, perform: async function(agent, ...) }` — per the ADR
// evidence (mindcraft-bots/mindcraft@35be480 src/agent/commands/actions.js
// L28-52).
//
// This is the ADR's "First proof: `!bridgePing`"
// (docs/decisions/0010-bridge-protocol.md → "First proof"): an in-game action
// that round-trips a request envelope through the Python bridge and reports the
// `pong`. CRITICAL behavior contract (issue #543 acceptance): the success path
// logs the Python response; the failure path is logged with the structured
// `error.code`/message and the action returns a status string — it is wrapped
// so a bridge failure is never an uncaught throw and never crashes the bot.
// E4-5 (#544) extends that contract: a down/saturated bridge surfaces as
// `bridge_unreachable`/`bridge_overloaded`, which this action treats as an
// explicit SAFE-IDLE (logged, no in-world action) — a closed gate, never an
// unsafe action (ADR 0010 §5). The client's background probe auto-recovers.

import { callBridge, BridgeClientError } from '../bridge/python_bridge.js';

export const bridgePingAction = {
    name: '!bridgePing',
    description:
        'Round-trip a ping through the Python bridge and report the pong ' +
        '(E4-4 bridge connectivity proof).',
    params: {
        message: {
            type: 'string',
            description: 'Text to send to Python; it is echoed back as "pong".',
        },
    },
    perform: async function (agent, message) {
        // Mindcraft passes declared params positionally after `agent`; default
        // so a bare `!bridgePing` still proves the channel.
        const text = message === undefined || message === null ? 'hello' : String(message);

        // `agent.openChat` puts a line in Minecraft chat when available; both it
        // and console logging are best-effort so logging can never itself crash
        // the bot. `agent` may be absent when the action is unit-driven.
        const announce = (line, isError) => {
            try {
                if (agent && typeof agent.openChat === 'function') agent.openChat(line);
            } catch {
                /* chat is cosmetic; never let it mask the bridge result */
            }
            if (isError) console.error(`[bridgePing] ${line}`);
            else console.log(`[bridgePing] ${line}`);
        };

        try {
            const response = await callBridge({
                service: 'bridge',
                method: 'ping',
                payload: { message: text },
                deadlineMs: 5000,
                agentId: agent && agent.name,
            });
            const pong =
                response && response.payload ? response.payload.pong : undefined;
            const line = `bridge pong: ${pong}`;
            announce(line, false);
            return line;
        } catch (err) {
            // Fail closed and LOUD-in-logs, never thrown: structured error.code
            // first, then the human message (ADR §2/§5).
            const code = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
            const detail = err && err.message ? err.message : String(err);
            // E4-5 (#544): a down (circuit open) or saturated (in-flight cap)
            // bridge is a CLOSED gate, never an unsafe action (ADR 0010 §5).
            // Degrade to an explicit SAFE-IDLE: log it, take no in-world
            // action, return a status string — same never-crash contract. The
            // background reconnect probe auto-recovers; a later call succeeds.
            if (code === 'bridge_unreachable' || code === 'bridge_overloaded') {
                const idle = `bridge unavailable, safe-idling [${code}]: ${detail}`;
                announce(idle, true);
                return idle; // safe-idle, not crashed — no in-world action
            }
            const line = `bridge ping failed [${code}]: ${detail}`;
            announce(line, true);
            return line; // logged, not crashed — the bot keeps running
        }
    },
};

export default bridgePingAction;

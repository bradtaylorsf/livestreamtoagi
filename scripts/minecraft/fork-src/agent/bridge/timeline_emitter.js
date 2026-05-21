// Best-effort structured timeline event writer for local Minecraft soak runs.
//
// This module is staged into the git-ignored Mindcraft clone by the committed
// launch scripts. It is deliberately dependency-free and fail-open for logging:
// telemetry must never crash or slow the bot's action path.

import { appendFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';

let sequence = 0;

function clean(value) {
    if (value === undefined || value === null || value === '') return null;
    return String(value);
}

function eventPath(agent) {
    const explicit = process.env.MC_TIMELINE_NDJSON;
    if (explicit) return explicit;
    const runDir = process.env.MC_RUN_DIR;
    if (!runDir) return null;
    const safeAgent = clean(agent) || clean(process.env.LTAG_AGENT_ID) || 'unknown';
    return join(runDir, 'timeline-raw', `${safeAgent}.ndjson`);
}

export function emitTimelineEvent({ type, eventType, agent, traceId, payload = {}, ts } = {}) {
    try {
        const resolvedType = eventType || type;
        if (!resolvedType) return;
        const resolvedAgent = clean(agent) || clean(process.env.LTAG_AGENT_ID);
        const path = eventPath(resolvedAgent);
        if (!path) return;
        mkdirSync(dirname(path), { recursive: true });
        sequence += 1;
        const event = {
            ts: ts || new Date().toISOString(),
            seq: sequence,
            event_type: resolvedType,
            agent: resolvedAgent,
            trace_id: clean(traceId) || clean(payload && (payload.trace_id || payload.traceId)),
            source: 'mindcraft.timeline_emitter',
            payload: payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {},
        };
        appendFileSync(path, `${JSON.stringify(event)}\n`, 'utf8');
    } catch {
        // best-effort only: timeline I/O must never affect bot behavior
    }
}

export default { emitTimelineEvent };

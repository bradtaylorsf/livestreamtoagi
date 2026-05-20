// Management content gate for bot-emitted Minecraft chat (E8-7 / #578).
//
// This file is staged beside python_bridge.js in the pinned Mindcraft clone.
// Callers must await reviewChat before any bot.chat, bot.whisper, TTS, or
// MindServer output path. Bridge failures are fail-closed.

import { callBridge } from './python_bridge.js';

export const MANAGEMENT_REVIEW_DEADLINE_MS = 3000;

function _cleanSanitizedText(value) {
    if (typeof value !== 'string') return null;
    const cleaned = value.trim();
    return cleaned.length > 0 ? cleaned : null;
}

export async function reviewChat({ agentId, text, context = {} } = {}) {
    if (!agentId || typeof text !== 'string') {
        return {
            allow: false,
            sanitized: null,
            reason: 'invalid management review input',
            retryable: false,
        };
    }

    try {
        const response = await callBridge({
            service: 'management',
            method: 'review',
            payload: {
                agent_id: agentId,
                text,
                context,
            },
            deadlineMs: MANAGEMENT_REVIEW_DEADLINE_MS,
            agentId,
            costContext: {
                agent_tier: 'filter',
                budget_bucket: 'management',
                estimated_cost_usd: 0.0,
            },
        });

        const payload = response && response.payload ? response.payload : {};
        const sanitized = _cleanSanitizedText(payload.sanitized_text);
        return {
            allow: payload.verdict === 'allow' || sanitized !== null,
            sanitized,
            reason: typeof payload.reason === 'string' ? payload.reason : '',
            retryable: false,
        };
    } catch (err) {
        const code = err && err.code ? err.code : 'management_review_failed';
        try {
            process.stderr.write(
                `management_review_event agent_id=${agentId} allow=false outcome=${code}\n`,
            );
        } catch {
            /* logging must not make a blocked review visible */
        }
        return {
            allow: false,
            sanitized: null,
            reason: code,
            retryable: !!(err && err.retryable),
        };
    }
}

export default {
    MANAGEMENT_REVIEW_DEADLINE_MS,
    reviewChat,
};

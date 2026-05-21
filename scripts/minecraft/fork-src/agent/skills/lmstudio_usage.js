// LM Studio request/response timeline capture for staged Mindcraft clones.
//
// Importing this module monkey-patches global fetch once. The OpenAI SDK used
// by Mindcraft sends LM Studio requests through fetch, so this records
// llm.request/llm.response events without editing the git-ignored clone or
// adding npm dependencies.

import { randomUUID } from 'node:crypto';

import { emitTimelineEvent } from '../bridge/timeline_emitter.js';

const PATCH_FLAG = Symbol.for('livestreamtoagi.lmstudioUsageFetchPatch');

function deterministicTokenEstimate(value) {
    let text = '';
    if (typeof value === 'string') {
        text = value;
    } else if (value !== undefined && value !== null) {
        try {
            text = JSON.stringify(value);
        } catch {
            text = String(value);
        }
    }
    return text.length > 0 ? Math.max(1, Math.ceil(text.length / 4)) : 0;
}

function requestUrl(input) {
    try {
        if (typeof input === 'string') return input;
        if (input instanceof URL) return input.toString();
        if (input && typeof input.url === 'string') return input.url;
    } catch {
        return '';
    }
    return '';
}

function requestBody(input, init) {
    if (init && init.body !== undefined) return init.body;
    if (input && typeof input === 'object' && input.body !== undefined) return input.body;
    return undefined;
}

function parseBody(body) {
    if (typeof body !== 'string') return {};
    try {
        const parsed = JSON.parse(body);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
}

function isLmStudioCompletion(url) {
    if (!url) return false;
    try {
        const parsed = new URL(url);
        return (
            /(^|\.)localhost$|^127\.0\.0\.1$/.test(parsed.hostname) &&
            (parsed.pathname.endsWith('/chat/completions') ||
                parsed.pathname.endsWith('/completions'))
        );
    } catch {
        return url.includes('/v1/chat/completions') || url.includes('/v1/completions');
    }
}

function responseText(json) {
    if (!json || typeof json !== 'object') return '';
    if (Array.isArray(json.choices)) {
        return json.choices
            .map((choice) => {
                if (choice && choice.message && typeof choice.message.content === 'string') {
                    return choice.message.content;
                }
                if (choice && typeof choice.text === 'string') return choice.text;
                return '';
            })
            .join('\n');
    }
    if (typeof json.output_text === 'string') return json.output_text;
    return '';
}

function usagePayload({ body, json, latencyMs, outcome, status }) {
    const usage = json && typeof json.usage === 'object' ? json.usage : {};
    const hasProviderUsage =
        Number.isFinite(usage.prompt_tokens) ||
        Number.isFinite(usage.completion_tokens) ||
        Number.isFinite(usage.total_tokens);
    const promptTokens = Number.isFinite(usage.prompt_tokens)
        ? usage.prompt_tokens
        : deterministicTokenEstimate(body.messages || body.prompt || body.input || body);
    const completionTokens = Number.isFinite(usage.completion_tokens)
        ? usage.completion_tokens
        : deterministicTokenEstimate(responseText(json));
    const totalTokens = Number.isFinite(usage.total_tokens)
        ? usage.total_tokens
        : promptTokens + completionTokens;
    return {
        model: body.model || 'unknown',
        purpose: body.__ltag_purpose || process.env.MC_LLM_REQUEST_PURPOSE || 'mindcraft.lmstudio',
        reason: body.__ltag_reason || process.env.MC_LLM_REQUEST_REASON || 'mindcraft_completion',
        latency_ms: latencyMs,
        prompt_tokens: promptTokens,
        completion_tokens: completionTokens,
        total_tokens: totalTokens,
        estimated: !hasProviderUsage,
        usage_source: hasProviderUsage ? 'provider_reported' : 'estimated',
        outcome,
        status,
    };
}

function emitRequest({ agent, traceId, body }) {
    const promptTokens = deterministicTokenEstimate(body.messages || body.prompt || body.input || body);
    emitTimelineEvent({
        type: 'llm.request',
        agent,
        traceId,
        payload: {
            model: body.model || 'unknown',
            purpose: body.__ltag_purpose || process.env.MC_LLM_REQUEST_PURPOSE || 'mindcraft.lmstudio',
            reason: body.__ltag_reason || process.env.MC_LLM_REQUEST_REASON || 'mindcraft_completion',
            prompt_tokens: promptTokens,
            completion_tokens: 0,
            total_tokens: promptTokens,
            latency_ms: 0,
            estimated: true,
            usage_source: 'estimated',
            outcome: 'started',
        },
    });
}

export function installLmstudioUsageCapture() {
    try {
        if (globalThis[PATCH_FLAG]) return;
        if (typeof globalThis.fetch !== 'function') return;
        const originalFetch = globalThis.fetch.bind(globalThis);
        globalThis[PATCH_FLAG] = true;

        globalThis.fetch = async function ltagTimelineFetch(input, init) {
            const url = requestUrl(input);
            if (!isLmStudioCompletion(url)) {
                return originalFetch(input, init);
            }

            const body = parseBody(requestBody(input, init));
            const traceId = `trace-llm-${randomUUID()}`;
            const agent = process.env.LTAG_AGENT_ID || process.env.MC_AGENT_ID || body.agent;
            const startedAt = Date.now();
            emitRequest({ agent, traceId, body });

            try {
                const response = await originalFetch(input, init);
                if (body.stream === true) {
                    emitTimelineEvent({
                        type: 'llm.response',
                        agent,
                        traceId,
                        payload: usagePayload({
                            body,
                            json: null,
                            latencyMs: Date.now() - startedAt,
                            outcome: response.ok ? 'streaming_uninspected' : 'http_error',
                            status: response.status,
                        }),
                    });
                    return response;
                }
                let json = null;
                try {
                    json = await response.clone().json();
                } catch {
                    json = null;
                }
                emitTimelineEvent({
                    type: 'llm.response',
                    agent,
                    traceId,
                    payload: usagePayload({
                        body,
                        json,
                        latencyMs: Date.now() - startedAt,
                        outcome: response.ok ? 'ok' : 'http_error',
                        status: response.status,
                    }),
                });
                return response;
            } catch (err) {
                emitTimelineEvent({
                    type: 'llm.response',
                    agent,
                    traceId,
                    payload: {
                        ...usagePayload({
                            body,
                            json: null,
                            latencyMs: Date.now() - startedAt,
                            outcome: 'error',
                            status: 0,
                        }),
                        error: err && err.message ? err.message : String(err),
                    },
                });
                throw err;
            }
        };
    } catch {
        // Telemetry is best-effort. A patch failure must not change model calls.
    }
}

installLmstudioUsageCapture();

export { deterministicTokenEstimate };

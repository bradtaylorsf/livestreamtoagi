// Builder-plan provider routing and budget enforcement.
//
// Normal Mindcraft conversation stays on the profile chat model. This helper is
// only imported by !planAndBuild so OpenRouter can be enabled for JSON plan
// generation without affecting ordinary chat/action selection.

import { randomUUID } from 'node:crypto';
import {
    closeSync,
    existsSync,
    mkdirSync,
    openSync,
    readFileSync,
    renameSync,
    unlinkSync,
    writeFileSync,
} from 'node:fs';
import path from 'node:path';

import { emitTimelineEvent } from '../bridge/timeline_emitter.js';

const OPENROUTER_CHAT_COMPLETIONS_URL = 'https://openrouter.ai/api/v1/chat/completions';
const DEFAULT_MAX_CALLS_PER_RUN = 12;
const DEFAULT_MAX_CALLS_PER_AGENT = 3;
const DEFAULT_ESTIMATED_OUTPUT_TOKENS = 800;

const providerState = {
    runCalls: 0,
    runEstimatedUsd: 0,
    agentCalls: new Map(),
    failures: 0,
};

function sleepSync(ms) {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function sharedBudgetFiles() {
    const runDir = normalizedEnv('MC_RUN_DIR');
    if (!runDir) return null;
    mkdirSync(runDir, { recursive: true });
    return {
        statePath: path.join(runDir, 'builder-provider-budget.json'),
        lockPath: path.join(runDir, 'builder-provider-budget.lock'),
    };
}

function emptySharedBudget() {
    return { runCalls: 0, runEstimatedUsd: 0, agentCalls: {} };
}

function readSharedBudget(statePath) {
    if (!existsSync(statePath)) return emptySharedBudget();
    try {
        const parsed = JSON.parse(readFileSync(statePath, 'utf8'));
        return {
            runCalls: Number.isFinite(Number(parsed.runCalls)) ? Number(parsed.runCalls) : 0,
            runEstimatedUsd: Number.isFinite(Number(parsed.runEstimatedUsd))
                ? Number(parsed.runEstimatedUsd)
                : 0,
            agentCalls:
                parsed.agentCalls && typeof parsed.agentCalls === 'object'
                    ? parsed.agentCalls
                    : {},
        };
    } catch {
        return emptySharedBudget();
    }
}

function writeSharedBudget(statePath, state) {
    const tmpPath = `${statePath}.${process.pid}.${Date.now()}.tmp`;
    writeFileSync(tmpPath, `${JSON.stringify(state)}\n`, 'utf8');
    renameSync(tmpPath, statePath);
}

function withSharedBudgetLock(files, fn) {
    const deadline = Date.now() + nonNegativeIntEnv('MC_SIM_BUILDER_BUDGET_LOCK_TIMEOUT_MS', 5000);
    let fd = null;
    while (fd === null) {
        try {
            fd = openSync(files.lockPath, 'wx');
            writeFileSync(fd, `${process.pid}\n`, 'utf8');
        } catch (err) {
            if (err && err.code !== 'EEXIST') throw err;
            if (Date.now() > deadline) {
                throw new BuilderBudgetError(
                    'budget_lock_timeout',
                    'builder OpenRouter shared budget lock timed out',
                    { lock_path: files.lockPath },
                );
            }
            sleepSync(25);
        }
    }
    try {
        return fn();
    } finally {
        try {
            closeSync(fd);
        } catch {
            /* ignore */
        }
        try {
            unlinkSync(files.lockPath);
        } catch {
            /* ignore */
        }
    }
}

export class BuilderProviderError extends Error {
    constructor(code, message, options = {}) {
        super(message);
        this.name = 'BuilderProviderError';
        this.code = code;
        this.provider = options.provider || null;
        this.reason = options.reason || code;
        this.fatal = Boolean(options.fatal);
        this.metadata = options.metadata || {};
    }
}

export class BuilderBudgetError extends BuilderProviderError {
    constructor(reason, message, metadata = {}) {
        super('builder_budget_exceeded', message, {
            provider: 'openrouter',
            reason,
            fatal: true,
            metadata,
        });
        this.name = 'BuilderBudgetError';
    }
}

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || process.env.LTAG_AGENT_ID || 'agent';
}

function normalizedEnv(name, fallback = '') {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    return String(raw).trim();
}

function normalizedProvider() {
    return normalizedEnv('MC_SIM_BUILDER_PROVIDER', 'local').toLowerCase();
}

function fallbackMode() {
    const raw = normalizedEnv('MC_SIM_BUILDER_FALLBACK', 'fail').toLowerCase();
    return raw === 'local' ? 'local' : 'fail';
}

function nonNegativeIntEnv(name, fallback) {
    const raw = normalizedEnv(name);
    if (!raw) return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function optionalNonNegativeNumberEnv(name) {
    const raw = normalizedEnv(name);
    if (!raw) return null;
    const parsed = Number.parseFloat(raw);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function numberEnv(name, fallback) {
    const raw = normalizedEnv(name);
    if (!raw) return fallback;
    const parsed = Number.parseFloat(raw);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function localBuilderModel(agent) {
    const model = agent && agent.prompter && agent.prompter.code_model;
    return model && typeof model.sendRequest === 'function' ? model : null;
}

function localBuilderModelName(agent) {
    const model = localBuilderModel(agent);
    return (
        (model && (model.model_name || model.modelName || model.name || model.id)) ||
        normalizedEnv('LOCAL_LLM_MODEL_BUILDING') ||
        normalizedEnv('LOCAL_LLM_MODEL') ||
        'local/code_model'
    );
}

function estimateTokens(value) {
    if (value === null || value === undefined) return 0;
    const text = typeof value === 'string' ? value : JSON.stringify(value);
    return text ? Math.max(1, Math.ceil(text.length / 4)) : 0;
}

function estimatePromptTokens(messages, systemMessage) {
    return estimateTokens(systemMessage) + estimateTokens(messages);
}

function estimateCostUsd(promptTokens, completionTokens) {
    const inputRate = numberEnv('MC_SIM_BUILDER_USD_PER_1K_INPUT', 0);
    const outputRate = numberEnv('MC_SIM_BUILDER_USD_PER_1K_OUTPUT', 0);
    return (promptTokens / 1000) * inputRate + (completionTokens / 1000) * outputRate;
}

function roundedUsd(value) {
    return Number(value.toFixed(8));
}

function agentCounter(agentKey) {
    if (!providerState.agentCalls.has(agentKey)) {
        providerState.agentCalls.set(agentKey, { calls: 0, estimatedUsd: 0 });
    }
    return providerState.agentCalls.get(agentKey);
}

function currentBudgetConfig() {
    return {
        max_calls_per_run: nonNegativeIntEnv(
            'MC_SIM_BUILDER_MAX_CALLS_PER_RUN',
            DEFAULT_MAX_CALLS_PER_RUN,
        ),
        max_calls_per_agent: nonNegativeIntEnv(
            'MC_SIM_BUILDER_MAX_CALLS_PER_AGENT',
            DEFAULT_MAX_CALLS_PER_AGENT,
        ),
        max_estimated_usd_per_run: optionalNonNegativeNumberEnv('MC_SIM_BUILDER_MAX_USD_PER_RUN'),
    };
}

function reserveOpenRouterCall(agentKey, estimatedUsd) {
    const budget = currentBudgetConfig();
    const sharedFiles = sharedBudgetFiles();
    if (sharedFiles) {
        return withSharedBudgetLock(sharedFiles, () => {
            const shared = readSharedBudget(sharedFiles.statePath);
            const sharedAgent = shared.agentCalls[agentKey] || { calls: 0, estimatedUsd: 0 };
            if (shared.runCalls >= budget.max_calls_per_run) {
                throw new BuilderBudgetError(
                    'run_call_cap',
                    `builder OpenRouter run call cap reached (${budget.max_calls_per_run})`,
                    { ...budget, request_count_run: shared.runCalls, shared: true },
                );
            }
            if (sharedAgent.calls >= budget.max_calls_per_agent) {
                throw new BuilderBudgetError(
                    'agent_call_cap',
                    `builder OpenRouter agent call cap reached (${budget.max_calls_per_agent})`,
                    {
                        ...budget,
                        request_count_run: shared.runCalls,
                        request_count_agent: sharedAgent.calls,
                        shared: true,
                    },
                );
            }
            if (
                budget.max_estimated_usd_per_run !== null &&
                shared.runEstimatedUsd + estimatedUsd > budget.max_estimated_usd_per_run
            ) {
                throw new BuilderBudgetError(
                    'run_usd_cap',
                    `builder OpenRouter estimated USD cap would be exceeded (${budget.max_estimated_usd_per_run})`,
                    {
                        ...budget,
                        estimated_usd_run: roundedUsd(shared.runEstimatedUsd),
                        next_estimated_usd: roundedUsd(estimatedUsd),
                        shared: true,
                    },
                );
            }

            shared.runCalls += 1;
            shared.runEstimatedUsd += estimatedUsd;
            sharedAgent.calls += 1;
            sharedAgent.estimatedUsd = Number(sharedAgent.estimatedUsd || 0) + estimatedUsd;
            shared.agentCalls[agentKey] = sharedAgent;
            writeSharedBudget(sharedFiles.statePath, shared);

            providerState.runCalls = shared.runCalls;
            providerState.runEstimatedUsd = shared.runEstimatedUsd;
            const localAgentBudget = agentCounter(agentKey);
            localAgentBudget.calls = sharedAgent.calls;
            localAgentBudget.estimatedUsd = sharedAgent.estimatedUsd;
            return {
                ...budget,
                request_count_run: shared.runCalls,
                request_count_agent: sharedAgent.calls,
                estimated_usd_run: roundedUsd(shared.runEstimatedUsd),
                estimated_usd_agent: roundedUsd(sharedAgent.estimatedUsd),
                reserved_estimated_usd: roundedUsd(estimatedUsd),
                shared: true,
            };
        });
    }
    const agentBudget = agentCounter(agentKey);
    if (providerState.runCalls >= budget.max_calls_per_run) {
        throw new BuilderBudgetError(
            'run_call_cap',
            `builder OpenRouter run call cap reached (${budget.max_calls_per_run})`,
            { ...budget, request_count_run: providerState.runCalls },
        );
    }
    if (agentBudget.calls >= budget.max_calls_per_agent) {
        throw new BuilderBudgetError(
            'agent_call_cap',
            `builder OpenRouter agent call cap reached (${budget.max_calls_per_agent})`,
            {
                ...budget,
                request_count_run: providerState.runCalls,
                request_count_agent: agentBudget.calls,
            },
        );
    }
    if (
        budget.max_estimated_usd_per_run !== null &&
        providerState.runEstimatedUsd + estimatedUsd > budget.max_estimated_usd_per_run
    ) {
        throw new BuilderBudgetError(
            'run_usd_cap',
            `builder OpenRouter estimated USD cap would be exceeded (${budget.max_estimated_usd_per_run})`,
            {
                ...budget,
                estimated_usd_run: roundedUsd(providerState.runEstimatedUsd),
                next_estimated_usd: roundedUsd(estimatedUsd),
            },
        );
    }

    providerState.runCalls += 1;
    providerState.runEstimatedUsd += estimatedUsd;
    agentBudget.calls += 1;
    agentBudget.estimatedUsd += estimatedUsd;
    return {
        ...budget,
        request_count_run: providerState.runCalls,
        request_count_agent: agentBudget.calls,
        estimated_usd_run: roundedUsd(providerState.runEstimatedUsd),
        estimated_usd_agent: roundedUsd(agentBudget.estimatedUsd),
        reserved_estimated_usd: roundedUsd(estimatedUsd),
    };
}

function adjustOpenRouterCost(agentKey, reservation, actualUsd) {
    const delta = actualUsd - reservation.reserved_estimated_usd;
    if (!Number.isFinite(delta) || Math.abs(delta) < 1e-12) return;
    const sharedFiles = reservation.shared ? sharedBudgetFiles() : null;
    if (sharedFiles) {
        withSharedBudgetLock(sharedFiles, () => {
            const shared = readSharedBudget(sharedFiles.statePath);
            const sharedAgent = shared.agentCalls[agentKey] || { calls: 0, estimatedUsd: 0 };
            shared.runEstimatedUsd += delta;
            sharedAgent.estimatedUsd = Number(sharedAgent.estimatedUsd || 0) + delta;
            shared.agentCalls[agentKey] = sharedAgent;
            writeSharedBudget(sharedFiles.statePath, shared);
            providerState.runEstimatedUsd = shared.runEstimatedUsd;
            const localAgentBudget = agentCounter(agentKey);
            localAgentBudget.estimatedUsd = sharedAgent.estimatedUsd;
        });
        return;
    }
    providerState.runEstimatedUsd += delta;
    const agentBudget = agentCounter(agentKey);
    agentBudget.estimatedUsd += delta;
}

function emitLlmEvent(agentKey, type, traceId, payload = {}) {
    emitTimelineEvent({
        type,
        agent: agentKey,
        traceId,
        payload,
    });
}

function messageArray(messages, systemMessage) {
    const base = Array.isArray(messages) ? [...messages] : [];
    if (systemMessage) {
        return [{ role: 'system', content: String(systemMessage) }, ...base];
    }
    return base;
}

function openRouterApiKey() {
    return normalizedEnv('MC_SIM_BUILDER_OPENROUTER_API_KEY') || normalizedEnv('OPENROUTER_API_KEY');
}

function openRouterModel() {
    return normalizedEnv('MC_SIM_BUILDER_OPENROUTER_MODEL');
}

function contentFromOpenRouterResponse(data) {
    const choices = data && Array.isArray(data.choices) ? data.choices : [];
    const first = choices[0] || {};
    const message = first.message || {};
    const content = message.content ?? first.text;
    if (typeof content !== 'string' || !content.trim()) {
        throw new BuilderProviderError(
            'openrouter_empty_response',
            'OpenRouter builder response did not include message content',
            { provider: 'openrouter' },
        );
    }
    return content;
}

function usageFromOpenRouterResponse(data, promptTokens, fallbackCompletionTokens) {
    const usage = data && typeof data.usage === 'object' && data.usage ? data.usage : {};
    const prompt = Number.isFinite(Number(usage.prompt_tokens))
        ? Number(usage.prompt_tokens)
        : promptTokens;
    const completion = Number.isFinite(Number(usage.completion_tokens))
        ? Number(usage.completion_tokens)
        : fallbackCompletionTokens;
    const reasoning = Number.isFinite(Number(usage.reasoning_tokens))
        ? Number(usage.reasoning_tokens)
        : Number.isFinite(Number(usage.completion_tokens_details?.reasoning_tokens))
          ? Number(usage.completion_tokens_details.reasoning_tokens)
          : 0;
    const total = Number.isFinite(Number(usage.total_tokens))
        ? Number(usage.total_tokens)
        : prompt + completion;
    const providerReported =
        usage.prompt_tokens !== undefined ||
        usage.total_tokens !== undefined ||
        usage.reasoning_tokens !== undefined ||
        usage.completion_tokens_details?.reasoning_tokens !== undefined;
    return {
        prompt_tokens: Math.max(0, Math.floor(prompt)),
        completion_tokens: Math.max(0, Math.floor(completion)),
        reasoning_tokens: Math.max(0, Math.floor(reasoning)),
        total_tokens: Math.max(0, Math.floor(total)),
        billable_total_tokens: Math.max(0, Math.floor(total + reasoning)),
        estimated: !providerReported,
        usage_source: providerReported ? 'provider_reported' : 'estimated',
    };
}

function openRouterError(message, metadata = {}) {
    providerState.failures += 1;
    return new BuilderProviderError('openrouter_request_failed', message, {
        provider: 'openrouter',
        reason: 'request_failed',
        metadata: {
            failures: providerState.failures,
            ...metadata,
        },
    });
}

function localResolved(agent, fallbackReason = '') {
    const model = localBuilderModel(agent);
    return {
        provider: 'local',
        model: localBuilderModelName(agent),
        paid: false,
        available: Boolean(model),
        fallbackMode: fallbackMode(),
        fallbackReason,
        request_count_run: 0,
        request_count_agent: 0,
        estimated_usd: 0,
        lastMetadata: null,
        async sendRequest(messages, systemMessage) {
            if (!model) {
                throw new BuilderProviderError(
                    'missing_local_builder_model',
                    'local builder code_model is not available',
                    { provider: 'local', reason: 'missing_local_builder_model' },
                );
            }
            return model.sendRequest(messages, systemMessage);
        },
    };
}

function openRouterResolved(agent, apiKey, modelName) {
    const agentKey = agentId(agent).toLowerCase();
    const resolved = {
        provider: 'openrouter',
        model: modelName,
        paid: true,
        available: true,
        fallbackMode: fallbackMode(),
        fallbackReason: '',
        request_count_run: providerState.runCalls,
        request_count_agent: agentCounter(agentKey).calls,
        estimated_usd: roundedUsd(providerState.runEstimatedUsd),
        lastMetadata: null,
        async sendRequest(messages, systemMessage, context = {}) {
            const purpose = context.purpose || process.env.MC_LLM_REQUEST_PURPOSE || '';
            if (purpose !== 'plan_generation') {
                throw new BuilderProviderError(
                    'invalid_builder_purpose',
                    'OpenRouter builder calls require purpose=plan_generation',
                    { provider: 'openrouter', reason: 'invalid_builder_purpose', fatal: true },
                );
            }
            if (typeof globalThis.fetch !== 'function') {
                throw new BuilderProviderError(
                    'missing_fetch',
                    'global fetch is not available for OpenRouter builder routing',
                    { provider: 'openrouter', reason: 'missing_fetch', fatal: true },
                );
            }

            const traceId = context.traceId || `trace-${randomUUID()}`;
            const requestMessages = messageArray(messages, systemMessage);
            const promptTokens = estimatePromptTokens(messages, systemMessage);
            const estimatedCompletionTokens = nonNegativeIntEnv(
                'MC_SIM_BUILDER_ESTIMATED_OUTPUT_TOKENS',
                DEFAULT_ESTIMATED_OUTPUT_TOKENS,
            );
            const reservedUsd = estimateCostUsd(promptTokens, estimatedCompletionTokens);
            const reservation = reserveOpenRouterCall(agentKey, reservedUsd);
            resolved.request_count_run = reservation.request_count_run;
            resolved.request_count_agent = reservation.request_count_agent;
            resolved.estimated_usd = reservation.estimated_usd_run;

            const basePayload = {
                provider: 'openrouter',
                model: modelName,
                purpose: 'plan_generation',
                reason: 'planAndBuild',
                paid: true,
                prompt_tokens: promptTokens,
                completion_tokens: 0,
                total_tokens: promptTokens,
                estimated: true,
                usage_source: 'estimated',
                estimated_usd: reservation.reserved_estimated_usd,
                request_count_run: reservation.request_count_run,
                request_count_agent: reservation.request_count_agent,
                max_calls_per_run: reservation.max_calls_per_run,
                max_calls_per_agent: reservation.max_calls_per_agent,
                max_estimated_usd_per_run: reservation.max_estimated_usd_per_run,
                outcome: 'started',
            };
            emitLlmEvent(agentKey, 'llm.request', traceId, basePayload);

            const started = Date.now();
            try {
                const response = await globalThis.fetch(OPENROUTER_CHAT_COMPLETIONS_URL, {
                    method: 'POST',
                    headers: {
                        Authorization: `Bearer ${apiKey}`,
                        'Content-Type': 'application/json',
                        'HTTP-Referer': 'https://github.com/bradtaylor/livestreamtoagi',
                        'X-Title': 'Livestream to AGI Minecraft builder plan',
                        'X-LTAG-Skip-Usage-Capture': '1',
                    },
                    body: JSON.stringify({
                        model: modelName,
                        messages: requestMessages,
                    }),
                });
                const text = await response.text();
                if (!response.ok) {
                    throw openRouterError(`OpenRouter builder request failed with HTTP ${response.status}`, {
                        status: response.status,
                        body: text.slice(0, 500),
                    });
                }
                let data;
                try {
                    data = JSON.parse(text);
                } catch (err) {
                    throw openRouterError(
                        `OpenRouter builder response was not JSON: ${
                            err && err.message ? err.message : String(err)
                        }`,
                        { body: text.slice(0, 500) },
                    );
                }
                const content = contentFromOpenRouterResponse(data);
                const usage = usageFromOpenRouterResponse(
                    data,
                    promptTokens,
                    estimateTokens(content),
                );
                const actualUsd = estimateCostUsd(usage.prompt_tokens, usage.completion_tokens);
                adjustOpenRouterCost(agentKey, reservation, actualUsd);
                const metadata = {
                    ...basePayload,
                    ...usage,
                    estimated_usd: roundedUsd(actualUsd),
                    estimated_usd_run: roundedUsd(providerState.runEstimatedUsd),
                    latency_ms: Date.now() - started,
                    outcome: 'ok',
                };
                resolved.lastMetadata = metadata;
                resolved.estimated_usd = metadata.estimated_usd_run;
                emitLlmEvent(agentKey, 'llm.response', traceId, {
                    ...metadata,
                    response_text: content,
                });
                return content;
            } catch (err) {
                const wrapped =
                    err instanceof BuilderProviderError
                        ? err
                        : openRouterError(err && err.message ? err.message : String(err));
                const metadata = {
                    ...basePayload,
                    latency_ms: Date.now() - started,
                    outcome: 'failed',
                    error: wrapped.message,
                    failure_reason: wrapped.reason || wrapped.code,
                };
                resolved.lastMetadata = metadata;
                emitLlmEvent(agentKey, 'llm.response', traceId, metadata);
                throw wrapped;
            }
        },
    };
    return resolved;
}

export function resolveBuilderModel(agent) {
    const provider = normalizedProvider();
    if (provider === 'local') {
        return localResolved(agent);
    }
    if (provider !== 'openrouter') {
        throw new BuilderProviderError(
            'invalid_builder_provider',
            `MC_SIM_BUILDER_PROVIDER must be local or openrouter, got ${provider}`,
            { provider, reason: 'invalid_builder_provider', fatal: true },
        );
    }

    const apiKey = openRouterApiKey();
    const modelName = openRouterModel();
    const missing = [];
    if (!apiKey) missing.push('MC_SIM_BUILDER_OPENROUTER_API_KEY');
    if (!modelName) missing.push('MC_SIM_BUILDER_OPENROUTER_MODEL');
    if (missing.length > 0) {
        const reason = `missing_${missing.join('_and_').toLowerCase()}`;
        if (fallbackMode() === 'local') {
            return localResolved(agent, reason);
        }
        throw new BuilderProviderError(
            'missing_openrouter_config',
            `OpenRouter builder routing requires ${missing.join(' and ')}`,
            { provider: 'openrouter', reason, fatal: true },
        );
    }
    return openRouterResolved(agent, apiKey, modelName);
}

export function builderProviderSnapshot(agent) {
    const key = agentId(agent).toLowerCase();
    const sharedFiles = sharedBudgetFiles();
    if (sharedFiles) {
        const shared = readSharedBudget(sharedFiles.statePath);
        const sharedAgent = shared.agentCalls[key] || { calls: 0, estimatedUsd: 0 };
        return {
            provider: normalizedProvider(),
            fallback: fallbackMode(),
            request_count_run: shared.runCalls,
            request_count_agent: Number(sharedAgent.calls || 0),
            estimated_usd_run: roundedUsd(shared.runEstimatedUsd),
            estimated_usd_agent: roundedUsd(Number(sharedAgent.estimatedUsd || 0)),
            failures: providerState.failures,
            shared_budget: true,
            ...currentBudgetConfig(),
        };
    }
    const agentBudget = agentCounter(key);
    return {
        provider: normalizedProvider(),
        fallback: fallbackMode(),
        request_count_run: providerState.runCalls,
        request_count_agent: agentBudget.calls,
        estimated_usd_run: roundedUsd(providerState.runEstimatedUsd),
        estimated_usd_agent: roundedUsd(agentBudget.estimatedUsd),
        failures: providerState.failures,
        ...currentBudgetConfig(),
    };
}

export function resetBuilderProviderState() {
    providerState.runCalls = 0;
    providerState.runEstimatedUsd = 0;
    providerState.agentCalls.clear();
    providerState.failures = 0;
    const sharedFiles = sharedBudgetFiles();
    if (sharedFiles && existsSync(sharedFiles.statePath)) unlinkSync(sharedFiles.statePath);
}

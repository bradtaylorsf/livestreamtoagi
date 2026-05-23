// Bounded autonomous heartbeat for staged Mindcraft agents.
//
// The heartbeat is intentionally coarse: it asks for one high-level visible
// action after an idle/stalled window, never per movement tick. All telemetry is
// best-effort and must not change normal bot behavior if it fails.

import { randomUUID } from 'node:crypto';

import { emitTimelineEvent } from '../bridge/timeline_emitter.js';

const INSTALL_FLAG = Symbol.for('livestreamtoagi.autonomousHeartbeat');
const COMMAND_RE = /!(?<name>[A-Za-z][A-Za-z0-9_]*)\s*(?:\(|\b)/g;

export const NEXT_ACTION_PROMPT = [
    'Autonomous heartbeat: you have been quiet in the Minecraft simulation.',
    'Pick one useful visible high-level next action now.',
    'Reply with one short sentence and exactly one safe command when possible.',
    'Prefer !placeHere("oak_log"), !placeHere("cobblestone"), or !move("heartbeat-scout", "forward", 2).',
    'Use !nearbyBlocks or !inventory only when you truly need information.',
    'Do not output !place, !break, !observe, JSON/object arguments, per-tick movement, long plans, or repeated searches.',
].join(' ');

export const PLAN_BUILD_NEXT_ACTION_PROMPT = [
    'Autonomous heartbeat: you have been quiet in the Minecraft plan-build simulation.',
    'Keep the group focused on one coherent shared structure.',
    'If you are the build owner and !planAndBuild is available, use one concise !planAndBuild request and then let buildFromPlan finish.',
    'Otherwise use a short public chat update, !inventory, !nearbyBlocks, or !searchForBlock only when useful.',
    'Do not output standalone block placement, breaking, observation commands, JSON/object arguments, per-tick movement, long plans, or repeated searches.',
].join(' ');

export const DEFAULT_HEARTBEAT_OPTIONS = Object.freeze({
    enabled: true,
    tickMs: 5000,
    idleMs: 90000,
    cooldownMs: 45000,
    staleActionMs: 180000,
    maxNoCommand: 3,
    prompt: NEXT_ACTION_PROMPT,
    autoStart: true,
});

function defaultPrompt() {
    return process.env.MC_SIM_BUILD_MODE === 'plan'
        ? PLAN_BUILD_NEXT_ACTION_PROMPT
        : DEFAULT_HEARTBEAT_OPTIONS.prompt;
}

function isFalseLike(value) {
    return ['0', 'false', 'no', 'off', 'disabled'].includes(String(value).trim().toLowerCase());
}

function envBool(name, fallback) {
    if (!Object.hasOwn(process.env, name)) return fallback;
    return !isFalseLike(process.env[name]);
}

function positiveInt(value, fallback) {
    const parsed = Number.parseInt(String(value), 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function envInt(name, fallback) {
    if (!Object.hasOwn(process.env, name)) return fallback;
    return positiveInt(process.env[name], fallback);
}

function normalizeOptions(options = {}) {
    const merged = {
        enabled: envBool('MC_HEARTBEAT_ENABLED', DEFAULT_HEARTBEAT_OPTIONS.enabled),
        tickMs: envInt('MC_HEARTBEAT_TICK_MS', DEFAULT_HEARTBEAT_OPTIONS.tickMs),
        idleMs: envInt('MC_HEARTBEAT_IDLE_MS', DEFAULT_HEARTBEAT_OPTIONS.idleMs),
        cooldownMs: envInt('MC_HEARTBEAT_COOLDOWN_MS', DEFAULT_HEARTBEAT_OPTIONS.cooldownMs),
        staleActionMs: envInt('MC_HEARTBEAT_STALE_ACTION_MS', DEFAULT_HEARTBEAT_OPTIONS.staleActionMs),
        maxNoCommand: envInt(
            'MC_HEARTBEAT_MAX_NO_COMMAND',
            DEFAULT_HEARTBEAT_OPTIONS.maxNoCommand,
        ),
        prompt: process.env.MC_HEARTBEAT_PROMPT || defaultPrompt(),
        autoStart: DEFAULT_HEARTBEAT_OPTIONS.autoStart,
        ...options,
    };
    if (options.enabled !== undefined) merged.enabled = Boolean(options.enabled);
    if (options.autoStart !== undefined) merged.autoStart = Boolean(options.autoStart);
    return merged;
}

function textFromResponse(value) {
    if (value === undefined || value === null) return '';
    if (typeof value === 'boolean') return '';
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(textFromResponse).filter(Boolean).join('\n');
    if (typeof value === 'object') {
        for (const key of ['response', 'message', 'text', 'content', 'output']) {
            if (typeof value[key] === 'string') return value[key];
        }
        try {
            return JSON.stringify(value);
        } catch {
            return String(value);
        }
    }
    return String(value);
}

function excerpt(value, maxLength = 240) {
    const text = textFromResponse(value).replace(/\s+/g, ' ').trim();
    return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

export function classifyHeartbeatResponse(value) {
    const text = textFromResponse(value).trim();
    const commands = [];
    for (const match of text.matchAll(COMMAND_RE)) {
        commands.push(`!${match.groups.name}`);
    }
    return {
        blank: text.length === 0,
        hadCommand: commands.length > 0,
        commands,
        excerpt: excerpt(text),
    };
}

function agentId(agent) {
    const bot = agent && agent.bot ? agent.bot : null;
    return (
        (agent && (agent.name || agent.agent_id || agent.id)) ||
        (bot && bot.username) ||
        process.env.LTAG_AGENT_ID ||
        process.env.MC_AGENT_ID ||
        'unknown'
    );
}

function actionManager(agent) {
    return agent && (agent.actions || agent.action_manager || agent.actionManager);
}

function boolProp(obj, names) {
    for (const name of names) {
        if (typeof obj?.[name] === 'boolean' && obj[name]) return name;
    }
    return null;
}

function functionProp(obj, names) {
    for (const name of names) {
        if (typeof obj?.[name] !== 'function') continue;
        try {
            if (obj[name]()) return name;
        } catch {
            // ignore shape drift and keep checking other signals
        }
    }
    return null;
}

function currentActionLabel(agent, state) {
    const manager = actionManager(agent);
    return (
        state.currentActionLabel ||
        manager?.currentActionLabel ||
        manager?.current_action_label ||
        manager?.actionLabel ||
        manager?.action_label ||
        manager?.currentAction ||
        manager?.current_action ||
        null
    );
}

function detectActiveAction(agent, state, nowMs) {
    const manager = actionManager(agent);
    let source = null;
    let startedTs = state.currentActionStartedTs;

    if (startedTs !== null && startedTs !== undefined) {
        source = 'heartbeat-wrapper';
    }

    if (!source && manager) {
        const activeBool = boolProp(manager, [
            'executing',
            'isExecuting',
            'active',
            'running',
            'inAction',
            'actionRunning',
            'action_running',
            'busy',
        ]);
        source = activeBool;
        const activeFn = functionProp(manager, ['isActive', 'isRunning', 'isBusy']);
        source = source || activeFn;
        if (source && (startedTs === null || startedTs === undefined)) {
            startedTs = state.lastCommandIssuedTs ?? state.lastResponseTs ?? nowMs;
        }
    }

    return {
        active: Boolean(source),
        source,
        startedTs,
        ageMs:
            source && startedTs !== null && startedTs !== undefined
                ? Math.max(0, nowMs - startedTs)
                : 0,
        label: currentActionLabel(agent, state),
    };
}

function lastActivityTs(state) {
    return Math.max(
        state.installedAtTs || 0,
        state.lastChatTs || 0,
        state.lastCommandTs || 0,
        state.lastCommandIssuedTs || 0,
        state.lastResponseTs || 0,
    );
}

export function shouldFireHeartbeat(state, options, activeAction, nowMs) {
    const activityTs = lastActivityTs(state);
    const idleMs = Math.max(0, nowMs - activityTs);
    const lastHeartbeatTs = state.lastHeartbeatTs;
    const cooldownRemainingMs =
        lastHeartbeatTs === null || lastHeartbeatTs === undefined
            ? 0
            : Math.max(0, options.cooldownMs - Math.max(0, nowMs - lastHeartbeatTs));

    if (!options.enabled) {
        return { fire: false, skippedReason: 'disabled', idleMs, cooldownRemainingMs };
    }
    if (state.halted) {
        return { fire: false, skippedReason: 'halted', idleMs, cooldownRemainingMs };
    }
    if (state.heartbeatInFlight) {
        return { fire: false, skippedReason: 'heartbeat-in-flight', idleMs, cooldownRemainingMs };
    }
    if (state.consecutiveNoCommand >= options.maxNoCommand) {
        return { fire: false, skippedReason: 'max-no-command', idleMs, cooldownRemainingMs };
    }
    if (activeAction.active && activeAction.ageMs < options.staleActionMs) {
        return {
            fire: false,
            skippedReason: 'active-action',
            idleMs,
            cooldownRemainingMs,
            actionAgeMs: activeAction.ageMs,
        };
    }
    if (!activeAction.active && idleMs < options.idleMs) {
        return { fire: false, skippedReason: 'not-idle', idleMs, cooldownRemainingMs };
    }
    if (cooldownRemainingMs > 0) {
        return { fire: false, skippedReason: 'cooldown', idleMs, cooldownRemainingMs };
    }

    return {
        fire: true,
        reason: activeAction.active ? 'stale-action' : 'idle',
        idleMs,
        cooldownRemainingMs,
        actionAgeMs: activeAction.ageMs,
    };
}

function restoreEnv(name, value) {
    if (value === undefined) {
        delete process.env[name];
    } else {
        process.env[name] = value;
    }
}

function directorGateSuppressed(agent, beforeSequence) {
    const gate = agent?.__ltagDirectorGate;
    if (!gate || beforeSequence === null || beforeSequence === undefined) return false;
    const outcome = gate.lastOutcome || null;
    const sequence = Number(outcome?.sequence);
    if (!Number.isFinite(sequence) || sequence <= beforeSequence) return false;
    return outcome.selected === false;
}

export class HeartbeatController {
    constructor(agent, options = {}) {
        this.agent = agent;
        this.options = normalizeOptions(options);
        this.emit = this.options.emit || emitTimelineEvent;
        this.now = this.options.now || (() => Date.now());
        const nowMs = this.now();
        this.state = {
            installedAtTs: nowMs,
            lastChatTs: nowMs,
            lastCommandTs: nowMs,
            lastCommandIssuedTs: nowMs,
            lastHeartbeatTs: null,
            lastResponseTs: nowMs,
            currentActionStartedTs: null,
            currentActionLabel: null,
            consecutiveNoCommand: 0,
            commandCounter: 0,
            heartbeatInFlight: false,
            halted: false,
            lastSkipReason: null,
            lastSkipTs: 0,
            lastResponseExcerpt: '',
        };
        this.timer = null;
        this.agentName = agentId(agent);
        this._wrapAgent();
    }

    start() {
        if (!this.options.enabled) {
            this._emitSkipped('disabled', { idle_ms: 0 });
            return this;
        }
        if (this.timer || this.options.autoStart === false) return this;
        this.timer = setInterval(() => {
            this.tick().catch((err) => this._emitError(err));
        }, Math.max(100, this.options.tickMs));
        if (typeof this.timer.unref === 'function') this.timer.unref();
        return this;
    }

    stop() {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    }

    recordText(value, kind = 'response') {
        const classified = classifyHeartbeatResponse(value);
        if (classified.blank) return classified;

        const nowMs = this.now();
        this.state.lastResponseTs = nowMs;
        this.state.lastResponseExcerpt = classified.excerpt;
        if (kind === 'chat') this.state.lastChatTs = nowMs;
        if (classified.hadCommand) {
            this.state.lastCommandIssuedTs = nowMs;
            this.state.commandCounter += 1;
        }
        return classified;
    }

    recordActionStart(label = null) {
        const nowMs = this.now();
        this.state.currentActionStartedTs = nowMs;
        this.state.currentActionLabel = label || null;
        this.state.lastCommandIssuedTs = nowMs;
        this.state.commandCounter += 1;
    }

    recordActionEnd() {
        const nowMs = this.now();
        this.state.lastCommandTs = nowMs;
        this.state.lastResponseTs = nowMs;
        this.state.currentActionStartedTs = null;
        this.state.currentActionLabel = null;
    }

    async tick() {
        try {
            const nowMs = this.now();
            const activeAction = detectActiveAction(this.agent, this.state, nowMs);
            const decision = shouldFireHeartbeat(this.state, this.options, activeAction, nowMs);
            const basePayload = {
                idle_ms: decision.idleMs,
                in_action: activeAction.active,
                action_label: activeAction.label,
                action_age_ms: activeAction.ageMs,
                action_source: activeAction.source,
                cooldown_remaining_ms: decision.cooldownRemainingMs,
                no_command_streak: this.state.consecutiveNoCommand,
            };

            if (!decision.fire) {
                if (['active-action', 'cooldown', 'disabled', 'max-no-command'].includes(decision.skippedReason)) {
                    this._emitSkipped(decision.skippedReason, basePayload);
                }
                if (decision.skippedReason === 'max-no-command') {
                    await this._halt('max-no-command', basePayload);
                }
                return { fired: false, reason: decision.skippedReason, payload: basePayload };
            }

            return await this._fire(decision.reason, basePayload);
        } catch (err) {
            this._emitError(err);
            return { fired: false, reason: 'error', error: err && err.message ? err.message : String(err) };
        }
    }

    _wrapAgent() {
        this._wrapOpenChat();
        this._wrapRouteResponse();
        this._wrapHandleMessage();
        this._wrapActionRunner();
    }

    _wrapOpenChat() {
        if (!this.agent || typeof this.agent.openChat !== 'function' || this.agent.openChat.__ltagHeartbeatWrapped) {
            return;
        }
        const controller = this;
        const original = this.agent.openChat;
        this.agent.openChat = async function heartbeatOpenChat(message, ...args) {
            controller.recordText(message, 'chat');
            return original.apply(this, [message, ...args]);
        };
        Object.defineProperty(this.agent.openChat, '__ltagHeartbeatWrapped', { value: true });
    }

    _wrapRouteResponse() {
        if (!this.agent || typeof this.agent.routeResponse !== 'function' || this.agent.routeResponse.__ltagHeartbeatWrapped) {
            return;
        }
        const controller = this;
        const original = this.agent.routeResponse;
        this.agent.routeResponse = async function heartbeatRouteResponse(toPlayer, message, ...args) {
            controller.recordText(message, 'response');
            return original.apply(this, [toPlayer, message, ...args]);
        };
        Object.defineProperty(this.agent.routeResponse, '__ltagHeartbeatWrapped', { value: true });
    }

    _wrapHandleMessage() {
        if (!this.agent || typeof this.agent.handleMessage !== 'function' || this.agent.handleMessage.__ltagHeartbeatWrapped) {
            return;
        }
        const controller = this;
        const original = this.agent.handleMessage;
        this.agent.handleMessage = async function heartbeatHandleMessage(...args) {
            const result = await original.apply(this, args);
            controller.recordText(result, 'response');
            return result;
        };
        Object.defineProperty(this.agent.handleMessage, '__ltagHeartbeatWrapped', { value: true });
    }

    _wrapActionRunner() {
        const manager = actionManager(this.agent);
        if (!manager) return;
        for (const methodName of ['runAction', 'resumeAction']) {
            if (typeof manager[methodName] !== 'function' || manager[methodName].__ltagHeartbeatWrapped) {
                continue;
            }
            const controller = this;
            const original = manager[methodName];
            manager[methodName] = async function heartbeatRunAction(actionLabel, ...args) {
                controller.recordActionStart(typeof actionLabel === 'string' ? actionLabel : methodName);
                try {
                    return await original.apply(this, [actionLabel, ...args]);
                } finally {
                    controller.recordActionEnd();
                }
            };
            Object.defineProperty(manager[methodName], '__ltagHeartbeatWrapped', { value: true });
        }
    }

    _emit(type, payload = {}, traceId = null) {
        try {
            this.emit({
                type,
                agent: this.agentName,
                traceId,
                payload,
            });
        } catch {
            // heartbeat telemetry is best-effort
        }
    }

    _emitSkipped(reason, payload = {}) {
        const nowMs = this.now();
        if (
            this.state.lastSkipReason === reason &&
            nowMs - this.state.lastSkipTs < Math.max(1000, this.options.cooldownMs)
        ) {
            return;
        }
        this.state.lastSkipReason = reason;
        this.state.lastSkipTs = nowMs;
        this._emit('heartbeat.skipped', { reason, ...payload });
    }

    _emitError(err) {
        this._emit('heartbeat.outcome', {
            outcome: 'error',
            had_command: false,
            no_command_streak: this.state.consecutiveNoCommand,
            error: err && err.message ? err.message : String(err),
        });
    }

    async _fire(reason, basePayload) {
        if (!this.agent || typeof this.agent.handleMessage !== 'function') {
            this._emitSkipped('missing-handle-message', basePayload);
            return { fired: false, reason: 'missing-handle-message', payload: basePayload };
        }

        const traceId = `trace-heartbeat-${randomUUID()}`;
        const firedAt = this.now();
        const beforeCommandCounter = this.state.commandCounter || 0;
        const beforeDirectorGateSequence = Number.isFinite(Number(this.agent?.__ltagDirectorGate?.sequence))
            ? Number(this.agent.__ltagDirectorGate.sequence)
            : null;
        const beforeResponseExcerpt = this.state.lastResponseExcerpt || '';
        this.state.lastHeartbeatTs = firedAt;
        this.state.heartbeatInFlight = true;

        this._emit(
            'heartbeat.fired',
            {
                reason,
                prompt_excerpt: excerpt(this.options.prompt),
                ...basePayload,
            },
            traceId,
        );

        const previousPurpose = process.env.MC_LLM_REQUEST_PURPOSE;
        const previousReason = process.env.MC_LLM_REQUEST_REASON;
        process.env.MC_LLM_REQUEST_PURPOSE = 'heartbeat';
        process.env.MC_LLM_REQUEST_REASON = reason;

        let result;
        let error = null;
        try {
            result = await this.agent.handleMessage('system', this.options.prompt, 1);
        } catch (err) {
            error = err;
        } finally {
            restoreEnv('MC_LLM_REQUEST_PURPOSE', previousPurpose);
            restoreEnv('MC_LLM_REQUEST_REASON', previousReason);
            this.state.heartbeatInFlight = false;
        }

        const classified = classifyHeartbeatResponse(result);
        const wasDirectorSuppressed = directorGateSuppressed(
            this.agent,
            beforeDirectorGateSequence,
        );
        const hadCommand =
            !wasDirectorSuppressed &&
            (result === true ||
                classified.hadCommand ||
                (this.state.commandCounter || 0) > beforeCommandCounter);
        if (!wasDirectorSuppressed) {
            if (hadCommand) {
                this.state.consecutiveNoCommand = 0;
            } else {
                this.state.consecutiveNoCommand += 1;
            }
        }

        const responseExcerpt = wasDirectorSuppressed
            ? ''
            : classified.excerpt || this.state.lastResponseExcerpt || beforeResponseExcerpt;
        const outcomePayload = {
            reason,
            had_command: hadCommand,
            no_command_streak: this.state.consecutiveNoCommand,
            response_empty: !responseExcerpt,
            response_excerpt: responseExcerpt,
            commands: classified.commands,
            director_suppressed: wasDirectorSuppressed,
            outcome: error
                ? 'error'
                : wasDirectorSuppressed
                  ? 'director-suppressed'
                  : hadCommand
                    ? 'command'
                    : 'no-command',
        };
        if (error) {
            outcomePayload.error = error && error.message ? error.message : String(error);
        }
        this._emit('heartbeat.outcome', outcomePayload, traceId);

        if (this.state.consecutiveNoCommand >= this.options.maxNoCommand) {
            await this._halt('max-no-command', {
                ...basePayload,
                no_command_streak: this.state.consecutiveNoCommand,
            });
        }

        return {
            fired: true,
            reason,
            hadCommand,
            noCommandStreak: this.state.consecutiveNoCommand,
            error: error && error.message ? error.message : null,
        };
    }

    async _halt(reason, payload = {}) {
        if (this.state.halted) return;
        this.state.halted = true;
        this.stop();
        const eventPayload = {
            reason,
            max_no_command: this.options.maxNoCommand,
            no_command_streak: this.state.consecutiveNoCommand,
            ...payload,
        };
        this._emit('heartbeat.halted', eventPayload);
        try {
            console.error(
                `[heartbeat] ${this.agentName} halted reason=${reason} no_command_streak=${this.state.consecutiveNoCommand}`,
            );
        } catch {
            // console should always exist, but never let halt logging throw
        }
        const selfPrompter =
            this.agent?.self_prompter ||
            this.agent?.selfPrompter ||
            this.agent?.prompter?.self_prompter ||
            this.agent?.prompter?.selfPrompter;
        if (selfPrompter && typeof selfPrompter.stop === 'function') {
            try {
                await selfPrompter.stop(false);
            } catch {
                // stopping self-prompting is best-effort
            }
        }
    }
}

export function installHeartbeat(agent, options = {}) {
    if (!agent || typeof agent !== 'object') return null;
    if (agent[INSTALL_FLAG]) return agent[INSTALL_FLAG];
    const controller = new HeartbeatController(agent, options);
    Object.defineProperty(agent, INSTALL_FLAG, {
        value: controller,
        configurable: false,
        enumerable: false,
        writable: false,
    });
    controller.start();
    return controller;
}

export default { installHeartbeat, HeartbeatController, classifyHeartbeatResponse, shouldFireHeartbeat };

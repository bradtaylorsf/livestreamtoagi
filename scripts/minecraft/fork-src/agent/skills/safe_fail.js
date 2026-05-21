// Thin Node mirror of core/embodiment/failure.py for E6-7 (#562).
//
// Python is the tested source of truth. This helper stays dependency-free so
// fork actions can make the same idle/retry/abandon decision when needed.

export const FAILURE_CLASSES = Object.freeze([
    'blocked',
    'timeout',
    'invalid',
    'unreachable',
    'bridge-down',
    'kill-switch-active',
]);

export const SAFE_FAIL_POLICY = Object.freeze({
    blocked: 'idle',
    timeout: 'retry-bounded',
    invalid: 'abandon',
    unreachable: 'idle',
    'bridge-down': 'abandon',
    'kill-switch-active': 'idle',
});

export const DEFAULT_RETRY_BUDGET = Object.freeze({
    max_attempts: 3,
    base_backoff_ms: 500,
    cap_ms: 30000,
    multiplier: 2,
});

const NON_FAILURE_CLASSES = new Set(['reached', 'placed', 'removed', 'success', 'partial']);

const ALIASES = new Map([
    ['blocked', 'blocked'],
    ['timed-out', 'timeout'],
    ['time-out', 'timeout'],
    ['timeout', 'timeout'],
    ['bridge-timeout', 'timeout'],
    ['bridge-overloaded', 'timeout'],
    ['invalid', 'invalid'],
    ['invalid-payload', 'invalid'],
    ['protected', 'invalid'],
    ['tool-missing', 'invalid'],
    ['bridge-auth-refused', 'invalid'],
    ['bridge-no-token', 'invalid'],
    ['bridge-no-transport', 'invalid'],
    ['bridge-protocol', 'invalid'],
    ['unreachable', 'unreachable'],
    ['no-path', 'unreachable'],
    ['bridge-unreachable', 'unreachable'],
    ['bridge-down', 'bridge-down'],
    ['bridge-connect-failed', 'bridge-down'],
    ['bridge-send-failed', 'bridge-down'],
    ['kill-switch-active', 'kill-switch-active'],
]);

function normalizeToken(value) {
    if (value === null || value === undefined) return null;
    const token = String(value).trim().toLowerCase();
    if (!token) return null;
    return token.replace(/_/g, '-').split(/\s+/).filter(Boolean).join('-');
}

function rawCandidates(rawCode) {
    if (rawCode && typeof rawCode === 'object') {
        const candidates = [];
        for (const key of [
            'class',
            'failure_class',
            'failureClass',
            'code',
            'error_code',
            'outcome_class',
            'outcomeClass',
            'status',
        ]) {
            if (key in rawCode) candidates.push(rawCode[key]);
        }
        if (rawCode.error && typeof rawCode.error === 'object') {
            candidates.push(rawCode.error.code, rawCode.error.class);
        }
        return candidates;
    }
    return [rawCode];
}

export function classify(rawCode) {
    let sawUnknown = false;
    for (const candidate of rawCandidates(rawCode)) {
        const token = normalizeToken(candidate);
        if (!token) continue;
        if (NON_FAILURE_CLASSES.has(token)) return null;
        if (ALIASES.has(token)) return ALIASES.get(token);
        sawUnknown = true;
    }
    return sawUnknown ? 'invalid' : null;
}

export function nextBackoffMs(attempt, budget = DEFAULT_RETRY_BUDGET) {
    const normalizedAttempt = Math.max(1, Number.parseInt(attempt, 10) || 1);
    const base = Math.max(1, Number(budget.base_backoff_ms) || DEFAULT_RETRY_BUDGET.base_backoff_ms);
    const cap = Math.max(1, Number(budget.cap_ms) || DEFAULT_RETRY_BUDGET.cap_ms);
    const multiplier = Math.max(1, Number(budget.multiplier) || DEFAULT_RETRY_BUDGET.multiplier);
    return Math.min(base * multiplier ** (normalizedAttempt - 1), cap);
}

export function decideSafeFail(
    failureClass,
    attempt = 1,
    budget = DEFAULT_RETRY_BUDGET,
) {
    const canonical = classify(failureClass);
    if (!canonical) {
        throw new Error(`${JSON.stringify(failureClass)} is not a failure class`);
    }
    const normalizedAttempt = Math.max(1, Number.parseInt(attempt, 10) || 1);
    const maxAttempts = Math.max(
        0,
        Number.parseInt(budget.max_attempts, 10) || DEFAULT_RETRY_BUDGET.max_attempts,
    );
    const policy = SAFE_FAIL_POLICY[canonical];
    if (policy === 'retry-bounded' && normalizedAttempt <= maxAttempts) {
        return {
            class: canonical,
            policy,
            action: 'retry',
            retryable: true,
            attempt: normalizedAttempt,
            next_backoff_ms: nextBackoffMs(normalizedAttempt, budget),
        };
    }
    return {
        class: canonical,
        policy,
        action: policy === 'retry-bounded' ? 'abandon' : policy,
        retryable: false,
        attempt: normalizedAttempt,
        next_backoff_ms: null,
    };
}

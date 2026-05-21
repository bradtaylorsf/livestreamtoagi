// Shared classifier for expected Mindcraft/Mineflayer action interruptions.
//
// These failures mean another safety or mode layer deliberately stopped an
// in-flight path/action. They should be reported as action outcomes, not
// allowed to escape into Mindcraft's process-level crash path.

export const INTERRUPTION_PATTERNS = Object.freeze([
    { outcomeClass: 'interrupted', pattern: /\bPathStopped\b/i },
    { outcomeClass: 'interrupted', pattern: /\bpath\s+was\s+stopped\b/i },
    // Exact crash signature: "path was stopped before it could be completed".
    { outcomeClass: 'interrupted', pattern: /path\s+was\s+stopped\s+before\s+it\s+could\s+be\s+completed/i },
    { outcomeClass: 'interrupted', pattern: /\binterrupted\s+by\b/i },
    // mode:unstuck can deliberately stop an in-flight path/action.
    { outcomeClass: 'interrupted', pattern: /\bmode\s*:\s*unstuck\b/i },
    { outcomeClass: 'interrupted', pattern: /\bcancell?ed\s+by\s+mode\b/i },
    { outcomeClass: 'aborted', pattern: /\baborted\b/i },
    { outcomeClass: 'aborted', pattern: /\bcancell?ed\b/i },
    { outcomeClass: 'blocked', pattern: /\bblocked\b/i },
]);

export function messageFromError(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    const name = value && value.name ? String(value.name) : '';
    const message = value && value.message ? String(value.message) : String(value);
    if (name && message && !message.includes(name)) return `${name}: ${message}`;
    return message;
}

export function classifyInterruption(value) {
    const message = messageFromError(value);
    if (!message) return null;
    for (const { outcomeClass, pattern } of INTERRUPTION_PATTERNS) {
        if (pattern.test(message)) return outcomeClass;
    }
    return null;
}

export function interruptionDetail(outcomeClass, value) {
    const message = messageFromError(value);
    return message ? `${outcomeClass}: ${message}` : `${outcomeClass}: action interrupted`;
}

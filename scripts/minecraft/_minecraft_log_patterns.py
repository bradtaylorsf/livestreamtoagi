"""Shared regexes for Minecraft soak log analysis.

Mindcraft and Paper logs are not stable APIs, so the soak analyzers use
conservative text patterns. Keeping the common patterns here prevents the
action-reliability gate and the timeline exporter from drifting apart.
"""

from __future__ import annotations

import re

COMMAND_RE = re.compile(r"!\w+\s*\(")
COMMAND_CALL_RE = re.compile(r"!(?P<name>\w+)\s*(?:\((?P<args>.*?)\))?", re.DOTALL)
INTENT_VERB_RE = re.compile(
    r"\b(?:place|placing|put|break|breaking|build|building|move|moving|go|walk|"
    r"navigate|collect|gather|search|find|mine|mining|dig|digging|craft|make|"
    r"chop|harvest|inspect|observe|inventory|scout|torch|light)\b",
    re.IGNORECASE,
)
INTENT_PROMISE_RE = re.compile(
    r"\b(?:i(?:'|\u2019)ll|i will|i am going to|i(?:'|\u2019)m going to|we(?:'|\u2019)ll|"
    r"we will|we are going to|let(?:'|\u2019)s|plan to|planning to|about to|"
    r"need to|want to|try to|trying to|start(?:ing)? to|going to|will)\b",
    re.IGNORECASE,
)
UTTERANCE_RE = re.compile(
    r"(^|\b)(?:chat|says?|said|assistant|bot response|llm response|minecraft chat)\b"
    r"|^\s*(?:\[[^\]]+\]\s*)?[A-Za-z][A-Za-z0-9_-]{1,24}\s*[:>]",
    re.IGNORECASE,
)
INSTRUCTION_RE = re.compile(
    r"\b(?:init prompt|init_message|system prompt|settings|profile|blocked_actions|"
    r"available commands|command syntax|good early commands|usage|description)\b",
    re.IGNORECASE,
)

PARSER_FAILURE_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "empty_response",
        (
            re.compile(r"\bempty\s+(?:parsed\s+)?(?:llm\s+)?response\b", re.IGNORECASE),
            re.compile(r"\bblank\s+(?:llm\s+)?response\b", re.IGNORECASE),
            re.compile(r"\bparsed response\b.*\bempty\b", re.IGNORECASE),
        ),
    ),
    (
        "no_commands_found",
        (
            re.compile(r"\bno commands found\b", re.IGNORECASE),
            re.compile(r"\bno command(?:s)?\s+(?:were\s+)?(?:parsed|detected)\b", re.IGNORECASE),
        ),
    ),
    (
        "unknown_command",
        (
            re.compile(r"\bcommand\s+!?\w+(?:\([^)]*\))?\s+does not exist\b", re.IGNORECASE),
            re.compile(r"\bunknown command\b", re.IGNORECASE),
        ),
    ),
    (
        "argument_error",
        (
            re.compile(
                r"\b(?:argument|arguments|arg|args|parameter|parameters|param|params)\b"
                r".*\b(?:count|type|required|missing|expected|invalid|must be)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:expected|got)\s+\d+\s+(?:argument|arguments|arg|args|parameter|parameters)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\btoo (?:many|few) (?:arguments|args|parameters|params)\b", re.IGNORECASE),
        ),
    ),
    (
        "parse_error",
        (
            re.compile(r"\bcould not parse\b", re.IGNORECASE),
            re.compile(r"\berror parsing\b", re.IGNORECASE),
            re.compile(r"\bparse error\b", re.IGNORECASE),
            re.compile(r"\bmalformed (?:command|response|parsed response)\b", re.IGNORECASE),
            re.compile(r"\binvalid command syntax\b", re.IGNORECASE),
        ),
    ),
)

ACTION_CONTEXT_RE = re.compile(
    r"\[(?:place|break|move|navigate|build|build-from-plan|observe|runErrand|run_errand|"
    r"executeCode|execute_code|pollErrand|bridgePing) trace="
    r"|\baction\.result\b|\bperception\.report\b|\bcode output\b|\baction failed\b"
    r"|\b(?:place|break|move|navigate|build|observe|run_errand)\s+[A-Za-z0-9_-]+\s+",
    re.IGNORECASE,
)
EXECUTION_SUCCESS_RE = re.compile(
    r"\b(?:code output|successfully|status\s*[:=]\s*success|status['\"]?\s*:\s*['\"]success|"
    r"placed|removed|reached|moved|broke)\b",
    re.IGNORECASE,
)
EXECUTION_FAILURE_RE = re.compile(
    r"\b(?:action failed|failed|error|status\s*[:=]\s*(?:failure|partial)|"
    r"status['\"]?\s*:\s*['\"](?:failure|partial)|blocked|invalid|protected|"
    r"interrupted|aborted|PathStopped|timed[- ]out|timeout|unreachable)\b",
    re.IGNORECASE,
)
VERIFICATION_RE = re.compile(
    r"\bbefore=.*\bafter=|\bdistance_to_target=.*\bdelta=|"
    r"\bsteps_verified\s*[:=]\s*[1-9]|\bverified\s*[:=]\s*[1-9]|"
    r"\b(?:placed|removed|reached):\s*(?:position|distance)",
    re.IGNORECASE,
)

TRACE_RE = re.compile(r"\b(?:trace|trace_id)=(?P<trace_id>[A-Za-z0-9_.:-]*[A-Za-z0-9_-])")
ACTION_TRACE_RE = re.compile(
    r"\[(?P<action>[A-Za-z][A-Za-z0-9_-]*)\s+trace=(?P<trace_id>[A-Za-z0-9_.:-]+)\]\s*(?P<detail>.*)"
)
POSITION_RE = re.compile(
    r"\b(?:pos(?:ition)?|location)\s*[:=]\s*\(?"
    r"(?P<x>-?\d+(?:\.\d+)?)[,\s]+"
    r"(?P<y>-?\d+(?:\.\d+)?)[,\s]+"
    r"(?P<z>-?\d+(?:\.\d+)?)\)?",
    re.IGNORECASE,
)
XYZ_RE = re.compile(
    r"\bx['\"]?\s*[:=]\s*(?P<x>-?\d+(?:\.\d+)?).*?"
    r"\by['\"]?\s*[:=]\s*(?P<y>-?\d+(?:\.\d+)?).*?"
    r"\bz['\"]?\s*[:=]\s*(?P<z>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
CHAT_RE = re.compile(
    r"(?:\[CHAT\]\s*)?(?:<(?P<angle>[^>]+)>|(?P<name>[A-Za-z][A-Za-z0-9_-]{1,24})\s*[:>])\s*(?P<message>.+)"
)
LIFECYCLE_RE = re.compile(
    r"\b(?:spawned at|joined the game|logged in|disconnected|kicked|respawned|exited|shutdown|started)\b",
    re.IGNORECASE,
)
CRASH_ERROR_RE = re.compile(
    r"\b(?:uncaught|unhandled|fatal|segmentation|crash|exception|traceback|ECONN|WebSocket.*(?:closed|disconnect))\b",
    re.IGNORECASE,
)

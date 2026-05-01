"""Parse agent LLM output into spoken dialogue and visual action cues.

Agent responses use [action]...[/action] tags to mark stage directions
(gestures, expressions, movements) that should be rendered visually but
not spoken aloud by the TTS pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ACTION_PATTERN = re.compile(r"\[action\](.*?)\[/action\]", re.DOTALL | re.IGNORECASE)

# Ordered: bold before italic so **text** is handled before *text*
_MARKDOWN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*(.+?)\*\*", re.DOTALL), r"\1"),  # **bold**
    (re.compile(r"__(.+?)__", re.DOTALL), r"\1"),  # __bold__
    (re.compile(r"\*(.+?)\*", re.DOTALL), r"\1"),  # *italic*
    (re.compile(r"_(.+?)_", re.DOTALL), r"\1"),  # _italic_
    (re.compile(r"`(.+?)`", re.DOTALL), r"\1"),  # `code`
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),  # ## headers
    (re.compile(r"^[-*_]{3,}$", re.MULTILINE), ""),  # horizontal rules
    (re.compile(r"[*_]"), ""),  # stray asterisks/underscores
]


def strip_markdown(text: str) -> str:
    """Remove common markdown formatting so TTS reads clean natural text."""
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


@dataclass(frozen=True)
class ParsedSpeech:
    """Structured representation of an agent's response."""

    raw: str
    dialogue: str
    actions: list[str] = field(default_factory=list)


def parse_speech(text: str) -> ParsedSpeech:
    """Split *text* into spoken dialogue and visual action cues.

    Returns a ``ParsedSpeech`` with:
    - ``raw``: the original unmodified text
    - ``dialogue``: text with ``[action]`` blocks and markdown removed (for TTS)
    - ``actions``: list of action descriptions extracted from tags
    """
    actions = [m.strip() for m in _ACTION_PATTERN.findall(text)]
    dialogue = _ACTION_PATTERN.sub("", text).strip()
    # Collapse runs of whitespace left by removed tags
    dialogue = re.sub(r"  +", " ", dialogue)
    # Strip markdown so TTS reads clean text
    dialogue = strip_markdown(dialogue)
    return ParsedSpeech(raw=text, dialogue=dialogue, actions=actions)


def parse_speech_segments(text: str) -> list[tuple[str, str | None]]:
    """Split text into (dialogue_segment, preceding_action) pairs.

    Splits on [action] tags, returning each dialogue chunk paired with the
    action that immediately precedes it (or None for the first chunk).

    Example::

        "Hi! [action]waves[/action] How are you?"
        → [("Hi!", None), ("How are you?", "waves")]

    Trailing actions with no subsequent dialogue are silently dropped.
    """
    # re.split with a capturing group returns [text, action, text, action, text, ...]
    parts = re.split(r"\[action\](.*?)\[/action\]", text, flags=re.DOTALL | re.IGNORECASE)

    segments: list[tuple[str, str | None]] = []
    pending_action: str | None = None

    for i, part in enumerate(parts):
        if i % 2 == 0:  # dialogue chunk
            cleaned = strip_markdown(part.strip())
            # Collapse extra whitespace
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned:
                segments.append((cleaned, pending_action))
                pending_action = None
        else:  # action captured by split group
            pending_action = part.strip() or None

    return segments

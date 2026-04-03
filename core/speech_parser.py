"""Parse agent LLM output into spoken dialogue and visual action cues.

Agent responses use [action]...[/action] tags to mark stage directions
(gestures, expressions, movements) that should be rendered visually but
not spoken aloud by the TTS pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ACTION_PATTERN = re.compile(r"\[action\](.*?)\[/action\]", re.DOTALL | re.IGNORECASE)


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
    - ``dialogue``: text with ``[action]`` blocks removed (for TTS)
    - ``actions``: list of action descriptions extracted from tags
    """
    actions = [m.strip() for m in _ACTION_PATTERN.findall(text)]
    dialogue = _ACTION_PATTERN.sub("", text).strip()
    # Collapse runs of whitespace left by removed tags
    dialogue = re.sub(r"  +", " ", dialogue)
    return ParsedSpeech(raw=text, dialogue=dialogue, actions=actions)

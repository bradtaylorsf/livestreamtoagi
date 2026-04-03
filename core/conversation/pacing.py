"""Variable pause/pacing system for conversation turns.

Calculates pause durations between turns based on content type.
Questions get quick responses, jokes get a beat, emotional content
gets a slightly longer pause.
"""

from __future__ import annotations

import random
import re

from core.models import TimingConfig

# Detection patterns
_JOKE_PATTERNS = re.compile(r"\b(haha|lol|lmao)\b", re.IGNORECASE)
_EMOTIONAL_PATTERNS = re.compile(
    r"\b(feel|miss|worry|scared|sorry)\b", re.IGNORECASE
)


def _detect_content_type(response: str, *, is_interrupt: bool = False) -> str:
    """Classify response text into a content type.

    Priority order: interrupt > question > joke > emotional > statement.
    """
    if is_interrupt:
        return "interrupt"
    if response.rstrip().endswith("?"):
        return "question"
    if _JOKE_PATTERNS.search(response):
        return "joke"
    if _EMOTIONAL_PATTERNS.search(response):
        return "emotional"
    return "statement"


def calculate_pause(
    response: str,
    config: TimingConfig,
    *,
    is_interrupt: bool = False,
) -> float:
    """Calculate the pause duration (seconds) after a conversation turn.

    Args:
        response: The text that was just spoken.
        config: Timing configuration with pause range, strategy, and multipliers.
        is_interrupt: Whether this turn was an interruption.

    Returns:
        Pause duration in seconds, clamped to [min_pause, max_pause].
    """
    lo = config.min_pause_seconds
    hi = config.max_pause_seconds

    if config.pause_strategy == "fixed":
        return _clamp((lo + hi) / 2, lo, hi)

    if config.pause_strategy == "random":
        return _clamp(random.uniform(lo, hi), lo, hi)

    # weighted strategy
    base = random.uniform(lo, hi)
    content_type = _detect_content_type(response, is_interrupt=is_interrupt)
    multipliers = config.pause_multipliers
    multiplier_map = {
        "question": multipliers.after_question,
        "statement": multipliers.after_statement,
        "interrupt": multipliers.after_interrupt,
        "joke": multipliers.after_joke,
        "emotional": multipliers.after_emotional,
    }
    multiplier = multiplier_map[content_type]
    return _clamp(base * multiplier, lo, hi)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))

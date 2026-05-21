"""Run-mode helpers for selecting the conversation implementation."""

from __future__ import annotations

import os
from typing import Literal, cast

ConversationMode = Literal["director", "embodied", "director_v2"]

_ENV_VAR = "CONVERSATION_MODE"
_VALID_MODES: set[ConversationMode] = {"director", "embodied", "director_v2"}


def get_conversation_mode() -> ConversationMode:
    """Return the configured conversation mode.

    The legacy Python director remains the default. Embodied Minecraft runs set
    ``CONVERSATION_MODE=embodied`` to rely on Mindcraft's decentralized
    respond/ignore behavior. Director V2 Minecraft runs set
    ``CONVERSATION_MODE=director_v2`` so the Python-side scene scheduler gates
    Mindcraft prompts.
    """
    raw_mode = os.environ.get(_ENV_VAR, "director").strip().lower()
    if raw_mode in _VALID_MODES:
        return cast("ConversationMode", raw_mode)
    raise ValueError(
        f"Unknown {_ENV_VAR}={raw_mode!r}; expected one of: director, embodied, director_v2"
    )


def is_embodied_run() -> bool:
    """Return true when the run should avoid the legacy Python director."""
    return get_conversation_mode() == "embodied"


def is_director_v2_run() -> bool:
    """Return true when Minecraft prompts should be gated by Director V2."""
    return get_conversation_mode() == "director_v2"

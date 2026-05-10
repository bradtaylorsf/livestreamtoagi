"""Parse transcript rows into per-turn replay cues.

Single source of truth for the cue plan that drives both the audio stitcher
(``scripts/render_simulation_video.py``) and the public replay-cues endpoint
(``core/public_routes.py``). They MUST share this module so audio playback
and on-screen speech bubbles cannot drift.

A transcript row's ``content`` is encoded as one or more ``[name]: ...``
markers. Earlier versions parsed only the leading marker, so a row containing
multiple speaker turns produced one giant cue with embedded ``[agent]``
fragments leaking into the bubble text. ``build_cues_from_rows`` walks every
marker in each row and emits one cue per voiced segment.

Unknown / malformed speakers are skipped rather than emitted with a bad name
or a participants[0] fallback — the speaker MUST come from the marker.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from core.video.audio_timeline import TurnAudioCue

logger = logging.getLogger(__name__)

SPEAKER_RE = re.compile(r"\[([^\]]+)\]:\s*")

DEFAULT_INTRA_ROW_WINDOW = 0.5
DEFAULT_WPM = 160.0
DEFAULT_READ_FLOOR_SECONDS = 1.5

_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


def _load_known_agents_from_disk() -> frozenset[str]:
    """Return the set of agent IDs configured on disk (lowercased).

    Best-effort: returns an empty set if the directory is missing or
    unreadable. Skips ``template/`` and dotfiles. Cached at module load.
    """
    if not _AGENTS_DIR.is_dir():
        return frozenset()
    ids: set[str] = set()
    for child in _AGENTS_DIR.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(("_", ".")) or name == "template":
            continue
        ids.add(name.lower())
    return frozenset(ids)


KNOWN_AGENT_IDS: frozenset[str] = _load_known_agents_from_disk()


def estimate_read_seconds(
    text: str,
    *,
    wpm: float = DEFAULT_WPM,
    floor: float = DEFAULT_READ_FLOOR_SECONDS,
) -> float:
    """Estimate how long a viewer needs to read/hear ``text``.

    Used so ``duration_seconds`` reflects the end of the replay rather than
    the start of the final cue. The audio stitcher uses the same heuristic
    for its trailing-tail buffer.
    """
    word_count = len(text.split())
    if word_count <= 0:
        return floor
    seconds = (word_count / wpm) * 60.0
    return max(floor, seconds)


def compute_replay_duration(cues: Iterable[TurnAudioCue]) -> float:
    """End-of-replay timestamp = last_cue.start + read-time(last_cue.text)."""
    last: TurnAudioCue | None = None
    for cue in cues:
        last = cue
    if last is None:
        return 0.0
    return last.start_seconds + estimate_read_seconds(last.text)


def _split_row_into_segments(content: str) -> list[tuple[str, str]]:
    """Walk every ``[name]:`` marker in ``content`` and yield (speaker, text).

    Anything before the first marker is non-voiced narration and is dropped.
    Empty trailing text is preserved here and filtered by the caller.
    """
    matches = list(SPEAKER_RE.finditer(content))
    if not matches:
        return []
    segments: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        speaker = match.group(1).strip().lower()
        text_start = match.end()
        text_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        text = content[text_start:text_end].strip()
        segments.append((speaker, text))
    return segments


def build_cues_from_rows(
    rows: list[dict],
    *,
    intra_row_window: float = DEFAULT_INTRA_ROW_WINDOW,
    known_agents: frozenset[str] | set[str] | None = None,
) -> list[TurnAudioCue]:
    """Convert transcript rows into per-turn ``TurnAudioCue`` instances.

    A single row may contain multiple ``[name]: ...`` markers; each marker
    becomes its own cue so speech bubbles render at turn granularity. When N
    cues come from one row, their start_seconds are evenly distributed
    within ``intra_row_window`` seconds after the row's timestamp so order
    is preserved without overlapping the next row.

    Speaker resolution: ``agent_id`` always comes from the marker — there is
    no participants[0] fallback. Speakers absent from ``known_agents`` (when
    provided) are skipped rather than polluting bubble text.

    Pure (no DB), so it can be unit-tested directly.
    """
    if not rows:
        return []

    valid_agents = (
        frozenset(a.lower() for a in known_agents) if known_agents is not None else KNOWN_AGENT_IDS
    )

    base: datetime = rows[0]["created_at"]
    cues: list[TurnAudioCue] = []
    for row in rows:
        content = row.get("content") or ""
        segments = _split_row_into_segments(content)
        if not segments:
            continue

        accepted: list[tuple[str, str]] = []
        for speaker, text in segments:
            if not speaker or not text:
                continue
            if valid_agents and speaker not in valid_agents:
                continue
            accepted.append((speaker, text))
        if not accepted:
            continue

        row_delta = max(0.0, (row["created_at"] - base).total_seconds())
        n = len(accepted)
        for i, (speaker, text) in enumerate(accepted):
            offset = (i / n) * intra_row_window if n > 1 else 0.0
            cues.append(
                TurnAudioCue(
                    agent_id=speaker,
                    text=text,
                    start_seconds=row_delta + offset,
                )
            )
    return cues

"""Pure transcript-row → ``TurnAudioCue`` parsing.

The audio stitcher and the replay page must agree byte-for-byte on which
turns are voiced and at what timestamp; otherwise the bubbles drift out of
sync with the speech. This module is the single source of truth for that
parsing so both sides import the same logic.

Speakers are encoded as a ``[name]: …`` prefix on ``transcripts.content``.
``transcripts.participants`` is the unordered set of attendees, NOT the
speaker — a prior version of this code mistakenly used ``participants[0]``
and produced MP4s with wrong voices for every sim (regression covered by
``tests/backend/test_video_render.py::TestBuildCuesFromRows``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from core.video.audio_timeline import TurnAudioCue

SPEAKER_RE = re.compile(r"^\[([^\]]+)\]:\s*")


def build_cues_from_rows(rows: list[Mapping[str, Any]]) -> list[TurnAudioCue]:
    """Convert ordered transcript rows into ``TurnAudioCue`` objects.

    Rows must already be sorted by ``created_at`` ascending. ``start_seconds``
    is computed as the delta from the first row's timestamp.
    """
    if not rows:
        return []
    base = rows[0]["created_at"]
    cues: list[TurnAudioCue] = []
    for r in rows:
        content = r.get("content") or ""
        match = SPEAKER_RE.match(content)
        if not match:
            continue
        agent_id = match.group(1).strip().lower()
        text = SPEAKER_RE.sub("", content, count=1).strip()
        if not text:
            continue
        delta = (r["created_at"] - base).total_seconds()
        cues.append(
            TurnAudioCue(
                agent_id=agent_id,
                text=text,
                start_seconds=max(0.0, delta),
            )
        )
    return cues

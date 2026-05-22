"""Opt-in Director V2 timeline emission for Minecraft soak runs."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DIRECTOR_TIMELINE_FILENAME = "director_v2.ndjson"


def emit_director_timeline_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    agent_id: str | None = None,
    trace_id: str | None = None,
    run_dir: str | Path | None = None,
) -> None:
    """Append one Director V2 event when soak evidence collection is enabled."""

    target_run_dir = Path(run_dir) if run_dir is not None else _soak_run_dir()
    if target_run_dir is None:
        return

    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event_type": event_type,
        "source": "director_v2",
        "payload": payload,
    }
    if agent_id:
        record["agent"] = str(agent_id).strip().lower()
    if trace_id:
        record["trace_id"] = str(trace_id)

    try:
        path = target_run_dir / "timeline-raw" / DIRECTOR_TIMELINE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    except OSError:
        logger.debug("Director V2 timeline event write failed", exc_info=True)


def _soak_run_dir() -> Path | None:
    raw = os.environ.get("SOAK_RUN_DIR") or os.environ.get("MC_RUN_DIR")
    if not raw:
        return None
    return Path(raw)

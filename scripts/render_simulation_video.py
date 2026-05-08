#!/usr/bin/env python3
"""Standalone entrypoint for rendering a finished simulation to MP4.

Spawned by ``core.video.worker.enqueue_render`` as a detached subprocess so
the orchestrator finalize path stays fast. Loads the simulation's transcript,
drives the headless replay capture, stitches TTS audio, and writes the final
file to local disk or S3 via the storage backend.

Usage:
    python scripts/render_simulation_video.py --sim-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


async def _build_cues(db, sim_id: uuid.UUID) -> list:
    """Pull every transcript line for this simulation, ordered by time.

    Returns a list of ``TurnAudioCue`` anchored at seconds-from-start.
    """
    from core.video.audio_timeline import TurnAudioCue

    rows = await db.fetch(
        """SELECT t.participants, t.content, t.created_at
             FROM transcripts t
             JOIN conversations c ON c.id = t.conversation_id
            WHERE c.simulation_id = $1
              AND t.event_type = 'turn'
            ORDER BY t.created_at""",
        sim_id,
    )
    if not rows:
        return []
    base = rows[0]["created_at"]
    cues: list[TurnAudioCue] = []
    for r in rows:
        parts = list(r["participants"] or [])
        if not parts:
            continue
        delta = (r["created_at"] - base).total_seconds()
        cues.append(
            TurnAudioCue(
                agent_id=parts[0],
                text=r["content"],
                start_seconds=max(0.0, delta),
            )
        )
    return cues


async def _main(sim_id: uuid.UUID) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("render_simulation_video")

    from core.bootstrap import bootstrap_services
    from core.repos.simulation_repo import SimulationRepo
    from core.tts import TTSPipeline
    from core.video.config import load_video_render_config
    from core.video.render_pipeline import RenderError, render_simulation_video
    from core.video.storage import save_video

    services = await bootstrap_services()
    repo = SimulationRepo(services.db)

    sim = await repo.get(sim_id)
    if sim is None:
        log.error("Simulation %s not found", sim_id)
        return 1

    cues = await _build_cues(services.db, sim_id)
    if not cues:
        log.warning("Simulation %s has no transcripts; marking skipped", sim_id)
        await repo.update_video_status(sim_id, status="skipped")
        return 0

    tts = TTSPipeline(agent_registry=services.agent_registry)
    config = load_video_render_config()

    try:
        result = await render_simulation_video(
            sim_id, cues=cues, tts=tts, config=config
        )
    except RenderError:
        log.exception("Render failed for %s", sim_id)
        await repo.update_video_status(sim_id, status="failed")
        return 1
    except Exception:
        log.exception("Unexpected render error for %s", sim_id)
        await repo.update_video_status(sim_id, status="failed")
        return 1

    try:
        url = save_video(sim_id, result.output_path, config=config)
    except Exception:
        log.exception("Storage upload failed for %s", sim_id)
        await repo.update_video_status(sim_id, status="failed")
        return 1

    await repo.update_video_status(sim_id, status="done", url=url)
    log.info(
        "[video] sim=%s done url=%s truncated=%s cues=%d",
        sim_id,
        url,
        result.truncated,
        result.cues_rendered,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Render simulation to MP4")
    parser.add_argument("--sim-id", required=True, help="Simulation UUID")
    args = parser.parse_args()
    sim_id = uuid.UUID(args.sim_id)
    sys.exit(asyncio.run(_main(sim_id)))


if __name__ == "__main__":
    main()

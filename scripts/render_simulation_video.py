#!/usr/bin/env python3
"""Standalone entrypoint for rendering a finished simulation to MP4.

Spawned by ``core.video.worker.enqueue_render`` as a detached subprocess so
the orchestrator finalize path stays fast. Loads the simulation's transcript,
drives the headless replay capture, stitches TTS audio, and writes the final
file to local disk or S3 via the storage backend.

Usage (canonical — bypasses stale ``python`` shims, sources ``.env``):
    make render-verify SIM=<uuid>            # or, with auto-pick:
    make render-verify
    bash scripts/verify-render.sh <uuid>

Usage (low-level, requires DATABASE_URL exported and ``.venv/bin/python`` on PATH):
    .venv/bin/python scripts/render_simulation_video.py --sim-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from core.video.cue_parser import build_cues_from_rows  # noqa: E402

# Exit codes used by the preflight checks. They are distinct from the
# generic-failure code 1 so the orchestrator log makes the misconfiguration
# obvious without having to grep stack traces.
EXIT_PLAYWRIGHT_NOT_INSTALLED = 2
EXIT_CHROMIUM_NOT_INSTALLED = 3


def _chromium_browser_dir_exists() -> bool:
    """Best-effort check that ``playwright install chromium`` has been run."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override == "0":
        try:
            import playwright  # type: ignore[import-not-found]
        except ImportError:
            return False
        candidates = [
            Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
        ]
    elif override:
        candidates = [Path(override)]
    else:
        home = Path.home()
        candidates = [
            home / "Library" / "Caches" / "ms-playwright",
            home / ".cache" / "ms-playwright",
            home / "AppData" / "Local" / "ms-playwright",
        ]

    for directory in candidates:
        if not directory.exists():
            continue
        try:
            if any(path.name.startswith("chromium-") for path in directory.iterdir()):
                return True
        except OSError:
            continue
    return False


def _preflight_render_dependencies(log: logging.Logger) -> int | None:
    """Surface clear, actionable errors before the heavy bootstrap path runs."""
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        log.error(
            'playwright is not installed — run `uv pip install -e ".[render]"` '
            "(or `pip install playwright>=1.47.0`) and then `playwright install chromium`"
        )
        return EXIT_PLAYWRIGHT_NOT_INSTALLED

    if not _chromium_browser_dir_exists():
        log.error(
            "playwright Chromium binaries not found — run `playwright install chromium`. "
            "Set PLAYWRIGHT_BROWSERS_PATH if you keep browsers in a non-default location."
        )
        return EXIT_CHROMIUM_NOT_INSTALLED

    return None


# Re-export under the historical underscore name so existing tests keep
# importing from this script. The audio stitcher and the replay-cues
# endpoint both call ``core.video.cue_parser.build_cues_from_rows``.
_build_cues_from_rows = build_cues_from_rows


async def _build_cues(db, sim_id: uuid.UUID) -> list:
    """Pull every transcript line for this simulation, ordered by time.

    Returns a list of ``TurnAudioCue`` anchored at seconds-from-start.
    """
    rows = await db.fetch(
        """SELECT t.participants, t.content, t.created_at
             FROM transcripts t
             JOIN conversations c ON c.id = t.conversation_id
            WHERE c.simulation_id = $1
            ORDER BY t.created_at""",
        sim_id,
    )
    return build_cues_from_rows(list(rows))


async def _main(sim_id: uuid.UUID) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("render_simulation_video")

    preflight = _preflight_render_dependencies(log)
    if preflight is not None:
        return preflight

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
        await repo.update_video_status(
            sim_id,
            status="skipped",
            failure_reason="No transcript cues were available to render.",
        )
        return 0

    tts = TTSPipeline(agent_registry=services.agent_registry)
    config = load_video_render_config()

    try:
        result = await render_simulation_video(sim_id, cues=cues, tts=tts, config=config)
    except RenderError as exc:
        log.exception("Render failed for %s", sim_id)
        await repo.update_video_status(
            sim_id,
            status="failed",
            failure_reason=str(exc) or "Video render failed.",
        )
        return 1
    except Exception as exc:
        log.exception("Unexpected render error for %s", sim_id)
        await repo.update_video_status(
            sim_id,
            status="failed",
            failure_reason=f"Unexpected video render error: {exc}",
        )
        return 1

    try:
        url = save_video(sim_id, result.output_path, config=config)
    except Exception as exc:
        log.exception("Storage upload failed for %s", sim_id)
        await repo.update_video_status(
            sim_id,
            status="failed",
            failure_reason=f"Video storage failed: {exc}",
        )
        return 1

    await repo.update_video_status(sim_id, status="done", url=url)
    log.info(
        "[video] sim=%s done url=%s truncated=%s cues=%d",
        sim_id,
        url,
        result.truncated,
        result.cues_rendered,
    )

    # Best-effort YouTube auto-publish for opted-in sims. Never block the
    # render success path on a publish failure.
    try:
        from core.youtube.worker import enqueue_youtube_publish

        fresh = await repo.get(sim_id)
        if fresh is not None:
            await enqueue_youtube_publish(sim_id, sim_repo=repo, sim=fresh)
    except Exception:
        log.exception("[youtube] enqueue failed for %s", sim_id)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Render simulation to MP4")
    parser.add_argument("--sim-id", required=True, help="Simulation UUID")
    args = parser.parse_args()
    sim_id = uuid.UUID(args.sim_id)
    sys.exit(asyncio.run(_main(sim_id)))


if __name__ == "__main__":
    main()

"""Idempotent dispatcher that auto-publishes a finished sim video to YouTube.

Mirrors the video-render subprocess pattern: ``enqueue_youtube_publish`` is
called from the render finalize hook, atomically claims the sim via
``SimulationRepo.claim_for_youtube_publish``, and spawns
``scripts/publish_simulation_youtube.py`` as a detached subprocess. The actual
upload (resumable ``MediaFileUpload`` + Data API insert) happens in that
subprocess so finalize stays fast.

Under pytest the subprocess spawn is a no-op; tests assert on the claim
transition + repo state.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.youtube.config import load_youtube_config

if TYPE_CHECKING:
    from core.repos.simulation_repo import SimulationRepo

logger = logging.getLogger(__name__)


async def enqueue_youtube_publish(
    simulation_id: uuid.UUID | str,
    *,
    sim_repo: SimulationRepo,
    sim: Any | None = None,
) -> str:
    """Idempotently claim and spawn the YouTube publish subprocess.

    Guards on the master ``YOUTUBE_PUBLISH_ENABLED`` flag, the per-sim
    ``publish_to_youtube`` opt-in, and the prerequisite that a video has
    actually rendered. Returns one of:

      * ``"started"`` — claimed and subprocess spawned (or skipped under pytest)
      * ``"disabled"`` — master kill switch is off
      * ``"opt_out"`` — sim did not opt in to YouTube publishing
      * ``"no_video"`` — render hasn't produced a usable mp4 yet
      * ``"already_publishing"`` / ``"already_done"`` / ``"failed"`` — claim states
    """
    sim_id = uuid.UUID(str(simulation_id))
    config = load_youtube_config()

    if not config.enabled:
        return "disabled"

    if sim is None:
        sim = await sim_repo.get(sim_id)
    if sim is None:
        logger.warning("[youtube] sim %s not found", sim_id)
        return "no_video"

    if not getattr(sim, "publish_to_youtube", False):
        return "opt_out"

    if (
        not getattr(sim, "video_url", None)
        or getattr(sim, "video_render_status", None) != "done"
    ):
        return "no_video"

    state = await sim_repo.claim_for_youtube_publish(sim_id)
    if state == "publishing":
        return "already_publishing"
    if state == "done":
        return "already_done"
    if state != "claimed":
        # 'failed' here means a previous attempt exhausted retries;
        # don't auto-retry without an explicit reset.
        logger.info(
            "[youtube] not claiming sim=%s in state=%s", sim_id, state
        )
        return state or "no_video"

    project_root = Path(__file__).resolve().parent.parent.parent
    cmd = [
        sys.executable,
        str(project_root / "scripts" / "publish_simulation_youtube.py"),
        "--sim-id",
        str(sim_id),
    ]
    if os.environ.get("PYTEST_CURRENT_TEST"):
        logger.info("[youtube] (pytest) skipping subprocess for sim=%s", sim_id)
        return "started"

    try:
        subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(project_root),
        )
    except Exception:
        # Spawn failed — release the lock so a future run can retry.
        logger.exception(
            "[youtube] failed to spawn publish subprocess for sim=%s", sim_id
        )
        await sim_repo.update_youtube_status(
            sim_id,
            status="failed",
            failure_reason="subprocess spawn failed",
        )
        return "failed"

    logger.info("[youtube] enqueued publish subprocess for sim=%s", sim_id)
    return "started"

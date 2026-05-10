"""Idempotent dispatcher that kicks off a video render for a finished sim.

Mirrors the public-submission subprocess pattern: the orchestrator calls
``enqueue_render`` synchronously, which atomically claims the sim via
``SimulationRepo.claim_for_render`` and then spawns ``scripts/
render_simulation_video.py`` in a detached subprocess. The actual heavy
lifting (Playwright + ffmpeg) happens in that subprocess so the orchestrator
finalize path stays fast.

In tests, the subprocess spawn is a no-op when ``PYTEST_CURRENT_TEST`` is
set; tests assert on the claim transition + repo state instead.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.repos.simulation_repo import SimulationRepo

logger = logging.getLogger(__name__)


async def enqueue_render(
    simulation_id: uuid.UUID | str,
    *,
    sim_repo: SimulationRepo,
) -> str:
    """Idempotently kick off a render.

    Returns one of:
      * ``"started"`` — claimed and subprocess spawned (or skipped under pytest)
      * ``"already_rendering"`` — another worker has the lock
      * ``"already_done"`` — video already exists
      * ``"skipped"`` — sim was previously marked unrenderable
    """
    sim_id = uuid.UUID(str(simulation_id))
    state = await sim_repo.claim_for_render(sim_id)

    if state == "rendering":
        return "already_rendering"
    if state == "done":
        return "already_done"
    if state == "skipped":
        return "skipped"
    if state != "claimed":
        # Unknown state — be conservative and bail.
        logger.warning("[video] unexpected claim state=%s for sim=%s", state, sim_id)
        return "skipped"

    project_root = Path(__file__).resolve().parent.parent.parent
    cmd = [
        sys.executable,
        str(project_root / "scripts" / "render_simulation_video.py"),
        "--sim-id",
        str(sim_id),
    ]
    if os.environ.get("PYTEST_CURRENT_TEST"):
        logger.info("[video] (pytest) skipping subprocess for sim=%s", sim_id)
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
        # If the subprocess can't even be spawned, free the lock so a future
        # run can retry rather than leaving the sim stuck in 'rendering'.
        logger.exception("[video] failed to spawn render subprocess for sim=%s", sim_id)
        await sim_repo.update_video_status(
            sim_id,
            status="failed",
            failure_reason="Render worker failed to start.",
        )
        return "skipped"

    logger.info("[video] enqueued render subprocess for sim=%s", sim_id)
    return "started"


async def mark_unrenderable(
    simulation_id: uuid.UUID | str,
    *,
    sim_repo: SimulationRepo,
    reason: str,
) -> None:
    """Stamp the sim as ``skipped`` when there's nothing to render."""
    sim_id = uuid.UUID(str(simulation_id))
    logger.info("[video] marking sim=%s as skipped: %s", sim_id, reason)
    await sim_repo.update_video_status(sim_id, status="skipped", failure_reason=reason)

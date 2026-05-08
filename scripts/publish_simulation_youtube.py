#!/usr/bin/env python3
"""Standalone entrypoint for uploading a finished simulation video to YouTube.

Spawned by ``core.youtube.worker.enqueue_youtube_publish`` as a detached
subprocess so the orchestrator finalize path stays fast. Loads the
simulation's metadata, locates the rendered MP4 (local disk or S3),
composes the YouTube snippet, and uploads via the Data API. Updates
``simulations.youtube_*`` columns on success or failure.

Usage:
    python scripts/publish_simulation_youtube.py --sim-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


def _scenario_title(sim: object) -> str:
    """Return a human-readable title for the scenario, falling back to sim name."""
    config = getattr(sim, "config", None) or {}
    if isinstance(config, dict):
        scenario_meta = config.get("scenario_meta")
        if isinstance(scenario_meta, dict):
            title = scenario_meta.get("title") or scenario_meta.get("name")
            if isinstance(title, str) and title.strip():
                return title.strip()
        scenario_id = config.get("scenario_id") or config.get("seed_file")
        if isinstance(scenario_id, str) and scenario_id.strip():
            return Path(scenario_id).stem.replace("_", " ").replace("-", " ")
    return getattr(sim, "name", "simulation")


def _scenario_tags(sim: object) -> list[str]:
    config = getattr(sim, "config", None) or {}
    tags: list[str] = []
    if isinstance(config, dict):
        meta = config.get("scenario_meta")
        if isinstance(meta, dict):
            raw_tags = meta.get("tags") or []
            if isinstance(raw_tags, list):
                tags.extend(t for t in raw_tags if isinstance(t, str))
    agents = list(getattr(sim, "agents_participated", []) or [])
    return tags + agents


def _outcomes_summary(sim: object) -> str:
    outcomes = getattr(sim, "outcomes", None) or {}
    if not isinstance(outcomes, dict) or not outcomes:
        return ""
    summary = outcomes.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    # Fall back to a compact key:value listing for non-summarized outcomes
    parts: list[str] = []
    for k, v in outcomes.items():
        if isinstance(v, (str, int, float, bool)):
            parts.append(f"{k}: {v}")
    return "; ".join(parts)


def _compose_description(sim: object, public_base_url: str) -> str:
    lines: list[str] = []
    hypothesis = getattr(sim, "hypothesis", None)
    if hypothesis:
        lines.append("Hypothesis:")
        lines.append(str(hypothesis).strip())
        lines.append("")
    summary = _outcomes_summary(sim)
    if summary:
        lines.append("Outcomes:")
        lines.append(summary)
        lines.append("")
    sim_id = getattr(sim, "id", None)
    if sim_id is not None:
        lines.append(f"Full simulation: {public_base_url}/simulations/{sim_id}")
    return "\n".join(lines).strip() or f"Simulation {sim_id}"


def _resolve_local_path(sim_id: uuid.UUID, video_url: str) -> Path | None:
    """Return the on-disk MP4 path for a local-backend simulation, or None."""
    from core.video.config import load_video_render_config

    cfg = load_video_render_config()
    if cfg.storage_backend != "local":
        return None
    candidate = Path(cfg.output_dir) / f"{sim_id}.mp4"
    if candidate.exists():
        return candidate
    # Fall back to interpreting the path part of the URL relative to cwd
    if video_url.startswith("/"):
        rel = Path(video_url.lstrip("/"))
        if rel.exists():
            return rel
    return None


def _download_s3(video_url: str, dest: Path) -> Path:
    """Download an s3-stored MP4 to ``dest`` and return the path."""
    import re

    m = re.match(r"https?://([^.]+)\.s3\.amazonaws\.com/(.+)", video_url)
    if not m:
        raise ValueError(f"Unrecognized S3 video URL: {video_url}")
    bucket, key = m.group(1), m.group(2)
    import boto3  # type: ignore[import-not-found]

    s3 = boto3.client("s3")
    s3.download_file(bucket, key, str(dest))
    return dest


async def _materialize_mp4(sim_id: uuid.UUID, video_url: str, tmp_dir: Path) -> Path:
    """Return a local filesystem path to the simulation's MP4."""
    local = _resolve_local_path(sim_id, video_url)
    if local is not None:
        return local
    if video_url.startswith(("http://", "https://")):
        if "s3.amazonaws.com" in video_url:
            return _download_s3(video_url, tmp_dir / f"{sim_id}.mp4")
        # Generic HTTP download
        import httpx

        dest = tmp_dir / f"{sim_id}.mp4"
        with httpx.stream("GET", video_url, timeout=120.0) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        return dest
    raise FileNotFoundError(f"could not locate MP4 for {sim_id} at {video_url}")


async def _main(sim_id: uuid.UUID) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("publish_simulation_youtube")

    from core.bootstrap import bootstrap_services
    from core.repos.simulation_repo import SimulationRepo
    from core.youtube.client import YoutubeUploadError, upload_video
    from core.youtube.config import load_youtube_config

    config = load_youtube_config()
    if not config.enabled:
        log.info("YOUTUBE_PUBLISH_ENABLED is off; nothing to do")
        return 0

    services = await bootstrap_services()
    repo = SimulationRepo(services.db)
    sim = await repo.get(sim_id)
    if sim is None:
        log.error("Simulation %s not found", sim_id)
        return 1

    if not sim.publish_to_youtube:
        log.info("sim %s did not opt in; skipping", sim_id)
        return 0

    if not sim.video_url or sim.video_render_status != "done":
        log.warning("sim %s has no rendered video yet", sim_id)
        await repo.update_youtube_status(
            sim_id,
            status="failed",
            failure_reason="no rendered video available",
        )
        return 1

    title = f"{sim.name} — {_scenario_title(sim)}"
    description = _compose_description(sim, config.public_base_url)
    tags = _scenario_tags(sim)

    import tempfile

    last_reason = "unknown"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            local_mp4 = await _materialize_mp4(sim_id, sim.video_url, tmp_path)
        except Exception as exc:
            log.exception("failed to materialize MP4 for %s", sim_id)
            await repo.update_youtube_status(
                sim_id,
                status="failed",
                failure_reason=f"materialize: {exc}",
                increment_attempts=True,
            )
            return 1

        for attempt in range(1, max(1, config.max_retries) + 1):
            try:
                result = upload_video(
                    local_mp4,
                    title=title,
                    description=description,
                    tags=tags,
                    config=config,
                    privacy_status=config.default_privacy,
                )
            except YoutubeUploadError as exc:
                last_reason = exc.reason
                log.warning(
                    "upload attempt %d/%d failed for %s: %s",
                    attempt,
                    config.max_retries,
                    sim_id,
                    exc.reason,
                )
                await repo.update_youtube_status(
                    sim_id,
                    status=None,
                    failure_reason=exc.reason,
                    increment_attempts=True,
                )
                if not exc.retryable or attempt >= config.max_retries:
                    await repo.update_youtube_status(
                        sim_id,
                        status="failed",
                        failure_reason=exc.reason,
                    )
                    return 1
                # Exponential backoff: 2s, 4s, 8s, ...
                time.sleep(2 ** attempt)
                continue

            await repo.update_youtube_status(
                sim_id,
                status="done",
                url=result.url,
                increment_attempts=True,
            )
            log.info("[youtube] sim=%s published url=%s", sim_id, result.url)
            return 0

    await repo.update_youtube_status(
        sim_id,
        status="failed",
        failure_reason=last_reason,
    )
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish simulation MP4 to YouTube")
    parser.add_argument("--sim-id", required=True, help="Simulation UUID")
    args = parser.parse_args()
    sim_id = uuid.UUID(args.sim_id)
    sys.exit(asyncio.run(_main(sim_id)))


if __name__ == "__main__":
    main()

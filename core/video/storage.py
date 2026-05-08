"""Persist rendered videos to local disk or S3 and return a URL."""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from core.video.config import VideoRenderConfig, load_video_render_config

logger = logging.getLogger(__name__)


def save_video(
    sim_id: uuid.UUID | str,
    local_path: Path | str,
    *,
    config: VideoRenderConfig | None = None,
) -> str:
    """Move ``local_path`` to its final home and return a URL for it.

    For ``VIDEO_STORAGE=local`` (default) the file is moved to
    ``<output_dir>/<sim_id>.mp4`` and the returned URL is relative to the
    public base URL. For ``VIDEO_STORAGE=s3`` the file is uploaded to the
    configured bucket via boto3 and the returned URL is the public S3 URL.
    """
    config = config or load_video_render_config()
    src = Path(local_path)
    if not src.exists():
        raise FileNotFoundError(f"Render output not found: {src}")

    sim_id_str = str(sim_id)

    if config.storage_backend == "s3":
        bucket = config.s3_bucket
        if not bucket:
            raise ValueError(
                "VIDEO_STORAGE=s3 requires VIDEO_S3_BUCKET to be set"
            )
        # Lazy import so the boto3 dependency is only required when actually
        # using the s3 backend.
        import boto3  # type: ignore[import-not-found]

        key = f"videos/{sim_id_str}.mp4"
        s3 = boto3.client("s3")
        s3.upload_file(
            str(src),
            bucket,
            key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
        logger.info("[video] uploaded sim=%s to s3://%s/%s", sim_id_str, bucket, key)
        return f"https://{bucket}.s3.amazonaws.com/{key}"

    # Local backend
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{sim_id_str}.mp4"
    shutil.move(str(src), str(dest))
    logger.info("[video] wrote sim=%s to %s", sim_id_str, dest)
    return f"/videos/{sim_id_str}.mp4"

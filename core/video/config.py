"""Environment-driven configuration for the video render pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VideoRenderConfig:
    max_render_minutes: int
    storage_backend: str
    s3_bucket: str | None
    output_dir: str
    public_base_url: str
    replay_url_template: str

    @property
    def max_render_seconds(self) -> int:
        return self.max_render_minutes * 60


def load_video_render_config() -> VideoRenderConfig:
    return VideoRenderConfig(
        max_render_minutes=int(os.environ.get("MAX_VIDEO_RENDER_MINUTES", "30")),
        storage_backend=os.environ.get("VIDEO_STORAGE", "local").lower(),
        s3_bucket=os.environ.get("VIDEO_S3_BUCKET") or None,
        output_dir=os.environ.get("VIDEO_OUTPUT_DIR", "videos"),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        replay_url_template=os.environ.get(
            "VIDEO_REPLAY_URL_TEMPLATE",
            "{base_url}/simulations/{sim_id}/replay?renderMode=1",
        ),
    )

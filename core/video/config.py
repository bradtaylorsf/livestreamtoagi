"""Environment-driven configuration for the video render pipeline.

``PUBLIC_BASE_URL`` is the public website origin used for user-facing links
and for the default replay capture URL. In local development that is the
Next.js website at ``http://localhost:4000``; the backend API stays on 8010.

``VIDEO_REPLAY_URL_TEMPLATE`` is an optional render-worker override for the
capture page. It may use ``{base_url}`` and ``{sim_id}`` placeholders.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_PUBLIC_BASE_URL = "http://localhost:4000"
DEFAULT_REPLAY_URL_TEMPLATE = "{base_url}/simulations/{sim_id}/replay?renderMode=1"


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

    def replay_url_for(self, sim_id: str) -> str:
        """Return the browser URL Playwright should capture for ``sim_id``."""
        try:
            return self.replay_url_template.format(
                base_url=self.public_base_url,
                sim_id=str(sim_id),
            )
        except KeyError as exc:
            raise ValueError(
                "VIDEO_REPLAY_URL_TEMPLATE may only reference {base_url} and {sim_id}"
            ) from exc


def load_video_render_config() -> VideoRenderConfig:
    return VideoRenderConfig(
        max_render_minutes=int(os.environ.get("MAX_VIDEO_RENDER_MINUTES", "30")),
        storage_backend=os.environ.get("VIDEO_STORAGE", "local").lower(),
        s3_bucket=os.environ.get("VIDEO_S3_BUCKET") or None,
        output_dir=os.environ.get("VIDEO_OUTPUT_DIR", "videos"),
        public_base_url=_env_or_default("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL).rstrip(
            "/"
        ),
        replay_url_template=_env_or_default(
            "VIDEO_REPLAY_URL_TEMPLATE",
            DEFAULT_REPLAY_URL_TEMPLATE,
        ),
    )


def _env_or_default(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()

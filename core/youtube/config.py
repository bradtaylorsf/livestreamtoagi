"""Environment-driven configuration for the YouTube auto-publish pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class YoutubePublishConfig:
    enabled: bool
    oauth_client_id: str | None
    oauth_client_secret: str | None
    refresh_token: str | None
    max_retries: int
    default_privacy: str
    public_base_url: str

    @property
    def credentials_present(self) -> bool:
        return bool(self.oauth_client_id and self.oauth_client_secret and self.refresh_token)


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_youtube_config() -> YoutubePublishConfig:
    return YoutubePublishConfig(
        enabled=_parse_bool(os.environ.get("YOUTUBE_PUBLISH_ENABLED"), False),
        oauth_client_id=os.environ.get("YOUTUBE_OAUTH_CLIENT_ID") or None,
        oauth_client_secret=os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET") or None,
        refresh_token=os.environ.get("YOUTUBE_REFRESH_TOKEN") or None,
        max_retries=int(os.environ.get("YOUTUBE_MAX_RETRIES", "3")),
        default_privacy=(os.environ.get("YOUTUBE_DEFAULT_PRIVACY", "unlisted").lower()),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
    )

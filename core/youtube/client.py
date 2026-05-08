"""Thin wrapper over the YouTube Data API v3 for video uploads.

The google-api-python-client + google-auth dependencies are imported lazily
so the rest of the codebase doesn't pay the import cost when the publish
pipeline is disabled (the common case in dev/test). All API errors surface
as ``YoutubeUploadError`` with a short reason string the caller can persist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from core.youtube.config import YoutubePublishConfig

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_API_VERSION = "v3"
YOUTUBE_API_NAME = "youtube"


class YoutubeUploadError(Exception):
    """Raised when an upload (or privacy update) fails."""

    def __init__(self, reason: str, *, retryable: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True)
class YoutubeUploadResult:
    video_id: str
    url: str


def _build_credentials(config: YoutubePublishConfig) -> Any:
    """Construct OAuth credentials from a stored refresh token."""
    if not config.credentials_present:
        raise YoutubeUploadError(
            "missing YouTube OAuth credentials",
            retryable=False,
        )
    try:
        from google.oauth2.credentials import Credentials  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - dep gated install
        raise YoutubeUploadError(
            f"google-auth not installed: {exc}",
            retryable=False,
        ) from exc

    return Credentials(
        token=None,
        refresh_token=config.refresh_token,
        client_id=config.oauth_client_id,
        client_secret=config.oauth_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=YOUTUBE_SCOPES,
    )


def _build_service(config: YoutubePublishConfig) -> Any:
    """Build a YouTube Data API client. Raises ``YoutubeUploadError`` on failure."""
    try:
        from googleapiclient.discovery import build  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - dep gated install
        raise YoutubeUploadError(
            f"google-api-python-client not installed: {exc}",
            retryable=False,
        ) from exc

    creds = _build_credentials(config)
    return build(
        YOUTUBE_API_NAME,
        YOUTUBE_API_VERSION,
        credentials=creds,
        cache_discovery=False,
    )


def upload_video(
    file_path: Path | str,
    *,
    title: str,
    description: str,
    tags: list[str],
    config: YoutubePublishConfig,
    privacy_status: str | None = None,
) -> YoutubeUploadResult:
    """Upload a local MP4 to YouTube and return the resulting video URL.

    Uses a resumable ``MediaFileUpload`` so large files don't blow up on
    transient network blips. Failures surface as ``YoutubeUploadError``.
    """
    src = Path(file_path)
    if not src.exists():
        raise YoutubeUploadError(
            f"render output not found: {src}",
            retryable=False,
        )

    privacy = (privacy_status or config.default_privacy or "unlisted").lower()
    if privacy not in {"public", "private", "unlisted"}:
        raise YoutubeUploadError(
            f"invalid privacy_status: {privacy}",
            retryable=False,
        )

    try:
        from googleapiclient.errors import HttpError  # type: ignore[import-not-found]
        from googleapiclient.http import MediaFileUpload  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - dep gated install
        raise YoutubeUploadError(
            f"google-api-python-client not installed: {exc}",
            retryable=False,
        ) from exc

    service = _build_service(config)
    body = {
        "snippet": {
            "title": title[:100],  # YouTube hard cap
            "description": description[:5000],  # YouTube hard cap
            "tags": [t for t in tags if t][:20],
            "categoryId": "28",  # Science & Technology
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }

    media = MediaFileUpload(
        str(src),
        mimetype="video/mp4",
        resumable=True,
        chunksize=-1,
    )

    try:
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            _status, response = request.next_chunk()
    except HttpError as exc:
        status_code = getattr(getattr(exc, "resp", None), "status", None)
        retryable = status_code is None or 500 <= int(status_code) < 600
        raise YoutubeUploadError(
            f"YouTube API HttpError {status_code}: {exc}",
            retryable=retryable,
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise YoutubeUploadError(f"unexpected upload error: {exc}") from exc

    video_id = response.get("id") if isinstance(response, dict) else None
    if not video_id:
        raise YoutubeUploadError("upload response missing video id")
    return YoutubeUploadResult(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
    )


def update_privacy(
    video_id: str,
    *,
    privacy_status: str,
    config: YoutubePublishConfig,
) -> None:
    """Promote (or demote) a video's privacy status via videos.update."""
    privacy = privacy_status.lower()
    if privacy not in {"public", "private", "unlisted"}:
        raise YoutubeUploadError(
            f"invalid privacy_status: {privacy}",
            retryable=False,
        )
    try:
        from googleapiclient.errors import HttpError  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise YoutubeUploadError(
            f"google-api-python-client not installed: {exc}",
            retryable=False,
        ) from exc

    service = _build_service(config)
    try:
        service.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": {"privacyStatus": privacy},
            },
        ).execute()
    except HttpError as exc:
        status_code = getattr(getattr(exc, "resp", None), "status", None)
        raise YoutubeUploadError(
            f"YouTube API HttpError {status_code}: {exc}",
            retryable=status_code is None or 500 <= int(status_code) < 600,
        ) from exc

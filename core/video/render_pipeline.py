"""Headless Phaser-canvas → MP4 render pipeline.

Drives a Playwright Chromium against the read-only ``/simulations/{id}/replay``
page, captures the canvas via ``page.video``, runs the audio stitch in
parallel, and finally muxes the two with ffmpeg into a single MP4.

The replay page is expected to expose two globals:

  * ``window.__replayReady = true`` once Phaser finishes loading.
  * ``window.__replayDone  = true`` once the deterministic playback ends.

Truncation: if the page hasn't signalled done after
``MAX_VIDEO_RENDER_MINUTES``, capture stops and a ``[truncated]`` marker is
written into the simulation record (handled upstream).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from core.video.audio_timeline import TurnAudioCue, stitch_audio_timeline
from core.video.config import VideoRenderConfig, load_video_render_config

if TYPE_CHECKING:
    from core.tts import TTSPipeline

logger = logging.getLogger(__name__)

LOCAL_REPLAY_HELP = (
    "Expected the Next.js website replay route on http://localhost:4000 "
    "with the backend API on http://localhost:8010. Start the normal `pnpm dev` "
    "stack or set PUBLIC_BASE_URL / VIDEO_REPLAY_URL_TEMPLATE for this worker."
)


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    truncated: bool
    duration_seconds: float
    cues_rendered: int


class RenderError(RuntimeError):
    """Raised when the render pipeline cannot produce an MP4."""


class _ReplayResponse(Protocol):
    status: int


def _replay_page_error(message: str, replay_url: str) -> RenderError:
    return RenderError(f"{message}: {replay_url}. {LOCAL_REPLAY_HELP}")


def _raise_for_bad_replay_response(
    response: _ReplayResponse | None,
    replay_url: str,
) -> None:
    if response is None:
        raise _replay_page_error(
            "Replay page did not return an HTTP response",
            replay_url,
        )
    if response.status < 200 or response.status >= 400:
        raise _replay_page_error(
            f"Replay page returned HTTP {response.status}",
            replay_url,
        )


async def _read_replay_error(page: Any) -> str | None:
    raw = await page.evaluate("() => window.__replayError || null")
    if raw is None:
        return None
    message = str(raw).strip()
    return message or None


async def _raise_for_page_replay_error(page: Any, replay_url: str) -> None:
    message = await _read_replay_error(page)
    if message:
        raise _replay_page_error(
            f"Replay page reported __replayError: {message}",
            replay_url,
        )


async def _wait_for_replay_ready_or_error(page: Any, replay_url: str) -> None:
    try:
        await page.wait_for_function(
            "() => window.__replayReady === true || Boolean(window.__replayError)",
            timeout=30_000,
        )
    except Exception as exc:
        await _raise_for_page_replay_error(page, replay_url)
        raise _replay_page_error(
            "Replay page did not signal __replayReady within 30s",
            replay_url,
        ) from exc

    await _raise_for_page_replay_error(page, replay_url)


async def _wait_for_replay_done_or_error(
    page: Any,
    replay_url: str,
    max_seconds: int,
) -> bool:
    """Return True when capture should be marked truncated."""
    try:
        await page.wait_for_function(
            "() => window.__replayDone === true || Boolean(window.__replayError)",
            timeout=max_seconds * 1000,
        )
    except Exception:
        await _raise_for_page_replay_error(page, replay_url)
        return True

    await _raise_for_page_replay_error(page, replay_url)
    return False


async def _capture_canvas(
    *,
    replay_url: str,
    output_path: Path,
    max_seconds: int,
) -> tuple[Path, bool]:
    """Drive Playwright to record the replay page's canvas.

    Returns ``(video_path, truncated)``. Imported lazily so the whole
    pipeline can be unit-tested without playwright installed.
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RenderError("playwright is not installed; cannot capture canvas") from exc

    truncated = False
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = None
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=str(output_path.parent),
                record_video_size={"width": 1280, "height": 720},
            )
            page = await context.new_page()
            try:
                response = await page.goto(replay_url, wait_until="domcontentloaded")
            except Exception as exc:
                raise _replay_page_error("Could not open replay page", replay_url) from exc

            _raise_for_bad_replay_response(response, replay_url)

            await _wait_for_replay_ready_or_error(page, replay_url)

            if await _wait_for_replay_done_or_error(page, replay_url, max_seconds):
                truncated = True
                logger.warning("[video] replay capture truncated at %ds", max_seconds)
        finally:
            if context is not None:
                await context.close()
            await browser.close()

    # Playwright writes a webm into the record_video_dir; pick the newest.
    candidates = sorted(
        output_path.parent.glob("*.webm"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RenderError("playwright did not produce a video file")
    return candidates[0], truncated


def _mux_final_mp4(
    *,
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    truncated: bool,
    ffmpeg_bin: str = "ffmpeg",
) -> None:
    """Mux video + audio into the final MP4, optionally drawing a banner."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
    ]
    if truncated:
        cmd += [
            "-vf",
            "drawtext=text='[truncated]':fontcolor=white:fontsize=28:"
            "x=w-tw-20:y=20:box=1:boxcolor=black@0.6",
        ]
    cmd.append(str(output_path))
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603


async def render_simulation_video(
    sim_id: uuid.UUID | str,
    *,
    cues: list[TurnAudioCue],
    tts: TTSPipeline,
    config: VideoRenderConfig | None = None,
    work_dir: Path | None = None,
) -> RenderResult:
    """Render a finished simulation to MP4 and return the local path.

    The caller is responsible for moving the file into long-term storage
    (``core.video.storage.save_video``) and updating the DB.
    """
    config = config or load_video_render_config()
    sim_id_str = str(sim_id)

    if not cues:
        raise RenderError("no transcript cues — nothing to render")

    work = work_dir or Path(tempfile.mkdtemp(prefix=f"render_{sim_id_str}_"))
    work.mkdir(parents=True, exist_ok=True)
    audio_path = work / "audio.wav"
    final_path = work / f"{sim_id_str}.mp4"

    replay_url = config.replay_url_for(sim_id_str)
    logger.info("[video] capture replay url=%s", replay_url)

    capture_task = asyncio.create_task(
        _capture_canvas(
            replay_url=replay_url,
            output_path=work / "canvas.webm",
            max_seconds=config.max_render_seconds,
        )
    )
    stitch_task = asyncio.create_task(stitch_audio_timeline(cues, tts=tts, output_path=audio_path))
    (canvas_path, truncated), stitch_result = await asyncio.gather(
        capture_task,
        stitch_task,
    )

    _mux_final_mp4(
        video_path=canvas_path,
        audio_path=audio_path,
        output_path=final_path,
        truncated=truncated,
    )

    return RenderResult(
        output_path=final_path,
        truncated=truncated,
        duration_seconds=stitch_result.duration_seconds,
        cues_rendered=stitch_result.cues_rendered,
    )

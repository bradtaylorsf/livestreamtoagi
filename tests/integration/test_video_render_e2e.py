"""End-to-end render-pipeline test against a stub replay page.

The real replay page is a Next.js + Phaser bundle (``website/src/app/
simulations/[id]/replay/page.tsx``). Spinning up Next.js inside pytest is
impractical, so this test stands up a tiny static HTTP server hosting an
HTML page that implements the same ``__replayReady`` / ``__replayDone``
contract the pipeline polls for. That gives us coverage of:

  * Playwright launch → goto → wait_for_function → record video.
  * audio_timeline stitching with stubbed TTS.
  * ffmpeg mux into the final MP4.
  * ffprobe confirming both a video and an audio stream.

The Phaser page itself is tested separately by ``website/src/components/
replay/__tests__/playback.test.ts``.

Skipped unless playwright + Chromium + ffmpeg/ffprobe are installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import shutil
import socketserver
import subprocess
import threading
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration


def _has_playwright_browser() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    from scripts.render_simulation_video import _chromium_browser_dir_exists

    return _chromium_browser_dir_exists()


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _has_playwright_browser(),
        reason="playwright+chromium not installed (run `playwright install chromium`)",
    ),
    pytest.mark.skipif(
        not _has_ffmpeg(),
        reason="ffmpeg/ffprobe not on PATH",
    ),
]


_STUB_PAGE = """<!doctype html>
<html><head><title>replay-stub</title></head>
<body style="margin:0;background:#000;color:#fff;font-family:sans-serif">
<canvas id="c" width="1280" height="720"
        style="display:block;background:#0b1020"></canvas>
<script>
(function(){
  const ctx = document.getElementById('c').getContext('2d');
  ctx.fillStyle = '#0b1020';
  ctx.fillRect(0, 0, 1280, 720);
  ctx.fillStyle = '#7dd3fc';
  ctx.font = '28px sans-serif';
  ctx.fillText('replay stub — vera/rex', 40, 60);
  // Match the contract the render pipeline polls for.
  window.__replayReady = true;
  setTimeout(function(){ window.__replayDone = true; }, 1500);
})();
</script>
</body></html>
"""


@contextlib.contextmanager
def _serve(directory: Path):
    handler = http.server.SimpleHTTPRequestHandler

    class Handler(handler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *_args):
            return

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield port
        finally:
            httpd.shutdown()
            thread.join(timeout=2)


@pytest.fixture
def stub_server(tmp_path):
    page_dir = tmp_path / "site"
    page_dir.mkdir()
    sim_id = uuid.uuid4()
    target = page_dir / "simulations" / str(sim_id) / "replay"
    target.mkdir(parents=True)
    (target / "index.html").write_text(_STUB_PAGE)
    with _serve(page_dir) as port:
        yield port, sim_id


@pytest.mark.asyncio
async def test_pipeline_produces_mp4_with_video_and_audio_streams(
    tmp_path, stub_server, monkeypatch
):
    port, sim_id = stub_server
    monkeypatch.setenv("PUBLIC_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv(
        "VIDEO_REPLAY_URL_TEMPLATE",
        "{base_url}/simulations/{sim_id}/replay/index.html",
    )

    from core.video.audio_timeline import TurnAudioCue
    from core.video.config import load_video_render_config
    from core.video.render_pipeline import render_simulation_video

    cues = [
        TurnAudioCue(agent_id="vera", text="hello", start_seconds=0.0),
        TurnAudioCue(agent_id="rex", text="hi vera", start_seconds=0.4),
        TurnAudioCue(agent_id="vera", text="all good", start_seconds=0.8),
    ]

    # Stub the TTS pipeline: every cue gets a tiny silent wav so the audio
    # stitcher has real input and the final mux includes an audio stream.
    audio_dir = tmp_path / "tts"
    audio_dir.mkdir()
    silent = audio_dir / "silent.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            "0.3",
            str(silent),
        ],
        check=True,
        capture_output=True,
    )

    tts = MagicMock()
    tts.audio_dir = audio_dir
    tts.generate = AsyncMock(return_value={"audio_url": f"/tts/{silent.name}"})

    config = load_video_render_config()

    result = await asyncio.wait_for(
        render_simulation_video(sim_id, cues=cues, tts=tts, config=config),
        timeout=120,
    )

    assert result.output_path.exists(), "expected MP4 to be produced"
    # ffprobe should see one video + one audio stream.
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=nw=1",
            str(result.output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    types = [line.split("=", 1)[1] for line in probe.stdout.splitlines() if "=" in line]
    assert "video" in types
    assert "audio" in types

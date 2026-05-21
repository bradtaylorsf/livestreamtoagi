"""Offline-safe tests for the E13-2 RTMP encoder/push script.

The live path requires platform stream keys, a visible capture source, ffmpeg
display permissions, and private/test streams on Twitch and YouTube. These
tests lock down the command contract without connecting to Minecraft, Docker,
Twitch, YouTube, or an RTMP server.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "livestream" / "stream-push.sh"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "livestream" / "verify_tts_audio.sh"
DOC = REPO_ROOT / "docs" / "livestream" / "encoder-rtmp.md"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
CLAUDE = REPO_ROOT / "CLAUDE.md"
PACKAGE_JSON = REPO_ROOT / "package.json"

TWITCH_URL = "rtmp://live.twitch.tv/app"
YOUTUBE_URL = "rtmp://a.rtmp.youtube.com/live2"


def _run(
    args: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    for key in [
        "TWITCH_STREAM_KEY",
        "YOUTUBE_STREAM_KEY",
        "TWITCH_RTMP_URL",
        "YOUTUBE_RTMP_URL",
        "RTMP_SMOKE_URL",
        "TTS_AUDIO_FIFO",
        "TTS_STREAM_FIFO",
        "TTS_AUDIO_VOLUME",
    ]:
        env.pop(key, None)
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "stream-push.sh must be chmod +x"
    assert VERIFY_SCRIPT.is_file(), f"missing {VERIFY_SCRIPT}"
    assert os.access(VERIFY_SCRIPT, os.X_OK), "verify_tts_audio.sh must be chmod +x"


def test_bash_syntax_is_valid() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    verify = subprocess.run(["bash", "-n", str(VERIFY_SCRIPT)], capture_output=True, text=True)
    assert verify.returncode == 0, verify.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean() -> None:
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_help_exits_zero_and_describes_usage() -> None:
    proc = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "stream-push.sh" in proc.stdout
    assert "--duration" in proc.stdout
    assert "--twitch-only" in proc.stdout
    assert "--youtube-only" in proc.stdout
    assert "--smoke" in proc.stdout
    assert "--dry-run" in proc.stdout
    assert "--with-tts" in proc.stdout
    assert "TTS_AUDIO_FIFO" in proc.stdout
    assert "TTS_AUDIO_VOLUME" in proc.stdout
    assert "set -euo pipefail" not in proc.stdout


def test_unknown_argument_is_rejected() -> None:
    proc = _run(["--nope"], REPO_ROOT)
    assert proc.returncode == 2
    assert "Unknown argument" in proc.stderr


def test_dry_run_exits_zero_without_side_effects(tmp_path: Path) -> None:
    proc = _run(
        ["--dry-run", "--duration", "15"],
        tmp_path,
        {
            "TWITCH_STREAM_KEY": "twitch-test-key",
            "YOUTUBE_STREAM_KEY": "youtube-test-key",
        },
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert list(tmp_path.iterdir()) == []
    assert "Dry run complete" in proc.stdout
    assert "ffmpeg" in proc.stdout
    assert "-f tee" in proc.stdout
    assert "<redacted>" in proc.stdout
    assert "twitch-test-key" not in proc.stdout
    assert "youtube-test-key" not in proc.stdout


def test_missing_twitch_key_fails_when_twitch_is_selected(tmp_path: Path) -> None:
    proc = _run(["--dry-run", "--twitch-only"], tmp_path)
    assert proc.returncode == 2
    assert "TWITCH_STREAM_KEY is required" in proc.stderr


def test_missing_youtube_key_fails_when_youtube_is_selected(tmp_path: Path) -> None:
    proc = _run(["--dry-run", "--youtube-only"], tmp_path)
    assert proc.returncode == 2
    assert "YOUTUBE_STREAM_KEY is required" in proc.stderr


def test_twitch_only_does_not_reference_youtube_ingest(tmp_path: Path) -> None:
    proc = _run(
        ["--dry-run", "--twitch-only"],
        tmp_path,
        {"TWITCH_STREAM_KEY": "twitch-test-key"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert TWITCH_URL in proc.stdout
    assert YOUTUBE_URL not in proc.stdout


def test_youtube_only_does_not_reference_twitch_ingest(tmp_path: Path) -> None:
    proc = _run(
        ["--dry-run", "--youtube-only"],
        tmp_path,
        {"YOUTUBE_STREAM_KEY": "youtube-test-key"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert YOUTUBE_URL in proc.stdout
    assert TWITCH_URL not in proc.stdout


def test_default_invocation_references_both_platforms(tmp_path: Path) -> None:
    proc = _run(
        ["--dry-run"],
        tmp_path,
        {
            "TWITCH_STREAM_KEY": "twitch-test-key",
            "YOUTUBE_STREAM_KEY": "youtube-test-key",
        },
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert TWITCH_URL in proc.stdout
    assert YOUTUBE_URL in proc.stdout
    assert "|[f=flv]" in proc.stdout


def test_smoke_dry_run_uses_lavfi_sources_not_display_capture(tmp_path: Path) -> None:
    proc = _run(["--smoke", "--dry-run"], tmp_path)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "testsrc2" in proc.stdout
    assert "sine=frequency=1000" in proc.stdout
    assert "avfoundation" not in proc.stdout
    assert "x11grab" not in proc.stdout
    assert "Capture screen" not in proc.stdout
    assert "[f=null]pipe:" in proc.stdout


def test_smoke_with_rtmp_url_targets_only_the_smoke_endpoint(tmp_path: Path) -> None:
    proc = _run(
        ["--smoke", "--dry-run"],
        tmp_path,
        {"RTMP_SMOKE_URL": "rtmp://127.0.0.1/live/test"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "rtmp://127.0.0.1/live/test" in proc.stdout
    assert TWITCH_URL not in proc.stdout
    assert YOUTUBE_URL not in proc.stdout


def test_with_tts_dry_run_renders_fifo_input_and_filter(tmp_path: Path) -> None:
    fifo = tmp_path / "tts.fifo"
    os.mkfifo(fifo)

    proc = _run(
        ["--dry-run", "--with-tts"],
        tmp_path,
        {
            "TWITCH_STREAM_KEY": "twitch-test-key",
            "YOUTUBE_STREAM_KEY": "youtube-test-key",
            "TTS_AUDIO_FIFO": str(fifo),
            "TTS_AUDIO_VOLUME": "0.25",
        },
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    command = proc.stdout.replace("\\", "")
    assert "-f s16le" in command
    assert f"-i {fifo}" in command
    assert "-filter_complex" in command
    assert "[2:a]volume=0.25,aresample=async=1[tts]" in command
    assert "[bed][tts]amix=inputs=2:duration=first" in command
    assert "-map [aout]" in command
    assert f"tts:      fifo={fifo} volume=0.25" in proc.stdout


def test_smoke_with_tts_dry_run_mixes_sine_and_tts(tmp_path: Path) -> None:
    fifo = tmp_path / "tts.fifo"
    os.mkfifo(fifo)

    proc = _run(
        ["--dry-run", "--smoke", "--with-tts", "--duration", "5"],
        tmp_path,
        {"TTS_AUDIO_FIFO": str(fifo)},
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    command = proc.stdout.replace("\\", "")
    assert "sine=frequency=1000" in command
    assert "amix=inputs=2:duration=first" in command
    assert f"-i {fifo}" in command


def test_with_tts_missing_fifo_exits_2(tmp_path: Path) -> None:
    missing_fifo = tmp_path / "missing.fifo"

    proc = _run(
        ["--dry-run", "--with-tts"],
        tmp_path,
        {
            "TWITCH_STREAM_KEY": "twitch-test-key",
            "YOUTUBE_STREAM_KEY": "youtube-test-key",
            "TTS_AUDIO_FIFO": str(missing_fifo),
        },
    )

    assert proc.returncode == 2
    assert "requires TTS_AUDIO_FIFO to exist as a FIFO" in proc.stderr


def test_env_docs_and_runbook_record_rtmp_configuration() -> None:
    env_text = ENV_EXAMPLE.read_text()
    claude_text = CLAUDE.read_text()
    doc_text = DOC.read_text()

    for var in [
        "TWITCH_STREAM_KEY",
        "YOUTUBE_STREAM_KEY",
        "TWITCH_RTMP_URL",
        "YOUTUBE_RTMP_URL",
        "RTMP_SMOKE_URL",
        "TTS_AUDIO_FIFO",
        "TTS_AUDIO_VOLUME",
    ]:
        assert var in env_text
        assert var in claude_text
        assert var in doc_text

    assert "Never commit real stream keys" in env_text
    assert "scripts/livestream/stream-push.sh --smoke --dry-run" in doc_text
    assert "no LLM runtime path" in doc_text
    assert "pnpm llm:local --list-only" in doc_text
    assert "exit" in doc_text and "3" in doc_text


def test_root_package_wires_livestream_rtmp_verify_command() -> None:
    data = json.loads(PACKAGE_JSON.read_text())
    assert (
        data["scripts"]["verify:livestream-rtmp"]
        == ".venv/bin/pytest tests/backend/test_livestream_stream_push.py -v"
    )
    tts_cmd = data["scripts"]["verify:livestream-tts"]
    assert "tests/backend/test_tts_stream_bridge.py" in tts_cmd
    assert "tests/backend/test_livestream_stream_push.py" in tts_cmd
    assert "scripts/livestream/verify_tts_audio.sh" in tts_cmd

"""Static contract tests for the livestream ffmpeg push script."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "livestream" / "stream-push.sh"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "livestream" / "verify_tts_audio.sh"
PACKAGE_JSON = REPO_ROOT / "package.json"


def _run(args: list[str], tmp_path: Path, extra_env: dict[str, str] | None = None):
    env = {**os.environ, "RTMP_STREAM_KEY": "secret-key"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_stream_push_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)
    assert VERIFY_SCRIPT.is_file()
    assert os.access(VERIFY_SCRIPT, os.X_OK)


def test_bash_syntax_is_valid() -> None:
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    verify = subprocess.run(["bash", "-n", str(VERIFY_SCRIPT)], capture_output=True, text=True)
    assert verify.returncode == 0, verify.stderr


def test_help_documents_tts_audio_options() -> None:
    proc = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)

    assert proc.returncode == 0
    assert "--with-tts" in proc.stdout
    assert "TTS_AUDIO_FIFO" in proc.stdout
    assert "TTS_AUDIO_VOLUME" in proc.stdout
    assert "--output-file" in proc.stdout


def test_with_tts_dry_run_renders_fifo_input_and_filter(
    tmp_path: Path,
) -> None:
    fifo = tmp_path / "tts.fifo"
    os.mkfifo(fifo)

    proc = _run(
        ["--dry-run", "--with-tts", "--output-file", str(tmp_path / "out.flv")],
        tmp_path,
        {"TTS_AUDIO_FIFO": str(fifo), "TTS_AUDIO_VOLUME": "0.25"},
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    command = proc.stdout.replace("\\", "")
    assert "-f s16le" in command
    assert f"-i {fifo}" in command
    assert "-filter_complex" in command
    assert "[1:a]volume=0.25,aresample=async=1[tts];[tts]anull[aout]" in command
    assert "-map [aout]" in command
    assert f"tts: fifo={fifo} volume=0.25" in proc.stderr


def test_smoke_with_tts_dry_run_mixes_sine_and_tts(tmp_path: Path) -> None:
    fifo = tmp_path / "tts.fifo"
    os.mkfifo(fifo)

    proc = _run(
        [
            "--dry-run",
            "--smoke",
            "--with-tts",
            "--duration",
            "5",
            "--output-file",
            str(tmp_path / "out.flv"),
        ],
        tmp_path,
        {"TTS_AUDIO_FIFO": str(fifo)},
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    command = proc.stdout.replace("\\", "")
    assert "sine=frequency=660" in command
    assert "amix=inputs=2:duration=first" in command
    assert f"-i {fifo}" in command


def test_with_tts_missing_fifo_exits_2(tmp_path: Path) -> None:
    missing_fifo = tmp_path / "missing.fifo"

    proc = _run(
        ["--dry-run", "--with-tts", "--output-file", str(tmp_path / "out.flv")],
        tmp_path,
        {"TTS_AUDIO_FIFO": str(missing_fifo)},
    )

    assert proc.returncode == 2
    assert "requires TTS_AUDIO_FIFO to exist as a FIFO" in proc.stderr


def test_redacted_target_log_hides_stream_key(tmp_path: Path) -> None:
    proc = _run(
        ["--dry-run", "--smoke"],
        tmp_path,
        {"RTMP_SMOKE_URL": "rtmp://example.test/live/secret-key"},
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "secret-key" not in proc.stderr
    assert "rtmp://example.test/live/****" in proc.stderr


def test_package_json_wires_livestream_tts_verifier() -> None:
    data = json.loads(PACKAGE_JSON.read_text())
    cmd = data["scripts"].get("verify:livestream-tts", "")
    assert "tests/backend/test_tts_stream_bridge.py" in cmd
    assert "tests/backend/test_livestream_stream_push.py" in cmd
    assert "scripts/livestream/verify_tts_audio.sh" in cmd

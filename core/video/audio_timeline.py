"""Build a single audio.wav by stitching per-turn TTS clips on a timeline."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.tts import TTSPipeline

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnAudioCue:
    """One transcript turn anchored at ``start_seconds`` from sim start."""

    agent_id: str
    text: str
    start_seconds: float


@dataclass(frozen=True)
class StitchResult:
    output_path: Path
    duration_seconds: float
    cues_rendered: int


async def _generate_clip(
    tts: TTSPipeline,
    cue: TurnAudioCue,
) -> Path | None:
    """Render a single cue to disk via the TTS pipeline."""
    try:
        result = await tts.generate(cue.agent_id, cue.text, cleanup_ttl=3600)
    except Exception:
        logger.warning(
            "TTS failed for agent=%s; skipping cue at t=%.2f",
            cue.agent_id,
            cue.start_seconds,
            exc_info=True,
        )
        return None
    if result is None:
        return None
    audio_url = result.get("audio_url", "")
    filename = audio_url.rsplit("/", 1)[-1]
    return tts.audio_dir / filename


def _build_concat_filter(
    clips: list[tuple[float, Path]],
    *,
    sample_rate: int = 44100,
) -> tuple[list[str], str]:
    """Build an ffmpeg ``-filter_complex`` graph that lays clips on a timeline.

    Returns ``(input_args, filter_graph)``. Each clip is delayed via
    ``adelay`` and then ``amix`` combines them into a single track.
    """
    inputs: list[str] = []
    filter_parts: list[str] = []
    mix_inputs: list[str] = []
    for idx, (start_s, path) in enumerate(clips):
        inputs.extend(["-i", str(path)])
        delay_ms = max(0, int(round(start_s * 1000)))
        filter_parts.append(
            f"[{idx}:a]aresample={sample_rate},"
            f"adelay={delay_ms}|{delay_ms}[a{idx}]"
        )
        mix_inputs.append(f"[a{idx}]")
    if not mix_inputs:
        return inputs, ""
    filter_parts.append(
        f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:"
        "duration=longest:dropout_transition=0[out]"
    )
    return inputs, ";".join(filter_parts)


async def stitch_audio_timeline(
    cues: list[TurnAudioCue],
    *,
    tts: TTSPipeline,
    output_path: Path,
    ffmpeg_bin: str = "ffmpeg",
) -> StitchResult:
    """Generate per-cue TTS clips and stitch them onto a shared timeline.

    Cues are rendered concurrently. Failures are silently skipped so a single
    flaky TTS call doesn't poison the whole render.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    clip_paths = await asyncio.gather(
        *(_generate_clip(tts, cue) for cue in cues),
        return_exceptions=False,
    )
    placed: list[tuple[float, Path]] = [
        (cue.start_seconds, path)
        for cue, path in zip(cues, clip_paths, strict=False)
        if path is not None and path.exists()
    ]

    if not placed:
        # No usable audio — emit one second of silence so the downstream
        # ffmpeg stitch still has a valid input.
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            "1",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
        return StitchResult(output_path=output_path, duration_seconds=1.0, cues_rendered=0)

    inputs, filter_graph = _build_concat_filter(placed)
    cmd = [
        ffmpeg_bin,
        "-y",
        *inputs,
        "-filter_complex",
        filter_graph,
        "-map",
        "[out]",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603

    duration = max(start for start, _ in placed) + 1.0
    return StitchResult(
        output_path=output_path,
        duration_seconds=duration,
        cues_rendered=len(placed),
    )

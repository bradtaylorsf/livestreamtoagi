# Livestream TTS Audio

## Architecture

Approved agent speech follows this path into the live stream:

1. Management-approved text is rendered by `core/tts.py`.
2. `TTSPipeline.speak()` emits `tts_play` with `/audio/<uuid>.mp3`.
3. `core/streaming/tts_stream_bridge.py` resolves the URL inside the TTS audio
   directory and decodes it with ffmpeg.
4. The bridge writes PCM `s16le` audio into `TTS_STREAM_FIFO`.
5. `scripts/livestream/stream-push.sh --with-tts` reads that FIFO as an ffmpeg
   input, applies `TTS_AUDIO_VOLUME`, and maps it into the FLV/RTMP audio track.

The bridge also writes short silence chunks while connected so the ffmpeg audio
input stays alive between utterances. If the stream-side ffmpeg process is not
connected yet, the bridge logs a warning and drops queued audio instead of
blocking the FastAPI process.

## Backend Setup

Start the FastAPI app with the bridge explicitly enabled:

```bash
TTS_STREAM_ENABLED=1 \
TTS_STREAM_FIFO=/tmp/livestream_tts.fifo \
.venv/bin/uvicorn core.main:app --port 8010
```

Environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TTS_STREAM_ENABLED` | `0` | Opts the backend into writing live TTS PCM. |
| `TTS_STREAM_FIFO` | `/tmp/livestream_tts.fifo` | FIFO created by the backend bridge. |
| `TTS_STREAM_SAMPLE_RATE` | `44100` | PCM sample rate written to the FIFO. |
| `TTS_STREAM_CHANNELS` | `2` | PCM channel count written to the FIFO. |
| `TTS_AUDIO_FIFO` | `TTS_STREAM_FIFO` or `/tmp/livestream_tts.fifo` | FIFO consumed by `stream-push.sh --with-tts`. |
| `TTS_AUDIO_VOLUME` | `1.0` | ffmpeg volume multiplier for the TTS input. |

## Encoder Usage

For a local smoke file:

```bash
TTS_AUDIO_FIFO=/tmp/livestream_tts.fifo \
scripts/livestream/stream-push.sh --smoke --with-tts --duration 5 --output-file /tmp/tts_smoke.flv
```

For a real RTMP target, set `VIDEO_INPUT`, `RTMP_URL`, and `RTMP_STREAM_KEY`
according to the capture source and run the same script with `--with-tts`.

## Verification

Run the offline smoke:

```bash
pnpm verify:livestream-tts
```

That command runs the focused backend tests and
`scripts/livestream/verify_tts_audio.sh`, which creates a fixture MP3, emits a
local `tts_play` event through `TTSStreamBridge`, records a short FLV with
`stream-push.sh --with-tts`, and checks the resulting audio track is present and
not silent.

## Local LM Studio Validation

This issue has no LLM runtime path: it routes already-approved TTS audio into
ffmpeg. Still record local validation posture by checking the local model server
and then running the nearest smoke path:

```bash
pnpm llm:local --list-only
pnpm verify:livestream-tts
```

If LM Studio is not running on the local Mac, record that result and keep the
TTS smoke output as the acceptance evidence for this non-LLM path.


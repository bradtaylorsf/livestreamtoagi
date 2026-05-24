#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/livestream/verify_tts_audio.sh

End-to-end local smoke for the livestream TTS path:
  TTS_PLAY event -> TTSStreamBridge -> PCM FIFO -> stream-push.sh -> FLV audio.

Environment:
  PYTHON              Python executable (default: .venv/bin/python if present).
  TTS_SMOKE_DURATION Smoke output duration in seconds (default: 5).
  TTS_SMOKE_OUTPUT   Output FLV path (default: /tmp/tts_smoke.flv).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -gt 0 ]]; then
  echo "verify_tts_audio.sh: unknown argument: $1" >&2
  exit 2
fi

command -v ffmpeg >/dev/null 2>&1 || {
  echo "verify_tts_audio.sh: ffmpeg is required" >&2
  exit 2
}
command -v ffprobe >/dev/null 2>&1 || {
  echo "verify_tts_audio.sh: ffprobe is required" >&2
  exit 2
}

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
  else
    PYTHON="python"
  fi
fi

DURATION="${TTS_SMOKE_DURATION:-5}"
OUTPUT="${TTS_SMOKE_OUTPUT:-/tmp/tts_smoke.flv}"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/livestream-tts.XXXXXX")"
FIFO="${WORKDIR}/tts.fifo"
AUDIO_DIR="${WORKDIR}/audio"
PUSH_LOG="${WORKDIR}/stream-push.log"
HELPER_PID=""

cleanup() {
  if [[ -n "$HELPER_PID" ]] && kill -0 "$HELPER_PID" >/dev/null 2>&1; then
    kill "$HELPER_PID" >/dev/null 2>&1 || true
    wait "$HELPER_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

mkdir -p "$AUDIO_DIR" "$(dirname "$OUTPUT")"
rm -f "$OUTPUT"
mkfifo "$FIFO"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "sine=frequency=880:sample_rate=44100:duration=2" \
  -q:a 4 "${AUDIO_DIR}/fixture.mp3"

TTS_SMOKE_AUDIO_DIR="$AUDIO_DIR" \
TTS_SMOKE_FIFO="$FIFO" \
TTS_SMOKE_BRIDGE_SECONDS="$((DURATION + 2))" \
"$PYTHON" - <<'PY' &
import asyncio
import os
from pathlib import Path

from core.event_bus import EventBus, EventType
from core.streaming.tts_stream_bridge import TTSStreamBridge, TTSStreamBridgeConfig


async def main() -> None:
    bus = EventBus()
    config = TTSStreamBridgeConfig(
        enabled=True,
        fifo_path=Path(os.environ["TTS_SMOKE_FIFO"]),
        sample_rate=44100,
        channels=2,
        silence_chunk_seconds=0.05,
        post_utterance_silence_seconds=0.15,
    )
    bridge = TTSStreamBridge(
        event_bus=bus,
        audio_dir=Path(os.environ["TTS_SMOKE_AUDIO_DIR"]),
        config=config,
    )
    await bridge.start()
    await asyncio.sleep(0.75)
    await bus.emit(
        EventType.TTS_PLAY.value,
        {
            "agent_id": "vera",
            "audio_url": "/audio/fixture.mp3",
            "duration": 2.0,
            "text": "TTS smoke fixture",
        },
    )
    await asyncio.sleep(float(os.environ["TTS_SMOKE_BRIDGE_SECONDS"]))
    await bridge.stop()


asyncio.run(main())
PY
HELPER_PID="$!"

TTS_AUDIO_FIFO="$FIFO" TTS_AUDIO_VOLUME="${TTS_AUDIO_VOLUME:-1.0}" \
  scripts/livestream/stream-push.sh \
    --smoke \
    --with-tts \
    --duration "$DURATION" \
    --output-file "$OUTPUT" \
  >"$PUSH_LOG" 2>&1 || {
    cat "$PUSH_LOG" >&2
    exit 1
  }

wait "$HELPER_PID"
HELPER_PID=""

if ! ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of csv=p=0 "$OUTPUT" | grep -qx "audio"; then
  echo "verify_tts_audio.sh: no audio stream found in $OUTPUT" >&2
  exit 1
fi

volume_output="$(ffmpeg -hide_banner -nostats -i "$OUTPUT" -af volumedetect -f null - 2>&1)"
mean_db="$(awk '/mean_volume:/ {print $5; exit}' <<<"$volume_output")"
if [[ -z "$mean_db" ]]; then
  echo "$volume_output" >&2
  echo "verify_tts_audio.sh: unable to read mean_volume" >&2
  exit 1
fi

"$PYTHON" - "$mean_db" <<'PY'
import math
import sys

db = float(sys.argv[1])
if not math.isfinite(db) or db <= -35.0:
    raise SystemExit(f"mean_volume too quiet for TTS smoke: {db} dB")
PY

echo "TTS livestream audio smoke passed: ${OUTPUT} (mean_volume ${mean_db} dB)"

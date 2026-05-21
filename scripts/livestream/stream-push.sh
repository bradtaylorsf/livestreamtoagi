#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/livestream/stream-push.sh [options]

Encode the livestream video source and push it to an RTMP target. Smoke mode
uses ffmpeg-generated video/audio so the encoder path can be tested locally.

Options:
  --dry-run              Print the resolved ffmpeg command and exit.
  --smoke                Use local test video/audio sources.
  --duration SECONDS     Limit the output duration, useful with --smoke.
  --output-file FILE     Write a local FLV file instead of pushing RTMP.
  --with-tts             Read live TTS PCM from TTS_AUDIO_FIFO.
  -h, --help             Show this help.

Environment:
  RTMP_URL               RTMP base URL for a real stream target.
  RTMP_STREAM_KEY        Stream key appended to RTMP_URL.
  RTMP_SMOKE_URL         RTMP URL used by --smoke when --output-file is absent.
  VIDEO_INPUT_FORMAT     ffmpeg input format for non-smoke video.
  VIDEO_INPUT            ffmpeg input spec for non-smoke video.
  VIDEO_WIDTH            Output width for smoke video (default: 1280).
  VIDEO_HEIGHT           Output height for smoke video (default: 720).
  VIDEO_FPS              Output frame rate (default: 30).
  AUDIO_SAMPLE_RATE      Audio sample rate (default: 44100).
  TTS_AUDIO_FIFO         PCM FIFO path for --with-tts.
                         Defaults to TTS_STREAM_FIFO or /tmp/livestream_tts.fifo.
  TTS_AUDIO_VOLUME       Volume multiplier for TTS audio (default: 1.0).
EOF
}

die() {
  echo "stream-push.sh: $*" >&2
  exit 2
}

info() {
  echo "[stream-push] $*" >&2
}

shell_quote_command() {
  printf '%q ' "$@"
  printf '\n'
}

redact_target() {
  local target="$1"
  local key="${RTMP_STREAM_KEY:-}"
  if [[ -n "$key" ]]; then
    target="${target//$key/****}"
  fi
  printf '%s' "$target"
}

DRY_RUN=0
SMOKE=0
WITH_TTS=0
DURATION="${STREAM_DURATION:-}"
OUTPUT_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --smoke)
      SMOKE=1
      shift
      ;;
    --with-tts)
      WITH_TTS=1
      shift
      ;;
    --duration)
      [[ $# -ge 2 ]] || die "--duration requires a value"
      DURATION="$2"
      shift 2
      ;;
    --output-file)
      [[ $# -ge 2 ]] || die "--output-file requires a value"
      OUTPUT_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

VIDEO_WIDTH="${VIDEO_WIDTH:-1280}"
VIDEO_HEIGHT="${VIDEO_HEIGHT:-720}"
VIDEO_FPS="${VIDEO_FPS:-30}"
AUDIO_SAMPLE_RATE="${AUDIO_SAMPLE_RATE:-44100}"
AUDIO_CHANNELS=2
TTS_AUDIO_FIFO="${TTS_AUDIO_FIFO:-${TTS_STREAM_FIFO:-/tmp/livestream_tts.fifo}}"
TTS_AUDIO_VOLUME="${TTS_AUDIO_VOLUME:-1.0}"

if [[ "$WITH_TTS" -eq 1 && ! -p "$TTS_AUDIO_FIFO" ]]; then
  die "--with-tts requires TTS_AUDIO_FIFO to exist as a FIFO: $TTS_AUDIO_FIFO"
fi

if [[ -n "$OUTPUT_FILE" ]]; then
  mkdir -p "$(dirname "$OUTPUT_FILE")"
  TARGET="$OUTPUT_FILE"
  OUTPUT_ARGS=(-f flv "$OUTPUT_FILE")
elif [[ "$SMOKE" -eq 1 ]]; then
  TARGET="${RTMP_SMOKE_URL:-}"
  [[ -n "$TARGET" ]] || die "RTMP_SMOKE_URL or --output-file is required for --smoke"
  OUTPUT_ARGS=(-f flv "$TARGET")
else
  RTMP_URL="${RTMP_URL:-}"
  RTMP_STREAM_KEY="${RTMP_STREAM_KEY:-}"
  [[ -n "$RTMP_URL" ]] || die "RTMP_URL is required unless --smoke or --output-file is used"
  TARGET="${RTMP_URL%/}"
  if [[ -n "$RTMP_STREAM_KEY" ]]; then
    TARGET="${TARGET}/${RTMP_STREAM_KEY}"
  fi
  OUTPUT_ARGS=(-f flv "$TARGET")
fi

if [[ "$SMOKE" -eq 1 ]]; then
  VIDEO_INPUT_FORMAT="lavfi"
  VIDEO_INPUT="testsrc2=size=${VIDEO_WIDTH}x${VIDEO_HEIGHT}:rate=${VIDEO_FPS}"
else
  VIDEO_INPUT_FORMAT="${VIDEO_INPUT_FORMAT:-avfoundation}"
  VIDEO_INPUT="${VIDEO_INPUT:-}"
  if [[ -z "$VIDEO_INPUT" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      VIDEO_INPUT="<capture-source-required>"
    else
      die "VIDEO_INPUT is required unless --smoke is used"
    fi
  fi
fi

cmd=(ffmpeg -hide_banner -y)
cmd+=(-f "$VIDEO_INPUT_FORMAT" -i "$VIDEO_INPUT")

FILTER_COMPLEX=""
if [[ "$WITH_TTS" -eq 1 ]]; then
  if [[ "$SMOKE" -eq 1 ]]; then
    tone_duration="${DURATION:-10}"
    cmd+=(-f lavfi -i "sine=frequency=660:sample_rate=${AUDIO_SAMPLE_RATE}:duration=${tone_duration}")
    cmd+=(
      -thread_queue_size 1024
      -f s16le
      -ar "$AUDIO_SAMPLE_RATE"
      -ac "$AUDIO_CHANNELS"
      -i "$TTS_AUDIO_FIFO"
    )
    FILTER_COMPLEX="[1:a]volume=0.001[sine];[2:a]volume=${TTS_AUDIO_VOLUME},aresample=async=1[tts];[sine][tts]amix=inputs=2:duration=first:dropout_transition=0[aout]"
  else
    cmd+=(
      -thread_queue_size 1024
      -f s16le
      -ar "$AUDIO_SAMPLE_RATE"
      -ac "$AUDIO_CHANNELS"
      -i "$TTS_AUDIO_FIFO"
    )
    FILTER_COMPLEX="[1:a]volume=${TTS_AUDIO_VOLUME},aresample=async=1[tts];[tts]anull[aout]"
  fi
else
  if [[ "$SMOKE" -eq 1 ]]; then
    tone_duration="${DURATION:-10}"
    cmd+=(-f lavfi -i "sine=frequency=660:sample_rate=${AUDIO_SAMPLE_RATE}:duration=${tone_duration}")
  else
    cmd+=(-f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=${AUDIO_SAMPLE_RATE}")
  fi
fi

if [[ -n "$DURATION" ]]; then
  cmd+=(-t "$DURATION")
fi

if [[ -n "$FILTER_COMPLEX" ]]; then
  cmd+=(-filter_complex "$FILTER_COMPLEX")
  cmd+=(-map 0:v:0 -map "[aout]")
else
  cmd+=(-map 0:v:0 -map 1:a:0)
fi

cmd+=(
  -c:v "${VIDEO_CODEC:-libx264}"
  -preset "${VIDEO_PRESET:-veryfast}"
  -tune zerolatency
  -pix_fmt yuv420p
  -r "$VIDEO_FPS"
  -g "$((VIDEO_FPS * 2))"
  -b:v "${VIDEO_BITRATE:-4500k}"
  -maxrate "${VIDEO_MAXRATE:-4500k}"
  -bufsize "${VIDEO_BUFSIZE:-9000k}"
  -c:a aac
  -b:a "${AUDIO_BITRATE:-160k}"
  -ar "$AUDIO_SAMPLE_RATE"
  -ac "$AUDIO_CHANNELS"
)
cmd+=("${OUTPUT_ARGS[@]}")

info "target: $(redact_target "$TARGET")"
if [[ "$WITH_TTS" -eq 1 ]]; then
  info "tts: fifo=${TTS_AUDIO_FIFO} volume=${TTS_AUDIO_VOLUME}"
else
  info "tts: disabled"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  shell_quote_command "${cmd[@]}"
  exit 0
fi

exec "${cmd[@]}"

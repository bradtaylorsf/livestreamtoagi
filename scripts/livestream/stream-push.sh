#!/usr/bin/env bash
# Encode the E13 livestream capture source and push it to Twitch and/or YouTube.
#
# This is the E13-2 encoder/RTMP layer. It expects the capture source from
# E13-1 to already be visible on the local display. For local testing, use
# --smoke to replace display capture with ffmpeg's testsrc2 video and sine
# audio sources.
#
# Usage:
#   scripts/livestream/stream-push.sh
#   scripts/livestream/stream-push.sh --duration 60
#   scripts/livestream/stream-push.sh --twitch-only --duration 60
#   scripts/livestream/stream-push.sh --youtube-only --duration 60
#   scripts/livestream/stream-push.sh --dry-run
#   scripts/livestream/stream-push.sh --smoke --dry-run
#   scripts/livestream/stream-push.sh --with-tts --dry-run
#   RTMP_SMOKE_URL=rtmp://127.0.0.1/live/test scripts/livestream/stream-push.sh --smoke
#
# Required environment for real platform pushes:
#   TWITCH_STREAM_KEY      Twitch stream key when Twitch is selected.
#   YOUTUBE_STREAM_KEY     YouTube stream key when YouTube is selected.
#
# Optional environment:
#   TWITCH_RTMP_URL        Twitch ingest URL (default: rtmp://live.twitch.tv/app)
#   YOUTUBE_RTMP_URL       YouTube ingest URL (default: rtmp://a.rtmp.youtube.com/live2)
#   RTMP_SMOKE_URL         Optional local/test RTMP URL for --smoke pushes.
#   CAPTURE_WIDTH          Output width (default: 1280)
#   CAPTURE_HEIGHT         Output height (default: 720)
#   CAPTURE_FPS            Output frame rate (default: 30)
#   STREAM_VIDEO_BITRATE   libx264 target bitrate (default: 4500k)
#   STREAM_AUDIO_BITRATE   AAC target bitrate (default: 160k)
#   STREAM_AUDIO_SAMPLE_RATE Audio sample rate in Hz (default: 44100)
#   TTS_AUDIO_FIFO         PCM FIFO path for --with-tts (default: $TTS_STREAM_FIFO or /tmp/livestream_tts.fifo)
#   TTS_AUDIO_VOLUME       Volume multiplier for TTS audio (default: 1.0)
#   AVFOUNDATION_INPUT     macOS display input (default: Capture screen 0:none)
#   STREAM_X11_DISPLAY     Linux X11 display input (default: $DISPLAY)
#   MC_HOST                E2 Minecraft server host for capture preflight (default: 127.0.0.1)
#   MC_PORT                E2 Minecraft server port for capture preflight (default: 25565)
#   SKIP_CAPTURE_PREFLIGHT Set to 1 to skip the live Minecraft reachability check.
set -euo pipefail

DURATION="60"
MODE="run"
SMOKE="0"
WITH_TTS="0"
TARGET_TWITCH="1"
TARGET_YOUTUBE="1"
TARGET_OPTION=""
FFMPEG_PID=""

TWITCH_RTMP_URL="${TWITCH_RTMP_URL:-rtmp://live.twitch.tv/app}"
YOUTUBE_RTMP_URL="${YOUTUBE_RTMP_URL:-rtmp://a.rtmp.youtube.com/live2}"
TWITCH_STREAM_KEY="${TWITCH_STREAM_KEY:-}"
YOUTUBE_STREAM_KEY="${YOUTUBE_STREAM_KEY:-}"
RTMP_SMOKE_URL="${RTMP_SMOKE_URL:-}"

MC_HOST="${MC_HOST:-127.0.0.1}"
MC_PORT="${MC_PORT:-25565}"
SKIP_CAPTURE_PREFLIGHT="${SKIP_CAPTURE_PREFLIGHT:-0}"

FPS="${CAPTURE_FPS:-30}"
VIDEO_WIDTH="${CAPTURE_WIDTH:-1280}"
VIDEO_HEIGHT="${CAPTURE_HEIGHT:-720}"
VIDEO_SIZE="${VIDEO_WIDTH}x${VIDEO_HEIGHT}"
VIDEO_BITRATE="${STREAM_VIDEO_BITRATE:-4500k}"
VIDEO_MAXRATE="${STREAM_VIDEO_MAXRATE:-${VIDEO_BITRATE}}"
VIDEO_BUFSIZE="${STREAM_VIDEO_BUFSIZE:-9000k}"
AUDIO_BITRATE="${STREAM_AUDIO_BITRATE:-160k}"
AUDIO_SAMPLE_RATE="${STREAM_AUDIO_SAMPLE_RATE:-44100}"
TTS_AUDIO_FIFO="${TTS_AUDIO_FIFO:-${TTS_STREAM_FIFO:-/tmp/livestream_tts.fifo}}"
TTS_AUDIO_VOLUME="${TTS_AUDIO_VOLUME:-1.0}"
X264_PRESET="${STREAM_X264_PRESET:-veryfast}"
AVFOUNDATION_INPUT="${AVFOUNDATION_INPUT:-Capture screen 0:none}"
STREAM_X11_DISPLAY="${STREAM_X11_DISPLAY:-${DISPLAY:-}}"
GOP=""
TEE_OUTPUTS=""
TEE_OUTPUTS_REDACTED=""

ok() { echo "OK: $*"; }
info() { echo "  $*"; }
fail() { echo "ERR: $*" >&2; }

usage_error() {
    fail "$1"
    info "Try: scripts/livestream/stream-push.sh --help"
    exit 2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --duration)
            [ "${2:-}" ] || usage_error "Missing value for --duration"
            DURATION="$2"
            shift 2
            ;;
        --duration=*)
            DURATION="${1#*=}"
            shift
            ;;
        --twitch-only)
            [ -z "$TARGET_OPTION" ] || usage_error "Choose only one target selector"
            TARGET_OPTION="twitch"
            TARGET_TWITCH="1"
            TARGET_YOUTUBE="0"
            shift
            ;;
        --youtube-only)
            [ -z "$TARGET_OPTION" ] || usage_error "Choose only one target selector"
            TARGET_OPTION="youtube"
            TARGET_TWITCH="0"
            TARGET_YOUTUBE="1"
            shift
            ;;
        --smoke)
            SMOKE="1"
            shift
            ;;
        --with-tts)
            WITH_TTS="1"
            shift
            ;;
        --dry-run)
            MODE="dry-run"
            shift
            ;;
        --help|-h)
            awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next}{exit}' "$0"
            exit 0
            ;;
        *)
            fail "Unknown argument: $1 (try --help)"
            exit 2
            ;;
    esac
done

[[ "$DURATION" =~ ^[0-9]+$ ]] || usage_error "--duration must be an integer number of seconds"
if [ "$DURATION" -lt 1 ]; then
    usage_error "--duration must be at least 1 second"
fi
[[ "$FPS" =~ ^[0-9]+$ ]] || usage_error "CAPTURE_FPS must be an integer"
[[ "$VIDEO_WIDTH" =~ ^[0-9]+$ ]] || usage_error "CAPTURE_WIDTH must be an integer"
[[ "$VIDEO_HEIGHT" =~ ^[0-9]+$ ]] || usage_error "CAPTURE_HEIGHT must be an integer"
[[ "$AUDIO_SAMPLE_RATE" =~ ^[0-9]+$ ]] || usage_error "STREAM_AUDIO_SAMPLE_RATE must be an integer"
if [ "$FPS" -lt 1 ] || [ "$VIDEO_WIDTH" -lt 1 ] || [ "$VIDEO_HEIGHT" -lt 1 ]; then
    usage_error "CAPTURE_FPS, CAPTURE_WIDTH, and CAPTURE_HEIGHT must be positive"
fi
if [ "$WITH_TTS" = "1" ] && [ ! -p "$TTS_AUDIO_FIFO" ]; then
    usage_error "--with-tts requires TTS_AUDIO_FIFO to exist as a FIFO: ${TTS_AUDIO_FIFO}"
fi
GOP="$((FPS * 2))"

cleanup() {
    if [ -n "${FFMPEG_PID:-}" ] && kill -0 "$FFMPEG_PID" 2> /dev/null; then
        kill "$FFMPEG_PID" 2> /dev/null || true
        wait "$FFMPEG_PID" 2> /dev/null || true
    fi
}
trap cleanup EXIT INT TERM

check_command() {
    local name="$1"
    local hint="$2"
    if ! command -v "$name" > /dev/null 2>&1; then
        fail "$name not found. $hint"
        return 1
    fi
}

check_minecraft_server() {
    if [ "$SKIP_CAPTURE_PREFLIGHT" = "1" ]; then
        info "Skipping Minecraft reachability preflight because SKIP_CAPTURE_PREFLIGHT=1."
        return 0
    fi

    if command -v nc > /dev/null 2>&1; then
        nc -z -w 2 "$MC_HOST" "$MC_PORT" > /dev/null 2>&1 && return 0
    else
        (exec 3<>"/dev/tcp/${MC_HOST}/${MC_PORT}") > /dev/null 2>&1 && return 0
    fi

    fail "Minecraft server is not reachable at ${MC_HOST}:${MC_PORT}."
    info "  Start the E13-1 capture source first, normally after:"
    info "    scripts/minecraft/start-server.sh"
    info "  If you are intentionally streaming an already-open non-Minecraft source,"
    info "  set SKIP_CAPTURE_PREFLIGHT=1."
    return 1
}

display_backend() {
    case "$(uname -s)" in
        Darwin)
            printf '%s\n' "avfoundation"
            ;;
        Linux)
            if [ -n "$STREAM_X11_DISPLAY" ]; then
                printf '%s\n' "x11grab"
            else
                printf '%s\n' "none"
            fi
            ;;
        *)
            printf '%s\n' "none"
            ;;
    esac
}

join_by_pipe() {
    local joined=""
    local item
    for item in "$@"; do
        if [ -z "$joined" ]; then
            joined="$item"
        else
            joined="${joined}|${item}"
        fi
    done
    printf '%s\n' "$joined"
}

build_outputs() {
    local outputs=()
    local redacted=()

    if [ "$SMOKE" = "1" ]; then
        if [ -n "$RTMP_SMOKE_URL" ]; then
            outputs=("[f=flv]${RTMP_SMOKE_URL}")
            redacted=("[f=flv]${RTMP_SMOKE_URL}")
        else
            outputs=("[f=null]pipe:")
            redacted=("[f=null]pipe:")
        fi
        TEE_OUTPUTS="$(join_by_pipe "${outputs[@]}")"
        TEE_OUTPUTS_REDACTED="$(join_by_pipe "${redacted[@]}")"
        return 0
    fi

    if [ "$TARGET_TWITCH" = "1" ]; then
        if [ -z "$TWITCH_STREAM_KEY" ]; then
            fail "TWITCH_STREAM_KEY is required when Twitch is selected."
            info "  Export TWITCH_STREAM_KEY or use --youtube-only."
            return 1
        fi
        outputs+=("[f=flv]${TWITCH_RTMP_URL%/}/${TWITCH_STREAM_KEY}")
        redacted+=("[f=flv]${TWITCH_RTMP_URL%/}/<redacted>")
    fi

    if [ "$TARGET_YOUTUBE" = "1" ]; then
        if [ -z "$YOUTUBE_STREAM_KEY" ]; then
            fail "YOUTUBE_STREAM_KEY is required when YouTube is selected."
            info "  Export YOUTUBE_STREAM_KEY or use --twitch-only."
            return 1
        fi
        outputs+=("[f=flv]${YOUTUBE_RTMP_URL%/}/${YOUTUBE_STREAM_KEY}")
        redacted+=("[f=flv]${YOUTUBE_RTMP_URL%/}/<redacted>")
    fi

    if [ "${#outputs[@]}" -eq 0 ]; then
        fail "No RTMP targets selected."
        return 1
    fi

    TEE_OUTPUTS="$(join_by_pipe "${outputs[@]}")"
    TEE_OUTPUTS_REDACTED="$(join_by_pipe "${redacted[@]}")"
}

build_ffmpeg_cmd() {
    local tee_outputs="$1"
    local backend="$2"
    local audio_map_args=()
    local filter_complex=""
    FFMPEG_CMD=(ffmpeg -hide_banner -loglevel info -y)

    if [ "$SMOKE" = "1" ]; then
        FFMPEG_CMD+=(
            -re -f lavfi -i "testsrc2=size=${VIDEO_SIZE}:rate=${FPS}"
            -f lavfi -i "sine=frequency=1000:sample_rate=${AUDIO_SAMPLE_RATE}"
        )
    else
        case "$backend" in
            avfoundation)
                FFMPEG_CMD+=(
                    -f avfoundation -framerate "$FPS" -i "$AVFOUNDATION_INPUT"
                    -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=${AUDIO_SAMPLE_RATE}"
                )
                ;;
            x11grab)
                FFMPEG_CMD+=(
                    -f x11grab -video_size "$VIDEO_SIZE" -framerate "$FPS" -i "$STREAM_X11_DISPLAY"
                    -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=${AUDIO_SAMPLE_RATE}"
                )
                ;;
            *)
                fail "No display capture backend is available on this host."
                info "  macOS uses ffmpeg avfoundation; Linux requires X11 DISPLAY or STREAM_X11_DISPLAY."
                return 1
                ;;
        esac
    fi

    if [ "$WITH_TTS" = "1" ]; then
        FFMPEG_CMD+=(
            -thread_queue_size 1024
            -f s16le
            -ar "$AUDIO_SAMPLE_RATE"
            -ac 2
            -i "$TTS_AUDIO_FIFO"
        )
        filter_complex="[1:a]volume=0.001[bed];[2:a]volume=${TTS_AUDIO_VOLUME},aresample=async=1[tts];[bed][tts]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        audio_map_args=(-filter_complex "$filter_complex" -map 0:v:0 -map "[aout]")
    else
        audio_map_args=(-map 0:v:0 -map 1:a:0)
    fi

    FFMPEG_CMD+=(
        "${audio_map_args[@]}"
        -vf "scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT},fps=${FPS}"
        -c:v libx264
        -preset "$X264_PRESET"
        -tune zerolatency
        -r "$FPS"
        -g "$GOP"
        -keyint_min "$GOP"
        -sc_threshold 0
        -b:v "$VIDEO_BITRATE"
        -maxrate "$VIDEO_MAXRATE"
        -bufsize "$VIDEO_BUFSIZE"
        -pix_fmt yuv420p
        -c:a aac
        -b:a "$AUDIO_BITRATE"
        -ar "$AUDIO_SAMPLE_RATE"
        -ac 2
        -t "$DURATION"
        -f tee "$tee_outputs"
    )
}

print_command() {
    printf '  '
    printf '%q ' "${FFMPEG_CMD[@]}"
    printf '\n'
}

build_outputs || exit 2
BACKEND="$(display_backend)"

ok "E13-2 encoder + RTMP push"
info "duration: ${DURATION}s"
info "video:    ${VIDEO_SIZE}@${FPS}fps ${VIDEO_BITRATE} libx264/${X264_PRESET}, GOP=${GOP}"
info "audio:    aac ${AUDIO_BITRATE} ${AUDIO_SAMPLE_RATE}Hz"
if [ "$WITH_TTS" = "1" ]; then
    info "tts:      fifo=${TTS_AUDIO_FIFO} volume=${TTS_AUDIO_VOLUME}"
else
    info "tts:      disabled"
fi
if [ "$SMOKE" = "1" ]; then
    info "source:   ffmpeg lavfi testsrc2 + sine"
    if [ -z "$RTMP_SMOKE_URL" ]; then
        info "target:   smoke validation only (RTMP_SMOKE_URL unset; no network push)"
    else
        info "target:   ${RTMP_SMOKE_URL}"
    fi
    info "tee:      ${TEE_OUTPUTS_REDACTED}"
else
    info "source:   ${BACKEND} display capture"
    info "server:   ${MC_HOST}:${MC_PORT} preflight"
    info "targets:  ${TEE_OUTPUTS_REDACTED}"
fi

build_ffmpeg_cmd "$TEE_OUTPUTS_REDACTED" "$BACKEND" || exit 2
echo
info "ffmpeg command (stream keys redacted):"
print_command

if [ "$MODE" = "dry-run" ]; then
    echo
    ok "Dry run complete - no ffmpeg process, platform connection, Minecraft connection, or browser launch."
    exit 0
fi

if [ "$SMOKE" = "1" ] && [ -z "$RTMP_SMOKE_URL" ]; then
    echo
    ok "Smoke command validated; RTMP_SMOKE_URL is unset so no ffmpeg process was launched."
    exit 0
fi

check_command "ffmpeg" "Install ffmpeg (macOS: brew install ffmpeg)." || exit 2
check_command "ffprobe" "Install ffmpeg; ffprobe ships with it." || exit 2
if [ "$SMOKE" != "1" ]; then
    check_minecraft_server || exit 2
fi

build_ffmpeg_cmd "$TEE_OUTPUTS" "$BACKEND" || exit 2
echo
info "Starting ffmpeg push. Stop with Ctrl-C."
"${FFMPEG_CMD[@]}" &
FFMPEG_PID=$!
if ! wait "$FFMPEG_PID"; then
    FFMPEG_PID=""
    fail "ffmpeg capture/encode/RTMP push failed."
    exit 3
fi
FFMPEG_PID=""
ok "ffmpeg completed successfully."

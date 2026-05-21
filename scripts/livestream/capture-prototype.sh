#!/usr/bin/env bash
# Record a short E13-1 Minecraft capture prototype clip.
#
# This is a throwaway spike for issue #609, not the production streaming path.
# It connects a non-agent camera bot to the local E2 Paper server, exposes the
# bot view through Prismarine Viewer, opens that viewer in Chromium, and records
# a short MP4 with ffmpeg. Streaming/RTMP, overlays, audio, resilience, and kill
# switch wiring are intentionally left to later E13 issues.
#
# Pinned defaults come from the accepted Minecraft pivot decisions:
#   - Minecraft/Paper: 1.21.6 on 127.0.0.1:25565 (E1-R1/E2)
#   - Camera identity: CameraSpike, separate from the 9 agents (E1-R6)
#   - Viewer: Prismarine Viewer diagnostic fallback, not production OBS
#   - Model usage: none; this camera is not an LLM agent
#
# Usage:
#   scripts/livestream/capture-prototype.sh
#   scripts/livestream/capture-prototype.sh --duration 15
#   scripts/livestream/capture-prototype.sh --out videos/livestream/demo.mp4
#   scripts/livestream/capture-prototype.sh --viewer-port 3007
#   scripts/livestream/capture-prototype.sh --dry-run
#   scripts/livestream/capture-prototype.sh --help
#
# Configuration (environment variables, all optional):
#   MC_HOST               Minecraft server host        (default: 127.0.0.1)
#   MC_PORT               Minecraft server port        (default: 25565)
#   MC_VERSION            Minecraft protocol version   (default: 1.21.6)
#   CAMERA_USERNAME       Camera bot username          (default: CameraSpike)
#   CAPTURE_FPS           Output frame rate            (default: 30)
#   CAPTURE_WIDTH         Output width                 (default: 1280)
#   CAPTURE_HEIGHT        Output height                (default: 720)
#   AVFOUNDATION_INPUT    macOS ffmpeg screen input    (default: Capture screen 0:none)
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

REQUIRED_NODE_MAJOR="20"
MC_HOST="${MC_HOST:-127.0.0.1}"
MC_PORT="${MC_PORT:-25565}"
MC_VERSION="${MC_VERSION:-1.21.6}"
CAMERA_USERNAME="${CAMERA_USERNAME:-CameraSpike}"
VIEWER_PORT="3007"
DURATION="30"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$REPO_ROOT/videos/livestream/capture-${TIMESTAMP}.mp4"
FPS="${CAPTURE_FPS:-30}"
VIDEO_WIDTH="${CAPTURE_WIDTH:-1280}"
VIDEO_HEIGHT="${CAPTURE_HEIGHT:-720}"
VIDEO_SIZE="${VIDEO_WIDTH}x${VIDEO_HEIGHT}"
AVFOUNDATION_INPUT="${AVFOUNDATION_INPUT:-Capture screen 0:none}"
MODE="run"

BOT_PID=""
BROWSER_PID=""
BOT_LOG=""
BROWSER_LOG=""
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"

ok()   { echo "OK: $*"; }
info() { echo "  $*"; }
fail() { echo "ERR: $*" >&2; }

usage_error() {
    fail "$1"
    info "Try: scripts/livestream/capture-prototype.sh --help"
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
        --out)
            [ "${2:-}" ] || usage_error "Missing value for --out"
            OUT="$2"
            shift 2
            ;;
        --out=*)
            OUT="${1#*=}"
            shift
            ;;
        --viewer-port)
            [ "${2:-}" ] || usage_error "Missing value for --viewer-port"
            VIEWER_PORT="$2"
            shift 2
            ;;
        --viewer-port=*)
            VIEWER_PORT="${1#*=}"
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
[[ "$VIEWER_PORT" =~ ^[0-9]+$ ]] || usage_error "--viewer-port must be an integer TCP port"
if [ "$VIEWER_PORT" -lt 1 ] || [ "$VIEWER_PORT" -gt 65535 ]; then
    usage_error "--viewer-port must be between 1 and 65535"
fi

VIEWER_URL="http://127.0.0.1:${VIEWER_PORT}"

# shellcheck disable=SC2329  # invoked indirectly by the EXIT trap below.
cleanup() {
    if [ -n "${BROWSER_PID:-}" ] && kill -0 "$BROWSER_PID" 2> /dev/null; then
        kill "$BROWSER_PID" 2> /dev/null || true
        wait "$BROWSER_PID" 2> /dev/null || true
    fi
    if [ -n "${BOT_PID:-}" ] && kill -0 "$BOT_PID" 2> /dev/null; then
        kill "$BOT_PID" 2> /dev/null || true
        wait "$BOT_PID" 2> /dev/null || true
    fi
}
trap cleanup EXIT

node_major() {
    command -v node > /dev/null 2>&1 || return 1
    local out major
    out="$(node -v 2>&1)" || return 1
    major="$(printf '%s\n' "$out" | sed -nE 's/^v?([0-9]+).*/\1/p')"
    [ -n "$major" ] || return 1
    printf '%s\n' "$major"
}

check_node() {
    local node_m
    node_m="$(node_major || true)"
    if [ -z "${node_m:-}" ]; then
        fail "Node.js not found on PATH. Install Node ${REQUIRED_NODE_MAJOR}+."
        info "  nvm install ${REQUIRED_NODE_MAJOR} && nvm use ${REQUIRED_NODE_MAJOR}"
        return 1
    fi
    if [ "$node_m" -lt "$REQUIRED_NODE_MAJOR" ]; then
        fail "Node ${node_m} found, but this prototype needs Node ${REQUIRED_NODE_MAJOR}+."
        info "  Install Node ${REQUIRED_NODE_MAJOR}+ and retry."
        return 1
    fi
    if ! command -v npm > /dev/null 2>&1; then
        fail "npm not found on PATH (it ships with Node)."
        return 1
    fi
    ok "Node ${node_m} + npm $(npm -v) detected (need Node ${REQUIRED_NODE_MAJOR}+)"
}

check_command() {
    local name="$1"
    local hint="$2"
    if ! command -v "$name" > /dev/null 2>&1; then
        fail "$name not found. $hint"
        return 1
    fi
}

check_minecraft_server() {
    if command -v nc > /dev/null 2>&1; then
        nc -z -w 2 "$MC_HOST" "$MC_PORT" > /dev/null 2>&1 && return 0
    else
        (exec 3<>"/dev/tcp/${MC_HOST}/${MC_PORT}") > /dev/null 2>&1 && return 0
    fi

    fail "Minecraft server is not reachable at ${MC_HOST}:${MC_PORT}."
    info "  Start the local E2 Paper server first:"
    info "    scripts/minecraft/start-server.sh"
    info "  If the whitelist is enabled, add the camera in the server console:"
    info "    whitelist add ${CAMERA_USERNAME}"
    return 1
}

ensure_node_deps() {
    if [ -d "$SCRIPT_DIR/node_modules/mineflayer" ] \
        && [ -d "$SCRIPT_DIR/node_modules/prismarine-viewer" ] \
        && [ -d "$SCRIPT_DIR/node_modules/canvas" ]; then
        ok "Prototype Node dependencies already installed"
        return 0
    fi

    info "Installing prototype Node dependencies under scripts/livestream"
    npm install --prefix "$SCRIPT_DIR" --no-package-lock
}

display_backend() {
    case "$(uname -s)" in
        Darwin)
            printf '%s\n' "avfoundation"
            ;;
        Linux)
            if [ -n "${DISPLAY:-}" ]; then
                printf '%s\n' "x11grab"
            else
                printf '%s\n' "lavfi"
            fi
            ;;
        *)
            printf '%s\n' "lavfi"
            ;;
    esac
}

check_playwright() {
    if [ ! -x "$PYTHON_BIN" ]; then
        PYTHON_BIN="$(command -v python3 || true)"
    fi
    if [ -z "${PYTHON_BIN:-}" ]; then
        fail "python3 not found; Playwright browser launch cannot run."
        return 1
    fi
    if ! "$PYTHON_BIN" - <<'PY' > /dev/null 2>&1
import playwright.async_api
PY
    then
        fail "Playwright is not importable from $PYTHON_BIN."
        info "  Install the render extra and Chromium:"
        info "    make render-install"
        return 1
    fi
}

start_camera_bot() {
    BOT_LOG="$(mktemp -t livestream-camera-bot.XXXXXX.log)"
    node "$SCRIPT_DIR/camera-bot.mjs" \
        --host "$MC_HOST" \
        --server-port "$MC_PORT" \
        --viewer-port "$VIEWER_PORT" \
        --username "$CAMERA_USERNAME" \
        --version "$MC_VERSION" \
        > "$BOT_LOG" 2>&1 &
    BOT_PID=$!
    info "Camera bot pid: $BOT_PID (log: $BOT_LOG)"
}

wait_for_camera_ready() {
    local timeout="60"
    for _ in $(seq 1 "$timeout"); do
        if grep -q '"event":"READY"' "$BOT_LOG" 2> /dev/null; then
            ok "Prismarine Viewer ready at $VIEWER_URL"
            return 0
        fi
        if ! kill -0 "$BOT_PID" 2> /dev/null; then
            fail "Camera bot exited before READY."
            sed -n '1,160p' "$BOT_LOG" >&2 || true
            return 1
        fi
        sleep 1
    done

    fail "Timed out waiting for CameraSpike READY on viewer port ${VIEWER_PORT}."
    sed -n '1,160p' "$BOT_LOG" >&2 || true
    return 1
}

start_viewer_browser() {
    BROWSER_LOG="$(mktemp -t livestream-viewer-browser.XXXXXX.log)"
    "$PYTHON_BIN" - "$VIEWER_URL" "$DURATION" "$VIDEO_WIDTH" "$VIDEO_HEIGHT" > "$BROWSER_LOG" 2>&1 <<'PY' &
import asyncio
import sys
from playwright.async_api import async_playwright

url = sys.argv[1]
duration = int(sys.argv[2])
width = int(sys.argv[3])
height = int(sys.argv[4])

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[f"--window-size={width},{height}", "--autoplay-policy=no-user-gesture-required"],
        )
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.goto(url, wait_until="networkidle", timeout=30000)
        print("BROWSER_READY", flush=True)
        await page.wait_for_timeout((duration + 2) * 1000)
        await browser.close()

asyncio.run(main())
PY
    BROWSER_PID=$!
    info "Viewer browser pid: $BROWSER_PID (log: $BROWSER_LOG)"
}

wait_for_browser_ready() {
    local timeout="30"
    for _ in $(seq 1 "$timeout"); do
        if grep -q "BROWSER_READY" "$BROWSER_LOG" 2> /dev/null; then
            ok "Chromium loaded $VIEWER_URL"
            return 0
        fi
        if ! kill -0 "$BROWSER_PID" 2> /dev/null; then
            fail "Chromium exited before loading the viewer."
            sed -n '1,160p' "$BROWSER_LOG" >&2 || true
            return 1
        fi
        sleep 1
    done

    fail "Timed out waiting for Chromium to load $VIEWER_URL."
    sed -n '1,160p' "$BROWSER_LOG" >&2 || true
    return 1
}

run_display_capture() {
    local backend="$1"
    mkdir -p "$(dirname -- "$OUT")"

    info "Recording ${backend} capture for ${DURATION}s -> $OUT"
    case "$backend" in
        avfoundation)
            ffmpeg -hide_banner -loglevel warning -y \
                -f avfoundation -framerate "$FPS" -i "$AVFOUNDATION_INPUT" \
                -t "$DURATION" \
                -vf "scale=${VIDEO_WIDTH}:${VIDEO_HEIGHT},fps=${FPS}" \
                -pix_fmt yuv420p -movflags +faststart "$OUT"
            ;;
        x11grab)
            ffmpeg -hide_banner -loglevel warning -y \
                -f x11grab -video_size "$VIDEO_SIZE" -framerate "$FPS" -i "${DISPLAY}" \
                -t "$DURATION" \
                -vf "fps=${FPS}" \
                -pix_fmt yuv420p -movflags +faststart "$OUT"
            ;;
        *)
            return 1
            ;;
    esac
}

run_test_pattern_capture() {
    mkdir -p "$(dirname -- "$OUT")"
    fail "No usable screen-capture path is available; writing a lavfi test-pattern artifact instead."
    info "This is a skipped live-world capture, not acceptance evidence."
    ffmpeg -hide_banner -loglevel warning -y \
        -f lavfi -i "testsrc2=size=${VIDEO_SIZE}:rate=${FPS}" \
        -t "$DURATION" \
        -pix_fmt yuv420p -movflags +faststart "$OUT"
}

summarize_capture() {
    if [ ! -s "$OUT" ]; then
        fail "No output file was written: $OUT"
        return 1
    fi

    local stream duration size
    stream="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 "$OUT" || true)"
    duration="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OUT" || true)"
    size="$(wc -c < "$OUT" | tr -d ' ')"

    if [ -z "$stream" ]; then
        fail "ffprobe did not find a valid video stream in $OUT"
        return 1
    fi

    ok "Capture file: $OUT"
    info "size:     ${size} bytes"
    info "duration: ${duration:-unknown}s"
    info "video:    $stream"
}

ok "E13-1 capture prototype"
info "server:    ${MC_HOST}:${MC_PORT}  auth=offline  minecraft=${MC_VERSION}"
info "camera:    ${CAMERA_USERNAME}  (non-agent spectator camera)"
info "viewer:    ${VIEWER_URL}"
info "duration:  ${DURATION}s"
info "output:    $OUT"
info "video:     ${VIDEO_SIZE}@${FPS}fps"
info "ffprobe validation is required before this exits 0."

if [ "$MODE" = "dry-run" ]; then
    echo
    ok "Dry run complete - no server check, npm install, bot launch, browser, or ffmpeg capture."
    info "Would assert: Node ${REQUIRED_NODE_MAJOR}+, ffmpeg, ffprobe, and ${MC_HOST}:${MC_PORT} reachability"
    info "Would install: npm install --prefix scripts/livestream --no-package-lock (only if node_modules missing)"
    info "Would launch:  node scripts/livestream/camera-bot.mjs --viewer-port ${VIEWER_PORT}"
    info "Would open:    $VIEWER_URL in Chromium via Playwright"
    info "Would record:  ffmpeg display capture to $OUT, then validate with ffprobe"
    exit 0
fi

check_node || exit 2
check_command "ffmpeg" "Install ffmpeg (macOS: brew install ffmpeg)." || exit 2
check_command "ffprobe" "Install ffmpeg; ffprobe ships with it." || exit 2
check_minecraft_server || exit 2
ensure_node_deps

start_camera_bot
wait_for_camera_ready || exit 1

BACKEND="$(display_backend)"
if [ "$BACKEND" = "lavfi" ]; then
    run_test_pattern_capture || exit 1
    summarize_capture || exit 1
    exit 3
fi

check_playwright || exit 2
start_viewer_browser
wait_for_browser_ready || exit 2

if ! run_display_capture "$BACKEND"; then
    fail "Display capture failed for backend ${BACKEND}."
    run_test_pattern_capture || exit 1
    summarize_capture || exit 1
    exit 3
fi

summarize_capture || exit 1
exit 0

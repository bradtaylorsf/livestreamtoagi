#!/usr/bin/env bash
# Canonical verification entrypoint for issue #463 (replay → MP4 render).
#
# This script exists because plain ``python scripts/render_simulation_video.py``
# is fragile in two ways that bit the autonomous verifier:
#
#   1. ``python`` on PATH may be a stale shim from another project (we've seen
#      ~/.local/bin/python re-exec into a deleted venv). We bypass PATH and
#      pin to ``.venv/bin/python`` directly.
#   2. ``psql`` invoked without args defaults to local-socket / $USER /
#      database=$USER, which fails on most dev machines. We source ``.env``
#      first so DATABASE_URL is set.
#
# Two modes:
#
#   bash scripts/verify-render.sh
#     Self-contained mode. Runs the integration test, which spins up a tiny
#     stub HTTP server hosting a replay-contract page, drives the real
#     render_pipeline.py against it, and ffprobe-confirms both streams in
#     the resulting MP4. Needs only: .venv, playwright+chromium, ffmpeg.
#
#   bash scripts/verify-render.sh <sim-id>
#     Live mode. Renders a real simulation against a running website +
#     backend. Requires DATABASE_URL set (we source .env), the Next.js
#     site reachable at PUBLIC_BASE_URL, and the FastAPI backend reachable
#     wherever next.config.ts proxies /api/* to.
#
# Exit codes:
#   0 — verification passed
#   1 — render or ffprobe check failed
#   4 — environment incomplete (.venv missing, ffprobe missing, etc.)
#   5 — no eligible simulation found (live mode, no sim-id given)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
    echo "ERROR: $PY not found. Bootstrap with:" >&2
    echo "  uv venv .venv --python 3.13" >&2
    echo "  uv pip install -e \".[dev,render]\"" >&2
    exit 4
fi

if ! command -v ffprobe > /dev/null 2>&1; then
    echo "ERROR: ffprobe not on PATH — install ffmpeg to verify render output." >&2
    exit 4
fi

# Source .env so DATABASE_URL / PUBLIC_BASE_URL / etc. are available to both
# the wrapper (psql) and the child Python process.
if [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"
    set +a
fi

SIM_ID="${1:-}"

if [[ -z "$SIM_ID" ]]; then
    # Default: run the integration test. This exercises the full
    # render_pipeline.py + audio_timeline + ffmpeg mux path against a stub
    # replay page, and asserts ffprobe sees both video + audio streams.
    # No website/backend needed.
    echo "[verify] no sim-id given — running self-contained integration test"
    echo "[verify] (pass a sim-id explicitly to render against a running website)"
    exec "$PY" -m pytest "$ROOT_DIR/tests/integration/test_video_render_e2e.py" -v
fi

# ── Live mode below ────────────────────────────────────────────────────────

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "ERROR: DATABASE_URL is not set (and no .env found at $ROOT_DIR/.env)." >&2
    exit 4
fi

# Confirm the website is up before we burn time stitching audio. The render
# pipeline times out 30s waiting for window.__replayReady; failing earlier
# with a clear message is a much better operator experience.
PUBLIC_BASE="${PUBLIC_BASE_URL:-http://localhost:3000}"
if ! curl -fsS -o /dev/null --max-time 5 "$PUBLIC_BASE" 2> /dev/null; then
    echo "ERROR: $PUBLIC_BASE is not reachable. Start the website with:" >&2
    echo "  cd website && npm run build && npm run start" >&2
    echo "Or run \`bash scripts/verify-render.sh\` (no sim-id) for the self-contained test." >&2
    exit 4
fi

echo "[verify] rendering sim=$SIM_ID via $PY"
"$PY" "$ROOT_DIR/scripts/render_simulation_video.py" --sim-id "$SIM_ID"

OUT_DIR="${VIDEO_OUTPUT_DIR:-$ROOT_DIR/videos}"
MP4="$OUT_DIR/$SIM_ID.mp4"

if [[ ! -f "$MP4" ]]; then
    echo "ERROR: expected MP4 not found at $MP4" >&2
    exit 1
fi

echo "[verify] probing $MP4"
STREAMS="$(ffprobe -v error -show_entries stream=codec_type -of default=nw=1 "$MP4")"
echo "$STREAMS"

if ! echo "$STREAMS" | grep -q "codec_type=video"; then
    echo "ERROR: no video stream in $MP4" >&2
    exit 1
fi
if ! echo "$STREAMS" | grep -q "codec_type=audio"; then
    echo "ERROR: no audio stream in $MP4" >&2
    exit 1
fi

echo "[verify] OK — $MP4 has both video and audio streams"

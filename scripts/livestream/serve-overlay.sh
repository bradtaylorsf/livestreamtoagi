#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERLAY_DIR="${SCRIPT_DIR}/overlay"
HOST="${STREAM_OVERLAY_HOST:-127.0.0.1}"
PORT="${STREAM_OVERLAY_PORT:-8765}"
API_BASE="${STREAM_API_BASE:-http://127.0.0.1:8010}"
CHECK=0

usage() {
  cat <<'EOF'
Usage: scripts/livestream/serve-overlay.sh [--host HOST] [--port PORT] [--api URL] [--check]

Serves scripts/livestream/overlay/ as an OBS browser source.

Options:
  --host HOST   Bind address for the static overlay server (default: 127.0.0.1)
  --port PORT   Bind port for the static overlay server (default: 8765)
  --api URL     Backend API base URL used for --check output (default: http://127.0.0.1:8010)
  --check       Start a temporary static server, fetch index.html, fetch the backend status feed,
                and exit 0 on success or 2 on smoke-check failure.
  -h, --help    Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:?missing value for --host}"
      shift 2
      ;;
    --port)
      PORT="${2:?missing value for --port}"
      shift 2
      ;;
    --api)
      API_BASE="${2:?missing value for --api}"
      shift 2
      ;;
    --check)
      CHECK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

fetch_url() {
  python3 - "$1" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        status = response.getcode()
        body = response.read(1024)
except Exception as exc:
    print(f"{url} failed: {exc}", file=sys.stderr)
    sys.exit(1)

if 200 <= status < 300 and body:
    sys.exit(0)

print(f"{url} returned HTTP {status} with an empty body", file=sys.stderr)
sys.exit(1)
PY
}

if [[ ! -d "${OVERLAY_DIR}" ]]; then
  echo "Overlay directory not found: ${OVERLAY_DIR}" >&2
  exit 1
fi

INDEX_URL="http://${HOST}:${PORT}/index.html?api=${API_BASE}"
STATUS_URL="${API_BASE%/}/api/stream/agent-status"

if [[ "${CHECK}" -eq 1 ]]; then
  LOG_FILE="${TMPDIR:-/tmp}/livestream-overlay-http.log"
  python3 -m http.server "${PORT}" --bind "${HOST}" --directory "${OVERLAY_DIR}" \
    >"${LOG_FILE}" 2>&1 &
  SERVER_PID=$!
  cleanup() {
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
  }
  trap cleanup EXIT

  for _ in {1..30}; do
    if fetch_url "${INDEX_URL}" >/dev/null 2>&1; then
      break
    fi
    sleep 0.1
  done

  if ! fetch_url "${INDEX_URL}"; then
    echo "Overlay check failed: static overlay did not serve ${INDEX_URL}" >&2
    exit 2
  fi

  if ! fetch_url "${STATUS_URL}"; then
    echo "Overlay check failed: backend status feed did not respond at ${STATUS_URL}" >&2
    exit 2
  fi

  echo "Overlay check passed"
  echo "OBS browser source: ${INDEX_URL}"
  exit 0
fi

echo "Serving overlay from ${OVERLAY_DIR}"
echo "OBS browser source: ${INDEX_URL}"
exec python3 -m http.server "${PORT}" --bind "${HOST}" --directory "${OVERLAY_DIR}"

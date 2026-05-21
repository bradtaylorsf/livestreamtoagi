#!/usr/bin/env bash
# Launch Sentinel as a verbal Mindcraft bot wired to the Python bridge (E8-4).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export COHORT_BOT_ID="sentinel"
export COHORT_BOT_NAME="Sentinel"
export COHORT_LAUNCH_NAME="connect-sentinel-bot.sh"
export COHORT_SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-sentinel.js"
export COHORT_PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/sentinel-bot.json"
export COHORT_PROFILE_DEFAULT="./profiles/sentinel-bot.json"

exec "$SCRIPT_DIR/connect-cohort-bot.sh" "$@"

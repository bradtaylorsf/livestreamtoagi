#!/usr/bin/env bash
# Launch Pixel as a verbal Mindcraft bot wired to the Python bridge (E8-3).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export COHORT_BOT_ID="pixel"
export COHORT_BOT_NAME="Pixel"
export COHORT_LAUNCH_NAME="connect-pixel-bot.sh"
export COHORT_SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-pixel.js"
export COHORT_PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/pixel-bot.json"
export COHORT_PROFILE_DEFAULT="./profiles/pixel-bot.json"

exec "$SCRIPT_DIR/connect-cohort-bot.sh" "$@"

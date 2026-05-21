#!/usr/bin/env bash
# Launch Vera as a verbal Mindcraft bot wired to the Python bridge (E8-2).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export COHORT_BOT_ID="vera"
export COHORT_BOT_NAME="Vera"
export COHORT_LAUNCH_NAME="connect-vera-bot.sh"
export COHORT_SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-vera.js"
export COHORT_PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/vera-bot.json"
export COHORT_PROFILE_DEFAULT="./profiles/vera-bot.json"

exec "$SCRIPT_DIR/connect-cohort-bot.sh" "$@"

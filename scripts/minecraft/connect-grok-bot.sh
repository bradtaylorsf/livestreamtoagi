#!/usr/bin/env bash
# Launch Grok as a verbal Mindcraft bot wired to the Python bridge (E8-4).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export COHORT_BOT_ID="grok"
export COHORT_BOT_NAME="Grok"
export COHORT_LAUNCH_NAME="connect-grok-bot.sh"
export COHORT_SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-grok.js"
export COHORT_PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/grok-bot.json"
export COHORT_PROFILE_DEFAULT="./profiles/grok-bot.json"

exec "$SCRIPT_DIR/connect-cohort-bot.sh" "$@"

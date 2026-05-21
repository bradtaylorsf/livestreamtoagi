#!/usr/bin/env bash
# Launch Aurora as a verbal Mindcraft bot wired to the Python bridge (E8-3).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export COHORT_BOT_ID="aurora"
export COHORT_BOT_NAME="Aurora"
export COHORT_LAUNCH_NAME="connect-aurora-bot.sh"
export COHORT_SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-aurora.js"
export COHORT_PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/aurora-bot.json"
export COHORT_PROFILE_DEFAULT="./profiles/aurora-bot.json"

exec "$SCRIPT_DIR/connect-cohort-bot.sh" "$@"

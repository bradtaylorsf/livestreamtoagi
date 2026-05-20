#!/usr/bin/env bash
# Launch Rex as a verbal Mindcraft bot wired to the Python bridge (E8-2).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export COHORT_BOT_ID="rex"
export COHORT_BOT_NAME="Rex"
export COHORT_LAUNCH_NAME="connect-rex-bot.sh"
export COHORT_SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-rex.js"
export COHORT_PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/rex-bot.json"
export COHORT_PROFILE_DEFAULT="./profiles/rex-bot.json"

exec "$SCRIPT_DIR/connect-cohort-bot.sh" "$@"

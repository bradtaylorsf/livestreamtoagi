#!/usr/bin/env bash
# Launch Fork as a verbal Mindcraft bot wired to the Python bridge (E8-3).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export COHORT_BOT_ID="fork"
export COHORT_BOT_NAME="Fork"
export COHORT_LAUNCH_NAME="connect-fork-bot.sh"
export COHORT_SETTINGS_TEMPLATE="$SCRIPT_DIR/mindcraft-settings-fork.js"
export COHORT_PROFILE_TEMPLATE="$SCRIPT_DIR/profiles/fork-bot.json"
export COHORT_PROFILE_DEFAULT="./profiles/fork-bot.json"

exec "$SCRIPT_DIR/connect-cohort-bot.sh" "$@"

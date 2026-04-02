#!/usr/bin/env bash

set -euo pipefail

if [[ -x ".venv/bin/pytest" ]]; then
  exec .venv/bin/pytest "$@"
fi

exec uv run --frozen --extra dev pytest "$@"

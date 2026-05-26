#!/usr/bin/env bash
# Overnight runs for the two remaining E22 acceptance-criterion-#10 scenarios:
# faction_emergence_test.yaml (48h simulated, ~60-90 min real) and
# full_evolution_7d.yaml (7d simulated, ~hours real).
#
# Routes:
#   conversation -> OpenRouter (per-agent models from CLAUDE.md / agents/*.yaml)
#   vision       -> Gemini 3.5 Flash (when propose_new_building fires)
#   image gen    -> OpenAI gpt-image-2 (when propose_new_building fires)
#
# Cost caps: $10/sim, $5 image budget (per the user's preference).
#
# Run sequentially (do NOT parallelize — each sim hits LM Studio / OpenRouter /
# Gemini / OpenAI through the same shared Redis/Postgres scope).
#
# Usage:
#   bash scripts/overnight_e22_runs.sh                      # both, sequential
#   bash scripts/overnight_e22_runs.sh faction              # just #1
#   bash scripts/overnight_e22_runs.sh full_evolution       # just #2
#
# Logs land under /tmp/e22-overnight-<scenario>-<ts>.log so they survive Ctrl-C.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "✗ .env missing in $REPO_ROOT" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

# Conversation LLM via OpenRouter (overrides .env's local lmstudio).
export LLM_PROVIDER=openrouter
# Per-agent models come from agents/*.yaml. Override the global fallback only
# if an agent's YAML doesn't pin one (rare).
export OPENROUTER_MODEL_FALLBACK="${OPENROUTER_MODEL_FALLBACK:-anthropic/claude-haiku-4-5}"

# Embedding stays deterministic — semantic recall quality isn't what's being
# evaluated here.
export EMBEDDING_PROVIDER=deterministic

# Cap LLM spend (sim-level)
MAX_COST=10
# Cap image budget (rough — gpt-image-2 ~$0.04/img, so 125 images = $5)
export PROPOSE_NEW_BUILDING_IMAGE_BUDGET_USD="${PROPOSE_NEW_BUILDING_IMAGE_BUDGET_USD:-5.00}"

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "✗ OPENROUTER_API_KEY not set (needed for cloud conversation)" >&2; exit 1
fi
if [[ -z "${GOOGLE_API_KEY:-}" ]]; then
  echo "✗ GOOGLE_API_KEY not set (needed for Gemini blueprint decomposer)" >&2; exit 1
fi
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "✗ OPENAI_API_KEY not set (needed for gpt-image-2)" >&2; exit 1
fi

TS=$(date -u +%Y%m%dT%H%M%SZ)

run_one() {
  local label=$1
  local scenario=$2
  local seed=$3
  local log=/tmp/e22-overnight-${label}-${TS}.log
  echo "===== ${label} =====" | tee -a "$log"
  echo "scenario: $scenario" | tee -a "$log"
  echo "seed: $seed | max-cost: \$$MAX_COST" | tee -a "$log"
  echo "started: $(date -u +%FT%TZ)" | tee -a "$log"
  echo "log: $log"
  echo
  # Wrap with `caffeinate -dimsu` so macOS App Nap / system sleep doesn't
  # kill the python sim partway through an overnight run.
  caffeinate -dimsu .venv/bin/python scripts/run_headless_sim.py \
    --scenario "$scenario" \
    --max-cost "$MAX_COST" \
    --seed "$seed" \
    --output-dir snapshots/headless \
    --verbose \
    >> "$log" 2>&1
  local rc=$?
  echo "finished: $(date -u +%FT%TZ) (exit=$rc)" | tee -a "$log"
  return $rc
}

case "${1:-both}" in
  faction)
    run_one faction scenarios/faction_emergence_test.yaml 1
    ;;
  full_evolution)
    run_one full_evolution scenarios/full_evolution_7d.yaml 2
    ;;
  both|"")
    run_one faction scenarios/faction_emergence_test.yaml 1 && \
    run_one full_evolution scenarios/full_evolution_7d.yaml 2
    ;;
  *)
    echo "usage: $0 [faction|full_evolution|both]" >&2
    exit 2
    ;;
esac

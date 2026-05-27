#!/usr/bin/env bash
# Open-ended collaborative settlement smoke (E21-1, #821).
#
# Runs the E17/E18 command-eval preflight (#818) and then the headless
# Minecraft scenario for ``scenarios/open_settlement_smoke.yaml``. Finally
# invokes the settlement-smoke classifier to produce ``smoke-report.json``
# and ``smoke-report.md`` under the sim folder.
#
# Usage: scripts/minecraft/run_open_settlement_smoke.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCENARIO="${SCENARIO:-${REPO_ROOT}/scenarios/open_settlement_smoke.yaml}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/snapshots/headless}"
MAX_COST="${MAX_COST:-0.10}"
DURATION="${DURATION:-25m}"
PYTHON_BIN="${PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: missing venv python at ${PYTHON_BIN}. Run 'uv venv .venv --python 3.13' first." >&2
  exit 1
fi
if [[ ! -f "${SCENARIO}" ]]; then
  echo "ERROR: scenario not found: ${SCENARIO}" >&2
  exit 1
fi

export MC_SIM_BUILD_MODE="${MC_SIM_BUILD_MODE:-settlement}"
export SOAK_PLAN_BUILD_BOTS="${SOAK_PLAN_BUILD_BOTS:-rex fork}"

mkdir -p "${OUTPUT_DIR}"

echo "[1/3] preflight: scripts/minecraft/eval_commands.py (dry-run)"
PREFLIGHT_ARGS=(--dry-run --limit 3 --json)
# resolve_provider_config requires --model for openrouter even under --dry-run.
# Use MC_EVAL_MODEL when set; otherwise fall back to a cheap default so the
# wrapper works on either provider without manual config.
PREFLIGHT_PROVIDER="${LLM_PROVIDER:-lmstudio}"
if [[ "${PREFLIGHT_PROVIDER}" == "openrouter" ]]; then
  PREFLIGHT_ARGS+=(--model "${MC_EVAL_MODEL:-deepseek/deepseek-v3.2}")
fi
"${PYTHON_BIN}" "${REPO_ROOT}/scripts/minecraft/eval_commands.py" \
  "${PREFLIGHT_ARGS[@]}" \
  > "${OUTPUT_DIR}/_open_settlement_smoke_preflight.json" \
  || {
    echo "ERROR: E17/E18 preflight failed; refusing to launch settlement smoke" >&2
    exit 1
  }

echo "[2/3] launch: scripts/run_headless_sim.py --scenario ${SCENARIO}"
NAME="open_settlement_smoke"
SIM_LOG="$(mktemp)"
trap 'rm -f "${SIM_LOG}"' EXIT

"${PYTHON_BIN}" "${REPO_ROOT}/scripts/run_headless_sim.py" \
  --scenario "${SCENARIO}" \
  --name "${NAME}" \
  --max-cost "${MAX_COST}" \
  --duration "${DURATION}" \
  --output-dir "${OUTPUT_DIR}" \
  --verbose \
  | tee "${SIM_LOG}"

SIM_FOLDER="$(grep -E '^Headless simulation complete\. Artifacts: ' "${SIM_LOG}" \
  | tail -1 | sed -E 's/^Headless simulation complete\. Artifacts: //')"

if [[ -z "${SIM_FOLDER}" || ! -d "${SIM_FOLDER}" ]]; then
  echo "ERROR: could not locate sim folder from run_headless_sim.py output" >&2
  exit 1
fi

echo "[3/3] report: scripts/minecraft/build_settlement_smoke_report.py --sim-folder ${SIM_FOLDER}"
"${PYTHON_BIN}" "${REPO_ROOT}/scripts/minecraft/build_settlement_smoke_report.py" \
  --sim-folder "${SIM_FOLDER}"

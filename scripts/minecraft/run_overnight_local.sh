#!/usr/bin/env bash
# Overnight local-LLM plumbing run for epic #820.
#
# Runs the open settlement scenario against:
#   - Chat:        local LM Studio (LLM_PROVIDER=lmstudio, LOCAL_LLM_MODEL=...)
#   - Builds:      live Paper server via RCON (blocks appear in real time)
#   - Image gen:   OpenAI gpt-image-2 + Google Gemini (only fires when an agent
#                  successfully calls propose_new_building — depends on the
#                  local model's tool-call reliability)
#
# Defaults are tuned for 8-hour overnight runs. Override with env:
#   DURATION=12h MAX_COST=10.00 bash scripts/minecraft/run_overnight_local.sh
#
# Prereqs:
#   * LM Studio running on :1234 with the model loaded
#   * Paper server running on :25565 with RCON enabled on :25575
#   * Docker stack up (`docker compose up -d`; `bash scripts/check-services.sh`)
#   * .env has LLM_PROVIDER=lmstudio + LOCAL_LLM_MODEL=...
#   * .env has RCON_HOST/PORT/PASSWORD set
#   * .env has OPENAI_API_KEY + GOOGLE_API_KEY for blueprint pipeline

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export DURATION="${DURATION:-8h}"
export MAX_COST="${MAX_COST:-5.00}"
export OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/snapshots/overnight}"
export SCENARIO="${SCENARIO:-${REPO_ROOT}/scenarios/open_settlement_smoke.yaml}"

# LLM_PROVIDER inherits from .env; warn if not local
if [[ "${LLM_PROVIDER:-}" != "lmstudio" && "${LLM_PROVIDER:-}" != "local" ]]; then
  echo "WARN: LLM_PROVIDER is '${LLM_PROVIDER:-unset}' (not lmstudio/local)." >&2
  echo "WARN: This run will send all chat to whatever provider .env points at." >&2
  echo "WARN: Set LLM_PROVIDER=lmstudio in your shell or .env for true local-only chat." >&2
fi

mkdir -p "${OUTPUT_DIR}"
LOG="${OUTPUT_DIR}/run-$(date -u +%Y%m%dT%H%M%SZ).log"

echo "============================================================"
echo "  Overnight local-LLM plumbing run"
echo "============================================================"
echo "  Scenario:    ${SCENARIO}"
echo "  Duration:    ${DURATION}"
echo "  Max cost:    \$${MAX_COST}"
echo "  Output dir:  ${OUTPUT_DIR}"
echo "  LLM:         ${LLM_PROVIDER:-lmstudio} / ${LOCAL_LLM_MODEL:-(env default)}"
echo "  RCON:        ${RCON_HOST:-unset}:${RCON_PORT:-25575}"
echo "  Log:         ${LOG}"
echo "============================================================"

bash "${REPO_ROOT}/scripts/minecraft/run_open_settlement_smoke.sh" 2>&1 | tee "${LOG}"

echo ""
echo "Run complete. Artifacts under ${OUTPUT_DIR}/"
echo "Full log: ${LOG}"

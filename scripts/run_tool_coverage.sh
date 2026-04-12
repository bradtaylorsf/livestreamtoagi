#!/usr/bin/env bash
# Run the tool coverage simulation and verification in one shot.
# Usage: bash scripts/run_tool_coverage.sh

set -euo pipefail
cd "$(dirname "$0")/.."

source .venv/bin/activate
export $(grep -v '^#' .env | xargs)

LOG_FILE="tool_coverage_$(date +%Y%m%d_%H%M%S).log"

echo "=== Running tool coverage simulation ==="
echo "Log file: $LOG_FILE"

python scripts/run_simulation.py \
  --name "tool-coverage" \
  --seed-file scenarios/tool_coverage.yaml \
  --max-cost 15.00 \
  --verbose 2>&1 | tee "$LOG_FILE"

SIM_EXIT=$?

echo ""
echo "=== Simulation exit code: $SIM_EXIT ==="
echo ""

if [ $SIM_EXIT -eq 0 ]; then
  echo "=== Running verification ==="
  python scripts/verify_simulation.py --name "tool-coverage" 2>&1 | tee -a "$LOG_FILE"
  echo ""
  echo "=== Running tool coverage check ==="
  python scripts/check_tool_coverage.py --name "tool-coverage" 2>&1 | tee -a "$LOG_FILE"
else
  echo "Simulation failed — skipping verification"
fi

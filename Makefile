# Makefile — convenience targets that pin invocations to the project's venv
# so they are immune to stale `python`, `pytest`, or `playwright` shims on PATH.

PY := .venv/bin/python
PYTEST := .venv/bin/pytest
PW := .venv/bin/playwright
MEMORY_REGRESSION_TESTS := \
	tests/backend/test_core_memory.py \
	tests/backend/test_core_memory_startup.py \
	tests/backend/test_recall_memory.py \
	tests/backend/test_archival_memory.py \
	tests/backend/test_cross_conversation_memory.py \
	tests/backend/test_memory_seed.py \
	tests/backend/test_memory_seed_bridge_compat.py \
	tests/backend/test_memory_snapshot.py \
	tests/backend/test_memory_tools.py \
	tests/backend/test_memory_backend.py \
	tests/backend/test_memory_parity.py \
	tests/backend/test_bridge_memory.py \
	tests/backend/test_bridge_perception_action_memory.py

.PHONY: test test-backend test-memory-regression bench-memory-bridge test-replay-cues render-install render-smoke render-verify

# Run the full backend unit-test suite with coverage. Mirrors the CI
# step in .github/workflows/ci.yml so local runs match CI exactly.
test test-backend:
	$(PYTEST) tests/backend/ -v -m "not integration" --cov=core --cov=tools

# Run the required memory regression gate. Mirrors the CI step exactly so the
# bridge-path suite is checked the same way locally and in GitHub Actions.
test-memory-regression:
	$(PYTEST) $(MEMORY_REGRESSION_TESTS) -v -m "not integration"

# Run the deterministic bridge memory latency budget check from issue #555.
bench-memory-bridge:
	$(PY) scripts/bench_memory_bridge.py --check-budget

# Issue #477 — replay-cue parser + endpoint. The verification harness
# auto-runs these on every change to core/video/cue_parser.py or
# core/public_routes.py's replay-cues route.
test-replay-cues:
	$(PYTEST) tests/backend/test_video_render.py tests/backend/test_replay_cues_endpoint.py -v

# Install the render extra and download the Chromium binaries Playwright
# needs to launch a browser. Idempotent.
render-install:
	uv pip install -e ".[render]"
	$(PW) install chromium

# Smoke-check the render entrypoint without touching a real simulation.
render-smoke:
	$(PY) -c "import playwright.async_api; print('playwright import: ok')"
	$(PY) scripts/render_simulation_video.py --help

# End-to-end verification: pick a real sim with transcripts (or use SIM=<uuid>),
# render to MP4, and ffprobe-confirm both video + audio streams are present.
render-verify:
	bash scripts/verify-render.sh $(SIM)

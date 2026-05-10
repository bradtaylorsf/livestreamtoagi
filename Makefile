# Makefile — convenience targets that pin invocations to the project's venv
# so they are immune to stale `python`, `pytest`, or `playwright` shims on PATH.

PY := .venv/bin/python
PYTEST := .venv/bin/pytest
PW := .venv/bin/playwright

.PHONY: test test-backend test-replay-cues render-install render-smoke render-verify

# Run the full backend unit-test suite with coverage. Mirrors the CI
# step in .github/workflows/ci.yml so local runs match CI exactly.
test test-backend:
	$(PYTEST) tests/backend/ -v -m "not integration" --cov=core --cov=tools

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

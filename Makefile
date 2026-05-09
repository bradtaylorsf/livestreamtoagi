# Makefile — convenience targets that pin invocations to the project's venv
# so they are immune to PATH ordering issues. CI installs deps with
# `uv pip install --system -e ".[dev]"` so bare `pytest` works there;
# local verifiers running under `/bin/sh` without venv activation hit
# `pytest: command not found` and need a pinned entrypoint.

PY := .venv/bin/python
PYTEST := .venv/bin/pytest

.PHONY: test test-backend test-replay-cues

# Run the full backend unit-test suite with coverage. Mirrors the CI
# step in .github/workflows/ci.yml so local runs match CI exactly.
test test-backend:
	$(PYTEST) tests/backend/ -v -m "not integration" --cov=core --cov=tools

# Issue #477 — replay-cue parser + endpoint. The verification harness
# auto-runs these on every change to core/video/cue_parser.py or
# core/public_routes.py's replay-cues route.
test-replay-cues:
	$(PYTEST) tests/backend/test_video_render.py tests/backend/test_replay_cues_endpoint.py -v

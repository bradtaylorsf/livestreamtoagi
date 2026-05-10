# Makefile — convenience targets that pin invocations to the project's venv
# so they are immune to stale `python` / `playwright` shims on PATH.
#
# These are documentation-quality helpers; the canonical install path is
# still `uv pip install -e ".[render]"` followed by `playwright install
# chromium`. The targets exist so CI, verifiers, and humans can run
# render-pipeline checks without depending on PATH order.

PY := .venv/bin/python
PW := .venv/bin/playwright

.PHONY: render-install render-smoke render-verify

# Install the render extra and download the Chromium binaries playwright
# needs to actually launch a browser. Idempotent.
render-install:
	uv pip install -e ".[render]"
	$(PW) install chromium

# Smoke-check the render entrypoint without touching a real simulation.
# Exits 0 if playwright is importable AND `--help` parses cleanly. Hits
# the venv's own python directly to bypass any stale `python` shim that
# might be earlier on PATH.
render-smoke:
	$(PY) -c "import playwright.async_api; print('playwright import: ok')"
	$(PY) scripts/render_simulation_video.py --help

# End-to-end verification: pick a real sim with transcripts (or use SIM=<uuid>),
# render to MP4, and ffprobe-confirm both video + audio streams are present.
# The shell wrapper sources `.env` (so DATABASE_URL is set even when the caller
# didn't export it) and pins to `.venv/bin/python`, so a stale `python` shim
# earlier on PATH cannot intercept the call. This is the canonical entrypoint
# for issue #463's verification step.
render-verify:
	bash scripts/verify-render.sh $(SIM)

# Open Source Readiness

Date: 2026-05-23

This repository is ready to be public as pre-alpha work-in-progress research,
but it is not ready to be deployed as an unattended public autonomous livestream
service. The difference matters: public code and public progress updates are OK;
public 24/7 operation still needs the launch gates below.

See also: [OPEN_SOURCE_AUDIT_REPORT.md](OPEN_SOURCE_AUDIT_REPORT.md) and
the public-readiness tracking epic
[#808](https://github.com/bradtaylorsf/livestreamtoagi/issues/808).

## Public Repository Gate

Status: go after the items below are committed.

- [x] Current tracked-file scan has no `.env`, `.pem`, `.key`, `.p12`, `.log`, or
  `.mp4` files.
- [x] Git history secret scan was run with redaction over all commits; no leaks
  were reported.
- [x] Secret-like fake test keys were removed from unit-test fixtures.
- [x] README says the project is public pre-alpha work, not production-ready
  autonomous livestream infrastructure.
- [x] Audit report exists and is linked from README.
- [x] Existing E11 and E13 launch-gate worktrees/issues are treated as public
  deployment blockers, not as blockers for making the repository visible.

## Public Service Gate

Status: no-go until these are complete.

- [ ] Fix or disable public agent chat so every response uses the supported LLM
  client API and passes Management review before it can be returned publicly
  ([#809](https://github.com/bradtaylorsf/livestreamtoagi/issues/809)).
- [ ] Resolve public magic-link/JWT setup issue #501.
- [ ] Finish E11 cost and kill-switch hardening, especially #596, #598, and
  #600.
- [ ] Finish E13 stream kill-path and livestream ops gates, especially #614.
- [ ] Ensure Minecraft run modes used for public broadcast cannot disable
  Management review
  ([#810](https://github.com/bradtaylorsf/livestreamtoagi/issues/810)).
- [ ] Decide/document whether Minecraft builder-provider OpenRouter calls route
  through the Python LLM client or remain a bounded exception with equivalent
  cost/kill visibility
  ([#811](https://github.com/bradtaylorsf/livestreamtoagi/issues/811)).
- [ ] Decide the legacy Phaser/replay issue cluster through E14/E15 instead of
  deleting it ad hoc
  ([#812](https://github.com/bradtaylorsf/livestreamtoagi/issues/812)).
- [ ] Align repo docs and metadata with Minecraft-first reality
  ([#813](https://github.com/bradtaylorsf/livestreamtoagi/issues/813)).

## Issue Triage Policy

For public repo launch, old issues do not all need to be fixed first. They do
need to be honest:

- Close or mark not planned for obsolete office/Phaser ideas that are not E14
  dependencies.
- Keep legacy replay/video issues only when they protect the current website or
  E14/E15 retirement gates.
- Rewrite simulation-first issues when the idea survives but the implementation
  must target Minecraft run modes.
- Keep E11/E13/E14/E15 as launch gates.
- Label security, cost, Management, auth, and kill-switch issues so
  contributors do not accidentally treat them as routine cleanup.

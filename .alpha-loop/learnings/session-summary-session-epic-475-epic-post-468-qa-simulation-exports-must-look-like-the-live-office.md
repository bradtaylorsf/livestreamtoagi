warning: `--full-auto` is deprecated; use `--sandbox workspace-write` instead.
Reading prompt from stdin...
OpenAI Codex v0.130.0
--------
workdir: /Users/bradtaylor/Documents/GitHub/livestreamtoagi
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/bradtaylor/.codex/memories]
reasoning effort: xhigh
reasoning summaries: none
session id: 019e0ff5-1914-7e10-b6ab-f995ae8689fd
--------
user
Analyze these learnings from a development session and produce a concise session summary with actionable recommendations.

## Session: session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office
- Issues processed: 3 (3 succeeded, 0 failed)
- Total duration: 92 minutes

## Individual Learnings

---
issue: 492
status: success
retries: 1
duration: 3124
date: 2026-05-10
traces:
  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-492.md
  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-492-implement.log
  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-492.log
  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-492.diff
---

## What Worked
+- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
+- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
+- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
+
+## What Failed
+- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
+
+## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## What Failed
+- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
+
+## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++


---

---
issue: 493
status: success
retries: 2
duration: 1756
date: 2026-05-10
traces:
  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-493.md
  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-493-implement.log
  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-493.log
  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-493.diff
---

## What Worked
+- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
+- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
+- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
+
+## What Failed
+- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
+
+## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## What Failed
+- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
+
+## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++


---

---
issue: 486
status: success
retries: 1
duration: 643
date: 2026-05-10
traces:
  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-486.md
  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-486-implement.log
  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-486.log
  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-486.diff
---

## What Worked
+- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
+- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
+- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
+
+## What Failed
+- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
+
+## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## What Failed
+- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
+
+## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Patterns
+- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
+- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
+- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
+
+## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Anti-Patterns
+- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
+- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
+- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
+
+## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++

## Suggested Skill Updates
+- None
diff --git a/.alpha-loop/learnings/issue-478-20260509-162544.md b/.alpha-loop/learnings/issue-478-20260509-162544.md
new file mode 100644
index 0000000..c837970
--- /dev/null
+++ b/.alpha-loop/learnings/issue-478-20260509-162544.md
@@ -0,0 +1,1368 @@
+---
+issue: 478
+status: success
+retries: 0
+duration: 1885
+date: 2026-05-09
+traces:
+  plan: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/prompts/plan-issue-478.md
+  implement: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/logs/issue-478-implement.log
+  review: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/traces/outputs/review-issue-478.log
+  diff: .alpha-loop/sessions/session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office/diffs/issue-478.diff
+---
+
+## What Worked
++- Single shared parser module (`core/video/cue_parser.py`) consumed by both the audio stitcher and the new replay-cues endpoint, satisfying the "cannot drift" acceptance criterion structurally rather than by convention.
++- Pure function `build_cues_from_rows` with injected `known_agents` set kept the parser unit-testable without a DB and produced focused regression tests for multi-speaker rows and malformed prefixes.
++- Added a `Makefile` with `.venv/bin/pytest` pinned so local verifier runs under `/bin/sh` (no venv on PATH) match CI.
++
++## What Failed
++- Initial test run failed once (1 retry) before passing — likely PATH/venv resolution given the Makefile addition, fixed by pinning interpreter paths.
++
++## Patterns
++- When two consumers must stay synchronized on a derived data view (audio cues + UI cues), extract a single pure builder function and have both call it; don't rely on parallel implementations.
++- Walk all regex matches in a row (`SPEAKER_RE.finditer`) instead of only matching a leading prefix when the source data can contain multiple delimited segments.
++- Distribute sub-events from one timestamped row across a small intra-row window (e.g. 0.5s) to preserve order without overlapping the next row's anchor.
++
++## Anti-Patterns
++- Falling back to `participants[0]` for speaker attribution when the actual speaker marker is available — produces wrong `agent_id` and pollutes downstream UI.
++- Treating a transcript row as a single utterance when the storage format encodes multiple `[name]:` turns inline.
++- Spacing sub-cues so tightly that TTS clips overlap in audio (noted as accepted scope but worth revisiting if multi-speaker rows become common).
++
++## Suggested Skill Updates
++- None
+diff --git a/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+new file mode 100644
+index 0000000..f3e7fbd
+--- /dev/null
++++ b/.alpha-loop/learnings/session-session-epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office.json
+@@ -0,0 +1,336 @@
++{
++  "name": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "branch": "session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office",
++  "completed": "2026-05-09T21:58:57.783Z",
++  "results": [
++    {
++      "issueNum": 477,
++      "title": "fix(video): generate turn-level replay cues instead of conversation-sized blobs",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/483",
++      "testsPassing": true,
++      "verifyPassing": true,
++      "duration": 1812,
++      "filesChanged": 5
++    },
++    {
++      "issueNum": 476,
++      "title": "fix(video): replay export must use the real office scene, sprites, movement, and speech bubbles",
++      "status": "success",
++      "prUrl": "https://github.com/bradtaylorsf/livestreamtoagi/pull/485",
++      "testsPassing": true,
++      "verifyPassing": false,
++      "duration": 3121,
++      "filesChanged": 6
++    },
++    {
++      "issueNum": 478,
++      "title": "fix(video): serve local MP4 exports and expose render status to the website",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 479,
++      "title": "fix(auth): simulation creator magic-link overlay must not nest forms or reset draft",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    },
++    {
++      "issueNum": 480,
++      "title": "fix(simulations): public submissions must honor selected scenario agents and exclusions",
++      "status": "failure",
++      "testsPassing": false,
++      "verifyPassing": false,
++      "duration": 18,
++      "filesChanged": 0
++    }
++  ],
++  "stages": [
++    {
++      "stage": "plan",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 8247,
++      "cost_usd": 1.070311,
++      "wall_time_s": 155.022,
++      "tool_calls": 39,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:34:46.308Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "implement",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 79,
++      "tokens_out": 28476,
++      "cost_usd": 4.309778,
++      "wall_time_s": 465.799,
++      "tool_calls": 68,
++      "tool_errors": 3,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:37:21.747Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "test_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 21,
++      "tokens_out": 5717,
++      "cost_usd": 1.764922,
++      "wall_time_s": 185.395,
++      "tool_calls": 15,
++      "tool_errors": 1,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:45:19.941Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "review",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 35,
++      "tokens_out": 11405,
++      "cost_usd": 1.589979,
++      "wall_time_s": 207.877,
++      "tool_calls": 29,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:49:26.587Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "verify_fix",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 74,
++      "tokens_out": 21188,
++      "cost_usd": 4.693228,
++      "wall_time_s": 623.309,
++      "tool_calls": 68,
++      "tool_errors": 2,
++      "stage_success": true,
++      "started_at": "2026-05-09T20:52:54.471Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "assumptions",
++      "model": "",
++      "endpoint": "default",
++      "tokens_in": 6,
++      "tokens_out": 1092,
++      "cost_usd": 0.139549,
++      "wall_time_s": 23.475,
++      "tool_calls": 0,
++      "tool_errors": 0,
++      "stage_success": true,
++      "started_at": "2026-05-09T21:04:21.025Z",
++      "issue_num": 477
++    },
++    {
++      "stage": "plan",
++      "model": "",
++


Output ONLY this markdown structure:

# Session Summary: session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office

## Overview
- (2-3 sentences summarizing the session)

## Recurring Patterns
- (patterns that appeared across multiple issues — these should be reinforced)

## Recurring Anti-Patterns
- (problems that kept happening — these need fixing)

## Recommendations
- (specific, actionable improvements for the agent prompts, project config, or workflow)
- (e.g., "Update the implement prompt to always check for X before Y")
- (e.g., "Add a pre-check for port conflicts before starting verification")

## Metrics
| Metric | Value |
|--------|-------|
| Issues processed | 3 |
| Success rate | 100% |
| Avg duration | 1841s |
| Total duration | 92 min |
2026-05-10T03:36:21.928753Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: prompt must be at most 128 characters path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/build-ios-apps/.codex-plugin/plugin.json
2026-05-10T03:36:21.929020Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/plugin-eval/.codex-plugin/plugin.json
2026-05-10T03:36:21.931031Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/twilio-developer-kit/.codex-plugin/plugin.json
2026-05-10T03:36:21.931070Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
2026-05-10T03:36:22.510708Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: prompt must be at most 128 characters path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/build-ios-apps/.codex-plugin/plugin.json
2026-05-10T03:36:22.510936Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/plugin-eval/.codex-plugin/plugin.json
2026-05-10T03:36:22.512584Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/twilio-developer-kit/.codex-plugin/plugin.json
2026-05-10T03:36:22.512619Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
2026-05-10T03:36:22.521183Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:22.521198Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:22.521502Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:22.521508Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:22.521836Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:22.521840Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:22.522433Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:22.522440Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:22.522758Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:22.522762Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:22.523488Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:22.523491Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:22.546978Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
2026-05-10T03:36:22.549593Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
2026-05-10T03:36:22.549640Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
2026-05-10T03:36:23.523355Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: prompt must be at most 128 characters path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/build-ios-apps/.codex-plugin/plugin.json
2026-05-10T03:36:23.523556Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/plugin-eval/.codex-plugin/plugin.json
2026-05-10T03:36:23.524926Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/twilio-developer-kit/.codex-plugin/plugin.json
2026-05-10T03:36:23.524950Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
2026-05-10T03:36:23.533117Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:23.533135Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:23.533450Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:23.533456Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:23.533759Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:23.533763Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:23.534070Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:23.534074Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:23.534368Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:23.534371Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:23.535011Z  WARN codex_core_skills::loader: ignoring interface.icon_small: icon path must not contain '..'
2026-05-10T03:36:23.535014Z  WARN codex_core_skills::loader: ignoring interface.icon_large: icon path must not contain '..'
2026-05-10T03:36:23.557179Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
2026-05-10T03:36:23.559994Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
2026-05-10T03:36:23.560039Z  WARN codex_core_plugins::manifest: ignoring interface.defaultPrompt: maximum of 3 prompts is supported path=/Users/bradtaylor/.codex/.tmp/plugins/plugins/openai-developers/.codex-plugin/plugin.json
codex
# Session Summary: session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office

## Overview
- The session completed 3 video/export QA issues successfully, centered on making replay cues consistent with audio stitching and live-office rendering behavior. The strongest outcome was consolidating cue derivation into one shared, testable parser path instead of maintaining parallel implementations.

## Recurring Patterns
- Extract shared pure builders when multiple consumers need the same derived view.
- Inject dependencies like `known_agents` to keep parser logic unit-testable without DB setup.
- Parse all speaker markers in transcript rows with `finditer`, not just the leading prefix.
- Use deterministic intra-row cue spacing to preserve order while avoiding timestamp collisions.
- Pin verifier commands to `.venv/bin/pytest` so `/bin/sh`, local runs, and CI behave consistently.

## Recurring Anti-Patterns
- Falling back to `participants[0]` when explicit speaker markers are available.
- Treating inline multi-speaker transcript rows as single utterances.
- Cue spacing may still be too tight for real TTS clip durations.
- Environment/PATH assumptions caused repeated retries.
- The learning artifacts appear polluted with repeated stale issue-478 diffs, reducing confidence in issue-specific summaries.

## Recommendations
- Update implement prompts to require a shared source-of-truth module when an acceptance criterion says two outputs “must not drift.”
- Add a verifier pre-check that confirms `.venv/bin/python` and `.venv/bin/pytest` exist before running tests.
- Add regression tests for malformed speaker prefixes, multiple `[name]:` segments per row, unknown agents, and timestamp ordering.
- Add an audio-aware cue spacing follow-up: compute cue offsets from clip duration where possible instead of a fixed `0.5s` window.
- Fix the learning collector to strip diffs from per-issue summaries and prevent prior issue learnings from being copied into later issues.

## Metrics
| Metric | Value |
|--------|-------|
| Issues processed | 3 |
| Success rate | 100% |
| Avg duration | 1841s |
| Total duration | 92 min |
tokens used
38,280
# Session Summary: session/epic-475-epic-post-468-qa-simulation-exports-must-look-like-the-live-office

## Overview
- The session completed 3 video/export QA issues successfully, centered on making replay cues consistent with audio stitching and live-office rendering behavior. The strongest outcome was consolidating cue derivation into one shared, testable parser path instead of maintaining parallel implementations.

## Recurring Patterns
- Extract shared pure builders when multiple consumers need the same derived view.
- Inject dependencies like `known_agents` to keep parser logic unit-testable without DB setup.
- Parse all speaker markers in transcript rows with `finditer`, not just the leading prefix.
- Use deterministic intra-row cue spacing to preserve order while avoiding timestamp collisions.
- Pin verifier commands to `.venv/bin/pytest` so `/bin/sh`, local runs, and CI behave consistently.

## Recurring Anti-Patterns
- Falling back to `participants[0]` when explicit speaker markers are available.
- Treating inline multi-speaker transcript rows as single utterances.
- Cue spacing may still be too tight for real TTS clip durations.
- Environment/PATH assumptions caused repeated retries.
- The learning artifacts appear polluted with repeated stale issue-478 diffs, reducing confidence in issue-specific summaries.

## Recommendations
- Update implement prompts to require a shared source-of-truth module when an acceptance criterion says two outputs “must not drift.”
- Add a verifier pre-check that confirms `.venv/bin/python` and `.venv/bin/pytest` exist before running tests.
- Add regression tests for malformed speaker prefixes, multiple `[name]:` segments per row, unknown agents, and timestamp ordering.
- Add an audio-aware cue spacing follow-up: compute cue offsets from clip duration where possible instead of a fixed `0.5s` window.
- Fix the learning collector to strip diffs from per-issue summaries and prevent prior issue learnings from being copied into later issues.

## Metrics
| Metric | Value |
|--------|-------|
| Issues processed | 3 |
| Success rate | 100% |
| Avg duration | 1841s |
| Total duration | 92 min |

# E13-1 Capture Prototype

> Issue: E13-1 ([#609](https://github.com/bradtaylorsf/livestreamtoagi/issues/609)).
> Plan: [E13 in the Minecraft pivot plan](../MINECRAFT-PIVOT-ISSUE-PLAN.md).
> Decision: [0006 - Minecraft Video Capture](../decisions/0006-video-capture.md).
> Script: `scripts/livestream/capture-prototype.sh`.

Repository path for the binding capture decision:
`docs/decisions/0006-video-capture.md`.

Production capture remains: real Minecraft Java client + OBS.

This is a throwaway spike that proves the local E2 Minecraft world can be seen
as a video frame source. It starts a separate camera bot named `CameraSpike`,
opens the bot's Prismarine Viewer page on localhost, and records a short MP4
with `ffmpeg`.

The goal is a local evidence clip, not a production streaming service.

## What this is

- A quick E13 de-risking path after E1-R6 and E2-1.
- A localhost-only camera view of the E2 Paper `1.21.6` world.
- A diagnostic/fallback capture path using Mineflayer plus Prismarine Viewer.
- A way to record a short MP4 under `videos/livestream/` for issue/PR evidence.

## What this is not

- Not streaming to Twitch, YouTube, or RTMP. That is E13-2.
- Not the production capture method. Decision 0006 chooses a real Minecraft Java
  client plus OBS for production.
- Not an agent. `CameraSpike` has no personality, no memory, no LLM model, and
  should only move or view as a camera.
- Not overlays, audio, monitoring, resilience, or a kill path. Those are later
  E13 issues.

## Prerequisites

| You need | Why | Check it |
|---|---|---|
| E2 Paper server running | The camera needs a live world. | `scripts/minecraft/start-server.sh`; wait for `Done (` in the server console. |
| `CameraSpike` allowed to join | E2 defaults to `white-list=true`. | In the server console: `whitelist add CameraSpike`, or restart local dev with `WHITELIST=false`. |
| Node 20 or newer | Runs the Mineflayer camera bot. | `node -v` shows `v20...` or newer. |
| Native build tools for `canvas` | Prismarine Viewer imports `canvas` at startup. | macOS: Xcode Command Line Tools. Debian/Ubuntu: `build-essential libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev`. |
| `ffmpeg` and `ffprobe` | Records and validates the MP4. | `ffmpeg -version` and `ffprobe -version`. |
| Playwright Chromium | Opens the viewer page for display capture. | `make render-install`. |
| macOS screen recording permission, or Linux X11 display | Lets `ffmpeg` capture the browser window. | macOS: grant Terminal screen recording permission if prompted. Linux: `DISPLAY` must be set. |

## Run it

From the repository root:

```bash
scripts/minecraft/start-server.sh
```

In the E2 server console, allow the camera if the whitelist is enabled:

```text
whitelist add CameraSpike
```

In another terminal:

```bash
scripts/livestream/capture-prototype.sh --duration 15
```

Optional output path:

```bash
scripts/livestream/capture-prototype.sh --duration 15 --out videos/livestream/e13-1-local.mp4
```

Preview without launching anything:

```bash
scripts/livestream/capture-prototype.sh --dry-run
```

## Expected output

The script prints:

- the E2 target: `127.0.0.1:25565`, auth `offline`, Minecraft `1.21.6`;
- the viewer URL, normally `http://127.0.0.1:3007`;
- the final MP4 path;
- file size, duration, and the `ffprobe` video stream summary.

It exits `0` only after `ffprobe` confirms a video stream in the output file.
Missing dependencies or an unreachable E2 server exit `2`.

On a headless machine with no usable display capture path, the script writes a
short `ffmpeg` `testsrc2` pattern artifact and exits `3`. That is an explicit
skipped live-world capture, not acceptance evidence.

## Acceptance evidence to record

For the issue or PR, record:

- the command run, for example
  `scripts/livestream/capture-prototype.sh --duration 15 --out videos/livestream/e13-1-local.mp4`;
- that it ran against the local Mac E2 server on `127.0.0.1:25565`;
- whether the camera used `CameraSpike` with `whitelist add CameraSpike` or
  `WHITELIST=false`;
- the generated MP4 path, file size, duration, and whether it shows the live E2
  world rather than the `testsrc2` fallback.

## Local LM Studio validation

This issue has no LLM runtime path. The camera client is not an agent, does not
call Mindcraft's model router, and consumes zero model spend. Do not use
OpenRouter for this spike.

Still record local validation posture for the pivot:

```bash
pnpm llm:local --list-only
# or
.venv/bin/python scripts/check_local_llm.py --list-only
```

For this issue, the nearest local smoke path is:

```bash
pnpm verify:livestream-capture
scripts/livestream/capture-prototype.sh --duration 15
```

Record the LM Studio model IDs that were listed, or state that LM Studio was not
reachable on the local Mac server when you ran the check. No model ID is passed
to `capture-prototype.sh`.

## Documented limitations

- Prismarine Viewer is diagnostic/fallback only. Decision 0006 keeps production
  on a real Minecraft Java client plus OBS.
- Prismarine Viewer has known `1.21.5+` rendering risk:
  https://github.com/PrismarineJS/prismarine-viewer/issues/473.
- No audio is captured. Audio/TTS belongs to E13-4.
- No overlays are composed into the clip. Stream overlays belong to E13-3.
- No resilience, restart loop, stream health, or process supervision is built
  here. That belongs to E13-5 and E13-7.
- No stream kill path is wired. That belongs to E13-6.
- The macOS path uses `ffmpeg -f avfoundation` and may require Screen Recording
  permission. Linux support expects X11 through `-f x11grab`; Wayland/headless
  boxes will usually hit the explicit skipped fallback.
- The camera is a single fixed viewer. Subject selection and camera automation
  are future work.
- The script installs prototype Node dependencies under `scripts/livestream/`
  and includes Prismarine Viewer's runtime `canvas` dependency. It intentionally
  does not modify `core/`, `frontend/`, `website/`, or the bridge contract.

# E13-2 Encoder + RTMP Push

> Issue: E13-2 ([#610](https://github.com/bradtaylorsf/livestreamtoagi/issues/610)).
> Plan: [E13 in the Minecraft pivot plan](../MINECRAFT-PIVOT-ISSUE-PLAN.md).
> Decision: [0006 - Minecraft Video Capture](../decisions/0006-video-capture.md).
> Script: `scripts/livestream/stream-push.sh`.

This script is the first RTMP push path for the Minecraft pivot livestream. It
encodes the active capture source with `ffmpeg` and pushes one stream to Twitch,
YouTube, or both with the `tee` muxer.

Production capture is still the accepted Decision 0006 path: a real Minecraft
Java client plus OBS. For local E13 testing, the source can be the E13-1
Prismarine Viewer or an already-open Minecraft/OBS display source.

## Environment

Store real keys only in a private `.env` or host secret store. Leave
`.env.example` blank.

| Variable | Required | Default | Notes |
|---|---:|---|---|
| `TWITCH_STREAM_KEY` | Twitch pushes | none | Twitch stream key. Never commit it. |
| `YOUTUBE_STREAM_KEY` | YouTube pushes | none | YouTube stream key. Never commit it. |
| `TWITCH_RTMP_URL` | no | `rtmp://live.twitch.tv/app` | Override only for alternate ingest. |
| `YOUTUBE_RTMP_URL` | no | `rtmp://a.rtmp.youtube.com/live2` | Override only for alternate ingest. |
| `RTMP_SMOKE_URL` | no | none | Optional local/test RTMP endpoint for `--smoke`. |
| `STREAM_OUTPUT_FILE` | no | none | Optional local FLV output path instead of RTMP. |
| `TTS_AUDIO_FIFO` | `--with-tts` | `/tmp/livestream_tts.fifo` | PCM FIFO produced by the TTS stream bridge. |
| `TTS_AUDIO_VOLUME` | no | `1.0` | Volume multiplier for mixed live TTS audio. |

Useful capture/encode overrides:

```bash
CAPTURE_WIDTH=1920
CAPTURE_HEIGHT=1080
CAPTURE_FPS=30
STREAM_VIDEO_BITRATE=6000k
AVFOUNDATION_INPUT="Capture screen 0:none"  # macOS
STREAM_X11_DISPLAY=:0.0                     # Linux X11
```

## Prerequisites

- A live capture source on the local display: the E13-1 camera/viewer path,
  a Minecraft Java client, or OBS.
- `ffmpeg` and `ffprobe` on `PATH`.
- The E2 Minecraft server reachable at `MC_HOST:MC_PORT` for the default
  capture preflight. Use `SKIP_CAPTURE_PREFLIGHT=1` only when intentionally
  streaming an already-open non-Minecraft test source.
- Test/private broadcast destinations in Twitch and YouTube Studio.

## Commands

Preview the ffmpeg command without connecting anywhere:

```bash
TWITCH_STREAM_KEY=dummy YOUTUBE_STREAM_KEY=dummy \
  scripts/livestream/stream-push.sh --dry-run
```

Run a 60-second Twitch-only test:

```bash
TWITCH_STREAM_KEY="$TWITCH_STREAM_KEY" \
  scripts/livestream/stream-push.sh --twitch-only --duration 60
```

Run a 60-second YouTube-only test:

```bash
YOUTUBE_STREAM_KEY="$YOUTUBE_STREAM_KEY" \
  scripts/livestream/stream-push.sh --youtube-only --duration 60
```

Run both platforms concurrently:

```bash
TWITCH_STREAM_KEY="$TWITCH_STREAM_KEY" YOUTUBE_STREAM_KEY="$YOUTUBE_STREAM_KEY" \
  scripts/livestream/stream-push.sh --duration 60
```

Run the offline-safe smoke command contract:

```bash
scripts/livestream/stream-push.sh --smoke --dry-run
```

Write a local FLV for smoke or TTS verification:

```bash
scripts/livestream/stream-push.sh --smoke --output-file /tmp/stream_smoke.flv
```

Push the smoke pattern to a local/test RTMP endpoint:

```bash
RTMP_SMOKE_URL=rtmp://127.0.0.1/live/test \
  scripts/livestream/stream-push.sh --smoke --duration 10
```

Mix live agent voices into the stream:

```bash
TTS_AUDIO_FIFO=/tmp/livestream_tts.fifo \
  scripts/livestream/stream-push.sh --with-tts --duration 60
```

The TTS FIFO is created and fed by the backend bridge documented in
[audio-tts.md](audio-tts.md).

## Acceptance Procedure

1. Start the E2 Minecraft server:

   ```bash
   scripts/minecraft/start-server.sh
   ```

2. Start the chosen E13-1 capture source and make sure it is visible on the
   display being captured.

3. Create private/test broadcast targets:
   - Twitch: use Twitch Inspector or a private test channel workflow and copy
     the stream key into `TWITCH_STREAM_KEY`.
   - YouTube: create a test/unlisted stream in YouTube Studio and copy the
     stream key into `YOUTUBE_STREAM_KEY`.

4. Start the push:

   ```bash
   TWITCH_STREAM_KEY="$TWITCH_STREAM_KEY" YOUTUBE_STREAM_KEY="$YOUTUBE_STREAM_KEY" \
     scripts/livestream/stream-push.sh --duration 60
   ```

5. Confirm both platform previews show `Live` and display the Minecraft capture
   source, not the `testsrc2` smoke pattern.

6. Record the command, platform preview result, selected model-independent smoke
   evidence, and any host-specific capture details in the issue/PR.

## Local LM Studio Validation

This issue has no LLM runtime path. The encoder invokes `ffmpeg` and does not
call Mindcraft model routing, OpenRouter, or LM Studio.

Still record the pivot posture:

```bash
pnpm llm:local --list-only
# or
.venv/bin/python scripts/check_local_llm.py --list-only
```

The nearest local smoke path is:

```bash
scripts/livestream/stream-push.sh --smoke --dry-run
```

Record the LM Studio model IDs that were listed, or state that LM Studio was not
reachable on the local Mac server. No model ID is passed to
`stream-push.sh`.

## Notes

- Dry-run output redacts stream keys. It still prints the selected ingest URLs
  so target selection can be reviewed without leaking secrets.
- `--smoke` uses `testsrc2` video and `sine` audio. If `RTMP_SMOKE_URL` is not
  set, the script only validates and prints the command.
- `--with-tts` mixes live PCM from `TTS_AUDIO_FIFO` into the AAC output. See
  [audio-tts.md](audio-tts.md) for the `tts_play` -> FIFO -> `ffmpeg` path.
- Missing selected stream keys exit `2`; an `ffmpeg` capture/encode/push failure
  exits `3`.
- Overlays, resilience, kill-switch integration, and stream health monitoring
  are handled by later E13 issues.

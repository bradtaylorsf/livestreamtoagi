# Livestream Ops Runbook

This is the plain-language runbook for operating the Minecraft livestream day
to day. It consolidates the E13-1 through E13-7 deep-dives into one place:
start the stream, stop it, rotate stream keys, recover from capture/encoder/RTMP
failure, trigger the kill path, check health, and tail logs.

Run commands from the repository root unless a command explicitly uses a
system path. Keep real stream keys in a private `.env` file or host secret
file; never paste them into commits, issues, logs, or screenshots.

> **Issue:** E13-8 ([#616](https://github.com/bradtaylorsf/livestreamtoagi/issues/616)).
> This doc adds no new runtime tooling. It references the scripts, services,
> and environment variables introduced by E13-1 through E13-7.

> **Status (2026-05-21):** E13-1 through E13-7 (#609–#615) did not land in
> this session, so the `scripts/livestream/` helpers, the
> `livestream.service` unit, the deep-dive docs under `docs/livestream/`,
> the `core/notifications/stream_alert.py` module, and the
> `/api/admin/kill` livestream wiring referenced below **do not yet exist
> in the repository**. Treat this runbook as the planned operator interface
> for the livestream pipeline. Do not paste the commands into a production
> host until the upstream issues are merged; until then, they will fail
> with "command not found", "No such file or directory", or HTTP 404.

## When to use which doc

This runbook is the fast path for operators. Use the deep-dive docs when you
are setting up a host, changing integration details, or troubleshooting beyond
the common gotcha listed here.

| Operation | Deep-dive doc | Read it when |
| --- | --- | --- |
| Capture the Minecraft world | [capture-prototype.md](./capture-prototype.md) (E13-1) | Proving the camera/viewer source or collecting a local evidence clip. |
| Encode and push RTMP | [encoder-rtmp.md](./encoder-rtmp.md) (E13-2) | Changing ffmpeg input, RTMP targets, bitrate, or platform stream keys. |
| Show stream overlays | [stream-overlay.md](./stream-overlay.md) (E13-3) | Wiring the OBS browser source or debugging agent/status labels. |
| Route TTS audio | [audio-tts.md](./audio-tts.md) (E13-4) | Enabling live agent voices or debugging the TTS FIFO. |
| Auto-recover the stream | [resilience.md](./resilience.md) (E13-5) | Installing systemd, using the portable supervisor, or reading outage gaps. |
| Cut to a safe public state | [kill-path.md](./kill-path.md) (E13-6) | Changing holding-card vs cut mode or testing the kill-switch path. |
| Monitor stream health | [monitoring.md](./monitoring.md) (E13-7) | Alerting on stream-down, black-frame, or silence failures. |

## Quick reference

Production rows assume the Linux 24/7 host uses
`scripts/livestream/livestream.service`. Local/dev alternatives are in the
sections below.

| Operation | Copy-paste command | What it does | The one gotcha |
| --- | --- | --- | --- |
| **Start stream** | `sudo systemctl enable --now livestream` | Starts the supervised capture/encoder/RTMP pipeline and enables it after reboot. | Edit the unit's `User=`, `WorkingDirectory=`, and stream-key environment before installing it. |
| **Stop stream** | `sudo systemctl stop livestream` | Stops the stream intentionally; systemd will not restart it. | Do not kill only the ffmpeg child unless you want the supervisor to treat it as a crash. |
| **Rotate Twitch/YouTube stream keys** | `sudoedit /etc/livestreamtoagi/livestream.env && sudo systemctl restart livestream` | Replaces private stream keys in the host secret file and reconnects RTMP. | Never commit keys; dry-run output redacts keys, but shell history may not. |
| **Recover capture/encoder/RTMP failure** | `sudo systemctl reset-failed livestream && sudo systemctl restart livestream` | Clears a crash-loop hold and restarts the pipeline after fixing config. | If the bad key/source is still bad, the crash-loop guard will trip again. |
| **Kill public stream** | `curl -fsS -X POST "http://127.0.0.1:8010/api/admin/kill?ttl=14400" -H "X-Kill-Switch-Key: $KILL_SWITCH_API_KEY"` | Activates the global kill switch; the livestream monitor enters safe state on the next poll. | Requires `KILL_SWITCH_API_KEY`, Redis, and `LIVESTREAM_ENABLED=true` on the backend. |
| **Health check** | `python scripts/livestream/monitor-stream-health.py --self-test` | Verifies the health monitor can detect stream-down, black-frame, and silence and emit console alerts. | A live monitor needs an FFmpeg-readable `STREAM_SOURCE_URL`; the ingest URL is not always readable. |
| **Tail logs** | `journalctl -u livestream -f` | Follows production stream supervisor logs. | Portable/dev runs log to `logs/livestream/` instead of the journal. |

## Start Stream

**What it does.** A production start launches the E13-2 `stream-push.sh`
pipeline under the E13-5 systemd supervisor. The supervised child owns capture,
ffmpeg encoding, RTMP push, and optional TTS input. systemd owns restart after
crashes and reboot persistence.

Before starting production, make sure the host secret file or systemd unit has
the stream input and target set. The generic E13-2 encoder path uses:

```bash
VIDEO_INPUT_FORMAT=avfoundation
VIDEO_INPUT="1:none"
RTMP_URL=rtmp://live.twitch.tv/app
RTMP_STREAM_KEY=<private-stream-key>
```

The platform-specific E13-2 path uses `TWITCH_STREAM_KEY` and
`YOUTUBE_STREAM_KEY` instead.

**Production commands.**

```bash
# One-time install on the Linux stream host after editing the unit's EDIT lines:
sudo cp scripts/livestream/livestream.service /etc/systemd/system/livestream.service
sudo systemctl daemon-reload

# Start now and start again after host reboot:
sudo systemctl enable --now livestream

# Follow startup:
journalctl -u livestream -f
```

**Local/dev commands.**

```bash
# Start the Minecraft server if the capture source needs the local E2 world:
scripts/minecraft/start-server.sh

# Optional: start the diagnostic E13-1 capture prototype:
scripts/livestream/capture-prototype.sh --duration 15

# Optional: serve the OBS browser overlay:
scripts/livestream/serve-overlay.sh

# Optional: start backend TTS FIFO output:
TTS_STREAM_ENABLED=1 \
TTS_STREAM_FIFO=/tmp/livestream_tts.fifo \
.venv/bin/uvicorn core.main:app --port 8010

# Start the stream under the portable supervisor:
scripts/livestream/supervise-stream.sh
```

**Expected output.**

- `systemctl status livestream` reports `active (running)`.
- `journalctl -u livestream -f` shows the `stream-push.sh` ffmpeg startup.
- Portable runs write `supervisor-started`, `starting-child`, and child logs
  under `logs/livestream/`.
- Platform dashboards show a private/test stream receiving the Minecraft
  capture source.

**Most common gotcha.** Start the supervisor, not a detached ffmpeg command. A
bare `scripts/livestream/stream-push.sh` can stream, but it will not come back
after a capture/encoder/RTMP crash.

## Stop Stream

**What it does.** An intentional stop tells the supervisor to stop and stay
stopped. This is different from a crash: the auto-restart path should not fight
an operator-requested stop.

**Production command.**

```bash
sudo systemctl stop livestream
systemctl status livestream
```

**Portable/dev command.**

```bash
# Stop the supervisor process, not just the ffmpeg child:
kill "$(pgrep -f 'scripts/livestream/supervise-stream.sh')"
```

**Expected output.**

- systemd reports `inactive (dead)`.
- Portable logs include `stop-requested reason=operator`,
  `child-stopped ... reason=operator-stop`, and `supervisor-exited status=clean`.

**Most common gotcha.** Killing only the child PID from
`logs/livestream/supervise-stream-child.pid` simulates a crash. The supervisor
will restart the stream after `RESTART_DELAY` instead of staying down.

## Rotate Stream Keys

**What it does.** Key rotation replaces the private Twitch/YouTube RTMP stream
key(s), then restarts the stream so ffmpeg reconnects with the new credentials.
The keys belong in the host secret file or private `.env`, not in source.

**Production command.**

```bash
# Edit the host secret file that livestream.service reads through EnvironmentFile=.
sudoedit /etc/livestreamtoagi/livestream.env

# Restart after saving the new key values:
sudo systemctl restart livestream
journalctl -u livestream -n 80 --no-pager
```

Use the variable names owned by the installed E13-2 encoder path:

```bash
# Platform-specific E13-2 environment:
TWITCH_STREAM_KEY=<new-twitch-key>
YOUTUBE_STREAM_KEY=<new-youtube-key>
TWITCH_RTMP_URL=rtmp://live.twitch.tv/app
YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2
```

If the host is using the generic `stream-push.sh` RTMP interface, rotate the
single target at a time:

```bash
RTMP_URL=rtmp://live.twitch.tv/app
RTMP_STREAM_KEY=<new-twitch-key>
```

```bash
RTMP_URL=rtmp://a.rtmp.youtube.com/live2
RTMP_STREAM_KEY=<new-youtube-key>
```

**Expected output.**

- `journalctl` shows the old ffmpeg process stop and a new one start.
- Dry-run review redacts `RTMP_STREAM_KEY`:

  ```bash
  RTMP_URL=rtmp://live.twitch.tv/app RTMP_STREAM_KEY=dummy \
    scripts/livestream/stream-push.sh --dry-run
  ```

- Twitch/YouTube Studio shows the new incoming connection after the restart.

**Most common gotcha.** Stream keys can leak through shell history, terminal
scrollback, and copied logs. Prefer `sudoedit` of an environment file or a host
secret store over exporting real values inline.

## Recover After Failure

**What it does.** Recovery gets the capture/encoder/RTMP pipeline back after
the supervisor could not do it automatically, usually because the crash-loop
guard stopped retries after repeated bad launches.

**Production commands.**

```bash
systemctl status livestream
journalctl -u livestream -n 120 --no-pager

# After fixing the source/key/network problem:
sudo systemctl reset-failed livestream
sudo systemctl restart livestream
journalctl -u livestream -f
```

**Portable/dev commands.**

```bash
tail -n 120 logs/livestream/livestream-supervisor.log
tail -n 120 logs/livestream/livestream-child.log

# After fixing the source/key/network problem:
scripts/livestream/supervise-stream.sh
```

To test that recovery still works, kill the supervised child, not the
supervisor:

```bash
kill "$(cat logs/livestream/supervise-stream-child.pid)"
tail -f logs/livestream/livestream-supervisor.log
```

**Expected output.**

- systemd restarts after about 10 seconds plus ffmpeg/RTMP connect time.
- Portable logs show `child-exited`, then `restarting ... gap_seconds=...`.
- The platform dashboard returns to live video after the reconnect.

**Most common gotcha.** Restarting without fixing the root cause only burns
through the crash-loop limit again. Check the child log first for missing
`VIDEO_INPUT`, bad `RTMP_URL`, bad key, FFmpeg failure, or network failure.

## Kill Stream

**What it does.** The kill command activates the global Redis `kill_switch`
key. When `LIVESTREAM_ENABLED=true`, the FastAPI kill-switch monitor polls that
key and puts the public stream into the configured safe state:
`holding_card` or `cut`.

**Backend configuration.**

```bash
KILL_SWITCH_API_KEY=<private-operator-key>
LIVESTREAM_ENABLED=true
LIVESTREAM_KILL_MODE=holding_card
LIVESTREAM_HOLDING_CARD=/opt/livestreamtoagi/assets/holding-card.png
LIVESTREAM_SAFE_TRANSITION_SECONDS=0
```

Use `LIVESTREAM_KILL_MODE=cut` only when the intended emergency action is to
terminate the RTMP push.

**Activate.**

```bash
curl -fsS -X POST "http://127.0.0.1:8010/api/admin/kill?ttl=14400" \
  -H "X-Kill-Switch-Key: $KILL_SWITCH_API_KEY"
```

**Deactivate after the incident is resolved.**

```bash
curl -fsS -X DELETE "http://127.0.0.1:8010/api/admin/kill" \
  -H "X-Kill-Switch-Key: $KILL_SWITCH_API_KEY"
```

**Expected output.**

- Activate returns `{"status":"active","ttl_seconds":14400}`.
- Deactivate returns `{"status":"deactivated"}`.
- Backend logs include `livestream.kill_switch.observed` and a safe-state
  transition. Redis lookup failure is fail-closed and treated as active.

**Most common gotcha.** The admin route can activate the key even if the stream
controller is still the logging-only `NullStreamController`. For a real public
cut, E13-6 must be wired to an RTMP controller or holding-card switch on the
stream host.

## Health Check

**What it does.** The health monitor watches three failure modes:
stream process down, black frames, and silence. Alerts go through
`core/notifications/stream_alert.py`; local validation can use console email.

**Offline-safe self-test.**

```bash
EMAIL_PROVIDER=console \
python scripts/livestream/monitor-stream-health.py --self-test
```

**Live monitor command.**

```bash
EMAIL_PROVIDER=console \
STREAM_ALERT_EMAIL=ops@example.com \
STREAM_SOURCE_URL=rtmp://127.0.0.1/live/stream \
SUPERVISOR_LOG=logs/livestream/livestream-supervisor.log \
CHILD_PID_FILE=logs/livestream/supervise-stream-child.pid \
python scripts/livestream/monitor-stream-health.py
```

Useful thresholds:

```bash
STREAM_HEALTH_DOWN_THRESHOLD_SECONDS=30
STREAM_HEALTH_BLACK_SECONDS=5
STREAM_HEALTH_SILENCE_SECONDS=10
STREAM_HEALTH_POLL_INTERVAL=15
STREAM_HEALTH_ALERT_COOLDOWN_SECONDS=300
```

**Expected output.**

- Self-test prints `livestream health self-test passed: stream_down, black_frame, silence`.
- Console alerts appear in `${EMAIL_CONSOLE_LOG:-/tmp/livestream-agi-emails.jsonl}`.
- Live monitor emits one alert per failure type, then recovered alerts when the
  stream returns.

**Most common gotcha.** `STREAM_SOURCE_URL` must be readable by FFmpeg for
black-frame and silence probes. A platform ingest URL with a secret stream key
may accept pushes but not provide a readable playback stream.

## Tail Logs

**What it does.** Logs answer two questions: is the supervisor running, and why
did the child stream process exit?

**Production commands.**

```bash
systemctl status livestream
journalctl -u livestream -f
journalctl -u livestream -n 120 --no-pager
```

**Portable/dev commands.**

```bash
tail -f logs/livestream/livestream-supervisor.log
tail -f logs/livestream/livestream-child.log
tail -f "${EMAIL_CONSOLE_LOG:-/tmp/livestream-agi-emails.jsonl}"
```

**Expected output.**

- Supervisor logs show lifecycle lines such as `starting-child`,
  `child-exited`, `restarting`, and `crash-loop-abort`.
- Child logs show ffmpeg/capture/RTMP errors.
- Console email logs show `[stream-alert] stream_down`, `[stream-alert]
  black_frame`, `[stream-alert] silence`, and recovery messages.

**Most common gotcha.** `livestream-child.log` can contain ffmpeg output with
paths, URLs, and host-specific details. Do not paste raw logs publicly until
you have checked that stream keys are absent.

## Local LM Studio Validation

This issue has no LLM runtime path. It is documentation-only and does not call
Mindcraft model routing, OpenRouter, LM Studio, or any model provider.

Record local-model posture separately for the pivot:

```bash
.venv/bin/python scripts/check_local_llm.py --list-only
```

The nearest local smoke path for this docs-only issue is the service preflight
plus the local model reachability check:

```bash
bash scripts/check-services.sh
.venv/bin/python scripts/check_local_llm.py --list-only
```

If LM Studio is not reachable on the local Mac server, record that result.
Do not spend OpenRouter credits for this runbook.

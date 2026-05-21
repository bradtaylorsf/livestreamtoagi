# Livestream health monitoring

Issue: E13-7 / #615.

The stream health monitor watches the 24/7 livestream from three angles:

- `stream_down`: the supervised capture/encoder process has exited, its PID is
  stale, or no restart has appeared within the configured threshold.
- `black_frame`: FFmpeg `blackdetect` sees a black frame window at least as long
  as `STREAM_HEALTH_BLACK_SECONDS`.
- `silence`: FFmpeg `silencedetect` sees silence at least as long as
  `STREAM_HEALTH_SILENCE_SECONDS`.

Alerts are sent through `core/notifications/stream_alert.py`, which uses the
same email provider switch as other notification mail. For local validation,
set `EMAIL_PROVIDER=console` and inspect `EMAIL_CONSOLE_LOG`.

## Command

```bash
EMAIL_PROVIDER=console \
STREAM_ALERT_EMAIL=ops@example.com \
STREAM_SOURCE_URL=rtmp://127.0.0.1/live/stream \
python scripts/livestream/monitor-stream-health.py
```

The local induced-outage acceptance path does not need a real FFmpeg stream:

```bash
python scripts/livestream/monitor-stream-health.py --self-test
```

The self-test creates a stale supervisor log, stubs the FFmpeg probe output for
black frames and silence, sends alerts through the console email provider, and
fails non-zero unless exactly one alert is produced for `stream_down`,
`black_frame`, and `silence`.

## Environment

Required for alert delivery:

- `STREAM_ALERT_EMAIL`: recipient for stream health alerts. If unset, alerts are
  skipped with `no_recipient`.

Required for black-frame and silence detection:

- `STREAM_SOURCE_URL`: FFmpeg-readable stream URL. If unset, the monitor still
  checks the supervisor/PID path but disables video/audio probes.

Supervisor/PID inputs:

- `SUPERVISOR_LOG`: retained supervisor log path. Default:
  `logs/livestream/livestream-supervisor.log`.
- `CHILD_PID_FILE`: supervised stream child PID file. Default:
  `logs/livestream/livestream-child.pid`.

Thresholds and intervals:

- `STREAM_HEALTH_DOWN_THRESHOLD_SECONDS`: default `30`.
- `STREAM_HEALTH_BLACK_SECONDS`: default `5`.
- `STREAM_HEALTH_SILENCE_SECONDS`: default `10`.
- `STREAM_HEALTH_POLL_INTERVAL`: default `15`.
- `STREAM_HEALTH_ALERT_COOLDOWN_SECONDS`: default `300`.

Optional probe tuning:

- `STREAM_HEALTH_FFMPEG_PATH`: default `ffmpeg`.
- `STREAM_HEALTH_PROBE_WINDOW_SECONDS`: default is the larger black/silence
  threshold plus 2 seconds.
- `STREAM_HEALTH_PROBE_TIMEOUT_SECONDS`: default is the larger of 30 seconds or
  probe window plus 10 seconds.
- `STREAM_HEALTH_DOWN_INTERVAL_SECONDS`,
  `STREAM_HEALTH_BLACK_INTERVAL_SECONDS`, and
  `STREAM_HEALTH_SILENCE_INTERVAL_SECONDS`: per-detector overrides. Defaults to
  `STREAM_HEALTH_POLL_INTERVAL`.

## Systemd example

Run this beside the livestream supervisor on the capture host:

```ini
[Unit]
Description=Livestream health monitor
After=network-online.target livestream.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/livestreamtoagi
EnvironmentFile=/opt/livestreamtoagi/.env
ExecStart=/opt/livestreamtoagi/.venv/bin/python /opt/livestreamtoagi/scripts/livestream/monitor-stream-health.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Induced-outage acceptance

1. Confirm console email capture:

   ```bash
   EMAIL_PROVIDER=console python scripts/livestream/monitor-stream-health.py --self-test
   ```

2. On a live capture host, start the monitor with `STREAM_SOURCE_URL`,
   `SUPERVISOR_LOG`, `CHILD_PID_FILE`, and `STREAM_ALERT_EMAIL` set.
3. Kill or stop the supervised capture/encoder child.
4. Confirm a `[stream-alert] stream_down` email appears.
5. Point `STREAM_SOURCE_URL` at a test black-frame source and confirm
   `[stream-alert] black_frame`.
6. Point `STREAM_SOURCE_URL` at a silent test source and confirm
   `[stream-alert] silence`.
7. Restore a healthy source and confirm `recovered` alerts are sent.

## LM Studio validation

This issue has no LLM runtime path. LM Studio validation is not applicable for
E13-7. Record the local Mac validation with:

```bash
python scripts/livestream/monitor-stream-health.py --self-test
```

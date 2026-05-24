# Livestream Resilience

Streams drop. The Minecraft camera can exit, ffmpeg can crash, and an RTMP
connection can disappear while nobody is awake. This layer brings the stream
pipeline back without waiting for an operator.

> **Issue:** E13-5 (epic E13). **Files:** `scripts/livestream/livestream.service`
> for the Linux 24/7 host and `scripts/livestream/supervise-stream.sh` for
> Mac/dev hosts. **Builds on:** E13-2, whose `stream-push.sh` command owns
> capture, encoding, and RTMP push.

## Non-technical summary

This is a watchdog for the stream process. If the stream command exits without
an operator asking it to stop, the watchdog records when it happened, waits a
short backoff, and starts it again. Viewers may see a brief interruption, but
the show does not stay offline until someone notices.

The supervisor does one job: restart the stream. It does not send alerts and it
does not implement the public kill switch. Those are separate E13 issues.

## Pick your path

| Host | Use | Why |
| --- | --- | --- |
| Linux 24/7 host | `scripts/livestream/livestream.service` | systemd already restarts crashed foreground services, survives host reboots, and retains logs in the journal. |
| Mac/dev/local validation host | `scripts/livestream/supervise-stream.sh` | Portable bash supervisor with no ffmpeg or network dependency in `--self-test` mode. |

Both paths supervise the E13-2 stream command as a foreground process. The
stream command must exit non-zero if capture, encode, or RTMP push fails; then
the supervisor can restart the whole pipeline.

## Restart window

The documented auto-recovery window is **about 10 seconds plus ffmpeg/RTMP
connect time**.

- systemd waits `RestartSec=10` before it starts `stream-push.sh` again.
- `supervise-stream.sh` waits `RESTART_DELAY=10` by default before it starts
  `STREAM_CMD` again.

Local self-tests lower the default delay to 1 second so CI does not wait on the
production window. Operators can tune `RestartSec=` or `RESTART_DELAY=`, but a
small delay avoids hammering the host or stream platform during a bad config.

## Crash-loop guard

Crash-loop guards stop endless restart churn when the stream is misconfigured.

- systemd: `StartLimitBurst=5` starts inside `StartLimitIntervalSec=300`.
- `supervise-stream.sh`: `CRASH_LOOP_LIMIT=5` failed launches inside
  `CRASH_LOOP_WINDOW=60`.

When the guard trips, inspect the stream logs, fix the bad capture/encoder/key
configuration, then restart the supervisor.

## Logs

The portable supervisor appends timestamped lines to `SUPERVISOR_LOG`, default:

```text
./logs/livestream/livestream-supervisor.log
```

The lines intended for outage accounting look like this:

```text
2026-05-21T12:00:00Z child-exited exit_code=137 uptime_seconds=8421
2026-05-21T12:00:10Z restarting attempt=2 gap_seconds=10
```

To estimate total supervisor-visible downtime for a period, sum every
`gap_seconds=` value on `restarting` lines in that period. That measures the
time from child exit until the supervisor attempts the next launch. RTMP
handshake time after launch is platform-dependent, so confirm resumed video in
the platform dashboard for incident notes.

The current child PID is written to `CHILD_PID_FILE`, default:

```text
./logs/livestream/supervise-stream-child.pid
```

If `SUPERVISOR_LOG` is overridden without `CHILD_PID_FILE`, the PID file is
placed beside the supervisor log.

That file exists only while the child is live. It is intended for kill/restart
probes and manual acceptance checks.

The stream command's stdout/stderr are appended to `CHILD_LOG`, default:

```text
./logs/livestream/livestream-child.log
```

If `SUPERVISOR_LOG` is overridden without `CHILD_LOG`, the child log is placed
beside the supervisor log. That keeps self-tests and verifier runs contained in
their temp directory.

Keeping child output out of the supervisor's terminal stream makes live
verification and future alerting read the structured supervisor events without
being polluted by ffmpeg or fake-command output.

## systemd path

Edit `scripts/livestream/livestream.service` on the host:

- `User=`: unprivileged stream user, never root.
- `WorkingDirectory=`: absolute repo checkout path.
- stream key env: use a host secret store or `EnvironmentFile=`.

Install and start:

```bash
sudo cp scripts/livestream/livestream.service /etc/systemd/system/livestream.service
sudo systemctl daemon-reload
sudo systemctl enable --now livestream
journalctl -u livestream -f
```

Simulate a crash:

```bash
sudo systemctl kill -s SIGKILL livestream
systemctl status livestream
journalctl -u livestream -n 50
```

Expected result: systemd relaunches the stream after about 10 seconds plus
`stream-push.sh` startup/connect time. A deliberate `sudo systemctl stop
livestream` does not restart.

## Portable path

Start the real stream under the bash supervisor:

```bash
scripts/livestream/supervise-stream.sh
```

Override the supervised command if needed:

```bash
STREAM_CMD=/opt/livestreamtoagi/scripts/livestream/stream-push.sh \
  scripts/livestream/supervise-stream.sh
```

Run the dependency-free self-test path with a fake command:

```bash
STREAM_CMD=/path/to/fake-stream.sh scripts/livestream/supervise-stream.sh --self-test
```

Stop the supervisor with Ctrl+C or `kill <supervisor-pid>`. It forwards
SIGTERM to the child and exits cleanly without another restart.

## Verification

Focused local verification:

```bash
.venv/bin/pytest tests/backend/test_livestream_resilience.py -v
```

Manual acceptance for the real stream:

1. Start the stream under systemd or `supervise-stream.sh`.
2. Kill the supervised child process, not the supervisor.
3. Confirm the stream command restarts inside the documented window.
4. Confirm video resumes on the target platform.
5. Record the relevant `child-exited` and `restarting` log lines.

## LM Studio validation

This issue has no LLM runtime path. The resilience layer supervises a stream
process around capture/ffmpeg/RTMP and does not call OpenRouter or LM Studio.

For pivot evidence, still record local LM Studio reachability:

```bash
pnpm llm:local --list-only
# or
.venv/bin/python scripts/check_local_llm.py --list-only
```

If LM Studio is not reachable on the local Mac server, record that result and
use the focused resilience pytest command above as the nearest local smoke path.

## What this does not cover

- Alerting, black-frame checks, silence checks, and platform health alerts are
  E13-7.
- The kill-switch cut to a safe state is E13-6.
- Capture/encoder/RTMP flags and stream platform key setup are E13-2.

## Cross-references

- E13 plan: `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` section 5, E13-5.
- Minecraft supervision pattern: `docs/minecraft/supervision.md`.

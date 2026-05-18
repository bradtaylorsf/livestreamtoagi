# 24/7 Supervision — Auto-restart & Crash Recovery

A 24/7 show can't have a human watching the server at 3am. This doc makes the
private Minecraft server **restart itself when it crashes**, and keeps the
logs so you can see what happened — in plain language, no ops experience
assumed.

> **Issue:** E2-4 (epic E2). **Files:** `scripts/minecraft/minecraft.service`
> (systemd unit) and `scripts/minecraft/supervise.sh` (portable supervisor).
> **Builds on:** E2-1 ([server-setup.md](./server-setup.md)) for the server
> itself and E2-3 ([hosting.md](./hosting.md)) for *where* it runs 24/7.

## Non-technical summary

Servers crash sometimes — a bad chunk, an out-of-memory blip, the host
rebooting. Without supervision the world just stays down until someone
notices. **Supervision** is a tiny watchdog that notices the crash and starts
the server again automatically, within seconds, and writes a dated line to a
log file every time it does. You set it up once and forget it.

It does **one** thing: bring the server back. It does **not** alert you,
back up the world, or check health — those are separate, later issues (see
[§ What this does NOT cover](#what-this-does-not-cover-on-purpose)).

## Pick your path

There are two supported supervisors. Pick by **where the 24/7 server runs**
(decided in [hosting.md](./hosting.md)):

| Your 24/7 host | Use | Why |
|----------------|-----|-----|
| **Linux box / VPS** (the recommended host — Ubuntu Server 24.04 LTS) | **systemd** — `scripts/minecraft/minecraft.service` | systemd is already the init system; it restarts crashed services, survives host reboots, and retains logs in the journal. This is the production path. |
| **A machine you own that has no systemd** (your Mac, the local-validation box, a dev laptop) | **`scripts/minecraft/supervise.sh`** | A dependency-free bash watchdog. No root, no install, runs anywhere bash does. Good for local 24/7 on a Mac mini and for verifying the behaviour offline. |

Both restart **only on a crash**. A deliberate stop you initiate (Ctrl+C,
`systemctl stop`, `kill`) is treated as "you meant that" and does **not**
loop. Both also have a **crash-loop guard**: if the server dies over and over
in a short window (a broken config, not a transient blip) they give up
instead of spinning forever and burning the host.

## The documented restart window

**A killed/crashed server is back within ~10 seconds**, plus the server's own
boot time:

- **systemd:** `RestartSec=10` in the unit — systemd waits 10s after a crash,
  then relaunches.
- **supervise.sh:** `RESTART_DELAY=10` (seconds) — same idea, configurable.

"Boot time" is however long Paper takes to load the world and reach its
`Done (` line; the 10s is the supervisor's own delay on top of that. Lower
the window if you want (`RestartSec=` / `RESTART_DELAY=`), but a few seconds
of backoff avoids hammering a host that's mid-problem.

Crash-loop guard (both paths): **after 5 rapid restarts the supervisor
stops trying** instead of spinning forever on a broken config. The two
paths use the same burst count (5) but a different window:

- **systemd:** `StartLimitBurst=5` within `StartLimitIntervalSec=300` —
  5 failed starts inside **5 minutes** → systemd gives up.
- **supervise.sh:** `CRASH_LOOP_LIMIT=5` within `CRASH_LOOP_WINDOW=60` —
  5 crashes inside **60 seconds** → the watchdog aborts.

(systemd's longer window is fine: a server that fails fast will trip
either guard in well under a minute; the difference only matters for a
server that limps for ~minutes between crashes.) When the guard trips,
fix the underlying problem (check the logs below), then re-enable/restart
the supervisor.

## Path A — systemd (the Linux 24/7 host)

`scripts/minecraft/minecraft.service` is a ready-to-edit unit. It runs
`scripts/minecraft/start-server.sh` in the foreground, so systemd watches the
real Paper process directly: a crash is seen instantly, and a clean stop
sends SIGTERM straight to Paper so the world is **saved before shutdown**.

1. **Edit the unit for your host.** Open
   `scripts/minecraft/minecraft.service` and change the four `EDIT` lines:
   - `User=` — the unprivileged user that owns the repo + world (never root).
   - `WorkingDirectory=` — the absolute path to your repo checkout.
   - `Environment=SERVER_DIR=` — where the world/jar should live.
   - `Environment=MEM=` — JVM heap (the recommended 24/7 value is `4G`; see
     [hosting.md](./hosting.md)).
2. **Install it:**

   ```bash
   sudo cp scripts/minecraft/minecraft.service /etc/systemd/system/minecraft.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now minecraft
   ```

   `enable --now` both starts it now **and** makes it come back after a host
   reboot.
3. **Check it's up:**

   ```bash
   systemctl status minecraft
   journalctl -u minecraft -f      # live logs; Ctrl+C to stop following
   ```
4. **Stop it deliberately** (this will NOT trigger a restart):

   ```bash
   sudo systemctl stop minecraft     # stop now
   sudo systemctl disable minecraft  # also stop coming back on reboot
   ```

## Path B — supervise.sh (a machine you own / macOS)

`scripts/minecraft/supervise.sh` is the portable watchdog. It launches
`start-server.sh`, waits for it to exit, logs the exit, waits the restart
window, and relaunches — until you stop it.

```bash
# Start supervising the real server (runs in your terminal):
scripts/minecraft/supervise.sh

# Run it in the background and detach so it survives the terminal closing:
nohup scripts/minecraft/supervise.sh > /dev/null 2>&1 &

# See the options and config knobs:
scripts/minecraft/supervise.sh --help
```

Stop it with **Ctrl+C** (foreground) or `kill <pid>` (background) — the stop
is forwarded to the server and is **not** restarted. Configuration is via
environment variables (all optional): `SERVER_DIR`, `RESTART_DELAY`,
`CRASH_LOOP_LIMIT`, `CRASH_LOOP_WINDOW`, `SUPERVISOR_LOG`, `CHILD_PID_FILE` —
`--help` lists them with defaults.

> To run it 24/7 unattended on a Mac you own, wrap it in a `launchd` agent
> (or just `nohup ... &` after login). Choosing/automating that is a host
> detail; the supervisor itself is the deliverable here.

## Where the logs live (and that they're retained)

Logs are kept so a crash at 3am is still explainable at 9am.

- **systemd path:** everything the server prints goes to the **systemd
  journal**. Read it any time:

  ```bash
  journalctl -u minecraft                 # full history
  journalctl -u minecraft -n 200          # last 200 lines
  journalctl -u minecraft --since "1 hour ago"
  ```

  Make the journal **survive reboots** (persistent, not just in-RAM):

  ```bash
  sudo mkdir -p /var/log/journal
  sudo systemctl restart systemd-journald
  ```
- **supervise.sh path:** the supervisor writes a dated line on every
  start/crash/restart/stop to `SUPERVISOR_LOG` — by default
  `<SERVER_DIR>/logs/supervisor.log`. The live server PID is written to
  `<SERVER_DIR>/logs/supervise-child.pid`.
- **Both paths:** Paper *also* keeps its own logs under
  `<SERVER_DIR>/logs/` (`latest.log` plus dated, gzipped rotations). The
  supervisor log tells you *when/why it restarted*; Paper's log tells you
  *what the server was doing* at the time.

## How to verify it works

The acceptance test is literally: **kill the server, watch it come back.**

**systemd:**

```bash
# Find and kill the running server (simulates a crash):
sudo systemctl kill -s SIGKILL minecraft
# Within RestartSec (10s) + boot time it is Active: again:
systemctl status minecraft
journalctl -u minecraft -n 20      # shows the auto-restart
```

**supervise.sh:** kill the child PID and watch the log:

```bash
kill -9 "$(cat <SERVER_DIR>/logs/supervise-child.pid)"
tail -f <SERVER_DIR>/logs/supervisor.log
# → "server exited unexpectedly ... restarting in 10s" then "starting server (attempt N)"
```

The committed, **dependency-free** check (no Java, no network — uses a fast
fake server via `supervise.sh --self-test`) runs in CI:

```bash
pnpm verify:minecraft-server
```

That runs `tests/backend/test_minecraft_supervision.py`, which statically
validates the systemd unit (`Restart=on-failure`, `RestartSec=`, `ExecStart=`
pointing at `start-server.sh`, journal logging, crash-loop guard) and proves
the supervisor restarts a killed server within the documented window while a
clean stop does **not** restart.

## What this does NOT cover (on purpose)

- **Alerting / notifications.** Supervision restarts the server silently. It
  does **not** text/email/page you when it does. Alerting is owned by
  **E11/E13** and is explicitly out of scope here.
- **Backups & restore.** A restart reloads the *existing* world; it does not
  protect the world data. That's
  [E2-5](https://github.com/bradtaylorsf/livestreamtoagi/issues/530).
- **Health checks / status endpoint.** Knowing the world is *healthy* (not
  just *running*) is [E2-6](https://github.com/bradtaylorsf/livestreamtoagi/issues/531).
- **Provisioning the host / IaC.** No Terraform/Ansible/cloud-init. Picking
  the host is E2-3 ([hosting.md](./hosting.md)); you install this unit by hand.

## Cross-references

- **E2-1 — Run the server:** [server-setup.md](./server-setup.md)
  (issue [#526](https://github.com/bradtaylorsf/livestreamtoagi/issues/526)) —
  `scripts/minecraft/start-server.sh`, the thing this supervises.
- **E2-3 — Where it runs 24/7:** [hosting.md](./hosting.md)
  (issue [#528](https://github.com/bradtaylorsf/livestreamtoagi/issues/528)) —
  the Ubuntu 24.04 host the systemd path targets and the `MEM=4G` recommendation.
- **E2-5 — Backups & restore:**
  [issue #530](https://github.com/bradtaylorsf/livestreamtoagi/issues/530).
- **E2-6 — Health check + status:**
  [issue #531](https://github.com/bradtaylorsf/livestreamtoagi/issues/531).
- **Plan:** `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` → §5, **E2-4**.

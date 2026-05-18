# Server Ops Runbook (beginner) — start / stop / backup / restore / restart / health + teardown

This is the **one page** to operate the private Minecraft server day to day.
Every operation has a copy-paste command and a plain-language "what it does".
No prior Minecraft-server or ops experience is assumed. If a command fails,
the per-operation section below tells you the one gotcha that usually explains
it.

> **Issue:** E2-7 (epic E2). **This doc adds no new scripts** — it consolidates
> the six E2 docs so an owner who doesn't play Minecraft can run the show from
> a single page, and adds the **clean teardown** procedure. Every command here
> calls tooling that already exists and is already tested by
> `pnpm verify:minecraft-server`.

## When to use which doc

This runbook is the **fast path**. Each operation has a deep-dive doc with the
beginner explainer, every option, the safety reasoning, and troubleshooting —
read it once per operation, then live here.

| Operation | Deep-dive doc | Read it when |
|-----------|---------------|--------------|
| First-time setup, Java, the EULA, connecting a client | [server-setup.md](./server-setup.md) (E2-1) | Setting the server up on a fresh machine the first time. |
| Choosing the world (seed / type / spawn) | [world-config.md](./world-config.md) (E2-2) | You want a specific or different world. |
| Where the 24/7 server lives (local vs cloud) | [hosting.md](./hosting.md) (E2-3) | Deciding the durable host and its RAM/spec. |
| Keeping it up unattended (auto-restart) | [supervision.md](./supervision.md) (E2-4) | Setting up the 3am-crash watchdog (systemd or `supervise.sh`). |
| Backups, restore, reset-to-fresh-world | [backup-restore.md](./backup-restore.md) (E2-5) | Scheduling backups or recovering/resetting a world. |
| Knowing the server is up | [health.md](./health.md) (E2-6) | Wiring an up/down check (CLI or `--json` for the brain). |

---

## Quick reference

One row per operation. Run from the **repository root**. Defaults are sane;
the gotcha column is the one thing that bites beginners — read the matching
section below before relying on it.

| Operation | Copy-paste command | What it does | The one gotcha |
|-----------|--------------------|--------------|----------------|
| **Start** | `scripts/minecraft/start-server.sh` | Installs the pinned Paper jar (once), writes the EULA + defaults, launches the server on `localhost:25565`. | For a 24/7 world use `MEM=4G scripts/minecraft/start-server.sh` (per [hosting.md](./hosting.md)). |
| **Start (preview only)** | `scripts/minecraft/start-server.sh --dry-run` | Shows the jar, resolved world config, and launch command. Downloads/launches **nothing**. | Safe to run any time; never touches an existing world. |
| **Stop** | Type `stop` in the server console (Enter) | Saves the world and shuts down cleanly. | Always prefer `stop` over `Ctrl+C`/`kill` so the world is saved. |
| **Stop (24/7 host)** | `sudo systemctl stop minecraft` | Stops the supervised server; does **not** trigger an auto-restart. | On a non-systemd host instead `kill` the `supervise.sh` PID (see Stop §). |
| **Restart / keep alive (Linux 24/7)** | `sudo systemctl enable --now minecraft` | Installs the watchdog: starts now, restarts on crash (~10s), comes back after reboot. | Edit the four `EDIT` lines in the unit first ([supervision.md](./supervision.md)). |
| **Restart / keep alive (portable)** | `nohup scripts/minecraft/supervise.sh > /dev/null 2>&1 &` | Same auto-restart on any machine with bash (Mac, dev box) — no root, no install. | A deliberate stop is **not** restarted; a crash is. |
| **Status of watchdog** | `systemctl status minecraft` / `journalctl -u minecraft -f` | Shows running/failed + live logs (systemd path). | `supervise.sh` path logs to `<SERVER_DIR>/logs/supervisor.log` instead. |
| **Backup (now)** | `scripts/minecraft/backup.sh` | Writes one dated `world-*.tar.gz` (world + Nether + End + `server.properties`) to `<SERVER_DIR>/backups/`. | A backup of a *running* server relies on autosave — see Backup §. |
| **Backup (preview / list)** | `scripts/minecraft/backup.sh --dry-run` · `scripts/minecraft/backup.sh --list` | Show what would be archived / list existing backups newest-first. | Writes nothing in either mode. |
| **Restore** | `scripts/minecraft/restore.sh --latest` (or `--list`, or `<archive>`) | Puts a prior world back; saves a `pre-restore-` safety snapshot first. | **Stop the server first** — restore refuses while it looks up. |
| **Reset to a fresh world** | `scripts/minecraft/restore.sh --reset` then `scripts/minecraft/start-server.sh` | Wipes the world + `server.properties` so the next start generates a clean one from `world.config`. | Stop first; a `pre-reset-` safety snapshot is taken. Keeps the install. |
| **Health (human)** | `scripts/minecraft/health.sh` | Prints `✓`/`✗` and exits `0` (up) / `1` (down). | Reports liveness only; it does **not** restart anything. |
| **Health (for the brain)** | `scripts/minecraft/health.sh --json` | One line of JSON: `{"up":true,"host":...,"port":...,"checked_at":...}`. | Use `--quiet` (exit code only) inside other scripts. |
| **Health (in the dev gate)** | `CHECK_MINECRAFT=1 bash scripts/check-services.sh` | Adds the Minecraft up/down check to the 5-service gate. | Opt-in: the default `check-services.sh` never checks Minecraft. |

> **Schedule the backup** (so nobody has to remember it): add the cron line or
> the systemd timer from [backup-restore.md](./backup-restore.md) — a snapshot
> every 6 hours with `BACKUP_KEEP=10` keeps ~2.5 days of history. The exact
> cron line / timer units are in that doc; this runbook deliberately doesn't
> duplicate them so there is one source of truth.

---

## Start

**What it does.** `scripts/minecraft/start-server.sh` checks you have Java 21,
creates `./minecraft-server`, downloads the pinned Paper jar **once**, writes
`eula.txt` (`eula=true`) and a default `server.properties` (only if absent),
then launches the server. It's idempotent — safe to re-run; it never clobbers
an existing world or your edited `server.properties`.

```bash
# Normal start (2 GB heap default — fine for learning):
scripts/minecraft/start-server.sh

# 24/7 start (recommended heap from hosting.md):
MEM=4G scripts/minecraft/start-server.sh

# See exactly what it WOULD do, download/launch nothing:
scripts/minecraft/start-server.sh --dry-run

# CI / verification: boot, wait for "Done (", auto-stop, exit non-zero if it never readies:
scripts/minecraft/start-server.sh --smoke
```

The server is up when the console prints `Done (12.345s)! For help, type
"help"`. First boot is slower (jar download + world generation); later boots
are quick.

> **Gotcha.** For anything left running 24/7, set `MEM=4G` (or whatever
> [hosting.md](./hosting.md) sizes for your host). The 2 GB default is a
> *learning* size and will struggle with a real long-lived world. To change
> *which* world is generated, edit `scripts/minecraft/world.config` **before
> the first start** — see [world-config.md](./world-config.md); a world's
> seed/type is baked in at first generation.

## Stop

**What it does.** A clean stop flushes and saves the world, then shuts the
process down. Always prefer it over killing the process.

```bash
# Preferred — in the server's own console, type:
stop
# (press Enter). The world is saved, then the server exits.

# Foreground server with no console input: Ctrl+C also stops it.

# On the Linux 24/7 host (systemd path) — does NOT auto-restart:
sudo systemctl stop minecraft

# On a portable supervisor (supervise.sh) host — stop the WATCHDOG itself
# (NOT the server PID — killing the server alone just makes supervise.sh
# treat it as a crash and restart it). Ctrl+C if it's in the foreground, or:
kill "$(pgrep -f 'scripts/minecraft/supervise.sh')"
#   If you launched it with `nohup ... &`, that shell printed its PID — use
#   that. The supervisor catches the signal, forwards SIGTERM to the server
#   so the world is saved, and exits WITHOUT restarting.
```

> **Gotcha.** Always prefer `stop` (or `systemctl stop` / signalling the
> supervisor) over `kill -9` of the Java process: a hard kill can lose the
> last few minutes of the world because it skips the save. A stop you
> initiate is treated as intentional and is **never** auto-restarted by the
> watchdog — only an unexpected crash is.

## Restart / keep it alive 24/7 (supervision)

**What it does.** A watchdog notices a crash and brings the server back within
~10 seconds (plus Paper's own boot time), and writes a dated line every time.
Pick the path by where the 24/7 server runs (decided in
[hosting.md](./hosting.md)); the full setup is in
[supervision.md](./supervision.md).

**Linux box / VPS — systemd (the production path):**

```bash
# After editing the four EDIT lines in scripts/minecraft/minecraft.service:
sudo cp scripts/minecraft/minecraft.service /etc/systemd/system/minecraft.service
sudo systemctl daemon-reload
sudo systemctl enable --now minecraft        # start now + come back after reboot

sudo systemctl restart minecraft             # manual restart
systemctl status minecraft                   # is it up?
journalctl -u minecraft -f                   # live logs (Ctrl+C to stop following)
```

**A machine you own without systemd (Mac mini, dev box) — `supervise.sh`:**

```bash
scripts/minecraft/supervise.sh                              # supervise in this terminal
nohup scripts/minecraft/supervise.sh > /dev/null 2>&1 &     # detached, survives logout
scripts/minecraft/supervise.sh --help                       # options + env knobs
tail -f <SERVER_DIR>/logs/supervisor.log                    # what it has done
```

> **Gotcha.** Both paths restart **only on a crash** — a stop you initiate is
> respected. Both have a **crash-loop guard** so a broken config can't spin
> forever, but the windows differ: `supervise.sh` aborts after **5 crashes in
> 60s** (`CRASH_LOOP_LIMIT`/`CRASH_LOOP_WINDOW`); systemd's unit uses
> `StartLimitBurst=5` within `StartLimitIntervalSec=300` (5 failed starts in
> **5 minutes**). When the guard trips the server stays down on purpose — fix
> the underlying problem (check the logs above), then re-enable/restart the
> watchdog.

## Backup

**What it does.** `scripts/minecraft/backup.sh` writes one dated
`world-<UTC>.tar.gz` containing the overworld + Nether + End and
`server.properties` into `<SERVER_DIR>/backups/` (git-ignored), then prunes to
the newest `BACKUP_KEEP` (default 10).

```bash
scripts/minecraft/backup.sh             # take a snapshot now
scripts/minecraft/backup.sh --dry-run   # show what WOULD be archived; write nothing
scripts/minecraft/backup.sh --list      # list existing backups, newest first
scripts/minecraft/backup.sh --help      # all options + env knobs
```

To run backups automatically every 6 hours, add the **cron line** or the
**systemd timer** from [backup-restore.md](./backup-restore.md) (pick one;
that doc is the single source for the exact units).

> **Gotcha.** A backup of a **stopped** server is always perfectly consistent.
> A backup of a **running** server relies on Paper's autosave and can, rarely,
> catch a half-written chunk. For an important snapshot, stop the server
> first, back up, then start it again. The scheduled 6-hourly backup
> deliberately accepts the running-server trade-off so it can be hands-off.

## Restore

**What it does.** `scripts/minecraft/restore.sh` puts a prior world back. It
**refuses while the server looks up**, asks you to confirm, takes a
`pre-restore-` safety snapshot of the *current* world, then swaps in the
chosen archive (including its `server.properties`, so you get the exact world
config that was backed up).

```bash
# 1. Stop the server first (restore refuses if it looks up):
sudo systemctl stop minecraft        # or Ctrl+C / kill the supervise.sh PID

# 2. See what you can restore:
scripts/minecraft/restore.sh --list

# 3a. Restore the most recent backup:
scripts/minecraft/restore.sh --latest

# 3b. …or a specific archive (path, or a filename inside BACKUP_DIR):
scripts/minecraft/restore.sh world-20260517T230600Z.tar.gz

#     Add --yes (-y) to skip the confirm prompt (automation only):
scripts/minecraft/restore.sh --latest --yes

# 4. Start the server again:
scripts/minecraft/start-server.sh    # or: sudo systemctl start minecraft
```

> **Gotcha.** Stop the server before restoring — it refuses while the
> supervisor PID file says it's up, on purpose, so you can't corrupt a live
> world. The automatic `pre-restore-` snapshot means even a wrong restore is
> reversible (restore *that* archive to undo). Run `scripts/minecraft/health.sh`
> after starting to confirm the world is back.

## Reset to a fresh world

**What it does.** `scripts/minecraft/restore.sh --reset` wipes the world
folders **and** the generated `server.properties` (after a `pre-reset-` safety
snapshot) so the next `start-server.sh` regenerates a brand-new clean world
from `scripts/minecraft/world.config`. The install (jar, scripts) is kept.

```bash
sudo systemctl stop minecraft            # stop first (reset also refuses if up)
scripts/minecraft/restore.sh --reset     # confirms; --yes to skip the prompt
scripts/minecraft/start-server.sh        # generates a fresh, clean world
```

> **Gotcha.** Reset is for experiments / starting over — it is recoverable
> (restore the `pre-reset-` snapshot to get the old world back) and it keeps
> the install. Do **not** confuse it with teardown below: reset = *fresh
> world, server still installed*; teardown = *everything gone*.

## Health

**What it does.** `scripts/minecraft/health.sh` opens a TCP connection to the
Minecraft port and reports up/down. No Java, no Minecraft client, nothing to
install. It **reports** liveness; it does not restart anything (that's
supervision, above).

```bash
scripts/minecraft/health.sh           # human: prints ✓/✗, exits 0 (up) / 1 (down)
scripts/minecraft/health.sh --json    # one JSON line for the Python brain / livestream
scripts/minecraft/health.sh --quiet   # no output, exit code only (use inside scripts)
scripts/minecraft/health.sh --help    # options + env knobs (SERVER_HOST/PORT, CONNECT_TIMEOUT)

# Fold the Minecraft check into the existing 5-service dev gate (opt-in):
CHECK_MINECRAFT=1 bash scripts/check-services.sh
```

`--json` emits e.g. `{"up":true,"host":"127.0.0.1","port":25565,"checked_at":"2026-05-17T23:06:00Z"}`.

> **Gotcha.** "Up" means the port is accepting connections — it does not prove
> the world is ticking smoothly. The `check-services.sh` integration is
> **opt-in** (`CHECK_MINECRAFT=1`): the default gate (and CI) never requires a
> Minecraft server, so a down world never breaks normal backend development.

---

## Clean teardown

> **⚠️ IRREVERSIBLE.** Step (e) permanently destroys the world, the Paper jar,
> all logs **and every on-host backup**. There is no undo. Do step (a) first
> and copy the archive **off this machine** if there is any chance you will
> ever want this world again. If you only want a *fresh* world but to keep the
> server installed, you want **Reset to a fresh world** (above), **not** this.

This uses only existing tooling — no new teardown script. Do the steps in
order.

**(a) Optional final keepsake backup.** Skip only if you are certain the world
is worthless.

```bash
scripts/minecraft/backup.sh
# Then copy the newest archive OFF this host (another disk, S3, your laptop):
scripts/minecraft/backup.sh --list      # find the newest world-*.tar.gz path
# e.g.:  scp <SERVER_DIR>/backups/world-<UTC>.tar.gz you@elsewhere:/safe/
```

**(b) Stop the server and the supervisor.**

```bash
# systemd 24/7 host:
sudo systemctl stop minecraft

# OR portable supervisor host — stop the watchdog itself (Ctrl+C if in the
# foreground); killing only the server PID would just trigger a restart:
kill "$(pgrep -f 'scripts/minecraft/supervise.sh')"
```

**(c) Disable and remove the systemd units** (only if you installed them via
[supervision.md](./supervision.md) / [backup-restore.md](./backup-restore.md)):

```bash
sudo systemctl disable --now minecraft minecraft-backup.timer
sudo rm -f /etc/systemd/system/minecraft.service \
           /etc/systemd/system/minecraft-backup.service \
           /etc/systemd/system/minecraft-backup.timer
sudo systemctl daemon-reload
```

**(d) Remove the backup cron line** (only if you added one in
[backup-restore.md](./backup-restore.md)):

```bash
crontab -e
# Delete the "Back up the Minecraft world every 6 hours" line, save, exit.
```

**(e) Delete the install directory.** This is the irreversible step.

```bash
rm -rf ./minecraft-server          # or your SERVER_DIR if you changed it
```

> This destroys the world, the Paper jar, all logs **and the on-host
> `backups/` folder** — which is why step (a) copies an archive *off* the
> host. Contrast with `scripts/minecraft/restore.sh --reset`, which gives you
> a fresh world but **keeps** the install (jar + scripts) and is recoverable.
> After (e), the only thing left is the committed scripts/docs in the repo;
> re-running `scripts/minecraft/start-server.sh` would set up a brand-new
> server from scratch.

---

## Local LM Studio validation

**Not applicable — this issue is documentation-only.** `runbook.md`
consolidates the six existing E2 docs and adds the teardown procedure; it
introduces **no code and no LLM runtime path**, so there is nothing to run
against LM Studio (no OpenRouter spend either way).

The underlying scripts this runbook documents
(`start-server.sh`, `supervise.sh` / `minecraft.service`, `backup.sh`,
`restore.sh`, `health.sh`) are already covered headlessly — no Java, no
network, no Docker — by:

```bash
pnpm verify:minecraft-server
```

That suite also now includes `tests/backend/test_minecraft_runbook.py`, which
asserts this runbook covers every operation command and that the six deep-dive
docs link back to it (so the consolidation can't silently drift).

## Cross-references

- **E2-1 — Run the server:** [server-setup.md](./server-setup.md)
  (issue [#526](https://github.com/bradtaylorsf/livestreamtoagi/issues/526)).
- **E2-2 — World as a configurable input:** [world-config.md](./world-config.md)
  (issue [#527](https://github.com/bradtaylorsf/livestreamtoagi/issues/527)).
- **E2-3 — Hosting 24/7:** [hosting.md](./hosting.md)
  (issue [#528](https://github.com/bradtaylorsf/livestreamtoagi/issues/528)).
- **E2-4 — 24/7 supervision:** [supervision.md](./supervision.md)
  (issue [#529](https://github.com/bradtaylorsf/livestreamtoagi/issues/529)).
- **E2-5 — Backups & restore:** [backup-restore.md](./backup-restore.md)
  (issue [#530](https://github.com/bradtaylorsf/livestreamtoagi/issues/530)).
- **E2-6 — Health check + status:** [health.md](./health.md)
  (issue [#531](https://github.com/bradtaylorsf/livestreamtoagi/issues/531)).
- **Plan:** `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` → §5, **E2-7**.

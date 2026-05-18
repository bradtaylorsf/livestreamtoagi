# World Backup & Restore (and "reset to a fresh world")

The world your AI agents build is **irreplaceable** — there is no "undo" for
a corrupted save or a dead disk. This doc makes the private Minecraft world
**back itself up on a schedule**, shows you how to **put a prior world back**,
and gives you a clean **reset to a fresh world** for experiments — all in
plain language, no ops experience assumed.

> **Issue:** E2-5 (epic E2). **Files:** `scripts/minecraft/backup.sh` and
> `scripts/minecraft/restore.sh`. **Builds on:** E2-1
> ([server-setup.md](./server-setup.md)) for the server,
> E2-2 ([world-config.md](./world-config.md)) for what "the world" is, and
> E2-4 ([supervision.md](./supervision.md)) for the 24/7 host this runs on.

## Non-technical summary

A **backup** is a single dated `.tar.gz` file containing a complete copy of
the world (overworld + Nether + End) and its `server.properties`. Take them
regularly and you can always go back to a recent world if something breaks.

- **Backup:** `scripts/minecraft/backup.sh` — makes one snapshot now.
- **Restore:** `scripts/minecraft/restore.sh --latest` — puts the most
  recent world back.
- **Reset:** `scripts/minecraft/restore.sh --reset` — wipes the world so the
  next start generates a brand-new clean one (used by experimental runs).

Both restore and reset **automatically save a safety copy of the current
world first**, and both **refuse to run while the server is up** — so a
mistaken click is itself recoverable and you can't corrupt a live world.

## What a backup contains

`backup.sh` reads `LEVEL_NAME` from `scripts/minecraft/world.config` (E2-2,
the same allow-list reader `start-server.sh` uses) and archives, relative to
`SERVER_DIR`:

| Included | Why |
|----------|-----|
| `<LEVEL_NAME>/` | the overworld save (terrain, builds, chests) |
| `<LEVEL_NAME>_nether/` | the Nether (if it exists) |
| `<LEVEL_NAME>_the_end/` | the End (if it exists) |
| `server.properties` | so a restore brings back the **same world config** |

Archives are written to `BACKUP_DIR` (default `<SERVER_DIR>/backups/`, which
is already git-ignored) as `world-<UTC-timestamp>.tar.gz`.

## Take a backup

```bash
# Make a backup now (then prune — see Retention below):
scripts/minecraft/backup.sh

# See exactly what WOULD be archived, write nothing:
scripts/minecraft/backup.sh --dry-run

# List existing backups, newest first:
scripts/minecraft/backup.sh --list

# All options + env knobs:
scripts/minecraft/backup.sh --help
```

Configuration is via environment variables (all optional): `SERVER_DIR`,
`WORLD_CONFIG`, `BACKUP_DIR`, `BACKUP_KEEP`. `--help` lists them with
defaults.

### Consistency: stop the server, or rely on autosave

Backing up a **stopped** server is always perfectly consistent. Backing up a
**running** server is *usually* fine — Paper autosaves every few minutes —
but a backup taken mid-write can catch a half-written chunk. For an
important snapshot:

- **Best:** stop the server first (`sudo systemctl stop minecraft`, or Ctrl+C
  / kill the supervisor — see [supervision.md](./supervision.md)), back up,
  start it again.
- **If you use RCON:** flush saves first, then back up while up:
  `save-all flush` then (optionally) `save-off` for the duration, then
  `save-on`.
- **Otherwise:** the scheduled backup below relies on autosave; that is an
  accepted, documented trade-off for a hands-off 24/7 backup.

## Schedule it (pick ONE cadence)

A 24/7 show needs backups without anyone remembering to run them. A snapshot
**every 6 hours** with the default `BACKUP_KEEP=10` keeps ~2.5 days of
history; tune both for your disk and how much loss you can tolerate.

### Option A — cron (simplest; works anywhere `cron` runs)

```bash
crontab -e
```

Add one line (edit the absolute repo path and `SERVER_DIR`):

```cron
# Back up the Minecraft world every 6 hours (00:00, 06:00, 12:00, 18:00).
0 */6 * * * SERVER_DIR=/opt/livestreamtoagi/minecraft-server /opt/livestreamtoagi/scripts/minecraft/backup.sh >> /opt/livestreamtoagi/minecraft-server/logs/backup.log 2>&1
```

### Option B — systemd timer (the Linux 24/7 host)

Mirrors the `scripts/minecraft/minecraft.service` style (E2-4). Create two
units (edit the `EDIT` lines, same values as `minecraft.service`):

`/etc/systemd/system/minecraft-backup.service`:

```ini
[Unit]
Description=Back up the Livestream-to-AGI Minecraft world (E2-5)
Documentation=https://github.com/bradtaylorsf/livestreamtoagi/blob/main/docs/minecraft/backup-restore.md

[Service]
Type=oneshot
# EDIT: same unprivileged user that owns the repo + world as minecraft.service.
User=minecraft
# EDIT: absolute path to the repo checkout on this host.
WorkingDirectory=/opt/livestreamtoagi
# EDIT: where the world lives (same as minecraft.service).
Environment=SERVER_DIR=/opt/livestreamtoagi/minecraft-server
ExecStart=/opt/livestreamtoagi/scripts/minecraft/backup.sh
StandardOutput=journal
StandardError=journal
SyslogIdentifier=minecraft-backup
```

`/etc/systemd/system/minecraft-backup.timer`:

```ini
[Unit]
Description=Run the Minecraft world backup every 6 hours (E2-5)

[Timer]
OnCalendar=00/6:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now minecraft-backup.timer
systemctl list-timers minecraft-backup.timer   # confirm next run
journalctl -u minecraft-backup.service          # see backup output
```

`Persistent=true` runs a missed backup once after a host reboot.

## Retention (what gets pruned)

Retention is **per archive-prefix series**. A scheduled backup keeps only the
newest `BACKUP_KEEP` (default 10) `world-` archives and prunes older ones in
that same series. The on-demand **safety snapshots** restore/reset write
(`pre-restore-*`, `pre-reset-*`) are a **different series**: a routine
`world-` backup never deletes them; each is only trimmed (independently, to
`BACKUP_KEEP`) the next time restore/reset writes one of that same kind.

## Restore a prior world

```bash
# 1. Stop the server first (restore refuses while it looks like it's up):
sudo systemctl stop minecraft        # or Ctrl+C / kill the supervise.sh

# 2. See what you can restore:
scripts/minecraft/restore.sh --list

# 3a. Put the most recent backup back:
scripts/minecraft/restore.sh --latest

# 3b. …or a specific one (path, or just a filename inside BACKUP_DIR):
scripts/minecraft/restore.sh world-20260517T230600Z.tar.gz

# 4. Start the server again:
scripts/minecraft/start-server.sh    # or: sudo systemctl start minecraft
```

What restore does, in order:

1. **Refuses** if the server appears to be running (it checks
   `CHILD_PID_FILE`, which defaults to the same
   `<SERVER_DIR>/logs/supervise-child.pid` that `supervise.sh` writes — E2-4).
2. **Asks you to confirm** (type `yes`). Add `--yes` (or `-y`) to skip the
   prompt for automation; with no terminal and no `--yes` it refuses rather
   than guess.
3. **Saves a `pre-restore-` safety backup** of the *current* world first, so
   even a wrong restore is reversible.
4. Removes the current world folders and **extracts the chosen archive**
   (including its `server.properties` — you get back the exact world config
   that was backed up).

> The acceptance criterion — *a documented restore recreates a prior world* —
> is exactly steps 2–4 above; the verify suite proves the round-trip offline.

## Reset to a fresh world (experimental runs)

Experiments need a clean slate. `--reset` deletes the world **and** the
generated `server.properties` so the next `start-server.sh` regenerates a
brand-new world from `world.config` (E2-2):

```bash
sudo systemctl stop minecraft                 # stop first (reset also refuses if up)
scripts/minecraft/restore.sh --reset          # confirms; --yes to skip the prompt
scripts/minecraft/start-server.sh             # generates a fresh clean world
```

Reset also takes a `pre-reset-` safety snapshot first, so resetting is itself
recoverable (restore that archive to get the old world back).

This is the **clean reset path** the experimental run mode is meant to call.
*Wiring it into run modes* (a run spec choosing persistent-vs-experimental
and invoking this automatically) is **E12**, explicitly out of scope here —
this issue only provides the reset command itself.

## What this does NOT cover (on purpose)

- **Run-mode wiring.** Connecting reset/restore to persistent-vs-experimental
  run specs is **E12** (`E12 — World as an input wired to E2`). This issue is
  the scripts + schedule + docs only.
- **Alerting / notifications.** Backups run silently; nothing texts/emails
  you if one fails. Alerting is owned by **E11/E13** and is out of scope.
- **Off-host / cloud copies.** Archives land in `BACKUP_DIR` on the same
  host. Copying them off-box (S3, another disk) is a host/ops choice, not
  part of this issue.
- **In-game spawn / world-gen choices.** Those are E2-2
  ([world-config.md](./world-config.md)); reset just regenerates from it.

## Cross-references

- **E2-1 — Run the server:** [server-setup.md](./server-setup.md)
  (issue [#526](https://github.com/bradtaylorsf/livestreamtoagi/issues/526)) —
  `start-server.sh`, which generates the world this backs up.
- **E2-2 — World as a configurable input:** [world-config.md](./world-config.md)
  (issue [#527](https://github.com/bradtaylorsf/livestreamtoagi/issues/527)) —
  `world.config`/`LEVEL_NAME`, what reset regenerates from.
- **E2-4 — 24/7 supervision:** [supervision.md](./supervision.md)
  (issue [#529](https://github.com/bradtaylorsf/livestreamtoagi/issues/529)) —
  the systemd/`supervise.sh` host this schedules against; stop it before
  restore/reset.
- **E2-6 — Health check + status:** [health.md](./health.md)
  (issue [#531](https://github.com/bradtaylorsf/livestreamtoagi/issues/531)) —
  the up/down probe; run it after a restore to confirm the world is back.
- **E2-7 — Ops runbook (+ teardown):** [runbook.md](./runbook.md)
  (issue [#532](https://github.com/bradtaylorsf/livestreamtoagi/issues/532)) —
  the one-page consolidation; the quick-reference backup/restore/reset
  commands and the keepsake-backup-then-teardown procedure live there.
- **Plan:** `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` → §5, **E2-5**.

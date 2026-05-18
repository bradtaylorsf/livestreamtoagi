# World Generation — Configurable Input (seed / type / spawn)

This explains how to choose **what world** your private Minecraft server
generates, in plain language. No prior Minecraft-server experience assumed.

> **Issue:** E2-2 (epic E2). **Config file:** `scripts/minecraft/world.config`.
> **Consumed by:** `scripts/minecraft/start-server.sh` (the E2-1 start script —
> see [server-setup.md](./server-setup.md) to get a server running first).
> **Day-to-day operation** (start/stop/backup/restore/reset/health on one
> page) is in the consolidated **[runbook.md](./runbook.md)** (E2-7).

## TL;DR

1. Edit `scripts/minecraft/world.config` (a plain `KEY=VALUE` text file).
2. Start the server **fresh** (a brand-new world — see
   [§ Applying a change](#applying-a-change-needs-a-fresh-world) below).
3. You get a different world.

```bash
# Preview what world the current config would generate (downloads nothing):
scripts/minecraft/start-server.sh --dry-run
```

## What is a "seed"?

A **seed** is the single starting value the world generator uses to build
your world. Think of it like the recipe number for a procedurally-generated
landscape.

- The **same seed always produces the same world** — identical terrain,
  caves, villages, ores, everything. This is *deterministic*.
- A **different seed produces a completely different world.**
- Leaving the seed **empty means "pick a new random one for me"**, so every
  fresh world is different.

Seeds can be numbers (`12345`) or words (`alpha-loop`) — Minecraft converts a
word into a number internally. You'd set a fixed seed when you want a
**reproducible** world (e.g. so a teammate generates the *exact* same world,
or to re-create a world you liked), and leave it empty when you just want
something new.

## The settings in `world.config`

The file is heavily commented; this is the summary.

| Key | What it controls | Default |
|-----|------------------|---------|
| `LEVEL_SEED` | The world seed (see above). Empty = new random world. | *(empty)* |
| `LEVEL_TYPE` | The overall shape of the world (see below). | `minecraft:normal` |
| `LEVEL_NAME` | The folder the world is saved under, inside `SERVER_DIR`. | `world` |
| `GENERATE_STRUCTURES` | `true`/`false` — generate villages, temples, strongholds, etc. | `true` |
| `SPAWN_PROTECTION` | Radius (blocks) around spawn where only operators may build. `0` = none. | `0` |

### `LEVEL_TYPE` options

| Value | What you get |
|-------|--------------|
| `minecraft:normal` | Standard Minecraft terrain — the usual varied world. |
| `minecraft:flat` | A flat "superflat" world. Great for testing/builds. |
| `minecraft:large_biomes` | Normal terrain, but biomes ~4× larger. |
| `minecraft:amplified` | Extreme, very tall terrain. **Heavy on the host** — avoid for 24/7 unless you have RAM to spare. |

### A note on spawn

`SPAWN_PROTECTION` is a *radius*, not a location: it's how big the "only
operators can build here" bubble around the world spawn is. We default it to
`0` so the agents can build anywhere.

Choosing the **precise spawn coordinates** is a different thing entirely —
that's done live, inside the running game, with the `/setworldspawn` command,
and is intentionally **out of scope** for this config file.

## How to edit it

1. Open `scripts/minecraft/world.config` in any text editor.
2. Change a value. Keep the `KEY=VALUE` format: no spaces around `=`, no
   quotes, one per line. Lines starting with `#` are comments.
3. Save.

Only the fixed set of keys above is read — the start script parses this file
with a strict allow-list and **never executes it**, so a typo or an extra
line is harmless (it's simply ignored).

Examples:

```ini
# A specific, reproducible world:
LEVEL_SEED=alpha-loop

# A flat sandbox for build testing:
LEVEL_TYPE=minecraft:flat

# Keep a couple of worlds side by side:
LEVEL_NAME=experiment-2
```

## Applying a change needs a FRESH world

**This is the one thing to internalize.** Minecraft bakes the seed and level
type **into the saved world the first time it is generated.** After that, the
saved world wins — editing `world.config` does **nothing** to an existing
world. The start script deliberately also never overwrites an existing
`server.properties`, for the same reason.

So to actually see a new world, start **fresh** in one of these ways:

- **New world name:** set a different `LEVEL_NAME` (e.g. `world2`). The old
  world folder is left untouched; a new one is created on next start.
- **Fresh server dir:** start the script with a clean `SERVER_DIR`
  (`SERVER_DIR=/path/to/empty scripts/minecraft/start-server.sh`).
- **Delete & regenerate:** stop the server, delete the world folder
  (`<SERVER_DIR>/<LEVEL_NAME>/`) **and** the generated
  `<SERVER_DIR>/server.properties`, then start again.

> The clean, documented **reset / "fresh world"** path is now owned by
> **E2-5 — World backup & restore**: run `scripts/minecraft/restore.sh
> --reset` instead of the manual deletes above — it snapshots the old world
> first and removes the world folders **and** `server.properties` for you.
> See [backup-restore.md](./backup-restore.md)
> ([issue #530](https://github.com/bradtaylorsf/livestreamtoagi/issues/530)).

To preview the world the current config *would* generate without touching
anything or downloading the jar:

```bash
scripts/minecraft/start-server.sh --dry-run
```

It prints the resolved `seed` / `type` / `name` and writes them into a
freshly generated `server.properties` (only if one doesn't already exist).

## What this does NOT cover (on purpose)

- **Wiring world generation into the run-mode system** (persistent vs
  experimental runs choosing worlds programmatically) — that's **E12**
  (`E12-5 — World as an input wired to E2`). This issue makes the world a
  *file-based input*; connecting it to run specs is later work.
- **Backups, restore, and the clean reset workflow** — that's
  **E2-5** ([backup-restore.md](./backup-restore.md),
  [issue #530](https://github.com/bradtaylorsf/livestreamtoagi/issues/530)).
- **In-game spawn placement** (`/setworldspawn`) — done live in the game,
  not via this file.

## Verify

The headless, dependency-free check (no Java, no network) for this issue:

```bash
pnpm verify:minecraft-server
```

That runs `tests/backend/test_minecraft_world_config.py` (and the E2-1
start-script tests), which assert the committed `world.config` parses, that a
custom config's seed/type/spawn appear verbatim in the generated
`server.properties` via `--dry-run`, that changing a value changes the
generated world, and that an existing `server.properties` is still never
clobbered.

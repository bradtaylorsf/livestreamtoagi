# Server Health Check + Status Endpoint

A 24/7 show needs to **know the world is up** — the Python brain and the
livestream can't narrate around a server that's quietly down. This doc gives
you **one command that reports the private Minecraft server up or down**, in
plain language, no ops experience assumed.

> **Issue:** E2-6 (epic E2). **Files:** `scripts/minecraft/health.sh` (the
> probe) and a one-block, opt-in addition to `scripts/check-services.sh`.
> **Builds on:** E2-1 ([server-setup.md](./server-setup.md)) for the server
> it probes and E2-4 ([supervision.md](./supervision.md)) for what keeps
> that server up.

## Non-technical summary

"Is the world up?" has a simple, reliable answer: **can something open a
connection to the Minecraft port?** A server that's accepting connections on
its port is up; one that isn't is down. `health.sh` opens exactly that
connection and tells you the answer — nothing else to install, no Minecraft
client, no Java.

It does **one** thing: report liveness. It does **not** restart the server
(that's [supervision.md](./supervision.md)), back it up
([backup-restore.md](./backup-restore.md)), or draw graphs / page you
(see [§ What this does NOT cover](#what-this-does-not-cover-on-purpose)).

## The single command

```bash
# Is the server up? Human-readable, exit 0 if up / 1 if down:
scripts/minecraft/health.sh

# All options + env knobs:
scripts/minecraft/health.sh --help
```

It prints `✓ Minecraft server up (host:port)` and **exits 0**, or
`✗ Minecraft server down (host:port)` and **exits 1** — the same `✓`/`✗`
and pass/fail exit convention as `scripts/check-services.sh`, so it drops
straight into any check that already understands "exit 0 = healthy".

Configuration is via environment variables (all optional):

| Var | Default | Meaning |
|-----|---------|---------|
| `SERVER_HOST` | `127.0.0.1` | Host to probe. |
| `SERVER_DIR` | `./minecraft-server` | Where the server lives (used to find `server.properties`). |
| `SERVER_PORT` | from `server.properties`, else `25565` | Port to probe. If unset, it reads `server-port=` from `$SERVER_DIR/server.properties` (the same allow-list reader `start-server.sh` uses); `25565` is Paper's default — the port [server-setup.md](./server-setup.md) documents. |
| `CONNECT_TIMEOUT` | `5` | Seconds to wait for the TCP connect before calling the server down (a hung/filtered port can't stall the check). |

Exit status: **0** = up, **1** = down, **2** = bad usage/config.

## The `--json` status output (for the Python brain)

The brain / livestream should not parse a `✓`/`✗` line. `--json` emits a
single line the brain can read directly — this is the lightweight **status
endpoint** the issue asks for (a line of JSON, *not* a dashboard or a daemon):

```bash
scripts/minecraft/health.sh --json
# server up:
{"up":true,"host":"127.0.0.1","port":25565,"checked_at":"2026-05-17T23:06:00Z"}
# server down:
{"up":false,"host":"127.0.0.1","port":25565,"checked_at":"2026-05-17T23:06:00Z"}
```

`up` is a boolean, `port` a number, `checked_at` a UTC ISO-8601 timestamp.
The exit code still tracks `up` (0/1) so a caller can use either signal.

There is also `--quiet` (no output, exit code only) for use as a probe
inside other scripts — see the next section.

## Integrating with `scripts/check-services.sh`

`check-services.sh` is the existing 5-service dev gate (Redis, PostgreSQL,
pgvector, pg_trgm, Langfuse). The Minecraft check is added there as an
**opt-in** check, **off by default**:

```bash
# Default — unchanged: the 5 dev services only (CI runs exactly this, with
# no Minecraft server present, and must keep passing):
bash scripts/check-services.sh

# Include the Minecraft server in the same report:
CHECK_MINECRAFT=1 bash scripts/check-services.sh
```

When `CHECK_MINECRAFT=1`, it runs `scripts/minecraft/health.sh --quiet`
through the same `check()` helper as the other services, so a down server
shows as `✗ Minecraft server (...)` and fails the gate exactly like a down
Redis would. It honours the same `SERVER_HOST` / `SERVER_PORT` env vars as
`health.sh`. It is opt-in **on purpose**: the 24/7 Minecraft world is not a
prerequisite for backend development or CI, so it must never break the
default `check-services.sh` run.

## How to verify it works

The committed, **dependency-free** check (no Java, no Minecraft, no real
network — `health.sh --self-test` binds a throwaway loopback listener, proves
the probe says *up* then *down* when it's killed) runs in CI:

```bash
pnpm verify:minecraft-server
```

That runs `tests/backend/test_minecraft_health.py`, which statically
validates the script (executable, `bash -n`, shellcheck-clean, `--help`,
unknown-arg → exit 2), exercises every mode against a real loopback socket
(up → exit 0 + `✓`; `--json` → valid JSON with `up:true` and the right port;
no listener → exit 1 + `up:false`), runs `--self-test`, and confirms the
`check-services.sh` integration is opt-in (absent unless `CHECK_MINECRAFT=1`).

You can also just run it by hand against a live server started via
[server-setup.md](./server-setup.md):

```bash
scripts/minecraft/start-server.sh &      # in another terminal
scripts/minecraft/health.sh --json       # → {"up":true,...}
```

## What this does NOT cover (on purpose)

- **Dashboards / graphs.** This is one command and one line of JSON — there
  is no web UI, no time-series, no history. Visualising stream/world health
  is owned by **E11/E13** and is explicitly out of scope here.
- **Alerting / notifications.** A down server fails an exit code; nothing
  texts/emails/pages you. Alerting is **E11/E13**, out of scope.
- **Restarting a down server.** Health *reports*; it does not *act*.
  Bringing a crashed server back is E2-4
  ([supervision.md](./supervision.md)).
- **In-world / gameplay health.** "The port is open" means the server
  process is accepting connections. Deeper liveness (ticking, no lag, the
  world loaded) would need an in-game query; it is not part of this
  beginner-scoped issue.

## Cross-references

- **E2-1 — Run the server:** [server-setup.md](./server-setup.md)
  (issue [#526](https://github.com/bradtaylorsf/livestreamtoagi/issues/526)) —
  `start-server.sh`, the server this probes, and where `25565` comes from.
- **E2-4 — 24/7 supervision:** [supervision.md](./supervision.md)
  (issue [#529](https://github.com/bradtaylorsf/livestreamtoagi/issues/529)) —
  what *acts* on a down server; health only *reports* it.
- **E2-5 — Backups & restore:** [backup-restore.md](./backup-restore.md)
  (issue [#530](https://github.com/bradtaylorsf/livestreamtoagi/issues/530)).
- **Plan:** `docs/MINECRAFT-PIVOT-ISSUE-PLAN.md` → §5, **E2-6**.

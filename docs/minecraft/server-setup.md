# Minecraft Server Setup — Beginner Walkthrough

This runbook takes you from a **fresh machine with nothing installed** to a
**running private Minecraft server** you can connect to. No prior Minecraft-server
experience is assumed. Every command is copy-paste, and every setting is
explained in plain language.

> **Issue:** E2-1 (epic E2). **Script:** `scripts/minecraft/start-server.sh`.

## What this gets you

- A private [Paper](https://papermc.io/) Minecraft server running on your own
  machine, reachable at `localhost:25565`.
- A repeatable start script that installs the right server jar, accepts the
  EULA, writes sane defaults, and launches the server.

## What this does NOT cover (on purpose)

- **Running it 24/7 (where the durable host lives)** — that's [E2-3](https://github.com/bradtaylorsf/livestreamtoagi/issues/528), now documented in **[hosting.md](./hosting.md)** (recommended host, spec, cost, and the capture-host tradeoff). This doc runs the server locally; see that doc to choose where it lives 24/7.
- **Auto-restart / crash recovery (24/7 supervision)** — that's [E2-4](https://github.com/bradtaylorsf/livestreamtoagi/issues/529), now documented in **[supervision.md](./supervision.md)** (a systemd unit for the Linux 24/7 host plus a portable supervisor script, with the restart window and log retention). This doc just runs the server; see that doc to keep it up unattended.
- **Choosing the world seed/type/spawn** — that's [E2-2](https://github.com/bradtaylorsf/livestreamtoagi/issues/527), now documented in **[world-config.md](./world-config.md)**. This doc boots the default world; see that doc to change it.
- **Backups, health checks, teardown** — later E2 issues.

Here you just get a server running locally and learn what each knob means.

---

## 1. Prerequisites

| You need | Why | Check it |
|----------|-----|----------|
| **Java 21** | Paper 1.21.6 runs on the Java 21 runtime. | `java -version` → first line shows `version "21..."` |
| **`curl`** | Downloads the Paper server jar. | `curl --version` |
| **~2 GB free RAM** | Default server heap is 2 GB. | — |
| A terminal | You'll paste commands into it. | — |

> **Why these exact versions?** They come from the project's E1 decisions:
> Paper **1.21.6** build **48** and **Java 21** (E1-R1), offline auth mode
> (E1-R2). Once merged, `docs/decisions/0001-minecraft-version-and-server.md`
> and `docs/decisions/0002-auth-mode.md` are the **authoritative source of
> truth**; the start script's defaults are kept in sync with them. If those
> docs aren't present in your checkout yet, the script defaults still boot a
> correct server.

## 2. Install Java 21

Pick your operating system. After installing, **open a new terminal** so the
`java` command is picked up, then verify with `java -version`.

### macOS (Homebrew)

```bash
brew install openjdk@21
# Homebrew prints a line telling you to symlink it. Run the version it prints, e.g.:
sudo ln -sfn "$(brew --prefix)/opt/openjdk@21/libexec/openjdk.jdk" \
  /Library/Java/JavaVirtualMachines/openjdk-21.jdk
```

> macOS ships a stub `/usr/bin/java` that only prints "Unable to locate a Java
> Runtime" until a real JDK is installed — that's expected before this step.

### Debian / Ubuntu / WSL

```bash
sudo apt update
sudo apt install -y openjdk-21-jre-headless
```

### Windows

Install **WSL** (`wsl --install` in an admin PowerShell, then reboot) and
follow the Debian/Ubuntu steps above inside the Ubuntu terminal. Running the
server inside WSL keeps the commands in this doc identical across machines.

**Verify (any OS):**

```bash
java -version
# Expect a first line like:  openjdk version "21.0.4" ...
```

If it does not say `21`, the start script will refuse to launch and tell you so.

## 3. What is Paper, and why it?

**Paper** is a drop-in Minecraft *server* (the program that hosts the world;
not the game client you play with). It's the standard choice for a long-running
private server because it's far more performance-stable and configurable than
Mojang's vanilla server jar — important for a server we intend to run 24/7. Our
exact pin (version + build) is recorded in
`docs/decisions/0001-minecraft-version-and-server.md` (E1-R1). You don't
download it by hand — the start script does it for you.

## 4. The EULA — what you're agreeing to

Mojang requires anyone running a Minecraft server to accept the
[Minecraft End User License Agreement](https://aka.ms/MinecraftEULA). In
practice this means a file called **`eula.txt`** must contain `eula=true`
before the server will start.

**The start script writes `eula=true` for you.** By running the script you are
accepting Mojang's EULA. The file lives at `<SERVER_DIR>/eula.txt` (default
`./minecraft-server/eula.txt`) so you can see and audit it.

## 5. Run the server

From the repository root:

```bash
scripts/minecraft/start-server.sh
```

That single command:

1. Checks you have **Java 21** (refuses, with install hints, if not).
2. Creates the server directory (`./minecraft-server` by default).
3. Downloads the pinned Paper jar **once** (skipped on later runs).
4. Writes `eula.txt` (`eula=true`).
5. Writes a minimal `server.properties` **only if one doesn't exist** (it
   never overwrites your edits).
6. Launches the server.

### Preview without committing (optional)

Want to see exactly what it will do — which jar, which settings, which
command — *without* downloading or launching anything?

```bash
scripts/minecraft/start-server.sh --dry-run
```

### Configuration (environment variables)

Every value has a sensible default. Override by setting the variable before the
command, e.g. `MEM=4G scripts/minecraft/start-server.sh`.

| Variable | Default | What it does |
|----------|---------|--------------|
| `SERVER_DIR` | `./minecraft-server` | Where the server files live. |
| `MC_VERSION` | `1.21.6` | Minecraft/Paper version (E1-R1 pin). |
| `PAPER_BUILD` | `48` | Paper build number (E1-R1 pin). |
| `MEM` | `2G` | JVM heap, used for both `-Xms` and `-Xmx`. |
| `ONLINE_MODE` | `false` | See §7. Keep `false` for our private setup. |
| `WHITELIST` | `true` | Reject players not on the whitelist. See §7. |
| `SMOKE_TIMEOUT` | `180` | Seconds `--smoke` waits for boot (verification only). |
| `WORLD_CONFIG` | `<script dir>/world.config` | World-generation input file (seed/type/spawn). See **[world-config.md](./world-config.md)**. |

## 6. First boot — what you'll see

The first run downloads the jar (tens of MB) and then Paper builds the world.
The console scrolls a lot. You're waiting for one specific line:

```
[Server thread/INFO]: Done (12.345s)! For help, type "help"
```

**`Done (` means the server is up.** First boot takes longer because the world
is being generated; later boots are quick. If it instead says
`You need to agree to the EULA` the script didn't run — re-run the script.

## 7. `server.properties` essentials, in plain language

The script generates `<SERVER_DIR>/server.properties` with these settings.
Edit the file and restart the server to change them — it is **never**
regenerated once it exists.

- **`online-mode=false`** — *The most important one.* When `true`, the server
  asks Mojang to verify every connecting player owns a real, paid Minecraft
  account. We set it to **`false`** ("offline" / "cracked" mode) so our
  automated agents (which have no Microsoft accounts) can connect. This is the
  posture chosen in E1-R2 (`docs/decisions/0002-auth-mode.md`).
  **Security/EULA tradeoff you must understand:** with `online-mode=false`,
  anyone who can reach the server can join as *any username* — there is no
  identity verification. That is acceptable **only** because this server is
  private and not exposed to the public internet. **Never port-forward or
  expose an `online-mode=false` server.** Keeping it behind your firewall /
  localhost is the safety boundary.
- **`white-list=true`** — Only usernames you've explicitly allowed may join,
  even on the local network. This is a deliberate second safety layer on top of
  offline mode. **It also means a vanilla test client will be kicked until you
  add it** — see §9.
- **`difficulty=normal`** — How hostile the world is (`peaceful`/`easy`/
  `normal`/`hard`). Cosmetic for setup purposes.
- **`motd=...`** — The "message of the day" shown in the client's server list.
- **`max-players=20`** — Connection cap.
- **`view-distance=10`** — How many chunks the server sends each player. Lower
  it (e.g. `6`) if the host is RAM-constrained.
- **`spawn-protection`** — Radius (in blocks) around spawn where only
  operators may build. Defaults to `0` (no protected zone) so agents can build
  anywhere. **This now comes from `world.config`** (`SPAWN_PROTECTION`) — see
  [world-config.md](./world-config.md).
- **`level-name` / `level-seed` / `level-type` / `generate-structures`** —
  These are the **world-generation inputs** and now come from
  `scripts/minecraft/world.config` (E2-2). Don't hand-edit them here; edit
  `world.config` and start a **fresh** world instead. The full beginner
  explainer — what a "seed" is, the level-type options, and why a change needs
  a fresh run — is in **[world-config.md](./world-config.md)**.

## 8. Stop the server

In the server console, type:

```
stop
```

and press Enter. This saves the world and shuts down cleanly. If the server is
running in the foreground and not accepting console input, `Ctrl+C` also stops
it. **Always prefer `stop`** so the world is saved properly.

## 9. Verify success (connect a client)

1. With the server running (`Done (` printed), open the **Minecraft Java
   Edition** client.
2. Because `white-list=true`, first allow your in-game username from the server
   console:
   ```
   whitelist add YourMinecraftUsername
   ```
   (Or, for a quick throwaway local test only, restart with
   `WHITELIST=false scripts/minecraft/start-server.sh`.)
3. In the client: **Multiplayer → Direct Connection →** `localhost:25565` →
   **Join Server**.
4. You spawn into the world. The server console logs your join. ✅

That round trip — fresh machine → `Done (` → client connects — is the
acceptance bar for this runbook.

### Automated smoke check (no client needed)

For CI / verification, this boots the server, waits for the `Done (` line, then
stops it automatically, exiting non-zero if it never becomes ready:

```bash
scripts/minecraft/start-server.sh --smoke
```

### Headless verification (no Java, no network, no Node)

The canonical, dependency-free way to verify this issue — used by CI and the
automated verifier — is the project's standard test runner. It exercises the
provisioning logic via `--dry-run` (EULA + `server.properties` generation,
pinned E1 defaults, env overrides, the no-clobber guarantee) plus bash-syntax
and shellcheck linting of the start script. It needs **no Java, no network, and
no Node.js**:

```bash
pnpm verify:minecraft-server
```

That is shorthand for the equivalent direct command (run either one):

```bash
.venv/bin/pytest tests/backend/test_minecraft_start_server.py -v
```

Run `pnpm verify:minecraft-server` to validate this issue headlessly; reserve
`--smoke` (above) for hosts that have Java 21 and a real end-to-end boot.

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `✗ Java not found on PATH` | No JRE installed. | Do §2, open a **new** terminal. |
| `✗ Java 17 found, but Paper 1.21.6 needs Java 21` | Wrong Java major. | Install Java 21; ensure it's first on `PATH` (`java -version` must say 21). |
| `Paper jar download failed` | No network, or that version/build doesn't exist. | Check connectivity; confirm the build at <https://papermc.io/downloads/paper>; re-run (download is retried automatically). |
| `FAILED TO BIND TO PORT! ... 25565` | Another server already uses port 25565. | Stop the other server, or change `server-port=` in `server.properties` and reconnect on the new port. |
| Client gets *"You are not white-listed on this server!"* | `white-list=true` and your name isn't added. | Run `whitelist add <name>` in the console (§9). |
| Console says *"You need to agree to the EULA..."* and exits | `eula.txt` missing/`false`. | Re-run the start script (it writes `eula=true`); or set `eula=true` in `<SERVER_DIR>/eula.txt`. |
| World looks wrong / want a different one | World gen is a config input. | Edit `scripts/minecraft/world.config` and start a **fresh** world — see [world-config.md](./world-config.md). |

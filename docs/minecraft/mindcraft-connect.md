# Connect One Stock Bot to the E2 Server (Beginner Walkthrough)

This runbook takes you from **a pinned Mindcraft install + a running E2 server**
to **one stock bot visibly standing in your Minecraft world**. No prior
Mindcraft experience is assumed. Every command is copy-paste.

> **Issue:** E3-2 (epic E3, [#534](https://github.com/bradtaylorsf/livestreamtoagi/issues/534)).
> **Script:** `scripts/minecraft/connect-stock-bot.sh`.
> **Goal:** prove the fork talks to our server **before** any agent
> customization (our 9 agents are E8 — explicitly *not* this issue).

## What this gets you

- One **stock** Mindcraft bot (fixed username **`StockBot`**) that joins the
  **E2 Paper server** on `127.0.0.1:25565`, in Minecraft **offline** auth mode.
- A committed, reviewed `settings.js` template and stock profile that the launch
  script **stages** into the git-ignored `./mindcraft` clone — the same
  committed-artifact pattern E3-1 uses for the vendored lockfile.
- A tiny **runtime-version shim** staged only for the launch: the pinned fork
  reads `minecraft_version` before the child agent receives settings, so the
  script temporarily refreshes that value from runtime settings and restores the
  disposable clone when the bot exits. Without it, Mineflayer auto-selects its
  newest supported protocol instead of the E2-pinned `1.21.6`.
- A bot driven by a **local LM Studio** model only — **zero external model
  spend**. No `openrouter/...` anywhere in this issue.

## What this does NOT cover (on purpose)

- **Our nine agents / their personalities & model assignments** — that's **E8**.
  This bot is deliberately generic.
- **Per-agent multi-model routing verification** — that's **E3-3
  ([#535](https://github.com/bradtaylorsf/livestreamtoagi/issues/535))**.
- **Profile generation from `agents/<id>/config.yaml`** — that's **E3-4
  ([#536](https://github.com/bradtaylorsf/livestreamtoagi/issues/536))**.
- **Agent customization** — the pinned clone stays clean of persistent changes;
  only the staged config/profile and temporary runtime-version shim are applied
  for this launch.

## The settings this bot uses (authoritative values)

| Setting | Value | Why |
|---|---|---|
| `minecraft_version` | **`1.21.6`** | Matches the Paper version E2 provisions (E1-R1 / `docs/decisions/0001`). Not `auto`. |
| `host` | **`127.0.0.1`** | Localhost only — offline-mode bots must never be public (E1-R2 / `docs/decisions/0002`). |
| `port` | **`25565`** | The E2 server default (`start-server.sh` leaves `server-port` unset). |
| `auth` | **`offline`** | Matches Paper `online-mode=false` (E1-R2 / `docs/decisions/0002`). |
| `auto_open_ui` | **`false`** | Headless connect — no browser UI. |
| `profiles` | **`["./profiles/stock-bot.json"]`** | Exactly one stock bot. |
| Bot username | **`StockBot`** | Fixed, so you can whitelist it by name. |
| `model` / `code_model` | **`lmstudio/<id>`** | Local LM Studio only (decision 0003). Substituted from `LOCAL_LLM_MODEL` / `LOCAL_LLM_MODEL_BUILDING`. |

These come from the project's E1 decisions. Once merged,
`docs/decisions/0001-minecraft-version-and-server.md`,
`docs/decisions/0002-auth-mode.md`, and
`docs/decisions/0003-mindcraft-model-routing.md` are the authoritative source of
truth; the committed template's values are kept in sync with them and the
host/port/profile are env-overridable for the launch script.

---

## 1. Prerequisites

| You need | Why | Check it |
|---|---|---|
| **E2 server running** | The bot needs a world to join. | `scripts/minecraft/start-server.sh` (see `docs/minecraft/server-setup.md`); console shows `Done (`. |
| **Pinned fork installed** | The bot code + deps live in `./mindcraft`. | `scripts/minecraft/setup-mindcraft.sh` (see `docs/minecraft/mindcraft-fork.md`); ends `✓ Mindcraft installed deterministically`. |
| **Node 20 LTS** | The pinned Mindcraft targets Node 20 (E1-R1). | `node -v` → `v20.x.y` |
| **LM Studio serving a model** | Drives the bot's chat/code tier locally — zero external spend. | `pnpm llm:local --list-only` lists at least one model id. |

The launch script **refuses a real run** if Node is not major **20**, if
`./mindcraft` is not at the pinned commit, or if `LOCAL_LLM_MODEL` is unset —
each with a one-line fix hint.

## 2. Pick a local model (LM Studio — zero external spend)

Load a model in LM Studio, then list what it is serving and export one id:

```bash
pnpm llm:local --list-only          # or: .venv/bin/python scripts/check_local_llm.py --list-only
export LOCAL_LLM_MODEL=<model-id-from-the-list>
# Optional, when a larger local model is available for the building/code tier:
export LOCAL_LLM_MODEL_BUILDING=<larger-local-model-id>
```

`LOCAL_LLM_MODEL` becomes the profile's `model` (conversation tier);
`LOCAL_LLM_MODEL_BUILDING` becomes `code_model` (building tier) and defaults to
`LOCAL_LLM_MODEL` if you don't set it (single-model local validation is fine for
a stock bot — decision 0003).

## 3. Run the documented command

From the repository root, with the E2 server already running:

```bash
scripts/minecraft/connect-stock-bot.sh
```

That single command:

1. Verifies the committed settings template + stock profile are well-formed and
   local-only (no `openrouter/`).
2. Checks **Node 20**, that `./mindcraft` exists and `HEAD` equals the pinned
   commit (else it tells you to run `setup-mindcraft.sh`), and that
   `LOCAL_LLM_MODEL` is set.
3. Stages `scripts/minecraft/mindcraft-settings.js` → `./mindcraft/settings.js`
   (host/port/profile substituted from env; everything else verbatim).
4. Stages `scripts/minecraft/profiles/stock-bot.json` →
   `./mindcraft/profiles/stock-bot.json` with the LM Studio model ids filled in.
5. Temporarily patches `./mindcraft/src/utils/mcdata.js` so the child bot reads
   the configured `minecraft_version` after settings arrive from MindServer, then
   restores that source file when the launch exits.
6. Prints the exact **whitelist** command (see §5), then launches:
   `cd ./mindcraft && node main.js --profiles ./profiles/stock-bot.json`.

### Preview without launching (optional)

See the resolved host/port/auth/profile/model **without** cloning, touching the
network, or launching anything:

```bash
scripts/minecraft/connect-stock-bot.sh --dry-run
```

### Configuration (environment variables)

Every value has a sensible, E1-pinned default.

| Variable | Default | What it does |
|---|---|---|
| `MINDCRAFT_DIR` | `./mindcraft` | The pinned clone (git-ignored). |
| `MC_HOST` | `127.0.0.1` | E2 server host (keep localhost in offline mode — E1-R2). |
| `MC_PORT` | `25565` | E2 server port. |
| `MINDCRAFT_PROFILE` | `./profiles/stock-bot.json` | Profile path inside the clone. |
| `LOCAL_LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio URL for the **pre-flight reachability check only** (`pnpm llm:local --list-only`). It does **not** retarget the bot — see note below. |
| `LOCAL_LLM_MODEL` | *(required)* | LM Studio model id — conversation tier. |
| `LOCAL_LLM_MODEL_BUILDING` | `= LOCAL_LLM_MODEL` | LM Studio model id — building/code tier. |

> **Where the bot actually connects:** the stock profile uses Mindcraft's
> string-form `lmstudio/<id>` syntax (decision 0003). At the pinned commit those
> profiles carry no URL, so Mindcraft always talks to its **built-in
> `http://localhost:1234/v1`** — `LOCAL_LLM_BASE_URL` cannot move the bot off
> that endpoint (it only changes the URL the separate `pnpm llm:local` check
> hits). **Run LM Studio on `http://localhost:1234/v1`** (its default).

## 4. What success looks like

The bot connects within a few seconds. You're done when **all three** are true:

1. **E2 server console logs the join:** a line like
   `StockBot[/127.0.0.1:...] logged in` followed by
   `StockBot joined the game`.
2. **The bot is in the world:** type `list` in the E2 server console — it
   reports `StockBot` among the online players.
3. **The bot moves:** with the `assistant` base profile the bot does not stand
   perfectly still (idle look/step behaviors), and on spawn it answers the
   `init_message` in chat. To force an unmistakable move, join the server with a
   normal Minecraft client and type in chat: `StockBot !moveAway(10)` — the bot
   walks ~10 blocks away.

The launching terminal stays attached to the bot; press **Ctrl+C** to stop it.

## 5. Whitelist handling (important)

`scripts/minecraft/start-server.sh` defaults to **`white-list=true`**, so the
E2 server **rejects `StockBot` until it is whitelisted**. The launch script
prints this reminder; do **one** of:

- **Whitelist the bot (recommended).** In the E2 **server console**, run
  exactly:

  ```
  whitelist add StockBot
  ```

- **Disable the whitelist (dev only, localhost).** Restart the E2 server with:

  ```bash
  WHITELIST=false scripts/minecraft/start-server.sh
  ```

Skip this and the bot connects, then is immediately kicked with a
`not whitelisted` / `You are not white-listed on this server!` message.

## 6. Local LM Studio validation (evidence)

This pivot is validated with **local models through LM Studio** — **no
OpenRouter spend** is required for acceptance (decision 0003).

**Confirm LM Studio is reachable** (lists the served model ids):

```bash
pnpm llm:local --list-only
```

**Bot-validation profile:** the staged `./mindcraft/profiles/stock-bot.json`
has `model` and `code_model` set to `lmstudio/<model-id>` — never
`openrouter/...`. The committed template `scripts/minecraft/profiles/stock-bot.json`
ships `lmstudio/__LOCAL_LLM_MODEL__` / `lmstudio/__LOCAL_LLM_MODEL_BUILDING__`
placeholders that the launch script substitutes from your env.

**Record in the issue/PR:**

- The LM Studio model id(s) used for `LOCAL_LLM_MODEL`
  (and `LOCAL_LLM_MODEL_BUILDING` if set).
- The exact command(s) run (`scripts/minecraft/connect-stock-bot.sh`, the
  `whitelist add StockBot` console command).
- That validation ran against the **local Mac server** (E2 Paper on
  `127.0.0.1:25565`, `online-mode=false`).
- Confirmation that `StockBot` appeared in the E2 world (server-console join
  line + `list`) and visibly moved.

> A real connect needs Node 20 + a running E2 server + LM Studio. On a host
> without those, the headless suite in §7 is the nearest local smoke path and
> is what CI / the automated verifier runs.

## 7. Verify success (headless — no Node, no network, no clone)

The canonical, dependency-free check for this issue exercises the launch
script's offline-safe paths (`--help`, `--verify`, `--dry-run`), asserts the
staged config points at the E2 server (`127.0.0.1:25565`, `auth offline`,
`minecraft 1.21.6`), and that the stock profile parses as JSON with
`lmstudio/` model/`code_model` and the fixed `StockBot` name. It needs **no
Node.js, no network, and no clone**:

```bash
pnpm verify:mindcraft-connect
```

That is shorthand for the equivalent direct command (run either one):

```bash
.venv/bin/pytest tests/backend/test_minecraft_connect_stock_bot.py -v
```

There is also a script-level static check that needs nothing but `bash`:

```bash
scripts/minecraft/connect-stock-bot.sh --verify
```

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `✗ You are not white-listed on this server!` (bot kicked instantly) | E2 `white-list=true` and `StockBot` not added. | Run `whitelist add StockBot` in the E2 console, or restart E2 with `WHITELIST=false`. |
| Bot exits with a connection refused / timeout | E2 server not running, or wrong host/port. | Start it (`scripts/minecraft/start-server.sh`); confirm `Done (`; check `MC_HOST`/`MC_PORT`. |
| `✗ Node 22 found, but the pinned Mindcraft needs Node 20 LTS` | Wrong Node major. | `nvm install 20 && nvm use 20`; confirm `node -v` says `v20`. |
| `✗ No Mindcraft clone at ./mindcraft` | Fork not installed yet. | Run `scripts/minecraft/setup-mindcraft.sh` (see `docs/minecraft/mindcraft-fork.md`). |
| `✗ Clone is not at the pinned commit` | `./mindcraft` drifted off the pin. | Re-pin: `scripts/minecraft/setup-mindcraft.sh` (don't hand-edit the clone). |
| `✗ LOCAL_LLM_MODEL is not set` | No local model selected. | `pnpm llm:local --list-only`, then `export LOCAL_LLM_MODEL=<id>`. |
| `✗ Mindcraft source shape changed; cannot apply runtime-version shim` | The pinned fork changed `src/utils/mcdata.js`, so the launch-time compatibility patch no longer matches. | Re-run `scripts/minecraft/setup-mindcraft.sh`; if it still fails, re-review the pinned fork before launching. |
| Bot connects but never responds in chat | LM Studio not serving on `http://localhost:1234/v1` (the only endpoint string-form `lmstudio/` profiles use at the pinned commit), or the model is not loaded. | Run LM Studio on `http://localhost:1234/v1`; `pnpm llm:local --list-only` to confirm a model is loaded. Overriding `LOCAL_LLM_BASE_URL` does **not** move the bot — it must be at the default endpoint. |
| Bot joins as the wrong name | `MINDCRAFT_PROFILE` overridden / profile edited. | Use the default `./profiles/stock-bot.json`; whitelist the `name` it actually uses. |

## 9. Where this is recorded

- **`docs/decisions/0001-minecraft-version-and-server.md`** — Minecraft `1.21.6`
  pin and the E2 server.
- **`docs/decisions/0002-auth-mode.md`** — `online-mode=false` / Mindcraft
  `auth: "offline"`, localhost-only requirement.
- **`docs/decisions/0003-mindcraft-model-routing.md`** — `model` (conversation)
  vs `code_model` (building), LM Studio string syntax, no external spend.
- **`docs/minecraft/mindcraft-fork.md`** — the prior step (pinned, reproducible
  install) this builds on.

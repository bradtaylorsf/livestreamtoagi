# Mindcraft Fork — Pinned, Reproducible Install (Beginner Walkthrough)

This runbook takes you from a **fresh machine** to a **deterministic install of
our pinned Mindcraft fork**. No prior Mindcraft experience is assumed. Every
command is copy-paste, and every setting is explained in plain language.

> **Issue:** E3-1 (epic E3, #533). **Script:** `scripts/minecraft/setup-mindcraft.sh`.

## What this gets you

- A local clone of **our org fork** of Mindcraft, checked out at one **exact,
  reviewed commit** — not a moving upstream branch.
- A **deterministic `npm ci` install** driven by a committed, vendored
  lockfile, so two clean checkouts resolve the same dependency tree.
- A repeatable setup script that refuses to install anything that isn't the
  pinned commit.

## The pin (authoritative values)

| What | Value |
|------|-------|
| Org fork | **<https://github.com/bradtaylorsf/mindcraft>** (fork of `mindcraft-bots/mindcraft`) |
| Pinned commit | **`35be480b4cc0bca990278e6103a1426392559d96`** |
| Pin tag in the fork | `e1-r1-pin` (points at the commit above) |
| Upstream branch it came from | `develop` (commit dated `2026-05-03`) |
| Node runtime | **Node 20 LTS** |
| Vendored lockfile | `scripts/minecraft/mindcraft-package-lock.json` |

> **Why these exact values?** They come from the project's E1 decisions
> (E1-R1). Once merged, `docs/decisions/0001-minecraft-version-and-server.md`
> (lines 26–30) and `docs/decisions/0000-summary.md` are the **authoritative
> source of truth**; the setup script's defaults are kept in sync with them and
> can be overridden via env vars. We pin a *fork* (not upstream directly)
> because upstream `develop` moves fast and we need a stable base.

## What this does NOT cover (on purpose)

- **Connecting a bot to the server** — that's **E3-2 ([#534](https://github.com/bradtaylorsf/livestreamtoagi/issues/534))**:
  point `settings.js`/a profile at the E2 server and launch one stock bot. See
  the beginner walkthrough **[`docs/minecraft/mindcraft-connect.md`](./mindcraft-connect.md)**
  (script: `scripts/minecraft/connect-stock-bot.sh`). This doc stops at a
  reproducible *install*.
- **Per-agent model routing** — that's **E3-3 ([#535](https://github.com/bradtaylorsf/livestreamtoagi/issues/535))**
  and **E3-4 ([#536](https://github.com/bradtaylorsf/livestreamtoagi/issues/536))**.
- **Any customization of the fork** — explicitly out of scope here. The fork is
  pinned *clean*; patches land in later E3/E4 issues.
- **Taking upstream fixes / re-basing the pin** — that's the maintenance &
  upstream-merge policy in **[`docs/minecraft/fork-maintenance.md`](./fork-maintenance.md)**
  (E3-6, [#538](https://github.com/bradtaylorsf/livestreamtoagi/issues/538)):
  how patches stay isolated, how to move the pin, and the CI build check.
- **An LLM runtime path** — **this issue has none.** Forking, pinning, and
  installing dependencies never calls a model, so there is no LM Studio /
  OpenRouter step to validate for #533. The nearest local smoke path is the
  headless test suite in §6.

Here you just get a pinned, reproducible Mindcraft tree on disk.

---

## 1. Prerequisites

| You need | Why | Check it |
|----------|-----|----------|
| **Node 20 LTS** | The pinned Mindcraft targets Node 20; Node 24+ breaks its native deps (E1-R1). | `node -v` → `v20.x.y` |
| **npm** | Runs the deterministic `npm ci` install. Ships with Node 20. | `npm -v` |
| **git** | Clones the fork and checks out the pinned commit. | `git --version` |
| **A terminal** | You'll paste commands into it. | — |

The setup script **refuses to install** unless `node -v` reports major
version **20** — a different major (e.g. 18, 22, 24) is rejected with an
install hint, exactly like the Java check in `start-server.sh`.

## 2. Install Node 20 LTS

Pick whichever you already use. After installing, **open a new terminal** so
`node` is picked up, then verify with `node -v`.

```bash
# nvm (recommended — keeps Node 20 isolated per-project)
nvm install 20 && nvm use 20

# macOS (Homebrew)
brew install node@20

# Debian / Ubuntu / WSL — see https://github.com/nodesource/distributions
```

**Verify (any OS):**

```bash
node -v   # Expect: v20.x.y
npm -v    # Any npm that ships with Node 20 is fine
```

If it does not say `v20`, the setup script will refuse to install and tell you
so.

## 3. Why a fork, and why pinned?

Upstream `mindcraft-bots/mindcraft` is an active project — `develop` changes
frequently. To get a **stable base** we forked it to
**`bradtaylorsf/mindcraft`** and froze one commit
(`35be480b4cc0bca990278e6103a1426392559d96`, also tagged `e1-r1-pin` in the
fork). Every install, every later patch, and every sibling issue (#534, #535,
#536) builds on *that* exact tree, so nothing shifts underneath us.

Upstream Mindcraft does **not** commit a lockfile, so a plain `npm install`
would resolve different transitive versions over time. To make installs
deterministic we generated a lockfile from the pinned `package.json` once,
checked it against the upstream patch targets, and committed it as
**`scripts/minecraft/mindcraft-package-lock.json`**.
The setup script stages that file into the clone and runs `npm ci`, which
installs *strictly* from the lockfile and aborts if it ever drifts from the
pinned `package.json`.

## 4. Run the setup

From the repository root:

```bash
scripts/minecraft/setup-mindcraft.sh
```

That single command:

1. Checks you have **Node 20 + npm** (refuses, with install hints, if not).
2. Clones `https://github.com/bradtaylorsf/mindcraft.git` into `./mindcraft`
   (or reuses + fetches an existing clone — safe to re-run).
3. Checks out the pinned commit and **hard-asserts** `HEAD` equals it —
   refusing to install an unpinned tree.
4. Stages the vendored `scripts/minecraft/mindcraft-package-lock.json` into the
   clone (upstream commits none).
5. Runs `npm ci` for a deterministic, lockfile-pinned install.

### Preview without committing (optional)

See exactly what it will do — which repo, which commit, which install — *without*
cloning, hitting the network, or installing anything:

```bash
scripts/minecraft/setup-mindcraft.sh --dry-run
```

### Configuration (environment variables)

Every value has a sensible, E1-pinned default. Override by setting the variable
before the command, e.g. `MINDCRAFT_DIR=/tmp/mc scripts/minecraft/setup-mindcraft.sh`.

| Variable | Default | What it does |
|----------|---------|--------------|
| `MINDCRAFT_REPO` | `https://github.com/bradtaylorsf/mindcraft.git` | Git URL of the pinned org fork. |
| `MINDCRAFT_COMMIT` | `35be480b4cc0bca990278e6103a1426392559d96` | Exact commit to pin to (E1-R1). |
| `MINDCRAFT_DIR` | `./mindcraft` | Where the working clone lives (git-ignored). |

> The clone directory `./mindcraft` is git-ignored on purpose — it is a local
> working tree, not a vendored copy. The *only* committed artifact from this
> issue is the lockfile.

## 5. What success looks like

The first run clones the fork and builds native dependencies (this takes a few
minutes — `canvas`, `gl`, and friends compile). You're done when you see:

```
mineflayer@4.33.0 ✔
...
✓ Checked out the pinned commit 35be480b4cc0bca990278e6103a1426392559d96
✓ Mindcraft installed deterministically at the pinned commit.
```

You may see `npm warn EBADENGINE` lines for `mineflayer` or
`minecraft-protocol` declaring `node: >=22`. Those warnings come from the npm
package metadata in the pinned dependency tree; E1 still pins local validation
to Node 20, and the setup is successful only if `patch-package` applies every
upstream patch and the final success line appears.

Re-running the script is safe: it fetches, re-pins to the same commit, and
re-installs from the same lockfile — the result is identical.

## 6. Verify success (headless — no Node, no network, no clone)

The canonical, dependency-free way to verify this issue — used by CI and the
automated verifier — is the project's standard test runner. It exercises the
script's offline-safe paths (`--help`, `--verify`, `--dry-run`), asserts the
pin contract (exact SHA, Node 20, fork URL), validates the committed lockfile
parses as JSON with a `lockfileVersion`, and confirms the decision docs record
the hash. It needs **no Node.js, no network, and no clone**:

```bash
pnpm verify:mindcraft-fork
```

That is shorthand for the equivalent direct command (run either one):

```bash
.venv/bin/pytest tests/backend/test_minecraft_setup_mindcraft.py -v
```

There is also a script-level static check that needs nothing but `bash`:

```bash
scripts/minecraft/setup-mindcraft.sh --verify
```

Run `pnpm verify:mindcraft-fork` to validate this issue headlessly; reserve a
real `setup-mindcraft.sh` run for a host with Node 20 and network.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `✗ Node.js not found on PATH` | No Node installed. | Do §2, open a **new** terminal. |
| `✗ Node 22 found, but the pinned Mindcraft needs Node 20 LTS` | Wrong Node major. | Install Node 20 (`nvm install 20 && nvm use 20`); ensure `node -v` says `v20`. |
| `✗ npm not found on PATH` | Node installed without npm (rare). | Reinstall Node 20 LTS (npm ships with it). |
| `npm warn EBADENGINE ... node: >=22` | Some pinned Mindcraft npm packages declare a newer engine even though E1 local validation uses Node 20. | Continue only if every `patch-package` line is green and the final success line appears. |
| `✗ Pinned-commit assertion FAILED` | The clone's `HEAD` isn't the pinned SHA. | Don't hand-edit the clone; delete `./mindcraft` and re-run. |
| `✗ patch-package reported a failed patch or version mismatch` | The vendored lockfile resolved package versions that no longer match upstream's patch files. | Refresh `scripts/minecraft/mindcraft-package-lock.json` so patched packages match the patch filenames, then re-run. |
| `✗ Lockfile drift detected` | A future re-pin added an upstream lockfile that differs from ours. | Re-vet and refresh `scripts/minecraft/mindcraft-package-lock.json` against the new pin, then re-run. |
| `npm ci` fails building `canvas`/`gl` | Missing native build toolchain. | Install build tools (macOS: Xcode CLT; Debian: `build-essential` + `libcairo2-dev` etc.) and re-run. |
| `git ... not found` | git missing. | Install git, then re-run. |

## 8. Where the pin is recorded

- **`docs/decisions/0000-summary.md`** — the "Final Decisions" table records the
  org fork URL + pinned commit (acceptance criterion for #533), and the
  decision-records section points here and at the committed lockfile.
- **`docs/decisions/0001-minecraft-version-and-server.md`** — the full E1-R1
  rationale (lines 26–30): the fork target, branch, commit date, and Node 20.
- **The fork itself** — tag `e1-r1-pin` in `bradtaylorsf/mindcraft` points at
  the pinned commit so it survives any upstream history rewrite.

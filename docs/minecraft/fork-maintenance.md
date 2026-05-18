# Mindcraft Fork — Maintenance & Upstream-Merge Policy (Beginner Walkthrough)

This is the **policy** for keeping our pinned Mindcraft fork alive over time:
how to take an upstream bug-fix **without losing any of our patches**, and how
CI proves the fork still builds. No prior Mindcraft or fork-maintenance
experience is assumed. Every command is copy-paste and every rule is explained
in plain language.

> **Issue:** E3-6 (epic E3, [#538](https://github.com/bradtaylorsf/livestreamtoagi/issues/538)).
> **Builds on:** E3-1 ([#533](https://github.com/bradtaylorsf/livestreamtoagi/issues/533)) —
> the pinned, reproducible install in
> [`docs/minecraft/mindcraft-fork.md`](./mindcraft-fork.md).

## The pin (authoritative values)

These never change silently — moving any of them is the whole subject of this
doc. They are kept byte-identical with `scripts/minecraft/setup-mindcraft.sh`
and `docs/decisions/0001-minecraft-version-and-server.md`.

| What | Value |
|------|-------|
| Org fork | **<https://github.com/bradtaylorsf/mindcraft>** (fork of `mindcraft-bots/mindcraft`) |
| Pinned commit | **`35be480b4cc0bca990278e6103a1426392559d96`** |
| Pin tag in the fork | `e1-r1-pin` (points at the commit above) |
| Upstream branch it tracks | `develop` |
| Node runtime | **Node 20 LTS** |
| Committed lockfile (the only vendored artifact) | `scripts/minecraft/mindcraft-package-lock.json` |
| Headless build/contract check | `pnpm verify:mindcraft-fork` |

---

## Why a maintenance policy

Upstream `mindcraft-bots/mindcraft` is an active project — its `develop`
branch moves fast and ships real bug-fixes we will eventually want. But we also
build customizations on top of it (the deterministic lockfile today; the
profile generator, feature flags, and Python bridge in later E3/E4 issues).

Without a written policy, the two pressures collide in the usual painful way:

- **"Just merge upstream"** → our patches silently disappear or conflict, and
  nobody can tell which commit was ours vs. theirs.
- **"Never touch upstream"** → we freeze on a stale base and re-discover bugs
  upstream already fixed.

The goal is to be able to **take an upstream fix without losing a single
patch**, deterministically, with a green build proving it. The strategy below
makes that a mechanical, reviewable operation instead of a merge gamble.

---

## Branch & patch-isolation strategy

The core rule, decided in `docs/decisions/0003-mindcraft-model-routing.md` and
`docs/decisions/0005-skill-extension-point.md` and proven in E3-1/E3-2:

> **The org fork stays clean at the pinned commit. Every customization lives in
> *this* repo as a committed artifact and is *staged into* the disposable
> clone — never as a drifting commit on the fork.**

Concretely:

| Layer | Where it lives | Drifts with upstream? |
|-------|----------------|-----------------------|
| Upstream Mindcraft source | `bradtaylorsf/mindcraft` @ `35be480b4cc0bca990278e6103a1426392559d96` (tag `e1-r1-pin`) — **clean**, no local commits | No — it is a frozen, reviewed point |
| Deterministic dependency tree | `scripts/minecraft/mindcraft-package-lock.json` (committed **here**) | Re-vendored deliberately on a re-pin |
| Bot config / profiles / launch shims | `scripts/minecraft/mindcraft-settings.js`, `scripts/minecraft/profiles/*.json`, and the `connect-stock-bot.sh` runtime-version shim (committed **here**, staged by the launch script) | No — they are ours, version-controlled here |
| Future patches (profile generator, feature flags, Python bridge) | `patch-package` patches + generators committed **here** in later E3/E4 issues | No — re-applied against each new pin |
| The working tree | `./mindcraft` — **git-ignored**, disposable, rebuilt by `setup-mindcraft.sh` | N/A — throwaway |

Why this isolates patches:

- The fork has **zero local commits**, so there is never an "ours vs. theirs"
  merge to untangle. Upstream history can even be force-rewritten and we are
  unaffected because we pin a **tag** (`e1-r1-pin`), not a moving branch.
- The git-ignored `./mindcraft` clone is **disposable** — `rm -rf ./mindcraft`
  and re-running `setup-mindcraft.sh` always reproduces the exact same tree
  (clone → checkout pinned commit → hard-assert `HEAD` → stage the committed
  lockfile → `npm ci`).
- Because every customization is a reviewed file **in this repo**, "did we lose
  a patch?" is answered by `git status` here, not by diffing two Git histories.
- `patch-package` patches (when later issues add them) are applied at
  `npm ci` time *from this repo's committed copies*, so a fresh clone of the
  pinned tree plus our staged files is always the full, intended system.

> **Note on terminology.** `docs/decisions/0005` calls the bridge a *"fork
> patch, not a plugin"*. That means a *controlled, source-level* change rather
> than an external plugin — it does **not** mean commits pushed onto the org
> fork. Operationally those changes are committed **here** and applied to the
> disposable clone, exactly as the lockfile is today. The org fork stays clean.

---

## How to re-base on upstream

Use this when upstream ships a fix we need. It produces a **new pin**; it never
edits the live `./mindcraft` clone by hand. Run every step from the repo root.

1. **Fetch upstream and pick the target commit.**

   ```bash
   git -C ./mindcraft remote add upstream https://github.com/mindcraft-bots/mindcraft.git 2>/dev/null || true
   git -C ./mindcraft fetch --tags upstream
   git -C ./mindcraft log --oneline upstream/develop -20
   ```

   Read the diff for the candidate commit and confirm it is the fix you want
   and nothing more:

   ```bash
   git -C ./mindcraft diff 35be480b4cc0bca990278e6103a1426392559d96..<new-sha>
   ```

2. **Create the new pin on the org fork.** Push the chosen upstream commit to
   `bradtaylorsf/mindcraft` and **move the pin tag forward** so old history
   survives any rewrite:

   ```bash
   git -C ./mindcraft push origin <new-sha>:refs/heads/develop
   git -C ./mindcraft tag e1-r2-pin <new-sha>          # new tag, do not delete e1-r1-pin
   git -C ./mindcraft push origin refs/tags/e1-r2-pin
   ```

   Keep the **old** tag (`e1-r1-pin`) in place — old branches/PRs still pin to
   it, so it must keep resolving.

3. **Re-vendor the lockfile.** Upstream commits no lockfile, so regenerate ours
   from the new pinned `package.json`, then commit it back here:

   ```bash
   git -C ./mindcraft checkout --detach <new-sha>
   ( cd ./mindcraft && npm install --package-lock-only )
   cp ./mindcraft/package-lock.json scripts/minecraft/mindcraft-package-lock.json
   ```

4. **Re-apply / verify `patch-package` patches against the new versions.** The
   pinned tree ships upstream `patches/*.patch` that `patch-package` applies on
   `npm ci`; any repo-owned patches (added in later E3/E4 issues) must also
   still apply. The re-vendored lockfile must resolve package versions whose
   numbers still match the patch filenames (e.g. `minecraft-data+3.97.0.patch`).

   ```bash
   rm -rf ./mindcraft && MINDCRAFT_COMMIT=<new-sha> scripts/minecraft/setup-mindcraft.sh
   ```

   If you see *"patch-package reported a failed patch or version mismatch"*,
   the new lockfile resolved versions that no longer match a patch filename.
   Update the patch (or pin the package version) until every `patch-package`
   line is green, then re-vendor the lockfile again.

5. **Prove the fork still builds and routing still holds.**

   The freshly re-based clone is now on disk — this is the **only** moment
   the E3-7 ([#539](https://github.com/bradtaylorsf/livestreamtoagi/issues/539))
   fork-**source** routing contract actually executes (it `skipif`s when no
   clone is present, e.g. in CI). Run both:

   ```bash
   pnpm verify:mindcraft-fork              # pin contract (SHA, Node 20, lockfile)
   pnpm verify:mindcraft-routing-contract  # E3-7: model/code_model tier routing survived the re-base
   ```

   If `verify:mindcraft-routing-contract` fails, the upstream change silently
   altered Mindcraft's native per-agent/per-tier routing — re-review the
   *"Evidence"* lines in `docs/decisions/0003-mindcraft-model-routing.md` and
   `docs/minecraft/model-routing.md` before accepting the new pin. **Do not
   proceed** until it is green against the re-based clone.

6. **Update every place the old pin is recorded** so docs and code cannot drift
   apart. Search-and-replace the old SHA/tag with the new ones in:

   - `scripts/minecraft/setup-mindcraft.sh` (the `MINDCRAFT_COMMIT` default + header comment)
   - `tests/backend/test_minecraft_setup_mindcraft.py` (`PINNED_SHA`)
   - `tests/backend/test_minecraft_fork_maintenance.py` (this doc's contract test)
   - `docs/decisions/0000-summary.md` (the "Final Decisions" table + "Begin Coding Here")
   - `docs/decisions/0001-minecraft-version-and-server.md` (the E1-R1 rationale)
   - `docs/minecraft/mindcraft-fork.md` (the pin table)
   - `docs/minecraft/fork-maintenance.md` (this file's pin table)

   Then re-run the full headless gate to confirm nothing was missed:

   ```bash
   pnpm verify:mindcraft-fork && pnpm verify:mindcraft-fork-maintenance
   pnpm verify:mindcraft-routing-contract   # re-confirm against the re-based clone
   ```

A re-pin is **not done** until all three verify commands are green (with the
re-based clone present, so `verify:mindcraft-routing-contract` actually runs
rather than skips) and every bullet in step 6 has been updated in the same
change.

---

## The CI build check

The acceptance criterion for this issue is "a green build check". The
dependency-free, deterministic check is the project's standard backend test
runner, which already runs on every push/PR in the **Backend Unit Tests** job
(`.github/workflows/ci.yml` → `pytest tests/backend/ -v -m "not integration"`).

Two suites in that job *are* the fork build check:

```bash
pnpm verify:mindcraft-fork              # pin contract: SHA, Node 20, fork URL, lockfile well-formed
pnpm verify:mindcraft-fork-maintenance  # this policy doc cannot silently drift
```

`pnpm verify:mindcraft-fork` is shorthand for
`.venv/bin/pytest tests/backend/test_minecraft_setup_mindcraft.py -v`, and
`pnpm verify:mindcraft-fork-maintenance` for
`.venv/bin/pytest tests/backend/test_minecraft_fork_maintenance.py -v`. Both
are picked up automatically by the existing CI `backend-test` job — no new CI
infrastructure was added (see the follow-up note below). They need **no
Node.js, no network, and no clone**: they assert the pin contract, that the
committed lockfile parses with a `lockfileVersion`, that the decision docs
record the hash, and that this policy doc stays in sync with the script and the
fork-install runbook.

There is also a `bash`-only static check that needs nothing else:

```bash
scripts/minecraft/setup-mindcraft.sh --verify
```

---

## Deferred follow-up: a live Node-20 `npm ci` clone build in CI

A literal, full Node-20 `npm ci` build of the live `./mindcraft` clone — the
heaviest possible "the fork builds" proof — is **intentionally a deferred
follow-up**, not part of this issue. Per this issue's *Out* scope ("the CI
infra itself if none exists — then open a follow-up"):

- The clone is **git-ignored and disposable**; CI has nothing to build without
  first cloning the fork and compiling native deps (`canvas`, `gl`), which
  needs new CI infrastructure (a Node-20 job, a build toolchain, network/clone
  budget) that does not exist today.
- The deterministic contract is already enforced headlessly by the suites
  above and by `npm ci`'s own lockfile/`package.json` drift abort during a real
  `setup-mindcraft.sh` run on a host with Node 20.

> **TODO / follow-up:** open a separate issue to add a Node-20 CI job that runs
> `scripts/minecraft/setup-mindcraft.sh` end-to-end (real clone + `npm ci` +
> `patch-package`) on a schedule, so an upstream change that breaks the *live*
> build is caught even though the headless contract still passes. This is
> out of scope for #538 by design.

---

## No LLM runtime path

**This issue has no LLM runtime path.** Documenting a maintenance policy and
adding a headless doc-contract test never calls a model, so there is no
LM Studio / OpenRouter step to validate for #538 — mirroring the same explicit
note in [`docs/minecraft/mindcraft-fork.md`](./mindcraft-fork.md) §"What this
does NOT cover". The **Local LM Studio validation** required by the epic does
not apply here; the nearest local smoke path is the dependency-free headless
suite:

```bash
pnpm verify:mindcraft-fork-maintenance   # this doc's contract test
pnpm verify:mindcraft-fork               # the pin contract it protects
```

Per-agent model routing through LM Studio is validated later in **E3-3
([#535](https://github.com/bradtaylorsf/livestreamtoagi/issues/535))**, not
here.

---

## Where this is recorded

- **`docs/decisions/0000-summary.md`** — the "Final Decisions" table records
  the org fork URL + pinned commit + tag.
- **`docs/decisions/0001-minecraft-version-and-server.md`** — the full E1-R1
  rationale (fork target, branch, commit date, Node 20).
- **`docs/decisions/0003-mindcraft-model-routing.md`** and
  **`docs/decisions/0005-skill-extension-point.md`** — why customizations are
  controlled patches in this repo rather than fork commits or external plugins.
- **`docs/minecraft/mindcraft-fork.md`** — the pinned, reproducible install
  this policy protects (and which links back here for the upstream-merge
  policy).
- **The fork itself** — tag `e1-r1-pin` in `bradtaylorsf/mindcraft` points at
  the pinned commit so it survives any upstream history rewrite.

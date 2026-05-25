---
name: alpha-loop-runner
description: Run and monitor ../alpha-loop sessions or epics from this repo safely. Use whenever the user asks to run alpha-loop, start the loop on an epic, prepare an epic run, monitor loop progress, verify an alpha-loop session, or validate completed epic issues. This skill must dry-run/validate epic queues, check ready labels, sync skills/agents, choose or recommend batch/test/verify settings, and stop on skipped checklist items.
auto_load: true
priority: high
---

# Alpha Loop Runner

## Trigger

Use this skill whenever the user asks to run `alpha-loop`, "the loop", or a GitHub epic through `../alpha-loop`.

## Command Resolution

From the repo root, prefer the adjacent checkout:

```bash
../alpha-loop/dist/cli.js <command>
```

Fallbacks: `alpha-loop <command>` if installed globally, or `npx @bradtaylorsf/alpha-loop <command>` only when the adjacent checkout is unavailable.

## Skill Sync Source Of Truth

This repo uses `.alpha-loop/templates/skills` as the canonical project skill directory. `.agents/skills` and `.claude/skills` are generated harness outputs.

When adding or changing a project skill:
- Edit or create it under `.alpha-loop/templates/skills/<skill-name>/`.
- Run `../alpha-loop/dist/cli.js sync` before any real alpha-loop run.
- Confirm the skill appears in every configured harness output.
- If sync deletes a useful skill that existed only under `.agents/skills` or `.claude/skills`, restore it and copy it into `.alpha-loop/templates/skills` before running sync again.

Before a real run, check:
- `git status --short --branch`
- `gh auth status`
- `../alpha-loop/dist/cli.js --version`
- `../alpha-loop/dist/cli.js run --help`
- `.alpha-loop.yaml` for `repo`, `agent`, `setup_command`, `test_command`, `smoke_test`, `skip_verify`, `auto_merge`, `batch`, `batch_size`, `max_issues`, and duration limits
- `ps -axo pid,ppid,etime,command | rg 'alpha-loop|dist/cli.js' | rg -v 'rg '` to ensure no duplicate loop is running

### Infra Preflight Gate (REQUIRED before consuming any retry budget)

Recent sessions burned 6+ retries diagnosing infrastructure failures as code bugs. Before the dry-run validation, all of these must pass — if any fail, fix the infra first and do NOT start the loop:

```bash
# Services
docker compose up -d
bash scripts/check-services.sh             # all 5 checks must pass

# Python env
.venv/bin/pytest --version                 # if this fails, re-run setup_command

# Redis auth (must match REDIS_URL — common failure: NOAUTH)
redis-cli -h 127.0.0.1 -p 6381 -a devpassword ping | grep -q PONG

# LLM provider: at least one must be reachable for issues whose AC depends on a live model
test -n "$OPENROUTER_API_KEY" \
  || curl -fsS "${LMSTUDIO_BASE_URL:-http://127.0.0.1:1234}/v1/models" >/dev/null
```

If preflight fails, status the failure as "infra-error" and do not invoke `alpha-loop run`. Retries against a broken environment are wasted.

## Running An Epic

1. Confirm the epic issue number and verify it has the `epic` label:
   `gh issue view <N> --json number,title,state,labels,body --repo bradtaylorsf/livestreamtoagi`
2. Confirm the epic body has one `## Ordered Work` task-list queue. Treat task-list issue refs as the exact execution order. Never let alpha-loop silently skip unchecked children.
3. Inspect every unchecked child issue in ordered position. Confirm each is open and has the configured ready label unless the epic explicitly says it is intentionally skipped. If the user asks to "get it ready", add the ready label to all intended children; otherwise stop and ask before changing labels.
4. Check for abandoned state before starting:
   - Open or closed session PRs for the same epic.
   - Local/remote `session/epic-<N>-...` branches.
   - Local/remote `agent/issue-<child>` branches for the ordered children.
   - Existing worktrees under `.worktrees/issue-*`.
   Clean abandoned branches/PRs only when the user has asked for cleanup or it is clearly from the current interrupted run; otherwise report and ask.
5. Run alpha-loop sync before the dry-run so all harnesses see the same skills and agents:
   `../alpha-loop/dist/cli.js sync`
   Then inspect `git status --short`. If sync deletes or mutates unexpected project-owned skill files, restore or report them before continuing.
6. Choose the run shape before the real run:
   - Default to `--batch --batch-size 2` for backend/Minecraft orchestration epics with ordered dependencies.
   - Use batch size 1 for high-risk migrations, security/auth, destructive data changes, or when adjacent issues cannot be reasoned about together.
   - Use batch size 3-5 only for small independent docs, tests, or frontend polish with little file overlap.
   - Prefer backend-only `test_command` such as `make test-backend` for backend/Minecraft orchestration. Use the full frontend/website gate only when those layers are touched.
   - Set `skip_verify: true` for per-child coding passes when the epic has a final integrated scenario/eval child. Run live/full verification after that final child instead.
7. Always run a dry-run validation with the intended command shape before the real run:
   `../alpha-loop/dist/cli.js run --epic <N> --dry-run --validate [--batch --batch-size <n>]`
   The dry run must show:
   - `Skip Verify` matches the intended posture.
   - `Batch Mode` and `Batch Size` match the intended posture.
   - The first batch starts at the first unchecked ordered child.
   - No unchecked child is skipped.
   - The total issue count matches the ordered unchecked checklist.
   - Validation warnings are understood; file-overlap warnings are acceptable only if batching is still coherent.
8. Set a 5-minute monitor before starting:
   - In Codex, create a thread heartbeat every 5 minutes that checks loop progress and resumes validation when the process exits.
   - If no heartbeat/reminder tool exists, keep the terminal session open and poll it roughly every 5 minutes.
9. Start the run in a long-running terminal session with the exact dry-run shape, for example:
   `../alpha-loop/dist/cli.js run --epic <N> --validate --batch --batch-size 2`
10. Watch for skip warnings, failed tests, transient rate limits, checklist update errors, and the final session PR.

Do not run two `alpha-loop run --epic <N>` processes against the same epic. The parent checklist is a single-writer queue.

## Stop Conditions

Interrupt the run immediately and report status if any of these happen:
- A child issue is skipped unexpectedly.
- The run starts at any child other than the first unchecked ordered child.
- The test command is broader than the agreed gate (for example frontend/website tests during a backend-only E12 run).
- Live Minecraft/Mindcraft verification runs before the agreed final validation phase.
- A duplicate alpha-loop process appears for the same epic.
- A merge conflict, service startup failure, or repeated verification loop indicates the issue is no longer a coding-only pass.
- The user says stop, pause, wait, or questions the queue order.

When interrupted, pause any heartbeat automation, wait for alpha-loop cleanup/finalization, inspect `git status`, restore accidental skill-sync deletions, and summarize the exact PRs/branches/issues touched.

## E12 / Minecraft Run-Mode Posture

For E12-style run-mode / starting-conditions work:
- Process all ordered children from the beginning. Do not start at later children just because early prerequisites are missing `ready`.
- Use batch size 2 unless the user says otherwise.
- Use backend-only tests during implementation: `make test-backend`.
- Disable per-child live verification with `skip_verify: true`.
- Defer full Minecraft/Mindcraft simulation validation until the final integrated scenario child, such as #775, and post-epic validation.
- After the final child lands, run final validation explicitly with verification enabled, for example:
  `SKIP_VERIFY=false ../alpha-loop/dist/cli.js run --verify-only <N>`
- For Minecraft post-epic checks, prefer E17/E18 tooling first:
  `pnpm mc:eval:commands --dry-run --list-only`
  and a dry-run multi-agent live eval before any expensive real soak.

## Running The Next Work

If the user says "run the loop" without an epic number:
- Prefer `../alpha-loop/dist/cli.js run` so the picker can show open epics above milestones.
- If they name "Minecraft pivot" and do not give a number, inspect open epic issues `#503`-`#517`; E1 is complete, so the normal implementation start is Epic E2 `#504` unless the tracker says otherwise.

## Completion Validation

When the loop stops, do not just report that it exited. Validate completion:

### Acceptance Evidence Classifier (run BEFORE declaring completion)

For each completed child issue, classify its AC:

- **Offline-acceptance**: tests + ruff + smoke logs alone satisfy the AC. Code-passing == done.
- **Live-acceptance**: AC explicitly references a live external surface (Twitch/YouTube stream capture, LM Studio reachable model, real Minecraft world artifact, real OpenRouter call, browser-rendered page).

If AC is live-acceptance, the loop's `make test-backend` + smoke is INSUFFICIENT. You must:
- Locate the named evidence artifact (stream URL, world snapshot path, browser screenshot, captured response).
- If missing, mark the issue "code-complete, acceptance-pending" and DO NOT close the parent epic checkbox until live evidence lands.

The empirical pattern from session E13: 7/7 issues had passing tests but missed acceptance because the loop conflated "tests green" with "acceptance complete".

1. Inspect the session output and session PR.
2. Inspect the epic and children with `gh issue view` / `gh pr list`; confirm completed child issues have merged PRs and checked boxes.
3. If per-child verification was disabled for the coding pass, run final epic verification with env override:
   `SKIP_VERIFY=false ../alpha-loop/dist/cli.js run --verify-only <N>`
   Otherwise run:
   `../alpha-loop/dist/cli.js run --verify-only <N>`
4. Run the most relevant local checks:
   - Backend/scripts: CLI tests or targeted Python tests.
   - Website/frontend: dev server plus browser or Playwright validation.
   - Minecraft/livestream behavior: CLI logs plus browser or Computer Use when a visible client/stream is involved.
5. For Minecraft pivot work, prefer local LM Studio validation. Record model IDs and commands. Do not require OpenRouter spend unless the issue explicitly asks for it.

If validation is partial, name the unchecked issue numbers, failed criteria, and next command to run.

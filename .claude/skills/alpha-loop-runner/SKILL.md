---
name: alpha-loop-runner
description: Run and monitor ../alpha-loop sessions or epics from this repo. Use when the user asks to run alpha-loop, run the loop, run an epic, monitor loop progress, verify an alpha-loop session, or validate completed epic issues.
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

Before a real run, check:
- `git status --short`
- `gh auth status`
- `../alpha-loop/dist/cli.js --version`
- `.alpha-loop.yaml` for `repo`, `agent`, `test_command`, `dev_command`, `auto_merge`, and duration limits

## Running An Epic

1. Confirm the epic issue number and verify it has the `epic` label:
   `gh issue view <N> --json number,title,state,labels,body --repo bradtaylorsf/livestreamtoagi`
2. Confirm the epic body has one `## Ordered Work` task-list queue. Treat task-list issue refs as the exact execution order.
3. Set a 5-minute monitor before starting:
   - In Codex, create a thread heartbeat every 5 minutes that checks loop progress and resumes validation when the process exits.
   - If no heartbeat/reminder tool exists, keep the terminal session open and poll it roughly every 5 minutes.
4. Start the run in a long-running terminal session:
   `../alpha-loop/dist/cli.js run --epic <N>`
5. Watch for skip warnings, failed tests, transient rate limits, checklist update errors, and the final session PR.

Do not run two `alpha-loop run --epic <N>` processes against the same epic. The parent checklist is a single-writer queue.

## Running The Next Work

If the user says "run the loop" without an epic number:
- Prefer `../alpha-loop/dist/cli.js run` so the picker can show open epics above milestones.
- If they name "Minecraft pivot" and do not give a number, inspect open epic issues `#503`-`#517`; E1 is complete, so the normal implementation start is Epic E2 `#504` unless the tracker says otherwise.

## Completion Validation

When the loop stops, do not just report that it exited. Validate completion:

1. Inspect the session output and session PR.
2. Inspect the epic and children with `gh issue view` / `gh pr list`; confirm completed child issues have merged PRs and checked boxes.
3. Run epic verification:
   `../alpha-loop/dist/cli.js run --verify-only <N>`
4. Run the most relevant local checks:
   - Backend/scripts: CLI tests or targeted Python tests.
   - Website/frontend: dev server plus browser or Playwright validation.
   - Minecraft/livestream behavior: CLI logs plus browser or Computer Use when a visible client/stream is involved.
5. For Minecraft pivot work, prefer local LM Studio validation. Record model IDs and commands. Do not require OpenRouter spend unless the issue explicitly asks for it.

If validation is partial, name the unchecked issue numbers, failed criteria, and next command to run.


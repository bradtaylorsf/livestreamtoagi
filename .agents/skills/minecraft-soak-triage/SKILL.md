---
name: minecraft-soak-triage
description: Run, monitor, and debug local Minecraft/Mindcraft smoke or soak runs in livestreamtoagi. Use this skill whenever the user asks to run a Minecraft Director V2 smoke, plan-build smoke, Minecraft soak, acceptance run, cabin/village build verification, log-monitoring loop, autonomous course-correction loop, or to decide whether a Minecraft run failure blocks an epic.
---

# Minecraft Soak Triage

Use this skill to drive a local Minecraft simulation from launch through evidence review and, when needed, focused fixes. The goal is not just to start a run; it is to keep watching until the run is verified, clearly failed, or a hard blocker is identified.

## Ground Rules

- Work from the repo root.
- Inspect `.env` only by key presence or through existing scripts; never print secret values.
- Do not commit `.env`, `logs/`, screenshots, videos, generated soak artifacts, or temporary Mindcraft clones.
- Prefer `pnpm` scripts and Makefile targets over ad hoc bare commands when they exist.
- For long-running work, start named terminal sessions and keep them open until they are no longer needed.
- Use a Codex heartbeat/reminder for runs longer than a few minutes when automation tools are available; otherwise poll the terminal and logs.
- Keep the user posted when launching, waiting, killing, fixing, and rerunning.
- **Preserve caller-supplied `LTAG_RUN_ID`.** `scripts/minecraft/soak.sh` and any wrapper must respect an existing `LTAG_RUN_ID`; only generate a timestamp fallback when the caller did not supply one. Issues #708 / #710 had soak.sh unconditionally overwriting the caller's ID, breaking lifecycle tracking and run-correlation.
- **Default `--management-policy` explicitly for local runs.** Silent default shifts have added cloud-LLM bridge review cost to scripts that were intended to be free local runs (issue #711). When invoking the orchestrator from a local script, pass an explicit policy (`local-only`, `bridge-off`, or whatever matches the run's intent) instead of relying on the framework default.

## Preflight

1. Check repo state:
   ```bash
   git status --short
   ```
2. Check `.env` without values:
   ```bash
   python - <<'PY'
   from pathlib import Path
   keys = []
   for raw in Path(".env").read_text(errors="replace").splitlines():
       line = raw.strip()
       if line and not line.startswith("#") and "=" in line:
           keys.append(line.split("=", 1)[0].removeprefix("export ").strip())
   print(f".env present: yes; key_count={len(keys)}")
   PY
   ```
3. Start the dev stack if not already healthy:
   ```bash
   pnpm dev
   ```
4. Confirm backend/services:
   ```bash
   curl -fsS http://127.0.0.1:8010/api/health
   bash scripts/check-services.sh
   ```
5. For Minecraft integration work, make sure the local Mindcraft commit used by the run matches the checkout unless the task explicitly tests the pinned commit:
   ```bash
   MINDCRAFT_COMMIT="$(git -C mindcraft rev-parse HEAD)"
   ```

## Launch Pattern

For a focused Director V2 plan-build smoke, use the current repo `.env` and override only the run-specific knobs:

```bash
MINDCRAFT_COMMIT="$(git -C mindcraft rev-parse HEAD)" \
MC_SIM_BUILD_MODE=plan \
MC_SIM_BUILD_MAX_PER_AGENT=1 \
MC_SIM_BUILD_COOLDOWN_SEC=0 \
MC_SIM_BUILD_ZONE_STRIDE=0 \
MINECRAFT_PLAN_BUILD_MAX_STEPS=64 \
CONVERSATION_MODE=director_v2 \
DIRECTOR_V2_GATE=1 \
MC_SIM_INIT_MESSAGE='...' \
pnpm mc:sim:smoke:director
```

Use a precise `MC_SIM_INIT_MESSAGE` that names one owner, one build, and explicit support behavior. For cabin or village work, say that non-owners should observe, inventory-check, chat, gather only when asked, and avoid standalone marker placement.

For broad #758 acceptance, use:

```bash
pnpm mc:sim:smoke:director
pnpm mc:sim:soak:director
```

## Monitoring Loop

While the run is active:

- Poll the long-running terminal session every few minutes.
- Watch `logs/supervisor.log`, `logs/paper-latest.log`, and the newest `logs/soak/<timestamp>/timeline.ndjson` once the run directory exists.
- If the run is meant to build, look for `action:planAndBuild`, `build_plan.generation.*`, and `build_plan.execution.*`.
- If logs show runaway all-agent fanout, repeated restarts, a stuck infinite loop, cost-cap risk, or a build-owner/tool-policy violation, stop the run early and diagnose instead of waiting for timeout.

When stopping a running smoke, prefer the owning terminal/session interrupt first. Use process killing only when the run is wedged and clearly belongs to the current smoke. Avoid broad `pkill` patterns unless the user has asked to clean the whole local stack.

## Evidence Review

After the run exits, find the newest run directory:

```bash
ls -td logs/soak/* | head -1
```

Always inspect:

- `acceptance-report.json`
- `action-reliability.md`
- `behavior.tsv`
- `timeline.ndjson`
- `timeline-totals.json`
- `logs/supervisor.log`
- `logs/paper-latest.log`
- `monitor.html`

For plan-build verification, require:

- at least one accepted `!planAndBuild` / `action:planAndBuild`
- at least one `build_plan.generation.completed`
- at least one successful `build_plan.execution.completed`
- `builder_plan_verified_blocks > 0`
- target `builder_plan_completion_rate >= 0.8`
- enough intended and verified blocks to plausibly match the requested structure
- visual or block-map evidence showing a coherent structure, not scattered markers

Use `references/director-v2-plan-build-evidence.md` for a compact checklist and Python snippets.

## Visual Evidence

Try normal screenshot capture first if Minecraft gameplay is visible. If screen capture is blocked or only the launcher is visible, inspect the live world directly with Mineflayer and save a block-map artifact into the run directory. Treat block-map evidence as acceptable when it uses the executed plan origin and observed world blocks.

For `monitor.html`, use the in-app Browser if allowed. If local file navigation is blocked by browser policy, inspect the HTML directly; do not route around browser security policy with another browser surface just to bypass the block.

## Diagnose And Iterate

Classify failures before editing:

- **No accepted command**: Director prompt/tool grants, parser, support-vs-owner prompt, or command policy.
- **Generation missing or bad**: planner prompt, provider config, local model JSON quality, material availability, validation.
- **Execution incomplete**: inventory, origin, pathing, timeout, max steps, placement verification.
- **Random/scattered blocks**: non-owner tool access, stale command execution, weak Director support policy, marker fallback.
- **Acceptance failed but build passed**: restart loop, heartbeat halt, action-reliability scoring, behavior gate.
- **Monitor/evidence missing**: timeline export, report builder, run profile, artifact paths.

Make the smallest fix that addresses the observed root cause. Add or update focused tests for behavior changes. Rerun syntax checks and targeted tests before rerunning the smoke.

## Closure Report

End with:

- final run directory
- pass/fail split: plan-build, acceptance report, action reliability, behavior gate
- screenshot or block-map path
- exact metrics
- code/config changes
- tests run
- remaining risks and recommended follow-up issue/epic

If the user asks whether a failure blocks an epic, map it to the epic's written acceptance criteria. Be strict about criteria that literally fail, but distinguish “blocks this epic” from “follow-up in E10/E12/E18 is cleaner.”

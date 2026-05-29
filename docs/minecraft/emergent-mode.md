# Emergent Mode (Operator Guide)

Issue: #909 E21-7e — emergent-mode acceptance + settlement regression
Parent epic: #820 Epic E21 — Autonomous Minecraft civilization readiness

Related references:

- [director-v2-acceptance-soak.md](director-v2-acceptance-soak.md)
- [director-v2-architecture.md](director-v2-architecture.md)

## What emergent mode is

`MC_SIM_BUILD_MODE=emergent` is the **default** build mode for the overnight
operator path (`pnpm mc:sim:soak:director` / `mc:sim:smoke:director`). Bots boot
with an **empty shared task board** and self-organize through personality-first,
tool-mediated collaboration:

- `manage_task create_task` posts an open, unowned proposal anyone can claim.
- `manage_task claim_task` is **first-claim-wins** (exactly one agent wins a
  contested task). In headless runs there is no audience, so claiming an
  in-progress task **is** the approval (auto-approve on claim, D3).
- `manage_task update_status -> done` finishes work with evidence.
- The civilization ledgers (`claim_ownership`, `propose_trade`, …) fire
  organically after builds.

There is **no seeded settlement objective list** and **no phase-rotation
machine** in emergent mode — the ordered-phase determinism in
`core/minecraft/director/prompt_gate.py` no-ops when there is no active
objective. Settlement mode is retained only as a known-good **regression
harness** (see "Falling back" below).

Contrast with the other build modes:

| Mode | Task board | Phase machine | Use |
| --- | --- | --- | --- |
| `single` | n/a | off | bare `smoke`/`soak` default |
| `plan` | n/a | one `!planAndBuild` | single-structure plan-build |
| `settlement` | seeded objectives | ordered phases | known-good regression harness |
| `emergent` | **empty, self-organized** | **bypassed** | **overnight default** |

## 30-minute documented smoke

Run a half-hour emergent acceptance smoke before committing to a longer soak:

```bash
MC_SIM_BUILD_MODE=emergent MC_SIM_SOAK_HOURS=0.5 pnpm mc:sim:soak:director
```

(`MC_SIM_BUILD_MODE=emergent` is already the `soak-director` default; it is shown
here for clarity. `MC_SIM_SOAK_HOURS=0.5` shortens the 2-hour default to 30
minutes.) The run writes the ordinary soak artifacts plus the emergent
acceptance gate output under `logs/soak/<UTC timestamp>/`.

## Reading `emergent-acceptance.{json,md}`

The emergent gate (`scripts/minecraft/emergent_acceptance.py`, invoked via
`build_director_acceptance_report.py --mode emergent`) reuses the Director V2
acceptance report (timeline) and the settlement smoke classifier
(`decision_log.jsonl`) and emits:

- `emergent-acceptance.json` — `overall_status`, `classification`, per-criterion
  pass/fail, and metrics.
- `emergent-acceptance.md` — the human-readable table appended to the run.

Criteria (all must pass for `overall_status=pass`):

| Criterion | Passes when |
| --- | --- |
| `emergent_empty_task_board_at_start` | `settlement_objective_count == 0` (no seed). |
| `emergent_distinct_task_creators` | `>= 3` distinct agents issue `create_task`. |
| `emergent_tasks_claimed_by_distinct_agents` | `>= 2` distinct agents `claim_task`. |
| `emergent_task_completed_with_evidence` | `>= 1` task reaches `done`. |
| `emergent_build_fired_from_claim` | `>= 1` build follows a claim (not a first-shouter race). |
| `emergent_civilization_tool_fired` | `>= 1` ownership claim or trade fires. |
| `emergent_no_phase_rotation_stall` | zero objectives and no phase-ordered path engaged. |
| `multi_turn_collaboration_scene` | `>= 1` scene has `>= 2` distinct selected turns. |
| `emergent_distinct_world_change_proxy` | `>= 2` world-changing intents from `>= 2` agents. |
| `emergent_collaborative_classification` | the smoke classifier reads the run as `collaborative`. |

The gate is non-fatal by default (`SOAK_REQUIRE_EMERGENT_ACCEPTANCE=0`) so the
overnight run still produces artifacts while the emergent telemetry substrate
matures. Set `SOAK_REQUIRE_EMERGENT_ACCEPTANCE=1` to make it a hard gate.

### Manual structure check (BlueMap)

The `>= 2 distinct structures` criterion is verified manually: open the BlueMap
web view at `http://localhost:25566` and confirm at least two distinct
structures built by at least two distinct agents. The automated proxy for this
is `emergent_distinct_world_change_proxy` (`>= 2` world-changing intents from
`>= 2` distinct agents).

## Falling back to the settlement regression harness

If an emergent run looks unhealthy and you need a known-good baseline, re-run in
settlement mode — it seeds an ordered objective list and exercises the
phase-rotation machine, then passes the #821 open-settlement smoke and the
ordered-phase Director acceptance (`settlement_objectives_have_structured_results`):

```bash
MC_SIM_BUILD_MODE=settlement pnpm mc:sim:soak:director
```

Settlement mode keeps its scripted init text and the
`seed_settlement_objectives.py` seed step; emergent mode seeds nothing.

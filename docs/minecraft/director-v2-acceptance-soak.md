# Director V2 Acceptance Soak

Issue: #758 E8.5-9 - Acceptance soak: meaningful collaboration without queue explosion  
Parent epic: #749 Epic E8.5 - Minecraft Director V2 + Tool Parity

This is the Director V2 proof run. The goal is not a pretty Minecraft demo; it
is evidence that the real cohort can run locally with bounded LM Studio queue
growth, selected-turn collaboration, useful memory, tool parity decisions, and
builder/gather/support macro evidence.

Related references:

- [director-v2-architecture.md](director-v2-architecture.md)
- [director-v2-tool-parity.md](director-v2-tool-parity.md)
- [cohort-monitor.md](cohort-monitor.md)
- [multi-agent-soak.md](multi-agent-soak.md)

## Smoke Profile

The smoke profile is a 0.25-hour Director V2 acceptance run:

```bash
pnpm dev
pnpm mc:sim:smoke:director
```

Equivalent direct command:

```bash
scripts/minecraft/run-local-sim.sh smoke-director
```

`smoke-director` forces:

- `CONVERSATION_MODE=director_v2`
- `DIRECTOR_V2_GATE=1`
- `SOAK_PROFILE=director_v2`
- `MINECRAFT_LLM_QUEUE_PROXY=1`

The smoke must show bounded queue growth and no all-agent response storm before
operators spend time on the longer soak.

## Soak Profile

The acceptance soak is a 2-hour Director V2 run:

```bash
pnpm dev
pnpm mc:sim:soak:director
```

Equivalent direct command:

```bash
scripts/minecraft/soak.sh --profile director_v2 --duration-hours 2 --log-dir logs/soak
```

The profile writes the ordinary soak artifacts plus Director V2 acceptance
artifacts under `logs/soak/<UTC timestamp>/`.

Static verification:

```bash
pnpm verify:director-acceptance-soak
```

## Local Single-Model Mode

Default validation is local-only. Chat and builder-plan generation use LM
Studio through the local queue proxy:

```bash
LLM_PROVIDER=lmstudio
LOCAL_LLM_BASE_URL=http://localhost:1234/v1
LOCAL_LLM_MODEL=<local-model-id>
LOCAL_LLM_MODEL_BUILDING=${LOCAL_LLM_MODEL}
CONVERSATION_MODE=director_v2
pnpm mc:sim:soak:director
```

Use this mode for acceptance sign-off unless the residual-gap section explicitly
explains why an optional builder route was needed.

## Optional OpenRouter Builder Mode

OpenRouter is optional and scoped only to `!planAndBuild` builder-plan JSON.
Normal chat remains local through LM Studio. Use strict caps:

```bash
MC_SIM_BUILD_MODE=plan \
MC_SIM_BUILDER_PROVIDER=openrouter \
MC_SIM_BUILDER_OPENROUTER_MODEL=<openrouter-model-id> \
MC_SIM_BUILDER_OPENROUTER_API_KEY=<key> \
MC_SIM_BUILDER_MAX_CALLS_PER_RUN=12 \
MC_SIM_BUILDER_MAX_CALLS_PER_AGENT=3 \
MC_SIM_BUILDER_MAX_USD_PER_RUN=<cap> \
pnpm mc:sim:soak:director
```

The acceptance report records provider, model, paid/local call counts, token
usage, estimated USD, and fallback reasons in `macro-evidence.ndjson` and
`acceptance-report.json`.

Structured distress and rescue events are written to `distress-evidence.ndjson`.
The acceptance report fails when `behavior-totals.env` records any unresolved
distress, so a stuck, drowning, trapped, low-health, dead, or repeatedly blocked
agent cannot silently pass the soak.

## Evidence: Monitor

`monitor.html` is the local visual review surface. It shows:

- per-agent latest chat/action/LLM state
- LM queue wait/running/completed/failed metrics
- inbox and action queue depths
- Director V2 selected/suppressed turns
- build-plan progress and builder provider usage
- warning badges for stalls, repeated commands, restarts, stuck loops, and no recent LLM

Use:

```bash
open logs/soak/<UTC timestamp>/monitor.html
```

## Evidence: Timeline

`timeline.ndjson` is the canonical structured event stream. Relevant columns:

| Column | Meaning |
| --- | --- |
| `ts` | UTC event timestamp. |
| `event_type` | Normalized event type such as `llm.queue.completed`, `director.gate.decision`, or `build_plan.execution.completed`. |
| `agent` | Agent id when known. |
| `trace_id` | Correlation id for LLM/action/director chains. |
| `payload.scene_id` | Director scene id when available. |
| `payload.queue_depth` / `payload.queued` | Director or LM queue depth evidence. |
| `payload.selected` | Whether Director V2 selected the agent for a turn. |

`timeline-totals.json` summarizes event counts, token totals, builder usage,
and Director totals.

## Evidence: Action Reliability

`action-reliability.json` and `action-reliability.md` prove local-model text
becomes parsed, executed, and verified Minecraft actions. The acceptance soak
still requires this existing gate because collaboration is not meaningful if
commands are never executed.

## Evidence: Director Decisions

`director-decisions.ndjson` is written by
`scripts/minecraft/build_director_acceptance_report.py`. Columns:

| Column | Meaning |
| --- | --- |
| `scene_id` | Scene that Director V2 is selecting for. |
| `agent` | Candidate or selected agent. |
| `selected` | `true` when the agent received the scene turn. |
| `turn_kind` | Speaker/action/macro style decision. |
| `reason_code` | Selection reason. |
| `suppression_reason` | Fanout, cooldown, or other suppression reason. |
| `queue_depth` | Director queue depth at decision time. |
| `build_plan_id` / `build_role` | Builder macro owner/support evidence when present. |

This file proves multi-turn collaboration and no all-agent response storm.

## Evidence: Tool Parity

`tool-parity.ndjson` records either callable Director tool use or an explicit
no-tool decision:

| Column | Meaning |
| --- | --- |
| `kind` | `tool_call` or `no_tool_decision`. |
| `tool_name` | Tool name when called. |
| `classification` | Tool parity classification or `documented_no_tool`. |
| `status` / `ok` | Tool outcome or documented no-tool status. |
| `available_tools` | Tools available on a no-tool selected turn. |
| `no_tool_reason` | Why the selected turn did not call a tool. |

This prevents a passing soak from silently skipping tool parity evidence.

## Evidence: Builder Macro

`macro-evidence.ndjson` captures build/gather/support macro attempts:

| Column | Meaning |
| --- | --- |
| `kind` | `build_plan.generation.*`, `build_plan.execution.*`, `action.result`, or `director_macro_assignment`. |
| `scene_id` | Scene id when known. |
| `owner` | Macro owner or support assignee. |
| `plan_id` | Build-plan/action id when present. |
| `provider` / `model` | Builder route used for plan generation. |
| `status` / `result` | Structured result, skip reason, failure, or support assignment. |
| `structured_result` | `true` when the event has enough structured outcome data for acceptance. |

At least one build, gather, or support macro attempt must have a structured
result.

## Evidence: Distress Rescue

`distress-evidence.ndjson` captures structured distress and rescue telemetry:

| Column | Meaning |
| --- | --- |
| `event_type` | `distress_reported`, `distress.reported`, `rescue.action.started`, or `rescue.action.completed`. |
| `agent` | Endangered agent when known. |
| `danger_id` | Shared-state danger id. |
| `kind` | `stuck`, `drowning`, `trapped`, `low_health`, `death`, or `repeated_failure`. |
| `rescuer_id` | Assigned or acting rescuer. |
| `recovery_status` | `open`, `rescue_dispatched`, `resolved`, `escaped`, `teleported`, or `failed`. |

The `no_unresolved_distress` criterion requires
`total_unresolved_distress=0` in `behavior-totals.env`.

## Evidence: Memory Digest

`memory-digest.ndjson` captures `director.scene.digest` and
`director.memory.compaction` rows:

| Column | Meaning |
| --- | --- |
| `scene_id` | Scene that was digested. |
| `participants` | Agents directly involved in the scene. |
| `distributed_to` | Agents that received the digest. |
| `entries_count` | Scene entries compacted. |
| `tokens` | Digest token count. |
| `summary` | Human-readable digest for scene memory. |
| `useful` | Acceptance helper boolean for non-empty, distributed digest evidence. |

At least one row must be useful.

## Evidence: Acceptance Report

`acceptance-report.json` schema:

| Key | Meaning |
| --- | --- |
| `schema_version` | Report schema version, currently `1`. |
| `profile` | Always `director_v2` for this report. |
| `overall_status` | `pass` or `fail`. |
| `thresholds` | Queue threshold, warm-up seconds, selected-agent ratio, tracked agent count. |
| `evidence_files` | Paths to Director decisions, tool parity, macro, and memory evidence. |
| `metrics` | Queue, collaboration, tool, macro, memory, restart, and behavior metrics. |
| `criteria` | Per-criterion pass/fail summary with evidence files and residual gap. |
| `residual_gaps` | Remaining blockers, or a no-gap statement for #511/#512/#514. |
| `downstream_epics` | Explicit notes for #511, #512, and #514. |

`acceptance-report.md` is the human-readable version appended to the run
summary.

## Acceptance Criteria Mapping

| Issue #758 criterion | Evidence and assertion |
| --- | --- |
| Local smoke run shows bounded queue growth and no all-agent response storm. | `timeline-raw/llm-queue.ndjson`, `timeline.ndjson`, and `director-decisions.ndjson`; `queue_depth_after_warmup_max < SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD` and selected agents per scene divided by tracked agents is `<= SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO`. |
| Soak includes one multi-turn collaboration scene. | `director-decisions.ndjson`; at least one `scene_id` has two or more selected Director turns. |
| Soak includes one useful memory digest. | `memory-digest.ndjson`; at least one row has `useful=true`. |
| Soak includes a tool call or documented no-tool decision. | `tool-parity.ndjson`; at least one `tool_call` or `no_tool_decision` row exists. |
| Soak includes a build/gather/support macro attempt with structured result. | `macro-evidence.ndjson`; at least one macro row exists and at least one row has `structured_result=true`. |
| LLM queue depth remains below threshold after warm-up. | `acceptance-report.json.metrics.queue_depth_after_warmup_max` is below `thresholds.queue_depth_after_warmup`. |
| No unrecovered bot restart loop occurs. | `early-exits.tsv`, `heartbeat-halts.tsv`, and `behavior-totals.env`; early exits, heartbeat halts, and restart recurrences must be zero. |
| No unresolved distress remains. | `distress-evidence.ndjson` and `behavior-totals.env`; `total_unresolved_distress` must be zero. |
| Evidence unblocks #511, #512, and #514 or documents blockers. | `acceptance-report.json.residual_gaps` and `downstream_epics` explicitly name #511, #512, and #514. |

## Emergent Mode Acceptance

`MC_SIM_BUILD_MODE=emergent` is the overnight operator default (E21-7c). It boots
the bots with an empty task board and lets them self-organize via `manage_task`
and the civilization ledgers instead of a seeded settlement objective list. The
settlement acceptance report above only rewards build-ish, phase-ordered macros,
so it is blind to the task lifecycle that defines emergent collaboration. The
**emergent acceptance gate** is the missing check.

When `MC_SIM_BUILD_MODE=emergent`, the soak runs the gate after the ordinary
report:

```bash
scripts/minecraft/build_director_acceptance_report.py \
  --mode emergent --run-dir logs/soak/<ts> --sim-folder logs/soak/<ts>
```

It reuses this report's `multi_turn_collaboration_scene_ids` and
`settlement_objective_count` (which must be `0` — no seed) plus the settlement
smoke classifier over `decision_log.jsonl`, and writes:

- `emergent-acceptance.json` — `overall_status`, `classification`, per-criterion
  pass/fail, and emergent metrics.
- `emergent-acceptance.md` — the human-readable table appended to the run.

The gate is non-fatal by default (`SOAK_REQUIRE_EMERGENT_ACCEPTANCE=0`) so the
overnight path still produces artifacts; set it to `1` to make it a hard gate.
The full operator walkthrough — the 30-minute smoke command, how to read the
artifacts, the `localhost:25566` BlueMap structure check, and how to fall back
to the settlement regression harness — is in
[emergent-mode.md](emergent-mode.md).

## Residual Gaps

The report is the source of truth after a run:

- #511 Dreams/journals remain blocked if memory digest evidence fails or no
  multi-turn scene exists.
- #512 Evals/reporting remain blocked if monitor/timeline/tool/macro evidence
  is missing or queue metrics are absent.
- #514 Run-mode/start-conditions remain blocked if the profile needs manual
  overrides, restart-loop recovery fails, or acceptance criteria are only
  partially satisfied.

When all criteria pass, the report writes: `None. Evidence is sufficient to
unblock #511, #512, and #514.`

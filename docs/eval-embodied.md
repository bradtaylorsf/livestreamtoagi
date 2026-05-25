# Embodied Eval Model

This document is a companion to
[`specs/AGENT-AUTONOMY-EVAL-STRATEGY.md`](../specs/AGENT-AUTONOMY-EVAL-STRATEGY.md).
The spec predates the Minecraft pivot and still describes the original
pixel-world model. `specs/` is read-only reference, so the adapted eval model for
epic #512 lives here.

## Why This Companion Exists

E10 keeps the existing autonomy eval coverage while adding embodied-world data:
bridge perception, bridge action results, Minecraft scene digests, and verified
build metrics. The eval system should still judge agency, creativity, dialogue,
productivity, safety, and narrative quality, but now it can also evaluate whether
agents changed the Minecraft world in ways that match their stated intent.

## Embodied Event Sources

[`core/eval/loader.py`](../core/eval/loader.py) is the main adapter from runtime
data to eval prompt context. It reads the existing transcript and artifact tables
and adds embodied inputs from these transcript event types:

- `bridge_perception` for bot perception snapshots and observations.
- `bridge_action_result` for terminal action outcomes reported by Mindcraft
  commands.
- `minecraft_scene` for scene digests from the embodied world.

The loader treats build commands in `BUILD_ACTION_NAMES` as build attempts and
parses `BUILD_METRIC_RE` fields such as `intended`, `present`, `missing`,
`unexpected`, `verified`, `abandoned`, and `completion`. These fields feed
`build_outcomes`, which lets evals compare intended work against observed world
state without requiring a hand-authored blueprint as the only construction path.

## Eval Categories

Prompt categories live in [`evals/prompts/`](../evals/prompts/). The embodied
model preserves the existing categories:

- `agency`
- `creativity`
- `dialogue_quality`
- `economic_behavior`
- `entertainment`
- `errors`
- `internal_state`
- `productivity`
- `safety`
- `simulation_narrative`
- `social_dynamics`
- `world_evolution`

[`evals/prompts/build_verification.yaml`](../evals/prompts/build_verification.yaml)
is the embodied build category added for E10. It receives `build_outcomes`,
embodied actions, world chunks, artifact totals, and the embodied summary from
`organize_by_category()` in
[`core/eval/loader.py`](../core/eval/loader.py).

## Reporting And Scorecards

[`core/reporting/sections/embodied_activity.py`](../core/reporting/sections/embodied_activity.py)
summarizes embodied activity for timeline reports: total actions, perception
reports, build attempts, verified/partial/failed builds, average completion, and
per-agent build stats.

[`core/reporting/scorecard.py`](../core/reporting/scorecard.py) includes the
`build_verification` scorecard criterion. For embodied runs, the criterion uses
report-section data when available and otherwise derives build outcomes directly
from transcript events. It is advisory rather than launch-blocking, but it keeps
verified-build signal visible in the same readiness surface as existing eval
criteria.

## Run-Mode Suites

Run-mode documentation starts at [`docs/run-modes.md`](run-modes.md). The E10
suites apply the same category set differently by run mode:

- [`docs/run-modes/blank-slate-embodied.md`](run-modes/blank-slate-embodied.md)
  emphasizes embodied autonomy, world evolution, productivity, safety, and build
  verification from a clean world and sparse memory.
- [`docs/run-modes/persistent.md`](run-modes/persistent.md) keeps longitudinal
  memory, relationships, economic behavior, productivity, safety, and embodied
  world-change continuity in scope.
- [`docs/run-modes/experimental.md`](run-modes/experimental.md) supports short
  focused tests where build, creative, or safety suites can be run without
  requiring a full persistent-world evaluation.

The executable suite mapping lives in
[`core/eval/engine.py`](../core/eval/engine.py). The `build` suite includes
`build_verification`, `world_evolution`, and `productivity`; embodied categories
are also available to broader creative, narrative, and default runs.

## Regression Gate

The E10 regression gate runs embodied data through the loader/reporting path
without dropping the older eval categories. It verifies that embodied actions,
build outcomes, existing prompt categories, run-mode suites, and scorecard
signals remain wired together. The intent is regression coverage, not a live
Minecraft acceptance test by itself.

## Local LM Studio Validation

Minecraft pivot issues should validate through LM Studio before acceptance and
should not require OpenRouter spend. Use the local OpenAI-compatible endpoint
documented in
[`specs/LOCAL-LLM-VALIDATION-PLAN.md`](../specs/LOCAL-LLM-VALIDATION-PLAN.md).
The minimum reachability check is:

```bash
pnpm llm:local --list-only
```

or:

```bash
.venv/bin/python scripts/check_local_llm.py --list-only
```

Runtime smoke tests should set local routing explicitly, for example:

```bash
LLM_PROVIDER=lmstudio \
LOCAL_LLM_BASE_URL=http://localhost:1234/v1 \
LOCAL_LLM_MODEL=<model-id-from-LM-Studio> \
EMBEDDING_PROVIDER=deterministic \
.venv/bin/python scripts/run_simulation.py \
  --seed-file scenarios/local_llm_validation.yaml \
  --max-cost 0.01
```

If an issue has no LLM runtime path, record that fact and verify the nearest
local smoke path instead.

## Build-Quality Feedback Loop

E10-8 / #714 adds structured build-quality feedback in
[`core/embodiment/build_feedback.py`](../core/embodiment/build_feedback.py). The
feedback builder compares a stated build goal with verified block/action data
and the next perception snapshot, then emits a record with:

- `attempt_id`
- `agent_id`
- `goal`
- `intended`, `present`, `missing`, `unexpected`, and `unsafe` buckets
- `completion`
- `classification`
- `suggested_next_step`

[`core/bridge/consumers/perception_action_memory.py`](../core/bridge/consumers/perception_action_memory.py)
pairs build action results with a later perception report, emits a
`build_feedback` event, stores the rendered feedback through
`MemoryCompactor.compact_interaction()`, and persists a `build_feedback`
artifact when the artifact repo is available. The recall-memory copy is what
makes a later agent turn able to retrieve the suggested repair or improvement
instead of repeating the same failed build.

The eval loader surfaces these artifacts as `build_feedback`, and
[`core/eval/prompt_loader.py`](../core/eval/prompt_loader.py) renders them under
`Build Quality Feedback` for categories that receive the field. Timeline reports
include `build_feedback_records`, missing/unsafe counts, and the latest
`suggested_next_step` through
[`core/reporting/sections/embodied_activity.py`](../core/reporting/sections/embodied_activity.py).
[`core/reporting/scorecard.py`](../core/reporting/scorecard.py) adds the
optional `build_quality_feedback` criterion so the E10 scorecard shows whether
embodied build attempts produced actionable repair feedback.

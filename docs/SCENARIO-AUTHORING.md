# Scenario Authoring Guide

Scenarios are YAML files in `scenarios/` that drive a simulation run. They
declare which agents participate, what phases unfold, optional world
configuration, and — added by E22-3 — which eval categories the scenario
is meant to exercise.

The canonical schema lives in `core/simulation/scenario_schema.py`. Use
the validator to catch errors before running:

```bash
python scripts/validate_scenario.py scenarios/my_scenario.yaml
python scripts/validate_scenario.py 'scenarios/*.yaml'
python scripts/validate_scenario.py --strict scenarios/*.yaml   # also require eval_targets
```

## Top-level blocks

| Block               | Required | Purpose |
|---------------------|----------|---------|
| `meta`              | yes      | Human-facing identity: `name`, `description`, `agents`, `expected_max_cost`, `expected_runtime_minutes`. |
| `phases`            | no       | Ordered list of phases (default empty for `persistent` runs). |
| `eval_targets`      | no       | Which eval categories this scenario targets (see below). |
| `audience`          | no       | Twitch audience-simulator config (initial viewers, chat frequency, personas). |
| `seed_tasks`        | no       | Bool — pre-fill the shared task board before phases begin. |
| `seed_goals`        | no       | Bool — pre-fill agent goals before phases begin. |
| `memory_seed`       | no       | Where startup memory comes from: `none`, `inherit`, or `custom`. |
| `persona_overrides` | no       | Per-run backstory / system-prompt overrides for individual agents. |
| `agent_goals`       | no       | Map of `agent_id → [goal, ...]` injected at startup. |
| `factions`          | no       | Pre-seeded alliances (`name`, `members`, `goal`, optional `stance`). |
| `world`             | no       | Minecraft world config: `seed`, `world_type`, `persistent`, `durable_world_id`. |
| `world_events`      | no       | Scheduled / probabilistic world events (full schema lands in E22-4). |
| `run_mode`          | no       | `experimental` (default for seeded), `persistent`, or `headless`. |
| `management_policy` | no       | `off`, `shadow`, or `enforce`. Defaults follow `run_mode`. |
| `experimental_goal` | no       | Bounded-run stop condition, e.g. `kind: turns, target: 50`. |
| `agents`            | no       | Override the active-agent list (otherwise taken from `meta.agents`). |

The schema is strict at the top level: unknown keys raise. Use the
validator as a guardrail when authoring.

## The `eval_targets` block

`eval_targets` tells the scoring pipeline (E22-9) and the website dashboard
(E22-10) which rubrics matter for this scenario, and what success looks like.

```yaml
eval_targets:
  primary:
    - social_dynamics
    - world_evolution
  secondary:
    - dialogue_quality
    - simulation_narrative
  success_criteria:
    social_dynamics: "min_score >= 60"
    world_evolution: "at_least_one_build_intent"
```

- **`primary`** — categories the scenario was designed to test. The dashboard
  highlights these and prioritises them in summary cards.
- **`secondary`** — categories that should still be measured but are not the
  reason this scenario exists.
- **`success_criteria`** — free-form per-category expressions read by the
  scorer. Examples: `min_score >= 60`, `at_least_one_build_intent`,
  `no_safety_violations`.

All category names must match a YAML file under `evals/prompts/*.yaml`.
The validator rejects unknown categories with a clear error.

### Choosing primary vs secondary

- A scenario named `goal_generation_test` exists to surface goal-generation
  evidence — `agency` belongs in `primary`. It still produces dialogue, so
  `dialogue_quality` can sit in `secondary`.
- A long social-dynamics arc like `full_evolution_7d` legitimately wants
  three primary categories (`social_dynamics`, `world_evolution`,
  `simulation_narrative`). Don't be afraid to list more than one — but if
  every category ends up "primary", the signal is lost.

## End-to-end example

```yaml
meta:
  name: "Survival Pressure"
  description: "Test how hunger and nightfall pressure shape build proposals."
  agents: [vera, rex, aurora, sentinel]
  expected_max_cost: 4.0
  expected_runtime_minutes: 30

eval_targets:
  primary: [internal_state, agency, world_evolution]
  secondary: [social_dynamics, dialogue_quality]
  success_criteria:
    internal_state: "min_score >= 50"
    agency: "at_least_one_self_directed_goal"

# (E22-4) Headless world-event scheduler — hunger decay + nightfall.
world_events:
  schedule:
    - { tick: 1000, event: nightfall }
    - { tick: 4000, event: dawn }
  probabilistic:
    - { event: enemy_nearby, prob_per_tick: 0.001, requires: nightfall }
  needs:
    hunger:
      tick_decay: 0.05
      critical_threshold: 25
      warning_threshold: 40

seed_tasks: true
seed_goals: true

phases:
  - name: morning_standup
    type: scheduled
    trigger: standup
    required_agents: [vera]
    location: town_square

  - name: open_planning
    type: organic
    count: 3
    location: town_square

  - name: dusk_reflection
    type: reflection
    reflection_type: 6hour
```

## Best practices

- **Run the validator** before committing a new scenario or changing the
  schema in `core/simulation/scenario_schema.py`.
- **Keep `meta.expected_max_cost` honest.** It's surfaced in the public
  Scenario Library and used for safety caps.
- **Pin a `run_mode`** when authoring a scenario for headless or persistent
  use. Without it, the orchestrator falls back to `experimental` for any
  seeded run.
- **Don't over-claim eval coverage.** A focused scenario with two primary
  categories scores better in the dashboard than one that lists every
  category as primary.
- **Reference other scenarios** when starting from scratch — copy a close
  cousin and trim, rather than building from a blank file.

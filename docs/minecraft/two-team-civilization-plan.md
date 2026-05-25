# Two-Team Civilization Goal System Plan

## Non-Technical Summary

We are moving from "one settlement objective list for everyone" toward a civilization model where teams, countries, guilds, or political entities can form around their own goals while still contributing to a shared world goal. This lets agents choose roles over time: builder, leader, scout, merchant, gatherer, guard, farmer, trader, or something emergent.

The near-term run uses static team assignments only as a test harness. The long-term system should let agents claim, vote on, or evolve roles dynamically, and the tool policy should follow those live role assignments instead of hard-coding personalities.

## Technical Detail

The current code can already run a useful approximation: scenario factions, per-agent goals, memory context, shared state, Director V2 selection, settlement objectives, and capped builder-plan calls. The missing layer is team-local state: each faction needs its own goal ledger, role roster, resource needs, scout reports, and progress history in addition to the global run objective queue.

## Issues

1. Dynamic Role Eligibility (S)
   - Add a runtime role/eligibility registry in shared state.
   - Support current builder-duty agents without permanently assigning any character to builder.
   - Acceptance: Director grants `!planAndBuild` only to agents currently eligible for builder duty; changing eligibility changes grants without code edits.

2. Team Goal Ledger (M)
   - Add faction/team goals alongside global settlement objectives.
   - Track status, owner, priority, dependencies, evidence, and memory links per team.
   - Acceptance: Team Ember and Team Grove can each have active goals while a global goal remains visible.

3. Team Role Roster And Voting Hook (M)
   - Represent leader, builder, gatherer, scout, merchant, guard, farmer, and custom roles as claims, nominations, or elected posts.
   - Add an API/shared-state mutation path for later voting.
   - Acceptance: a role change is recorded with reason, timestamp, previous holder, and effect on tool grants.

4. Resource Logistics Loop (M/L)
   - Make gatherers track requested materials, inventory, deposits, chest/storage location, and shortages.
   - Acceptance: a builder can request supplies, a gatherer can report supply status, and the report appears in team memory/shared state.

5. Scout Intel Loop (M)
   - Give scouts structured report targets: terrain, hazards, rival/team progress, resources, animals, and routes.
   - Acceptance: scout reports become team evidence and influence subsequent leader/build objectives.

6. Team-Aware Director Policy (M)
   - Teach Director V2 to prefer turns based on team role, active team goal, and recent team participation.
   - Acceptance: leaders plan, builders spend build-plan calls, gatherers/scouts produce evidence, and no one role starves.

7. Reporting And Evals (S/M)
   - Extend acceptance reports with team goal progress, role changes, scout reports, resource loops, and cross-team memory usage.
   - Acceptance: run summary shows global goal progress plus per-team goal status and role participation.

8. Scenario/Profile Library (S)
   - Add reusable profiles for two-team camps, trade guilds, rival towns, and mixed political entities.
   - Acceptance: operators can launch a run without hand-writing long environment blocks.

## Current Runnable Approximation

The first runnable profile is `scenarios/two_team_civilization_75m.yaml`. It uses:

- Team Ember: Alpha leader, Rex builder-duty, Vera gatherer/logistics, Sentinel scout.
- Team Grove: Aurora leader, Fork builder-duty, Pixel gatherer/designer, Grok scout.
- One global settlement objective queue that alternates between team-oriented structures.
- `SOAK_PLAN_BUILD_BOTS="rex fork"` as the current builder-duty policy for the test run.

This deliberately tests the tool-policy plumbing without pretending the larger dynamic role/voting system exists yet.

## Generated Run Prompt

Use this as the next simulation launch prompt after preflight:

```text
Run a 60-75 minute two-team Minecraft civilization shakeout on a fresh easy world.

Use Director V2, experimental run mode, memory_seed=none, management_policy=shadow, shared state enabled, memory context enabled, and local LM Studio for conversation.

Use OpenRouter/Gemini only for capped builder-plan JSON generation. Alpha and Aurora are local-model leaders. Code execution and !newAction stay blocked. The current builder-duty agents are Rex and Fork only for this run, via SOAK_PLAN_BUILD_BOTS="rex fork"; this is a temporary run policy, not a permanent character role.

Team Ember: Alpha leader, Rex builder, Vera gatherer/logistics, Sentinel scout.
Team Grove: Aurora leader, Fork builder, Pixel gatherer/designer, Grok scout.

Global goal: build two useful survival camps that can support actual Minecraft play: crafting, storage, resource prep, hunting prep, scouting, safety, and routes.

Progressively harder alternating objectives:
1. Ember crafting shelter
2. Grove crafting shelter
3. Ember storage/workshop station
4. Grove storage/workshop station
5. Ember hunting prep lodge or animal pen
6. Grove garden/animal pen
7. Ember mine-prep/smelter corner
8. Grove route/watch post
9. Shared comparison board or central meeting path

Leaders should plan and revise. Builders should use !planAndBuild only when granted. Gatherers should check inventory/material needs and report shortages. Scouts should check terrain, hazards, resources, and the other team's visible progress, then report back so leaders adapt.
```

## Launch Command Shape

```bash
SOAK_PLAN_BUILD_BOTS="rex fork" \
MC_SIM_BUILD_MODE=settlement \
MC_SIM_SETTLEMENT_OWNER_ORDER="rex,fork,rex,fork,rex,fork,rex,fork,rex" \
MC_SIM_SETTLEMENT_OBJECTIVES="Team Ember crafting shelter|Team Grove crafting shelter|Team Ember storage workshop station|Team Grove storage workshop station|Team Ember hunting prep lodge or animal pen|Team Grove garden animal pen|Team Ember mine prep smelter corner|Team Grove route watch post|shared comparison board and central meeting path" \
MC_SIM_BUILDER_PROVIDER=openrouter \
MC_SIM_BUILDER_OPENROUTER_MODEL=google/gemini-3.5-flash \
MC_SIM_BUILDER_MAX_CALLS_PER_RUN=10 \
MC_SIM_BUILDER_MAX_CALLS_PER_AGENT=5 \
SOAK_BLOCK_NEW_ACTIONS=1 \
SOAK_BLOCK_EXECUTE_CODE_ACTIONS=1 \
.venv/bin/python scripts/run_simulation.py \
  --name "e12-two-team-civilization-$(date -u +%Y%m%d-%H%M)" \
  --seed-file scenarios/two_team_civilization_75m.yaml \
  --agents alpha,vera,rex,aurora,pixel,fork,sentinel,grok \
  --conversation-mode director_v2 \
  --run-mode experimental \
  --duration-hours 1.0 \
  --max-cost 0.12 \
  --management-policy shadow \
  --memory-seed-mode none \
  --minecraft-log-dir logs/two-team-civilization
```

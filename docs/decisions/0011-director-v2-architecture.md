# Decision 0011: Director V2 Architecture

Status: accepted for coding; implementation split across #751-#758

Research date: 2026-05-21

Related issue: #750, E8.5-1

Related epic: #749, Epic E8.5 - Minecraft Director V2 + Tool Parity

Predecessor: #510, E8 - All Agents Embodied + Decentralized Conversation

## Non-Technical Summary

Director V2 is the Minecraft showrunner. It does not make the agents less free,
and it is not the Management content filter. It decides which Minecraft events
matter, which agent gets the next turn, and which compact context that selected
agent receives.

This fixes the post-#510 scaling problem. The current embodied path can let
every nearby bot independently decide whether to respond, which is good enough
for small local runs but can fan out into many LLM calls as the cast and world
grow. Director V2 keeps the useful show properties from the old Python loop:
one selected speaker at a time, bounded turns, memory-backed context, controlled
tool rounds, and a useful end-of-scene summary.

The long-form companion is
[docs/minecraft/director-v2-architecture.md](../minecraft/director-v2-architecture.md).

## Decision

Build Director V2 as an opt-in Minecraft orchestration layer after #510. The
#510 decentralized mode remains available and keeps its existing evidence value.
Director V2 becomes the scale path for #749 and must land before the later
dreams/journals, eval/reporting, and run-mode epics consume embodied activity.

### Runtime modes

Runtime selection stays centralized in `core/conversation_mode.py` and the
`CONVERSATION_MODE` environment variable. This issue does not change runtime
behavior, but the implementation contract is:

| Mode value | Meaning | Compatibility rule |
| --- | --- | --- |
| `director` | Existing legacy Python conversation engine for non-Minecraft simulations. | Keep as the default until a later run-mode issue changes defaults. |
| `embodied` | Current #510 Minecraft decentralized mode. It avoids constructing `ConversationEngine` and relies on Mindcraft/public-chat respond paths. | Must remain accepted for existing soak and evidence artifacts. |
| `decentralized` | Future explicit spelling for the same #510 behavior. | May be added as an alias, but must not remove `embodied`. |
| `director_v2` | New Minecraft Director V2 orchestration mode. | Must be explicit opt-in and must produce separate evidence from #510 artifacts. |

Sibling implementation issues may add a clearer run-spec field later, but the
environment knob above is the first compatibility boundary.

### Reused legacy components

Director V2 should not revive `ConversationEngine` wholesale. It should reuse
the parts that made the original show legible:

| Legacy component | Reuse in Director V2 |
| --- | --- |
| `core/conversation/speaker_selector.py` | Reuse the 5-factor scoring vocabulary: `time_since_spoke`, `topic_relevance`, `chattiness`, `adjacency_fit`, and `random_jitter`, plus interrupt metadata where it still fits Minecraft scenes. |
| `core/conversation_engine.py` bounded loop | Reuse the idea of bounded scenes, one selected next turn, energy/turn limits, productivity tracking, and a clean close. Do not reuse the whole in-memory office-room loop as the runtime owner. |
| `core/context_assembly.py` | Keep memory-backed prompt assembly and per-agent context boundaries. |
| `core/tool_executor.py` and `tools/` | Preserve controlled tool-call rounds, existing tool schemas, cost attribution, and approval gates. |
| `core/memory/*` compaction paths | Preserve 3-tier memory semantics: archival transcript, recall memories, and core memory boundaries. |
| `core/conversation_mode.py` | Extend the mode gate instead of scattering new flags across launch scripts. |

All LLM calls still route through `core/llm_client.py` or through the existing
Minecraft local-model path selected for the run. Director V2 must not introduce
direct provider SDK calls.

### New Director V2 modules

The sibling issues should introduce these module contracts. Exact file splits
may change, but these names describe the ownership boundaries:

| Issue | Planned module contract | Responsibility |
| --- | --- | --- |
| #751 | `core/minecraft/director/scene_inbox.py` and `spatial_hearing.py` | Convert bridge events, public chat, nearby agents, and action results into scene events with spatial scope. |
| #752 | `core/minecraft/director/turn_scheduler.py` | Pick the next speaker/tool/build step using legacy selection semantics plus Minecraft-specific state. |
| #753 | `scripts/minecraft/fork-src/agent/skills/director_gate.js` | Gate Mindcraft prompts through the Director V2 queue instead of letting every bot prompt independently. This wraps the external fork path `mindcraft/src/agent/conversation.js`; that file is not vendored in this repo. |
| #754 | `core/minecraft/director/memory_digest.py` | Batch scene transcript compaction and distribute compact digests to participant memories. |
| #755 | `core/minecraft/director/tool_adapter.py` | Expose valid backend tools to Minecraft scenes through typed, approval-aware calls. |
| #756 | `core/minecraft/director/build_scheduler.py` | Schedule builder macros, enforce builder budgets, and avoid duplicate build-plan calls. |
| #757 | `core/minecraft/director/monitor.py` | Emit evidence for selected turns, suppressed fanout, queue depth, stale/discarded responses, tool calls, memory compactions, and build outcomes. |

### Responsibilities

Director V2 owns:

- Scene detection: grouping bridge events into meaningful scenes rather than
  prompting on every raw event.
- Turn scheduling: selecting one next speaker or action at a time.
- Event routing: deciding which agents hear which scene facts.
- Memory digesting: batching noisy Minecraft activity into useful summaries.
- Tool invocation: routing valid tools through the existing backend/tool gates.
- Builder macro scheduling: budgeting and de-duplicating plan/build calls.
- Observability: making the chosen turns and suppressed fanout auditable.

### Non-responsibilities

Director V2 does not own:

- Management censorship for private Minecraft simulation talk. Private
  scheduler candidates and private scene state are orchestration data. Visible
  public chat, livestream output, TTS, external comms, and approval-gated tools
  still use their existing Management or human approval gates.
- A central blueprint mandate. Director V2 may schedule builder macros and
  enforce budgets, but it does not force a single top-down construction plan.
- Dreams, journals, or long-horizon planning. It produces better scene inputs
  for those systems; it does not replace them.
- Removal of #510. Decentralized mode remains runnable and useful for
  compatibility and regression comparison.

## Consequences

Director V2 gives #749 a scale path where prompt count grows with selected
scene turns, not with total nearby agents. It also gives later epics cleaner
activity to consume: selected-speaker traces, tool/build outcomes, and batched
scene summaries instead of raw per-agent prompt storms.

The cost is more orchestration surface area. We must keep the layer observable
and avoid turning it into a hidden central planner. Every Director V2 decision
needs a traceable reason and a mode label so #510 evidence stays separate.

## Alternatives

### Keep only #510 decentralized respond/ignore

Rejected for scale. The #510 path proved embodied agents can run and coordinate,
but independent respond/ignore checks can multiply LLM calls and make stale
responses expensive. It remains the compatibility mode.

### Restore the original Python `ConversationEngine` as-is

Rejected for fit. The original loop assumes a Python-owned conversation room.
Minecraft scenes need spatial hearing, action results, public chat, bridge
deadlines, and builder scheduling. We reuse its selection, bounded-turn, memory,
tool, and summary semantics instead.

### Add a central long-horizon planner

Rejected for product fit. The show should still feel character-driven. Director
V2 is runtime orchestration, not a blueprint engine and not a replacement for
future dreams, journals, or run-mode starting conditions.

## Compatibility And Handoff

- #510 evidence remains valid only for the decentralized/`embodied` mode. Do
  not relabel historical soak artifacts as Director V2 evidence.
- Director V2 evidence must record `CONVERSATION_MODE=director_v2`, selected
  speaker/action, suppressed fanout count, queue depth, stale response handling,
  tool calls, memory compactions, and build outcomes.
- #511 dreams/journals should consume Director V2 scene summaries, participant
  lists, key decisions, unresolved tensions, and verified outcomes.
- #512 eval/reporting should consume Director V2 monitor events and scene
  summaries instead of reconstructing intent from raw chat logs alone.
- #514 run modes should expose the mode choice and starting-condition inputs
  that Director V2 needs: agent set, factions, goals, memory seed, world seed,
  and persistent-vs-experimental mode.

## Evidence

- Legacy speaker scoring and bounded turn flow:
  `core/conversation/speaker_selector.py`,
  `core/conversation_engine.py`.
- Current mode gate:
  `core/conversation_mode.py`, `core/simulation/phases.py`,
  `core/main.py`.
- #510 decentralized evidence:
  [docs/minecraft/cohort-report.md](../minecraft/cohort-report.md),
  [docs/minecraft/multi-agent-soak.md](../minecraft/multi-agent-soak.md).
- Previous conversation decision:
  [0004-decentralized-conversation.md](0004-decentralized-conversation.md).
- Bridge protocol used by Minecraft events:
  [0010-bridge-protocol.md](0010-bridge-protocol.md).
- Long-form Director V2 companion:
  [docs/minecraft/director-v2-architecture.md](../minecraft/director-v2-architecture.md).

This issue has no runtime behavior change and no LLM runtime path. Verification
is a documentation review plus the dependency-free static doc test for #750.
